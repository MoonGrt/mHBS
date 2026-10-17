`timescale 1ns/1ps
`default_nettype none
// HBS microprogram ABI 3, fixed K1U1. Each ISSUE consumes exactly one HASH.
// L0/L1 are logical node/context slots sharing one physical Hash lane.
// Only typed metadata and branch instructions may retire between HASH and its explicit WAIT.
module executor #(
    parameter integer UNROLL=1, LANES=1,
    parameter bit PROFILE_ENABLE=0, SWAP_PHYSICAL_LANES=0
) (
    input wire [63:0] image_header, profile_descriptor, profile_identity,
    output wire [8:0] program_address,
    input wire [63:0] program_data,
    input wire [8:0] job_entry,
    output wire [4:0] descriptor_address,
    input wire [63:0] descriptor_data,
    input wire clk, rst,
    input wire job_valid, output wire job_ready, input wire [1:0] job_operation,
    input wire [6:0] job_message_length,
    input wire [31:0] job_index,
    input wire [127:0] job_identifier,
    input wire [255:0] job_secret_seed, job_secret_prf, job_public_seed, job_randomizer, job_public_root,
    input wire message_valid, output wire message_ready,
    input wire [63:0] message_data,
    input wire verify_valid, output wire verify_ready,
    input wire [255:0] verify_data,
    output logic verify_pass,
    output logic out_valid, output logic [255:0] out_data,
    output wire [5:0] out_bytes,
    output wire busy, output logic done, error, output logic [15:0] error_code,
    output wire [63:0] hash_count, permutation_count,
    output logic [63:0] cycles
);
    `include "rtl/executor/instructions.svh"
    localparam integer MAX_MESSAGE_BYTES=87;
    typedef enum logic [2:0] {IDLE,MESSAGE,LAUNCH,EXEC,FINISH,FAILED,MACRO} phase_t;
    phase_t phase;
    logic [1:0] operation;
    wire [7:0] n=profile_descriptor[7:0], hp=profile_descriptor[15:8];
    wire [7:0] layers=profile_descriptor[23:16], fors_k=profile_descriptor[31:24];
    wire [7:0] fors_a=profile_descriptor[39:32], digest_bytes=profile_descriptor[47:40];
    wire [7:0] total_height=profile_descriptor[55:48], chain_count=profile_descriptor[63:56];
    wire [5:0] node_bytes=n[5:0];
    wire [7:0] len1=n<<1;
    wire [8:0] fors_bytes=({1'b0,fors_k}*{1'b0,fors_a}+9'd7)>>3;
    wire [7:0] tree_bits=total_height-hp;
    wire family_slh=profile_identity==0 || profile_identity==1 || profile_identity==2
        || profile_identity==4 || profile_identity==5 || profile_identity==6;
    wire family_xmss=profile_identity>=8 && profile_identity<=10;
    wire family_lms=profile_identity>=11 && profile_identity<=13;
    wire family_stateful=family_xmss || family_lms;
    logic [63:0] expected_profile;
    always_comb case(
        profile_identity
    )
        0:expected_profile=64'h2342220621160310;
        1:expected_profile=64'h33422a0821160318;
        2:expected_profile=64'h4344310923110420;
        4:expected_profile=64'h233f1e0c0e070910;
        5:expected_profile=64'h333f270e11070918;
        6:expected_profile=64'h43402f0e16080820;
        8,11:expected_profile=64'h430a200000010a20;
        9:expected_profile=64'h4310200000011020;
        10,13:expected_profile=64'h4314200000011420;
        12:expected_profile=64'h430f200000010f20;
        default:expected_profile=0;
    endcase
    wire slh_config_valid=(n==16 || n==24 || n==32) && hp>0 && hp<=10
        && layers>0 && layers<=31 && fors_k>0 && fors_k<=35 && fors_a>0 && fors_a<=14
        && (fors_k*fors_a)<=320 && digest_bytes<=49 && digest_bytes>0
        && total_height>=hp && tree_bits<=64 && chain_count<=67 && chain_count>0;
    wire config_valid=family_slh ? slh_config_valid : expected_profile!=0 && profile_descriptor==expected_profile;
    logic [31:0] accepted_index;
    logic [127:0] accepted_identifier;
    logic [255:0] accepted_randomizer;
    wire [255:0] runtime_randomizer=family_lms ? accepted_randomizer : job_randomizer;
    wire index_valid=!family_stateful || job_operation==0 || job_index<(32'd1<<hp);


    // Every architectural field has fixed writers. There is no indexed scalar
    // register file, general integer ALU, or common scalar writeback network.
    logic [4:0] ctx_layer;
    logic [63:0] ctx_tree;
    logic [19:0] ctx_leaf;
    logic [5:0] ctx_group;
    // Digest bit offset is part of the bounded FORS context. Only explicit
    // GROUP_INIT/NEXT update it; this avoids a multiplier before TARGET.
    logic [8:0] ctx_fors_offset;
    logic [19:0] ctx_target;
    logic [20:0] ctx_cursor;
    logic [6:0] ctx_chain;
    logic [3:0] ctx_step [0:1],ctx_digit [0:1];
    logic [4:0] ctx_height,ctx_level;
    logic [19:0] ctx_index,ctx_path;
    logic [19:0] ctx_fors_base;
    logic [1:0] ctx_mask,ctx_digit_valid;
    logic [6:0] ctx_reduce_index,ctx_reduce_span;
    logic [19:0] addr_leaf [0:1];
    logic [6:0] addr_a [0:1];
    logic [31:0] addr_b [0:1];
    logic root_equal,root_compare_valid;
    localparam [1:0] CHAIN_FULL=0,CHAIN_CAP_FULL=1,CHAIN_CAP_PREFIX=2,CHAIN_SUFFIX=3;
    typedef enum logic [3:0] {CHAIN_SEED,CHAIN_F,CHAIN_ISSUE,CHAIN_RUN,
        CHAIN_CAP,CHAIN_RESULT,CHAIN_DONE,CHAIN_KEY_CHECK,CHAIN_MASK_CHECK,
        CHAIN_VALUE_INIT,CHAIN_CAPTURE_SAVE} chain_state_t;
    chain_state_t chain_state;
    logic [1:0] chain_mode;
    logic chain_slot,chain_feedback,chain_shadow_valid;
    localparam [1:0] C_SEED=0,C_F=1,C_KEY=2,C_MASK=3;
    logic [1:0] chain_hash_kind;
    wire chain_hash_stage=chain_hash_kind==C_F;
    logic chain_pending_terminal;
    logic [5:0] chain_seed_blocks,chain_key_blocks,chain_mask_blocks;
    logic [3:0] chain_digit;
    // Preflight fixes every F recipe field except the output length and
    // block limit. Snapshot only those two fields; reconstruct the validated
    // constants without retaining a second arbitrary 64-bit recipe bank.
    logic [5:0] chain_f_bytes,chain_f_blocks;
    // Family fixes shape/domain; only validated block bounds need snapshots.
    wire [63:0] chain_seed_recipe={4'd0,(family_xmss ? 4'd5 : family_lms ? 4'd9 : 4'd1),
        (family_slh ? 8'd5 : 8'd0),8'd1,2'd0,node_bytes,2'd0,chain_seed_blocks,24'd0};
    wire [63:0] chain_f_recipe={4'd0,(family_xmss ? 4'd6 : family_lms ? 4'd10 : 4'd2),
        8'd0,8'd1,2'd0,chain_f_bytes,2'd0,chain_f_blocks,24'd0};
    wire [63:0] chain_key_recipe={4'd0,4'd5,8'd2,8'd1,8'd32,2'd0,chain_key_blocks,24'd0};
    wire [63:0] chain_mask_recipe={4'd0,4'd5,8'd3,8'd1,8'd32,2'd0,chain_mask_blocks,24'd0};
    logic [5:0] chain_expected_hashes;
    logic [63:0] macro_count,macro_busy_cycles,macro_hashes;
    wire chain_active=phase==MACRO;
    wire [3:0] chain_terminal=chain_mode==CHAIN_CAP_PREFIX ? chain_digit : 4'd15;
    wire chain_capture_mode=chain_mode==CHAIN_CAP_FULL || chain_mode==CHAIN_CAP_PREFIX;
    wire chain_complete=chain_active && chain_state==CHAIN_DONE && !error;
    // Word 123 is a private transactional capture shadow. It is inaccessible
    // through every legal object/space selector and uses the existing 1R1W port.
    wire chain_capture_write,chain_cap_commit,chain_result_commit;
    wire [255:0] node [0:10];
    // Fixed architectural objects share one physical asynchronous 1R1W RAM.
    // Its addresses are private wires, never microprogram operands: LIST
    // 0..67, STACK 68..88, AUTH 89..108, node object 112+object. K1 recipes
    // consume either LIST, R, or one logical result; never two RAM operands.
    // V2, the public root V3, and RIGHT retain their dedicated fixed buses.
    (* ram_style="distributed" *) logic [255:0] node_memory [0:127];
    wire [6:0] node_memory_read_address;
    wire [255:0] node_memory_read=node_memory[node_memory_read_address];
    logic [15:0] scratch_valid;
    function automatic scratch_object(input [7:0] object);
        scratch_object=object==0 || object==1 || object==4 || object==5
            || object==7 || object==8 || object==9 || object==10
            ;
    endfunction
    wire [7:0] cpu_node_target=opcode==OP_XMSS_MASK ? 8'd4 : d;
    wire cpu_node_write=execute && (opcode==OP_NMOV || opcode==OP_LOAD || opcode==OP_XMSS_MASK
        || (opcode==OP_INPUT && verify_valid));
    wire [255:0] cpu_load_value=node_memory_read;
    wire [255:0] cpu_node_value=opcode==OP_NMOV ?
        read_node(a)
        : opcode==OP_XMSS_MASK ? (scratch_read ^ node[6])
        : opcode==OP_INPUT ? trim_node(verify_data) : cpu_load_value;
    wire scratch_write=cpu_node_write && scratch_object(cpu_node_target);
    wire result_write=execute && opcode==OP_WAIT && group_complete;
    wire [3:0] result_object=group_mask[1] ? 4'd5 : 4'd4;
    wire [255:0] scratch_read=scratch_valid[node_memory_read_address[3:0]]
        ? node_memory_read : 256'd0;
    logic node_memory_write;
    logic [6:0] node_memory_write_address;
    logic [255:0] node_memory_write_value;
    always_ff @(posedge clk) if(node_memory_write)
        node_memory[node_memory_write_address]<=node_memory_write_value;
    always_ff @(posedge clk) begin
        if(rst || job_accept) scratch_valid<=0;
        else if(scratch_write)
            scratch_valid[cpu_node_target[3:0]]<=1;
        else if(result_write) scratch_valid[result_object]<=1;
        else if(chain_cap_commit) scratch_valid[chain_slot ? 8 : 7]<=1;
        else if(chain_result_commit) scratch_valid[chain_slot ? 5 : 4]<=1;
    end
    genvar object;
    generate for(object=0;object<11;object=object+1) begin: node_objects
        if(object==0 || object==1 || object==4 || object==5 || object>=7) begin: scratch
            // The constant views are observations, not extra datapath reads.
`ifndef SYNTHESIS
            assign node[object]=scratch_valid[object] ? node_memory[112+object] : 256'd0;
`else
            assign node[object]=256'd0;
`endif
        end else begin: direct
            logic [255:0] value;
            assign node[object]=value;
            always_ff @(posedge clk) begin
                if(rst) value<=0;
                else if(job_accept) value<=object==3 ? trim_node(job_public_root) : 256'd0;
                else if(cpu_node_write && cpu_node_target==object) value<=cpu_node_value;
            end
        end
    end endgenerate
    logic [391:0] hmsg_digest;
    logic hmsg_valid,digits_valid;
    logic [255:0] digit_message;
    logic [11:0] digit_checksum;
    // Message reception finishes before any image instruction can issue a
    // Hash. A single dedicated read port therefore serves the physical lane;
    // bytes beyond message_length are masked by the lane's SHAKE padding.
    // Old words may remain across jobs and reset, without being observable.
    (* ram_style="distributed" *) logic [63:0] message_words [0:15];
    wire [3:0] message_word_address;
    wire [63:0] message_word_data=message_words[message_word_address];
    logic [6:0] message_length,message_received;
    wire message_write=!rst && phase==MESSAGE && message_valid;
    always_ff @(posedge clk) if(message_write)
        message_words[message_received[6:3]]<=message_data;

    function automatic [255:0] trim_node(input [255:0] value);
        case(n)
            16:trim_node={128'd0,value[127:0]};
            24:trim_node={64'd0,value[191:0]};
            default:trim_node=value;
        endcase
    endfunction
    function automatic [255:0] read_node(input [7:0] address);
        reg [255:0] value;
        begin
            value=0;
            if(address<11) begin
                if(scratch_object(address)) value=scratch_read;
                else value=node[address];
            end
            else case(address)
                11:value=job_secret_seed;
                12:value=job_secret_prf;
                13:value=job_public_seed;
                14:value=runtime_randomizer;
                default:value=0;
            endcase
            read_node=trim_node(value);
        end
    endfunction
    function automatic [1:0] select_lanes(input [7:0] selector,input [1:0] mask);
        case(selector)
            0:select_lanes=mask;
            1:select_lanes=mask&2'b01;
            2:select_lanes=mask&2'b10;
            default:select_lanes=0;
        endcase
    endfunction
    // DIGITS owns an immutable node snapshot and its bounded checksum.
    // Later writes to V2 cannot alter the WOTS digits already produced.
    function automatic [3:0] read_digit(input [6:0] address);
        begin
            if(address<len1) read_digit=digit_message[{(address[5:0]^6'd1),2'b0} +:4];
            else if(address==len1) read_digit=digit_checksum[11:8];
            else if(address==len1+8'd1) read_digit=digit_checksum[7:4];
            else if(address==len1+8'd2) read_digit=digit_checksum[3:0];
            else read_digit=0;
        end
    endfunction
    wire [4:0] checksum_byte [0:31];
    wire [5:0] checksum_pair [0:15];
    wire [6:0] checksum_quad [0:7];
    wire [7:0] checksum_octet [0:3];
    genvar check_index;
    generate
        for(check_index=0;check_index<32;check_index=check_index+1) begin: byte_sums
            assign checksum_byte[check_index]={1'b0,~node[2][check_index*8 +:4]}
                +{1'b0,~node[2][check_index*8+4 +:4]};
        end
        for(check_index=0;check_index<16;check_index=check_index+1) begin: pair_sums
            assign checksum_pair[check_index]={1'b0,checksum_byte[check_index*2]}
                +{1'b0,checksum_byte[check_index*2+1]};
        end
        for(check_index=0;check_index<8;check_index=check_index+1) begin: quad_sums
            assign checksum_quad[check_index]={1'b0,checksum_pair[check_index*2]}
                +{1'b0,checksum_pair[check_index*2+1]};
        end
        for(check_index=0;check_index<4;check_index=check_index+1) begin: octet_sums
            assign checksum_octet[check_index]={1'b0,checksum_quad[check_index*2]}
                +{1'b0,checksum_quad[check_index*2+1]};
        end
    endgenerate
    wire [8:0] checksum_low={1'b0,checksum_octet[0]}+{1'b0,checksum_octet[1]};
    wire [8:0] checksum_high=(n!=16 ? {1'b0,checksum_octet[2]} : 9'd0)
        +(n==32 ? {1'b0,checksum_octet[3]} : 9'd0);
    wire [9:0] checksum_total={1'b0,checksum_low}+{1'b0,checksum_high};
    task automatic fault(input [15:0] code);
        begin error<=1;error_code<=code;phase<=FAILED;end
    endtask
    // Current IR plus one prefetched instruction. A pending synchronous ROM
    // response also reserves a queue position. Redirect discards the obsolete
    // response and starts the target read on that same edge.
    logic fetch_active, ir_valid, prefetch_valid, fetch_pending;
    logic [63:0] ir, prefetch_word;
    (* dont_touch="true" *) logic [3:0] node_source_address;
    wire issue_now=1'b0;
    logic [8:0] fetch_pc;
    wire [7:0] opcode=ir[63:56], d=ir[55:48], a=ir[47:40], b=ir[39:32];
    wire [31:0] imm=ir[31:0];
    logic retire, redirect, halt_fetch;
    logic [8:0] redirect_pc;
    logic fetch_issue;
    integer fetch_occupancy;
    wire start_fetch=phase==LAUNCH;
    assign program_address=start_fetch ? job_entry : redirect ? redirect_pc : fetch_pc;
    always_comb begin
        fetch_occupancy=(ir_valid ? 1 : 0)+(prefetch_valid ? 1 : 0)
            +(fetch_pending ? 1 : 0)-(retire ? 1 : 0);
        fetch_issue=fetch_active && !halt_fetch && fetch_occupancy<2;
        if(start_fetch || redirect) fetch_issue=1;
        if(error || phase==FAILED || rst) fetch_issue=0;
    end
    always_ff @(posedge clk) begin
        if(rst) begin
            fetch_active<=0;ir_valid<=0;prefetch_valid<=0;fetch_pending<=0;
            fetch_pc<=0;ir<=0;prefetch_word<=0;node_source_address<=0;
        end else if(error || phase==FAILED || halt_fetch) begin
            fetch_active<=0;ir_valid<=0;prefetch_valid<=0;fetch_pending<=0;
        end else if(start_fetch || redirect) begin
            fetch_active<=1;ir_valid<=0;prefetch_valid<=0;fetch_pending<=1;
            fetch_pc<=(start_fetch ? job_entry : redirect_pc)+9'd1;
        end else begin
            fetch_pending<=fetch_issue;
            if(fetch_issue) fetch_pc<=fetch_pc+9'd1;
            case({fetch_pending,retire})
                2'b01:begin ir<=prefetch_word;node_source_address<=prefetch_word[40 +: $bits(node_source_address)];ir_valid<=prefetch_valid;prefetch_valid<=0;end
                2'b10:begin
                    if(!ir_valid) begin ir<=program_data;node_source_address<=program_data[40 +: $bits(node_source_address)];ir_valid<=1;end
                    else begin prefetch_word<=program_data;prefetch_valid<=1;end
                end
                2'b11:begin
                    ir_valid<=1;
                    if(prefetch_valid) begin ir<=prefetch_word;node_source_address<=prefetch_word[40 +: $bits(node_source_address)];prefetch_word<=program_data;prefetch_valid<=1;end
                    else begin ir<=program_data;node_source_address<=program_data[40 +: $bits(node_source_address)];prefetch_valid<=0;end
                end
                default:begin end
            endcase
        end
    end

    logic group_valid;
    logic [1:0] group_mask;
    // A one-hot logical destination is retained until explicit WAIT publishes
    // the physical response. Hardware never serializes a two-lane request.
    wire [1:0] response_pending=group_valid ? group_mask : 2'b00;
    logic [63:0] group_recipe, group_tree;
    logic [4:0] group_layer;
    logic [19:0] group_leaf_value;
    logic [6:0] group_a_value;
    logic [31:0] group_b_value;
    logic [1:0] ctx_address_type,group_address_type;
    wire [19:0] group_leaf [0:1];
    wire [6:0] group_a [0:1];
    wire [31:0] group_b [0:1];
    wire [391:0] result [0:1];
    wire [1:0] lane_ready,lane_valid,lane_error;
    wire [391:0] lane_value [0:1];
    wire [6:0] lane_list0 [0:1],lane_list1 [0:1];
    wire physical_ready,physical_valid,physical_error;
    wire [391:0] physical_value;
    wire [6:0] physical_list0,physical_list1;
    logic [63:0] hash_base,permutation_base;
    wire [63:0] total_hashes,total_permutations;
    wire lane_fault=group_valid && physical_valid && physical_error;
    wire group_complete=group_valid && physical_valid;
    wire chain_response=chain_active && chain_state==CHAIN_RUN && group_complete && !error && !lane_fault;
    wire chain_value_result=chain_hash_kind==C_SEED || chain_hash_kind==C_F;
    wire [4:0] chain_position=chain_hash_stage ? {1'b0,group_b_value[3:0]}+5'd1 : 5'd0;
    wire chain_at_end=chain_value_result && chain_position=={1'b0,chain_terminal};
    wire chain_capture_now=chain_value_result && chain_capture_mode && chain_position=={1'b0,chain_digit};
    // XMSS needs the value across KEY/MASK hashes. Word124 is private; a
    // capture copies it to word123 on a separate edge, using the same 1R1W RAM.
    wire chain_private_write=family_xmss && chain_active && !error && !rst
        && (chain_state==CHAIN_VALUE_INIT || (chain_response && chain_value_result));
    assign chain_capture_write=chain_active && !error && !rst
        && (family_xmss ? chain_state==CHAIN_CAPTURE_SAVE : chain_response && chain_capture_now);
    assign chain_cap_commit=chain_active && chain_state==CHAIN_CAP && !error && !rst;
    assign chain_result_commit=chain_active && chain_state==CHAIN_RESULT && !error && !rst;
    function automatic chain_recipe_valid(input [63:0] value,input bit seed);
        reg [3:0] expected_shape;
        begin
            expected_shape=family_xmss ? (seed ? 4'd5 : 4'd6)
                : family_lms ? (seed ? 4'd9 : 4'd10) : (seed ? 4'd1 : 4'd2);
            chain_recipe_valid=value[63:60]==0 && value[59:56]==expected_shape
                && value[55:48]==(seed && family_slh ? 8'd5 : 8'd0) && value[47:40]==8'd1
                && value[39:38]==0 && value[37:32]==node_bytes && value[31:30]==0
                && value[29:24]>=1 && value[29:24]<=32 && value[23:0]==0;
        end
    endfunction
    function automatic chain_key_recipe_valid(input [63:0] value,input bit mask);
        chain_key_recipe_valid=value[63:56]==8'd5 && value[55:48]==(mask ? 8'd3 : 8'd2)
            && value[47:40]==8'd1 && value[39:32]==8'd32 && value[31:30]==0
            && value[29:24]>=1 && value[29:24]<=32 && value[23:0]==0;
    endfunction
    wire chain_start=chain_active && !error && (family_xmss
        ? chain_state==CHAIN_MASK_CHECK && chain_key_recipe_valid(descriptor_data,1'b1)
        : chain_state==CHAIN_F && chain_recipe_valid(descriptor_data,1'b0));
    // KEY/MASK are bounded substages of one XMSS step. Only an F response
    // advances the chain position; each request still executes exactly one Hash.
    wire [1:0] chain_next_kind=!family_xmss ? C_F
        : chain_hash_kind==C_KEY ? C_MASK : chain_hash_kind==C_MASK ? C_F : C_KEY;
    wire [63:0] chain_next_recipe=chain_next_kind==C_KEY ? chain_key_recipe
        : chain_next_kind==C_MASK ? chain_mask_recipe : chain_f_recipe;
    wire chain_reissue=chain_response && !chain_at_end
        && !(family_xmss && chain_capture_now);
    wire [3:0] chain_next_step=chain_hash_stage ? group_b_value[3:0]+4'd1 : 4'd0+group_b_value[3:0];
    wire macro_request=chain_active && !error && (chain_state==CHAIN_ISSUE || chain_reissue
        || (family_xmss && (chain_state==CHAIN_VALUE_INIT
            || (chain_state==CHAIN_CAPTURE_SAVE && !chain_pending_terminal))));
    wire chain_issue=macro_request && physical_ready;
    wire [63:0] physical_recipe=chain_reissue ? chain_next_recipe : group_recipe;
    wire [31:0] physical_b_value=chain_reissue ? {28'd0,chain_next_step} : group_b_value;
    // Verification-only observation wires; they add no architectural state.
    wire [1:0] trace_hash_valid=((phase==EXEC && ir_valid && opcode==OP_WAIT && group_complete && !error && !lane_fault && !illegal)
        || chain_response)
        ? group_mask : 2'b00;
    wire [63:0] trace_recipe=group_recipe,trace_tree=group_tree;
    wire [1:0] trace_address_type=group_address_type;
    wire trace_stateful=family_stateful;
    wire [4:0] trace_layer=group_layer;
    wire [19:0] trace_leaf[0:1];
    wire [6:0] trace_a[0:1];
    wire [31:0] trace_b[0:1];
    wire [391:0] trace_result[0:1];
    assign hash_count=PROFILE_ENABLE ? total_hashes-hash_base : 64'd0;
    assign permutation_count=PROFILE_ENABLE ? total_permutations-permutation_base : 64'd0;
    assign descriptor_address=chain_active && chain_state==CHAIN_SEED ? 5'd7
        : chain_active && chain_state==CHAIN_F ? 5'd8
        : chain_active && chain_state==CHAIN_KEY_CHECK ? 5'd4
        : chain_active && chain_state==CHAIN_MASK_CHECK ? 5'd5 : d[4:0];
    genvar logical_slot;
    generate for(logical_slot=0;logical_slot<2;logical_slot=logical_slot+1) begin: logical_slots
        assign group_leaf[logical_slot]=group_leaf_value;
        assign group_a[logical_slot]=group_a_value;
        assign group_b[logical_slot]=group_b_value;
        assign trace_leaf[logical_slot]=group_leaf_value;
        assign trace_a[logical_slot]=group_a_value;
        assign trace_b[logical_slot]=group_b_value;
        assign lane_ready[logical_slot]=physical_ready && group_mask[logical_slot];
        assign lane_valid[logical_slot]=physical_valid && group_mask[logical_slot];
        assign lane_error[logical_slot]=physical_error && group_mask[logical_slot];
        assign lane_value[logical_slot]=physical_value;
        assign lane_list0[logical_slot]=physical_list0;
        assign lane_list1[logical_slot]=physical_list1;
        assign result[logical_slot]=physical_value;
        assign trace_result[logical_slot]=physical_value;
    end endgenerate
    generate for(genvar physical=0;physical<1;physical=physical+1) begin: lanes
        recipe #(.N(32),.DIGEST_BYTES(49),.INDEX_BITS(7),.UNROLL(UNROLL),
            .MAX_MESSAGE_BYTES(MAX_MESSAGE_BYTES),.RECIPE_MASK(16'hfffe),
            .PROFILE_ENABLE(PROFILE_ENABLE)) lane (
            .clk,.rst(rst || error),.node_bytes,
            .request_valid((phase==EXEC && group_valid && !physical_valid && !error) || macro_request),.request_ready(physical_ready),
            .request_recipe(physical_recipe),
            .request_key(chain_active && family_xmss ? hmsg_digest[255:0] : node[2]),.request_identifier(accepted_identifier),.request_index(accepted_index),
            .request_address_type(group_address_type),
            .secret_seed(job_secret_seed),.secret_prf(job_secret_prf),.public_seed(job_public_seed),
            .root(node[3]),.randomizer(group_recipe[59:56]==4 || group_recipe[59:56]==8 || group_recipe[59:56]==11 ? scratch_read : runtime_randomizer),
            .message_word_address,.message_word_data,.message_length,
            .request_layer(group_layer),.request_tree(group_tree),
            .request_leaf(group_leaf_value),.request_a(group_a_value),.request_b(physical_b_value),
            .request_left(chain_active && family_xmss
                ? (physical_recipe[59:56]==6 ? node_memory_read ^ physical_value[255:0] : node_memory_read)
                : chain_active && (chain_feedback || chain_reissue) ? physical_value[255:0] : scratch_read),.request_right(node[6]),
            .list_index0(physical_list0),.list_index1(physical_list1),.list_data0(list_value),.list_data1(256'd0),
            .response_valid(physical_valid),
            .response_ready((phase==EXEC && ir_valid && opcode==OP_WAIT && group_complete && !error && !lane_fault && !illegal) || chain_response),
            .response_value(physical_value),.error(physical_error),
            .hash_count(total_hashes),.permutation_count(total_permutations)
        );
    end endgenerate
    initial if(LANES!=1 || UNROLL!=1 || SWAP_PHYSICAL_LANES)
        $error("Microprogram production core requires fixed K1U1 without lane swap");

    // Bounded digest transforms. These circuits cannot launch a Hash.
    logic [63:0] parsed_tree;
    logic [19:0] parsed_leaf;
    // TARGET reads one bounded MD window. A fixed byte-bit reversal matches
    // FORS's MSB-first bit stream; the final reversal restores the integer.
    // Padding covers every legal final window without reading tree/leaf bytes.
    wire [332:0] fors_bitstream;
    assign fors_bitstream[332:320]=13'd0;
    genvar fors_byte,fors_bit;
    generate for(fors_byte=0;fors_byte<40;fors_byte=fors_byte+1) begin: fors_bytes_reverse
        for(fors_bit=0;fors_bit<8;fors_bit=fors_bit+1) begin: bits_reverse
            assign fors_bitstream[fors_byte*8+fors_bit]=hmsg_digest[fors_byte*8+7-fors_bit];
        end
    end endgenerate
    wire [8:0] target_offset=ctx_fors_offset;
    wire [13:0] fors_window=fors_bitstream[target_offset +:14];
    wire [13:0] fors_window_reverse={fors_window[0],fors_window[1],fors_window[2],fors_window[3],
        fors_window[4],fors_window[5],fors_window[6],fors_window[7],fors_window[8],fors_window[9],
        fors_window[10],fors_window[11],fors_window[12],fors_window[13]};
    wire [13:0] target_value=fors_window_reverse>>(4'd14-fors_a[3:0]);
    integer byte_index;
    always_comb begin
        parsed_tree=0;parsed_leaf=0;
        for(byte_index=0;byte_index<8;byte_index=byte_index+1)
            if(byte_index<((tree_bits+7)>>3))
                parsed_tree=(parsed_tree<<8)|{56'd0,hmsg_digest[(fors_bytes+byte_index)*8 +:8]};
        if(tree_bits<64) parsed_tree=parsed_tree&((64'd1<<tree_bits)-1'b1);
        for(byte_index=0;byte_index<2;byte_index=byte_index+1)
            if(byte_index<((hp+7)>>3))
                parsed_leaf=(parsed_leaf<<8)|{12'd0,hmsg_digest[(fors_bytes+((tree_bits+7)>>3)+byte_index)*8 +:8]};
        parsed_leaf=parsed_leaf&((20'd1<<hp)-1'b1);
    end
    wire [20:0] cursor_limit=21'd1<<ctx_height;
    wire [19:0] group_base={14'd0,ctx_group}<<fors_a;
    wire [1:0] pair_mask={ctx_chain+8'd1<chain_count,ctx_chain<chain_count};
    wire [1:0] selected_lanes=select_lanes(d,ctx_mask);
    wire [1:0] issue_mask=select_lanes(a,ctx_mask);
    wire [21:0] cursor_next={1'b0,ctx_cursor}+imm[1:0];
    wire [9:0] fors_offset_next={1'b0,ctx_fors_offset}+{2'd0,fors_a};
    wire [7:0] macro_chain_index={1'b0,ctx_chain}+{7'd0,issue_mask[1]};
    wire [7:0] chain_next={1'b0,ctx_chain}+imm[1:0];
    wire [4:0] requested_height=d==0 ? hp[4:0] : d==1 ? fors_a[4:0] : imm[4:0];
    logic [20:0] begin_index;
    always_comb case(d)
        0:begin_index=ctx_cursor;
        1:begin_index={1'b0,ctx_target};
        2:begin_index={1'b0,ctx_leaf};
        default:begin_index=imm[20:0];
    endcase
    logic [20:0] memory_address;
    always_comb case(b)
        IDX_LEVEL:memory_address={16'd0,ctx_level};
        IDX_CHAIN0:memory_address={9'd0,ctx_chain};
        IDX_CHAIN1:memory_address={9'd0,ctx_chain}+16'd1;
        IDX_GROUP:memory_address={15'd0,ctx_group};
        IDX_CURSOR:memory_address=ctx_cursor;
        IDX_REDUCE_LEFT:memory_address={8'd0,ctx_reduce_index,1'b0};
        IDX_REDUCE_RIGHT:memory_address={8'd0,ctx_reduce_index,1'b1};
        IDX_REDUCE_OUT:memory_address={9'd0,ctx_reduce_index};
        default:memory_address=imm[20:0];
    endcase
    wire [6:0] list_address=group_valid ? lane_list0[0] : memory_address[6:0];
    wire [255:0] list_value=list_address<68 ? node_memory_read : 256'd0;
    wire [6:0] cpu_load_address=a==0 ? memory_address[6:0]
        : (a==1 ? 7'd68 : 7'd89)+memory_address[6:0];
    assign node_memory_read_address=chain_active && chain_state==CHAIN_CAP ? 7'd123
        : chain_active && family_xmss ? (chain_state==CHAIN_VALUE_INIT
            ? (chain_slot ? 7'd117 : 7'd116) : 7'd124)
        : group_valid
        ? ((group_recipe[59:56]==12 || group_recipe[59:56]==15) ? list_address
            : {3'b111,(group_recipe[59:56]==4 || group_recipe[59:56]==8 || group_recipe[59:56]==11) ? 4'd0 : result_object})
        : opcode==OP_LOAD ? cpu_load_address
        : opcode==OP_XMSS_MASK ? (d==0 ? 7'd121 : 7'd122) : {3'b111,node_source_address};
    always_comb begin
        node_memory_write=0;
        node_memory_write_address=0;
        node_memory_write_value=0;
        if(scratch_write) begin
            node_memory_write=1;
            node_memory_write_address={3'b111,cpu_node_target[3:0]};
            node_memory_write_value=cpu_node_value;
        end else if(execute && opcode==OP_STORE) begin
            node_memory_write=1;
            node_memory_write_address=d==0 ? memory_address[6:0]
                : (d==1 ? 7'd68 : 7'd89)+memory_address[6:0];
            node_memory_write_value=read_node(a);
        end else if(result_write) begin
            node_memory_write=1;
            node_memory_write_address={3'b111,result_object};
            node_memory_write_value=trim_node(physical_value[255:0]);
        end else if(chain_private_write) begin
            node_memory_write=1;
            node_memory_write_address=7'd124;
            node_memory_write_value=chain_state==CHAIN_VALUE_INIT ? node_memory_read : physical_value[255:0];
        end else if(chain_capture_write) begin
            node_memory_write=1;
            node_memory_write_address=7'd123;
            node_memory_write_value=family_xmss ? node_memory_read : trim_node(physical_value[255:0]);
        end else if(chain_cap_commit) begin
            node_memory_write=1;
            node_memory_write_address=chain_slot ? 7'd120 : 7'd119;
            node_memory_write_value=node_memory_read;
        end else if(chain_result_commit) begin
            node_memory_write=1;
            node_memory_write_address=chain_slot ? 7'd117 : 7'd116;
            node_memory_write_value=family_xmss ? node_memory_read : trim_node(physical_value[255:0]);
        end
    end
    logic condition;
    always_comb begin
        condition=0;
        case(d)
            COND_CURSOR_MORE:condition=ctx_cursor<cursor_limit;
            COND_CHAIN_MORE:condition=ctx_chain<chain_count;
            COND_GROUP_MORE:condition=ctx_group<fors_k;
            COND_LAYER_MORE:condition=ctx_layer<layers;
            COND_FINAL_LAYER:condition=ctx_layer+8'd1==layers;
            COND_LEVEL_MORE:condition=ctx_level<ctx_height;
            COND_TARGET_LEAF:condition=ctx_cursor==ctx_target;
            COND_INDEX_ODD:condition=ctx_index[0];
            COND_AUTH_MATCH:condition=ctx_index==(ctx_path^20'd1);
            COND_SAME_PARENT:condition=ctx_index[19:1]==ctx_path[19:1];
            COND_STEP_EQ_DIGIT:condition=ctx_step[a[0]]==ctx_digit[a[0]];
            COND_STEP_MORE:condition=ctx_step[a[0]]<15;
            COND_LANE_ENABLED:condition=ctx_mask[a[0]];
            COND_MASK_ZERO:condition=ctx_mask==0;
            COND_FORS_PAIR_TARGET:condition=ctx_cursor=={ctx_target[19:1],1'b0};
            COND_REDUCE_MORE:condition=ctx_reduce_index<ctx_reduce_span;
            COND_REDUCE_AGAIN:condition=ctx_reduce_span>1;
            COND_ROOT_EQUAL:condition=root_equal;
            COND_LTREE_PAIR:condition={ctx_reduce_index,1'b1}<{1'b0,ctx_reduce_span};
            COND_LTREE_MORE:condition={ctx_reduce_index,1'b0}<{1'b0,ctx_reduce_span};
            default:condition=0;
        endcase
    end
    logic illegal;
    wire metadata_safe=typed_metadata(opcode);
    wire job_accept=phase==IDLE && job_valid && !error && config_valid
        && image_header[63:32]==32'h48425350 && image_header[31:27]==5'd3
        && job_operation<=2 && index_valid && (job_operation==0 ? job_message_length==0
            : (family_stateful || job_message_length>0) && job_message_length<=MAX_MESSAGE_BYTES);
    wire execute=phase==EXEC && ir_valid && !error && !lane_fault && !illegal;

    // A malformed instruction retires nothing and changes no context, node,
    // stream, or lane result. Fault control only cancels execution.
    always_comb begin
        retire=chain_complete;redirect=0;redirect_pc=imm[8:0];halt_fetch=0;illegal=0;
        if(phase==EXEC && ir_valid && !error && !lane_fault) begin
            illegal=!typed_encoding_valid(ir) || (group_valid && !metadata_safe && opcode!=OP_WAIT);
            retire=1;
            if(!illegal) case(opcode)
                OP_LAYER_NEXT:illegal=ctx_layer>=layers;
                OP_GROUP_NEXT:illegal=ctx_group>=fors_k || fors_offset_next>10'd320;
                OP_CURSOR_NEXT:illegal=cursor_next>{1'b0,cursor_limit};
                OP_CHAIN_NEXT:illegal=ctx_chain>=chain_count || chain_next>chain_count+8'd1;
                OP_HEIGHT:illegal=requested_height==0 || requested_height>(family_slh ? (d==2 ? 4 : 14) : 20);
                OP_TARGET:illegal=d==0 && (!hmsg_valid || ctx_group>=fors_k);
                OP_DIGITS:retire=1;
                OP_DIGIT_LOAD:illegal=!digits_valid
                    || (selected_lanes[0] && (ctx_chain>=chain_count || ctx_chain>=len1+8'd3))
                    || (selected_lanes[1] && (ctx_chain+8'd1>=chain_count || ctx_chain+8'd1>=len1+8'd3));
                OP_STEP_INIT:illegal=a==1 && (!digits_valid || (selected_lanes & ~ctx_digit_valid)!=0);
                OP_STEP_NEXT:illegal=(selected_lanes[0] && ctx_step[0]==15)
                    || (selected_lanes[1] && ctx_step[1]==15);
                OP_MASK:illegal=d==3 && (!digits_valid || (pair_mask & ~ctx_digit_valid)!=0);
                OP_NODE_BEGIN:illegal=ctx_height==0 || begin_index>=cursor_limit
                    || ctx_target>=cursor_limit || (a==1 && ctx_group>=fors_k);
                OP_NODE_PARENT,OP_LEVEL_NEXT:illegal=ctx_level>=ctx_height;
                OP_ADRS:case(d)
                    0,1:illegal=ctx_chain>=chain_count || (d==0 && ctx_cursor>=(21'd1<<hp));
                    2:illegal=ctx_group>=fors_k || ctx_cursor>=(21'd1<<fors_a);
                    3:illegal=ctx_group>=fors_k || ctx_target>=(21'd1<<fors_a);
                    4:illegal=ctx_group>=fors_k;
                    5:illegal=ctx_level>ctx_height || (family_xmss && ctx_level==0);
                    6:illegal=a==0 && ctx_cursor>=(21'd1<<hp);
                    8:illegal=ctx_reduce_index>=ctx_reduce_span || ctx_level==0;
                    9,10:illegal=!family_xmss || ctx_reduce_span<=1 || {ctx_reduce_index,1'b1}>={1'b0,ctx_reduce_span}
                        || ctx_level>7 || (d==9 && ctx_cursor>=(21'd1<<hp));
                    default:begin end
                endcase
                OP_REDUCE_INIT:illegal=d==2 ? !family_xmss
                    : cursor_limit>68 || ctx_height==0 || (d==1 && ctx_group>=fors_k);
                OP_REDUCE_NEXT:illegal=d==0 ? ctx_reduce_index>=ctx_reduce_span
                    : (ctx_reduce_span<=1 || ctx_level>=ctx_height || (d==2 && !family_xmss));
                OP_XMSS_MASK:illegal=!family_xmss;
                OP_PARSE:illegal=!hmsg_valid;
                OP_LOAD:illegal=memory_address>=(a==0 ? 68 : family_slh ? 16 : a==1 ? 21 : 20);
                OP_STORE:illegal=memory_address>=(d==0 ? 68 : family_slh ? 16 : d==1 ? 21 : 20);
                OP_HASH:illegal=(issue_mask!=2'b01 && issue_mask!=2'b10)
                    || (family_slh && ((descriptor_data[59:56]!=1 && descriptor_data[59:56]!=2
                        && descriptor_data[59:56]!=3 && descriptor_data[59:56]!=4 && descriptor_data[59:56]!=12)
                        || (issue_mask[1] && descriptor_data[59:56]!=1 && descriptor_data[59:56]!=2)
                        || (issue_mask[1] && descriptor_data[59:56]==2 && descriptor_data[47:40]!=1)))
                    || (family_stateful && issue_mask[1] && descriptor_data[59:56]!=5 && descriptor_data[59:56]!=6
                        && descriptor_data[59:56]!=9 && descriptor_data[59:56]!=10)
                    || (family_xmss && (descriptor_data[59:56]<5 || descriptor_data[59:56]>8))
                    || (family_lms && (descriptor_data[59:56]<9 || descriptor_data[59:56]==12))
                    ;
                OP_CHAIN:begin
                    retire=0;
                    illegal=(issue_mask!=2'b01 && issue_mask!=2'b10)
                        || macro_chain_index>=chain_count
                        || (b==0 && ctx_cursor>=(21'd1<<hp))
                        || (d!=CHAIN_FULL && (!digits_valid || !ctx_digit_valid[issue_mask[1]]));
                end
                OP_WAIT:begin retire=group_complete;illegal=!group_valid;end
                OP_INPUT:begin retire=verify_valid;illegal=operation!=2;end
                OP_EMIT:illegal=operation==2;
                OP_ROOT_COMPARE:illegal=operation!=2;
                OP_END:begin halt_fetch=1;illegal=operation==2 && !root_compare_valid;end
                OP_JMP:redirect=1;
                OP_BR:begin
                    redirect=condition^b[0];
                    illegal=(d==COND_ROOT_EQUAL && !root_compare_valid)
                        || (d==COND_STEP_EQ_DIGIT && !ctx_digit_valid[a[0]])
                        || ((d==COND_LTREE_PAIR || d==COND_LTREE_MORE) && !family_xmss);
                end
                default:begin end
            endcase
            if(illegal) begin retire=0;redirect=0;halt_fetch=1;end
        end
        if(lane_fault) halt_fetch=1;
    end
    assign job_ready=phase==IDLE && !error;
    assign message_ready=phase==MESSAGE;
    assign verify_ready=phase==EXEC && ir_valid && opcode==OP_INPUT && !group_valid
        && operation==2 && !error && !lane_fault && !illegal;
    assign out_bytes=node_bytes;
    assign busy=phase!=IDLE && phase!=FAILED;
    always_ff @(posedge clk) begin
        if(rst || job_accept) begin
            ctx_layer<=0;ctx_tree<=0;ctx_leaf<=job_accept && family_stateful && job_operation!=0 ? job_index[19:0] : 20'd0;ctx_group<=0;ctx_fors_offset<=0;ctx_target<=0;
            ctx_cursor<=0;ctx_chain<=0;ctx_height<=0;ctx_level<=0;
            ctx_index<=0;ctx_path<=0;ctx_fors_base<=0;ctx_mask<=0;
            ctx_reduce_index<=0;ctx_reduce_span<=0;ctx_digit_valid<=0;ctx_address_type<=0;
            for(integer lane=0;lane<2;lane=lane+1) begin
                ctx_step[lane]<=0;ctx_digit[lane]<=0;
                addr_leaf[lane]<=0;addr_a[lane]<=0;addr_b[lane]<=0;
            end
        end else if(chain_complete) begin
            ctx_step[chain_slot]<=chain_terminal;
        end else if(execute) begin
            case(opcode)
                OP_LAYER_INIT:ctx_layer<=d==0 ? 5'd0 : layers[4:0]-5'd1;
                OP_LAYER_NEXT:ctx_layer<=ctx_layer+5'd1;
                OP_TREE_NEXT:begin
                    ctx_leaf<=ctx_tree[19:0]&((20'd1<<hp)-1'b1);
                    ctx_tree<=ctx_tree>>hp;
                end
                OP_GROUP_INIT:begin ctx_group<=0;ctx_fors_offset<=0;end
                OP_GROUP_NEXT:begin ctx_group<=ctx_group+6'd1;ctx_fors_offset<=fors_offset_next[8:0];end
                OP_CURSOR_INIT:ctx_cursor<=0;
                OP_CURSOR_NEXT:ctx_cursor<=cursor_next[20:0];
                OP_CHAIN_INIT:begin ctx_chain<=0;ctx_digit_valid<=0;end
                OP_CHAIN_NEXT:begin ctx_chain<=chain_next[6:0];ctx_digit_valid<=0;end
                OP_HEIGHT:ctx_height<=requested_height;
                OP_TARGET:ctx_target<=d==0 ? {6'd0,target_value} : ctx_leaf;
                OP_DIGITS:ctx_digit_valid<=0;
                OP_DIGIT_LOAD:begin
                    if(selected_lanes[0]) ctx_digit[0]<=read_digit(ctx_chain);
                    if(selected_lanes[1]) ctx_digit[1]<=read_digit(ctx_chain+7'd1);
                    ctx_digit_valid<=ctx_digit_valid|selected_lanes;
                end
                OP_STEP_INIT:begin
                    if(selected_lanes[0]) ctx_step[0]<=a==0 ? 4'd0 : ctx_digit[0];
                    if(selected_lanes[1]) ctx_step[1]<=a==0 ? 4'd0 : ctx_digit[1];
                end
                OP_STEP_NEXT:begin
                    if(selected_lanes[0]) ctx_step[0]<=ctx_step[0]+4'd1;
                    if(selected_lanes[1]) ctx_step[1]<=ctx_step[1]+4'd1;
                end
                OP_MASK:case(d)
                    0:ctx_mask<=imm[1:0];
                    1:ctx_mask<=pair_mask;
                    2:ctx_mask<=pair_mask & {ctx_step[1]<15,ctx_step[0]<15};
                    3:ctx_mask<=pair_mask & {ctx_step[1]<ctx_digit[1],ctx_step[0]<ctx_digit[0]};
                    default:begin end
                endcase
                OP_NODE_BEGIN:begin
                    ctx_level<=0;ctx_index<=begin_index[19:0];ctx_path<=ctx_target;
                    ctx_fors_base<=a==1 ? group_base : 20'd0;
                end
                OP_NODE_PARENT:begin
                    ctx_level<=ctx_level+5'd1;ctx_index<=ctx_index>>1;
                    ctx_path<=ctx_path>>1;ctx_fors_base<=ctx_fors_base>>1;
                end
                OP_LEVEL_INIT:ctx_level<=0;
                OP_LEVEL_NEXT:ctx_level<=ctx_level+5'd1;
                OP_ADRS:case(d)
                    0,1:begin
                        ctx_address_type<=0;
                        for(integer lane=0;lane<2;lane=lane+1) begin
                            addr_leaf[lane]<=d==0 ? ctx_cursor[19:0] : ctx_leaf;
                            addr_a[lane]<=ctx_chain+7'(lane);
                            addr_b[lane]<={28'd0,ctx_step[lane]};
                        end
                    end
                    2,3:begin
                        for(integer lane=0;lane<2;lane=lane+1) begin
                            addr_leaf[lane]<=ctx_leaf;addr_a[lane]<=0;
                            addr_b[lane]<={12'd0,group_base}+(d==2 ? {11'd0,ctx_cursor} : {12'd0,ctx_target})+(d==2 ? 32'(lane) : 32'd0);
                        end
                    end
                    4,5:begin
                        ctx_address_type<=d==5 ? 2'd2 : 2'd0;
                        for(integer lane=0;lane<2;lane=lane+1) begin
                            addr_leaf[lane]<=d==4 ? ctx_leaf : 20'd0;
                            addr_a[lane]<=family_xmss && d==5 ? 7'(ctx_level-5'd1) : {2'd0,ctx_level};
                            addr_b[lane]<=family_lms && d==5 ? (32'd1<<(hp-ctx_level))+{12'd0,ctx_index}
                                : (d==4 ? {12'd0,ctx_fors_base} : 32'd0)+{12'd0,ctx_index};
                        end
                    end
                    6,7:begin
                        for(integer lane=0;lane<2;lane=lane+1) begin
                            addr_leaf[lane]<=d==7 || a==1 ? ctx_leaf : ctx_cursor[19:0];
                            addr_a[lane]<=0;addr_b[lane]<=0;
                        end
                    end
                    8:begin
                        for(integer lane=0;lane<2;lane=lane+1) begin
                            addr_leaf[lane]<=a==1 ? ctx_leaf : 20'd0;
                            addr_a[lane]<={2'd0,ctx_level};
                            addr_b[lane]<=(a==1 ? {12'd0,ctx_fors_base} : 32'd0)+{25'd0,ctx_reduce_index};
                        end
                    end
                    9,10:begin
                        ctx_address_type<=1;
                        for(integer lane=0;lane<2;lane=lane+1) begin
                            addr_leaf[lane]<=d==9 ? ctx_cursor[19:0] : ctx_leaf;
                            addr_a[lane]<={2'd0,ctx_level};addr_b[lane]<={25'd0,ctx_reduce_index};
                        end
                    end
                    default:begin end
                endcase
                OP_REDUCE_INIT:begin
                    ctx_reduce_span<=d==2 ? 7'd67 : cursor_limit[6:0];ctx_reduce_index<=0;
                    ctx_level<=0;ctx_fors_base<=d==1 ? group_base : 20'd0;
                end
                OP_REDUCE_NEXT:begin
                    if(d==0) ctx_reduce_index<=ctx_reduce_index+7'd1;
                    else begin
                        ctx_reduce_span<=d==2 ? (ctx_reduce_span+8'd1)>>1 : ctx_reduce_span>>1;ctx_reduce_index<=0;
                        ctx_level<=ctx_level+5'd1;ctx_fors_base<=ctx_fors_base>>1;
                    end
                end
                OP_PARSE:begin ctx_tree<=parsed_tree;ctx_leaf<=parsed_leaf;end
                default:begin end
            endcase
        end
    end
    // Optional observation counters have no control role and vanish when
    // PROFILE_ENABLE is false. Busy includes recipe setup and commit clocks.
    always_ff @(posedge clk) begin
        if(rst || job_accept || !PROFILE_ENABLE) begin
            macro_count<=0;macro_busy_cycles<=0;macro_hashes<=0;
        end else if(!error) begin
            if(chain_start) macro_count<=macro_count+64'd1;
            if(chain_active) macro_busy_cycles<=macro_busy_cycles+64'd1;
            if(chain_issue) macro_hashes<=macro_hashes+64'd1;
        end
    end
    always_ff @(posedge clk) begin
        if(rst) begin
            phase<=IDLE;operation<=0;done<=0;error<=0;error_code<=0;verify_pass<=0;
            out_valid<=0;out_data<=0;cycles<=0;hash_base<=0;permutation_base<=0;
            message_length<=0;message_received<=0;
            hmsg_digest<=0;hmsg_valid<=0;digits_valid<=0;digit_checksum<=0;
            root_equal<=0;root_compare_valid<=0;group_valid<=0;group_mask<=0;
            group_recipe<=0;group_layer<=0;group_tree<=0;group_address_type<=0;
            accepted_index<=0;accepted_identifier<=0;accepted_randomizer<=0;
            chain_state<=CHAIN_SEED;chain_mode<=0;chain_slot<=0;chain_digit<=0;
            chain_f_bytes<=0;chain_f_blocks<=0;chain_expected_hashes<=0;
            chain_seed_blocks<=0;chain_key_blocks<=0;chain_mask_blocks<=0;chain_pending_terminal<=0;
            chain_hash_kind<=C_SEED;chain_feedback<=0;chain_shadow_valid<=0;
            group_leaf_value<=0;group_a_value<=0;group_b_value<=0;
        end else begin
            done<=0;out_valid<=0;
            if(PROFILE_ENABLE && phase!=IDLE && phase!=FAILED) cycles<=cycles+1'b1;
            if(lane_fault) begin
                group_valid<=0;chain_shadow_valid<=0;if(family_xmss) hmsg_digest<=0;fault(16'h3007);
            end else if(illegal) begin
                group_valid<=0;chain_shadow_valid<=0;fault(16'h3006);
            end else case(phase)
                IDLE:if(job_valid && !error) begin
                    if(!config_valid || image_header[63:32]!=32'h48425350 || image_header[31:27]!=5'd3)
                        fault(16'h3006);
                    else if(job_operation>2 || (job_operation==0 ? job_message_length!=0
                        : (!family_stateful && job_message_length==0) || job_message_length>87)) fault(16'h3002);
                    else if(!index_valid) fault(16'h3008);
                    else begin
                        accepted_index<=job_index;accepted_identifier<=job_identifier;accepted_randomizer<=job_randomizer;
                        operation<=job_operation;verify_pass<=0;cycles<=0;
                        root_equal<=0;root_compare_valid<=0;
                        hash_base<=total_hashes;permutation_base<=total_permutations;
                        message_length<=job_message_length;message_received<=0;
                        hmsg_digest<=0;hmsg_valid<=0;digits_valid<=0;
                        phase<=job_operation==0 || job_message_length==0 ? LAUNCH : MESSAGE;
                    end
                end
                MESSAGE:if(message_valid) begin
                    message_received<=message_received+7'd8;
                    if(message_received+7'd8>=message_length) phase<=LAUNCH;
                end
                LAUNCH:phase<=EXEC;
                EXEC:if(ir_valid) begin
                    case(opcode)
                        OP_NMOV:begin
                            if(d==2 || d==3) root_compare_valid<=0;
                        end
                        OP_LOAD:begin
                            if(d==2 || d==3) root_compare_valid<=0;
                        end
                        OP_HASH:begin
                            group_valid<=1;group_mask<=issue_mask;
                            group_recipe<=descriptor_data;group_layer<=ctx_layer;group_tree<=ctx_tree;
                            group_address_type<=family_lms ? 2'd0 : ctx_address_type;
                            group_leaf_value<=addr_leaf[issue_mask[1]];
                            group_a_value<=addr_a[issue_mask[1]];
                            group_b_value<=addr_b[issue_mask[1]];
                        end
                        OP_CHAIN:begin
                            phase<=MACRO;chain_state<=CHAIN_SEED;
                            chain_mode<=d[1:0];chain_slot<=issue_mask[1];
                            chain_digit<=d==CHAIN_FULL ? 4'd0 : ctx_digit[issue_mask[1]];
                            if(family_xmss) chain_expected_hashes<=d==CHAIN_FULL || d==CHAIN_CAP_FULL ? 6'd46
                                : d==CHAIN_CAP_PREFIX ? 6'd1+6'(ctx_digit[issue_mask[1]])*6'd3
                                : (6'd15-6'(ctx_digit[issue_mask[1]]))*6'd3;
                            else chain_expected_hashes<=d==CHAIN_FULL || d==CHAIN_CAP_FULL ? 6'd16
                                : d==CHAIN_CAP_PREFIX ? 6'd1+{2'd0,ctx_digit[issue_mask[1]]}
                                : 6'd15-{2'd0,ctx_digit[issue_mask[1]]};
                            chain_hash_kind<=d==CHAIN_SUFFIX && !family_xmss ? C_F : C_SEED;chain_feedback<=0;chain_shadow_valid<=0;
                            group_valid<=0;group_mask<=issue_mask;
                            group_layer<=ctx_layer;group_tree<=ctx_tree;group_address_type<=0;
                            group_leaf_value<=b==0 ? ctx_cursor[19:0] : ctx_leaf;
                            group_a_value<=macro_chain_index[6:0];
                            group_b_value<=d==CHAIN_SUFFIX ? {28'd0,ctx_digit[issue_mask[1]]} : 32'd0;
                        end
                        OP_WAIT:if(group_complete) begin
                            if(group_mask[0] && group_recipe[59:56]==4) begin hmsg_digest<=result[0];hmsg_valid<=1;end
                            group_valid<=0;
                        end
                        OP_DIGITS:begin digit_message<=node[2];digit_checksum<={2'd0,checksum_total};digits_valid<=1;end
                        OP_INPUT:if(verify_valid) begin
                            if(d==2 || d==3) root_compare_valid<=0;
                        end
                        OP_EMIT:begin out_valid<=1;out_data<=read_node(a);end
                        OP_ROOT_COMPARE:begin root_equal<=read_node(2)==read_node(3);root_compare_valid<=1;end
                        OP_END:begin verify_pass<=operation==2 && root_equal;phase<=FINISH;end
                        default:begin end
                    endcase
                end
                MACRO:case(chain_state)
                    CHAIN_SEED:begin
                        if(!chain_recipe_valid(descriptor_data,1'b1)) begin
                            chain_shadow_valid<=0;fault(16'h3006);
                        end else begin
                            group_recipe<=descriptor_data;chain_seed_blocks<=descriptor_data[29:24];chain_state<=CHAIN_F;
                        end
                    end
                    CHAIN_F:begin
                        if(!chain_recipe_valid(descriptor_data,1'b0)) begin
                            chain_shadow_valid<=0;fault(16'h3006);
                        end else begin
                            chain_f_bytes<=descriptor_data[37:32];chain_f_blocks<=descriptor_data[29:24];
                            if(family_xmss) chain_state<=CHAIN_KEY_CHECK;
                            else begin
                                if(chain_mode==CHAIN_SUFFIX) group_recipe<=descriptor_data;
                                if(chain_mode==CHAIN_SUFFIX && chain_digit==15) chain_state<=CHAIN_DONE;
                                else begin group_valid<=1;chain_state<=CHAIN_ISSUE;end
                            end
                        end
                    end
                    CHAIN_KEY_CHECK:begin
                        if(!chain_key_recipe_valid(descriptor_data,1'b0)) begin
                            chain_shadow_valid<=0;fault(16'h3006);
                        end else begin chain_key_blocks<=descriptor_data[29:24];chain_state<=CHAIN_MASK_CHECK;end
                    end
                    CHAIN_MASK_CHECK:begin
                        if(!chain_key_recipe_valid(descriptor_data,1'b1)) begin
                            chain_shadow_valid<=0;fault(16'h3006);
                        end else begin
                            chain_mask_blocks<=descriptor_data[29:24];
                            if(chain_mode==CHAIN_SUFFIX && chain_digit==15) chain_state<=CHAIN_DONE;
                            else begin
                                group_valid<=1;
                                if(chain_mode==CHAIN_SUFFIX) begin
                                    group_recipe<=chain_key_recipe;chain_hash_kind<=C_KEY;chain_state<=CHAIN_VALUE_INIT;
                                end else chain_state<=CHAIN_ISSUE;
                            end
                        end
                    end
                    CHAIN_VALUE_INIT:if(chain_issue) chain_state<=CHAIN_RUN;
                    CHAIN_ISSUE:if(chain_issue) chain_state<=CHAIN_RUN;
                    CHAIN_RUN:if(chain_response) begin
                        if(family_xmss && chain_hash_kind==C_KEY) hmsg_digest[255:0]<=physical_value[255:0];
                        if(chain_capture_now && !family_xmss) chain_shadow_valid<=1;
                        if(family_xmss && chain_capture_now) begin
                            chain_pending_terminal<=chain_at_end;
                            group_recipe<=chain_next_recipe;chain_hash_kind<=chain_next_kind;
                            group_b_value<={28'd0,chain_next_step};
                            chain_state<=CHAIN_CAPTURE_SAVE;
                        end else if(chain_at_end) begin
                            group_valid<=0;
                            if(chain_capture_mode && !(chain_shadow_valid || chain_capture_now)) begin
                                chain_shadow_valid<=0;fault(16'h3006);
                            end else chain_state<=chain_capture_mode ? CHAIN_CAP : CHAIN_RESULT;
                        end else begin
                            chain_feedback<=1;chain_hash_kind<=chain_next_kind;
                            group_recipe<=chain_next_recipe;
                            group_b_value<={28'd0,chain_next_step};
                            chain_state<=chain_issue ? CHAIN_RUN : CHAIN_ISSUE;
                        end
                    end
                    CHAIN_CAPTURE_SAVE:begin
                        chain_shadow_valid<=1;
                        if(chain_pending_terminal) begin group_valid<=0;chain_state<=CHAIN_CAP;end
                        else if(chain_issue) chain_state<=CHAIN_RUN;
                    end
                    CHAIN_CAP:chain_state<=CHAIN_RESULT;
                    CHAIN_RESULT:chain_state<=CHAIN_DONE;
                    CHAIN_DONE:begin
                        chain_shadow_valid<=0;phase<=EXEC;
                        // The H_msg buffer is invalid throughout a stateful Job.
                        // Return it to its canonical invalid observation after use.
                        if(family_xmss) hmsg_digest<=0;
                    end
                    default:begin group_valid<=0;chain_shadow_valid<=0;fault(16'h3006);end
                endcase
                FINISH:begin done<=1;phase<=IDLE;end
                FAILED:group_valid<=0;
                default:fault(16'h3006);
            endcase
        end
    end
endmodule
`default_nettype wire
