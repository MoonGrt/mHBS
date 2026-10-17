`timescale 1ns/1ps
`default_nettype none
// HBS microprogram ABI 4, fixed K1U1. HASH executes one Hash, CHAIN one
// WOTS chain, and TREE one bounded HT/FORS tree; image selects groups/layers.
// L0/L1 are logical node/context slots sharing one physical Hash lane.
// Only typed metadata and branch instructions may retire between HASH and its explicit WAIT.
module executor #(
    parameter integer UNROLL=1, LANES=1,
    parameter bit PROFILE_ENABLE=0, SWAP_PHYSICAL_LANES=0
) (
    input wire [63:0] image_header, profile_descriptor,
    output wire [8:0] program_address,
    input wire [63:0] program_data,
    input wire [8:0] job_entry,
    output wire [4:0] descriptor_address,
    input wire [63:0] descriptor_data,
    input wire clk, rst,
    input wire job_valid, output wire job_ready, input wire [1:0] job_operation,
    input wire [6:0] job_message_length,
    input wire [255:0] job_secret_seed, job_secret_prf, job_public_seed, job_randomizer, job_public_root,
    input wire message_valid, output wire message_ready,
    input wire [63:0] message_data,
    input wire verify_valid, output wire verify_ready,
    input wire [255:0] verify_data,
    output logic verify_pass,
    output logic out_valid, output logic [255:0] out_data,
    output wire [5:0] out_bytes,
    output wire busy, output logic done, error, output logic [15:0] error_code,
    output wire [31:0] hash_count, permutation_count,
    output logic [31:0] cycles
);
    `include "rtl/executor/instructions.svh"
    localparam integer MAX_MESSAGE_BYTES=87;
    typedef enum logic [2:0] {IDLE,MESSAGE,LAUNCH,EXEC,FINISH,FAILED,MACRO,TREE_RUN} phase_t;
    phase_t phase;
    logic [1:0] operation;
    wire [7:0] n=profile_descriptor[7:0], hp=profile_descriptor[15:8];
    wire [7:0] layers=profile_descriptor[23:16], fors_k=profile_descriptor[31:24];
    wire [7:0] fors_a=profile_descriptor[39:32], digest_bytes=profile_descriptor[47:40];
    wire [7:0] total_height=profile_descriptor[55:48], chain_count=profile_descriptor[63:56];
    wire [5:0] node_bytes=tree_owner ? tree_node_bytes : {n[5:3],3'd0};
    wire [7:0] len1={2'd0,node_bytes}<<1;
    wire [8:0] fors_bytes=({1'b0,fors_k}*{1'b0,fors_a}+9'd7)>>3;
    wire [7:0] tree_bits=total_height-hp;
    wire config_valid=(n==16 || n==24 || n==32) && hp>0 && hp<=10
        && layers>0 && layers<=31 && fors_k>0 && fors_k<=35 && fors_a>0 && fors_a<=14
        && (fors_k*fors_a)<=320 && digest_bytes<=49 && digest_bytes>0
        && total_height>=hp && tree_bits<=64 && chain_count<=67 && chain_count>0;

    // Every architectural field has fixed writers. There is no indexed scalar
    // register file, general integer ALU, or common scalar writeback network.
    logic [4:0] ctx_layer;
    logic [63:0] ctx_tree;
    logic [9:0] ctx_leaf;
    logic [5:0] ctx_group;
    // Digest bit offset is part of the bounded FORS context. Only explicit
    // GROUP_INIT/NEXT update it; this avoids a multiplier before TARGET.
    logic [8:0] ctx_fors_offset;
    logic [13:0] ctx_target;
    logic [14:0] ctx_cursor;
    logic [6:0] ctx_chain;
    logic [3:0] ctx_step [0:1],ctx_digit [0:1];
    logic [3:0] ctx_height,ctx_level;
    logic [13:0] ctx_index,ctx_path;
    logic [19:0] ctx_fors_base;
    logic [1:0] ctx_mask,ctx_digit_valid;
    logic [6:0] ctx_reduce_index,ctx_reduce_span;
    logic [9:0] addr_leaf [0:1];
    logic [6:0] addr_a [0:1];
    // Every typed ADRS constructor is bounded by the FORS address domain:
    // at most 35 trees of height 14, so all legal B values fit in 20 bits.
    // Serialization restores the fixed 32-bit ADRS word with zero extension.
    logic [19:0] addr_b [0:1];
    logic root_equal,root_compare_valid;
    localparam [1:0] CHAIN_FULL=0,CHAIN_CAP_FULL=1,CHAIN_CAP_PREFIX=2,CHAIN_SUFFIX=3;
    typedef enum logic [2:0] {CHAIN_SEED,CHAIN_F,CHAIN_ISSUE,CHAIN_RUN,
        CHAIN_CAP,CHAIN_RESULT,CHAIN_DONE} chain_state_t;
    chain_state_t chain_state;
    logic [1:0] chain_mode;
    logic chain_slot,chain_feedback,chain_hash_stage,chain_shadow_valid;
    logic [3:0] chain_digit;
    // Preflight fixes every F recipe field except the output length and
    // block limit. Snapshot only those two fields; reconstruct the validated
    // constants without retaining a second arbitrary 64-bit recipe bank.
    logic [5:0] chain_f_bytes,chain_f_blocks;
    wire [63:0] chain_f_recipe={4'd0,4'd2,8'd0,8'd1,2'd0,
        chain_f_bytes,2'd0,chain_f_blocks,24'd0};
    logic [4:0] chain_expected_hashes;
    logic [31:0] macro_count,macro_busy_cycles,macro_hashes;
    wire chain_active=phase==MACRO;
    wire [3:0] chain_terminal=chain_mode==CHAIN_CAP_PREFIX ? chain_digit : 4'd15;
    wire chain_capture_mode=chain_mode==CHAIN_CAP_FULL || chain_mode==CHAIN_CAP_PREFIX;
    wire chain_complete=chain_active && chain_state==CHAIN_DONE && !error && !tree_owner;
    wire chain_child_complete=chain_active && chain_state==CHAIN_DONE && !error && tree_owner;
    // TREE is a fixed sequencer, not a second instruction stream. It never
    // changes the image-owned layer/tree/leaf/group/target. Child CHAIN returns
    // here rather than retiring the frozen TREE instruction.
    localparam [1:0] TREE_ROOT=0,TREE_SIGN=1,TREE_VERIFY=2;
    typedef enum logic [4:0] {T_PREFLIGHT,T_INIT,T_LEAF,T_INPUT_CHAIN,T_CHILD,
        T_EMIT_CAP,T_STORE_CHAIN,T_ZERO_LEAF,
        T_COMPRESS,T_ISSUE,T_WAIT,T_CAPTURE,T_CHECK,T_MERGE_RIGHT,
        T_MERGE_LEFT,T_SAVE,T_NEXT_LEAF,T_AUTH_BEGIN,T_SECRET_EMIT,
        T_AUTH_EMIT,T_RETURN,T_CLEANUP,T_DONE,T_FORS_PREP,T_FORS_RESULT,
        T_FORS_RIGHT,T_INPUT_SECRET,T_FORS_TARGET,
        T_VERIFY_BEGIN,T_VERIFY_POSITION,T_VERIFY_RIGHT,T_VERIFY_INPUT} tree_state_t;
    tree_state_t tree_state,tree_resume;
    logic tree_owner,tree_kind,chain_child_started,tree_profile_valid;
    logic [1:0] tree_mode;
    logic [0:0] tree_flags;
    logic [2:0] tree_node_words;
    wire [5:0] tree_node_bytes={tree_node_words,3'd0};
    logic [3:0] tree_height;
    logic [6:0] tree_chain_count;
    logic [9:0] tree_leaf_snapshot;
    logic [13:0] tree_target;
    logic [19:0] tree_group_base;
    logic [3:0] tree_recipe_id;
    logic [1:0] tree_recipe_index,tree_fors_stage;
    logic [5:0] tree_recipe_blocks[0:3];
    logic [31:0] tree_count,tree_busy_cycles,tree_hashes,tree_chains,tree_input_wait_cycles,tree_child_busy_cycles;
    wire tree_active=tree_owner && (phase==TREE_RUN || phase==MACRO);
    wire [4:0] tree_outer_layer=group_layer;
    wire [63:0] tree_outer_tree=group_tree;
    wire [9:0] tree_outer_leaf=tree_leaf_snapshot;
    wire [5:0] tree_outer_group=ctx_group;
    wire [13:0] tree_outer_target=tree_target;
    wire [14:0] tree_limit=15'd1<<tree_height;
    wire tree_selected=tree_mode==TREE_SIGN && ctx_cursor=={1'b0,tree_target};
    wire tree_pair_selected=ctx_cursor=={1'b0,tree_target[13:1],1'b0};
    wire tree_capture_auth=tree_mode==TREE_SIGN && ctx_index==(ctx_path^14'd1);
    wire tree_skip_parent=!tree_kind && tree_flags[0] && ctx_index[13:1]==ctx_path[13:1];
    wire tree_complete=tree_active && phase==TREE_RUN && tree_state==T_DONE && !error;
    wire tree_cleanup=tree_active && phase==TREE_RUN && tree_state==T_CLEANUP && !error;
    wire chain_child_start=chain_active && tree_owner && !chain_child_started && !error;
    wire tree_child_start=tree_active && phase==TREE_RUN && tree_state==T_CHILD && !error;
    wire tree_response=tree_active && phase==TREE_RUN && tree_state==T_WAIT
        && group_complete && !error && !lane_fault;
    // Non-target FORS pairs need no intermediate secret/auth capture. Their
    // PRF0, PRF1, F0, F1 requests turn over while the old response is drained.
    // The sole RAM port writes the old slot and reads the other F input.
    wire tree_fors_reissue=tree_response && tree_kind && tree_mode==TREE_SIGN
        && tree_resume==T_FORS_RESULT && tree_fors_stage!=3 && !tree_pair_selected;
    wire [1:0] tree_fors_next=tree_fors_stage+2'd1;
    wire [63:0] tree_fors_next_recipe=tree_recipe(tree_fors_next[1] ? 4'd5 : 4'd4);
    wire [19:0] tree_fors_next_b=tree_group_base+{5'd0,ctx_cursor}+{19'd0,tree_fors_next[0]};
    wire tree_direct_request=tree_active && phase==TREE_RUN && !error
        && (tree_state==T_ISSUE || tree_fors_reissue);
    wire tree_issue=tree_owner && ((tree_direct_request && physical_ready) || chain_issue);
    wire [1:0] trace_owner=tree_owner ? 2'd2 : chain_active ? 2'd1 : 2'd0;
    // Stage at request acceptance, including a CHAIN response/next-F turnover.
    wire [2:0] trace_tree_stage=tree_kind ? (physical_recipe[59:56]==1 ? 3'd4
        : physical_recipe[47:40]==1 ? 3'd5 : 3'd6)
        : chain_active ? (chain_reissue || chain_hash_stage ? 3'd1 : 3'd0)
        : physical_recipe[59:56]==12 ? 3'd2 : 3'd3;
    wire [3:0] trace_tree_step=physical_b_value[3:0];
    wire [14:0] trace_tree_leaf=ctx_cursor;
    wire [6:0] trace_tree_chain=ctx_chain;
    wire [3:0] trace_tree_level=ctx_level;
    function automatic [63:0] tree_recipe(input [3:0] rid);
        reg [3:0] shape;
        reg [7:0] domain,arity;
        reg [1:0] slot;
        begin
            shape=2;domain=0;arity=1;slot=0;
            case(rid)
                4:begin shape=1;domain=6;slot=0;end
                5:begin domain=3;slot=1;end
                6:begin domain=3;arity=2;slot=2;end
                7:begin shape=1;domain=5;slot=0;end
                8:slot=1;
                9:begin shape=12;domain=1;arity={1'b0,tree_chain_count};slot=2;end
                10:begin domain=2;arity=2;slot=3;end
                default:begin end
            endcase
            tree_recipe={4'd0,shape,domain,arity,2'd0,tree_node_bytes,
                2'd0,tree_recipe_blocks[slot],24'd0};
        end
    endfunction
    function automatic tree_recipe_valid(input [63:0] value,input [3:0] rid);
        reg [63:0] expected;
        reg [12:0] input_bytes,capacity;
        begin
            expected=tree_recipe(rid);
            input_bytes=13'd32+{7'd0,tree_node_bytes}+
                (rid==9 ? (tree_node_bytes==16 ? {2'd0,tree_chain_count,4'd0}
                    : tree_node_bytes==24 ? {2'd0,tree_chain_count,4'd0}+{3'd0,tree_chain_count,3'd0}
                    : {1'd0,tree_chain_count,5'd0})
                : (rid==6 || rid==10) ? {6'd0,tree_node_bytes,1'd0} : {7'd0,tree_node_bytes});
            capacity=({7'd0,value[29:24]}<<7)+({7'd0,value[29:24]}<<3);
            tree_recipe_valid=(value & 64'hffffff3f00ffffff)==(expected & 64'hffffff3f00ffffff)
                && value[39:38]==0 && value[31:30]==0 && value[29:24]>=1 && value[29:24]<=32
                && capacity>input_bytes;
        end
    endfunction
    wire tree_start=tree_active && phase==TREE_RUN && tree_state==T_PREFLIGHT
        && tree_profile_valid && tree_recipe_valid(descriptor_data,tree_recipe_id)
        && tree_recipe_id==(tree_kind ? 4'd6 : 4'd10) && !error;
    logic tree_memory_write,tree_right_write;
    logic [6:0] tree_read_address,tree_write_address;
    logic [255:0] tree_write_value,tree_right_value;

    // Word 123 is a private transactional capture shadow. It is inaccessible
    // through every legal object/space selector and uses the existing 1R1W port.
    wire chain_capture_write,chain_cap_commit,chain_result_commit;
    wire [255:0] node [0:10];
    // Fixed architectural objects share one physical asynchronous 1R1W RAM.
    // Its addresses are private wires, never microprogram operands: LIST
    // 0..67, STACK 80..95, AUTH 96..111, node object 112+object. K1 recipes
    // consume either LIST, R, or one logical result; never two RAM operands.
    // V2, the public root V3, and RIGHT retain their dedicated fixed buses.
    (* ram_style="distributed" *) logic [255:0] node_memory [0:127];
    wire [6:0] node_memory_read_address;
    wire [255:0] node_memory_read=node_memory[node_memory_read_address];
    logic [15:0] scratch_valid;
    function automatic scratch_object(input [7:0] object);
        scratch_object=object==0 || object==1 || object==4 || object==5
            || object==7 || object==8 || object==9 || object==10;
    endfunction
    wire cpu_node_write=execute && (opcode==OP_NMOV || opcode==OP_LOAD
        || (opcode==OP_INPUT && verify_valid));
    wire [255:0] cpu_load_value=node_memory_read;
    wire [255:0] cpu_node_value=opcode==OP_NMOV ? read_node(a)
        : opcode==OP_INPUT ? trim_node(verify_data) : cpu_load_value;
    wire scratch_write=cpu_node_write && scratch_object(d);
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
        else if(tree_cleanup) scratch_valid<=scratch_valid & 16'h0013;
        else if(tree_memory_write && tree_write_address>=112 && tree_write_address<123)
            scratch_valid[tree_write_address[3:0]]<=1;
        else if(scratch_write) scratch_valid[d[3:0]]<=1;
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
                else if(object==6 && tree_cleanup) value<=0;
                else if(object==6 && tree_right_write) value<=tree_right_value;
                else if(cpu_node_write && d==object) value<=cpu_node_value;
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
        case(node_bytes)
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
                14:value=job_randomizer;
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
                2'b01:begin ir<=prefetch_word;node_source_address<=prefetch_word[43:40];ir_valid<=prefetch_valid;prefetch_valid<=0;end
                2'b10:begin
                    if(!ir_valid) begin ir<=program_data;node_source_address<=program_data[43:40];ir_valid<=1;end
                    else begin prefetch_word<=program_data;prefetch_valid<=1;end
                end
                2'b11:begin
                    ir_valid<=1;
                    if(prefetch_valid) begin ir<=prefetch_word;node_source_address<=prefetch_word[43:40];prefetch_word<=program_data;prefetch_valid<=1;end
                    else begin ir<=program_data;node_source_address<=program_data[43:40];prefetch_valid<=0;end
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
    logic [9:0] group_leaf_value;
    logic [6:0] group_a_value;
    logic [19:0] group_b_value;
    wire [9:0] group_leaf [0:1];
    wire [6:0] group_a [0:1];
    wire [31:0] group_b [0:1];
    wire [391:0] result [0:1];
    wire [1:0] lane_ready,lane_valid,lane_error;
    wire [391:0] lane_value [0:1];
    wire [6:0] lane_list0 [0:1],lane_list1 [0:1];
    wire physical_ready,physical_valid,physical_error;
    wire [391:0] physical_value;
    wire [6:0] physical_list0,physical_list1;
    logic [31:0] hash_base,permutation_base;
    wire [31:0] total_hashes,total_permutations;
    wire lane_fault=group_valid && physical_valid && physical_error;
    wire group_complete=group_valid && physical_valid;
    wire chain_response=chain_active && chain_state==CHAIN_RUN && group_complete && !error && !lane_fault;
    wire [4:0] chain_position=chain_hash_stage ? {1'b0,group_b_value[3:0]}+5'd1 : 5'd0;
    wire chain_at_end=chain_position=={1'b0,chain_terminal};
    wire chain_capture_now=chain_capture_mode && chain_position=={1'b0,chain_digit};
    assign chain_capture_write=chain_response && chain_capture_now && !rst;
    assign chain_cap_commit=chain_active && chain_state==CHAIN_CAP && !error && !rst;
    assign chain_result_commit=chain_active && chain_state==CHAIN_RESULT && !error && !rst;
    function automatic chain_recipe_valid(input [63:0] value,input bit seed);
        chain_recipe_valid=value[63:60]==0 && value[59:56]==(seed ? 4'd1 : 4'd2)
            && value[55:48]==(seed ? 8'd5 : 8'd0) && value[47:40]==8'd1
            && value[39:38]==0 && value[37:32]==node_bytes && value[31:30]==0
            && value[29:24]>=1 && value[29:24]<=32 && value[23:0]==0;
    endfunction
    // Start observes fully validated snapshots. A malformed recipe never
    // starts an instance or reaches the physical Hash lane.
    wire chain_start=chain_active && !tree_owner && chain_state==CHAIN_F && !error
        && chain_recipe_valid(descriptor_data,1'b0);
    // Only this bounded macro can authorize the next F as its predecessor
    // drains. Ordinary HASH still needs its next explicit image instruction.
    wire chain_reissue=chain_response && !chain_at_end;
    wire [3:0] chain_next_step=chain_hash_stage ? group_b_value[3:0]+4'd1 : 4'd0;
    wire macro_request=chain_active && !error && (chain_state==CHAIN_ISSUE || chain_reissue);
    wire chain_issue=macro_request && physical_ready;
    wire [63:0] physical_recipe=chain_reissue ? chain_f_recipe
        : tree_fors_reissue ? tree_fors_next_recipe : group_recipe;
    wire [31:0] physical_b_value=chain_reissue ? {28'd0,chain_next_step}
        : {12'd0,tree_fors_reissue ? tree_fors_next_b : group_b_value};
    wire [1:0] physical_mask=tree_fors_reissue ? (tree_fors_next[0] ? 2'b10 : 2'b01) : group_mask;
    // Verification-only observation wires; they add no architectural state.
    wire [1:0] trace_hash_valid=((phase==EXEC && ir_valid && opcode==OP_WAIT && group_complete && !error && !lane_fault && !illegal)
        || chain_response || tree_response)
        ? group_mask : 2'b00;
    wire [63:0] trace_recipe=group_recipe,trace_tree=group_tree;
    wire [4:0] trace_layer=group_layer;
    wire [9:0] trace_leaf[0:1];
    wire [6:0] trace_a[0:1];
    wire [31:0] trace_b[0:1];
    wire [391:0] trace_result[0:1];
    assign hash_count=PROFILE_ENABLE ? total_hashes-hash_base : 32'd0;
    assign permutation_count=PROFILE_ENABLE ? total_permutations-permutation_base : 32'd0;
    assign descriptor_address=tree_active && phase==TREE_RUN && tree_state==T_PREFLIGHT ? {1'b0,tree_recipe_id}
        : chain_active && chain_state==CHAIN_SEED ? 5'd7
        : chain_active && chain_state==CHAIN_F ? 5'd8 : d[4:0];
    genvar logical_slot;
    generate for(logical_slot=0;logical_slot<2;logical_slot=logical_slot+1) begin: logical_slots
        assign group_leaf[logical_slot]=group_leaf_value;
        assign group_a[logical_slot]=group_a_value;
        assign group_b[logical_slot]={12'd0,group_b_value};
        assign trace_leaf[logical_slot]=group_leaf_value;
        assign trace_a[logical_slot]=group_a_value;
        assign trace_b[logical_slot]={12'd0,group_b_value};
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
            .MAX_MESSAGE_BYTES(MAX_MESSAGE_BYTES),.RECIPE_MASK(16'h101e),
            .PROFILE_ENABLE(PROFILE_ENABLE)) lane (
            .clk,.rst(rst || error),.node_bytes,
            .request_valid((phase==EXEC && group_valid && !physical_valid && !error) || macro_request || tree_direct_request),.request_ready(physical_ready),
            .request_recipe(physical_recipe),
            .secret_seed(job_secret_seed),.secret_prf(job_secret_prf),.public_seed(job_public_seed),
            .root(node[3]),.randomizer(group_recipe[59:56]==4 ? scratch_read : job_randomizer),
            .message_word_address,.message_word_data,.message_length,
            .request_layer(group_layer),.request_tree(group_tree),
            .request_leaf(group_leaf_value),.request_a(group_a_value),.request_b(physical_b_value),
            // WOTS F's fixed frame already selects exactly n digest bytes.
            // Truncate architectural writes, without duplicating that mux here.
            .request_left(chain_active && (chain_feedback || chain_reissue) ? physical_value[255:0] : scratch_read),.request_right(node[6]),
            .list_index0(physical_list0),.list_index1(physical_list1),.list_data0(list_value),.list_data1(256'd0),
            .response_valid(physical_valid),
            .response_ready((phase==EXEC && ir_valid && opcode==OP_WAIT && group_complete && !error && !lane_fault && !illegal)
                || chain_response || tree_response),
            .response_value(physical_value),.error(physical_error),
            .hash_count(total_hashes),.permutation_count(total_permutations)
        );
    end endgenerate
    initial if(LANES!=1 || UNROLL!=1 || SWAP_PHYSICAL_LANES)
        $error("Microprogram production core requires fixed K1U1 without lane swap");

    // Bounded digest transforms. These circuits cannot launch a Hash.
    logic [63:0] parsed_tree;
    logic [9:0] parsed_leaf;
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
    // TREE and LEAF are adjacent in H_msg. Select one bounded byte window,
    // then reorder its bytes; separate dynamic reads per byte duplicate muxes.
    wire [79:0] address_window=80'(hmsg_digest >> {fors_bytes,3'b000});
    wire [3:0] tree_byte_count=4'((tree_bits+8'd7)>>3);
    wire [63:0] tree_window_be={address_window[7:0],address_window[15:8],
        address_window[23:16],address_window[31:24],address_window[39:32],
        address_window[47:40],address_window[55:48],address_window[63:56]};
    wire [15:0] leaf_window=16'(address_window >> {tree_byte_count,3'b000});
    always_comb begin
        parsed_tree=tree_window_be >> {(4'd8-tree_byte_count),3'b000};
        if(tree_bits<64) parsed_tree=parsed_tree&((64'd1<<tree_bits)-1'b1);
        parsed_leaf=hp>8 ? {leaf_window[7:0],leaf_window[15:8]} : {2'd0,leaf_window[7:0]};
        parsed_leaf=parsed_leaf&((10'd1<<hp)-1'b1);
    end
    wire [14:0] cursor_limit=15'd1<<ctx_height;
    wire [19:0] group_base={14'd0,ctx_group}<<fors_a;
    wire [1:0] pair_mask={ctx_chain+8'd1<chain_count,ctx_chain<chain_count};
    wire [1:0] selected_lanes=select_lanes(d,ctx_mask);
    wire [1:0] issue_mask=select_lanes(a,ctx_mask);
    wire [15:0] cursor_next={1'b0,ctx_cursor}+imm[1:0];
    wire [9:0] fors_offset_next={1'b0,ctx_fors_offset}+{2'd0,fors_a};
    wire [7:0] chain_next={1'b0,ctx_chain}+imm[1:0];
    wire [7:0] macro_chain_index={1'b0,ctx_chain}+{7'd0,issue_mask[1]};
    wire [3:0] requested_height=d==0 ? hp[3:0] : d==1 ? fors_a[3:0] : imm[3:0];
    logic [14:0] begin_index;
    always_comb case(d)
        0:begin_index=ctx_cursor;
        1:begin_index={1'b0,ctx_target};
        2:begin_index={5'd0,ctx_leaf};
        default:begin_index=imm[14:0];
    endcase
    logic [15:0] memory_address;
    always_comb case(b)
        IDX_LEVEL:memory_address={12'd0,ctx_level};
        IDX_CHAIN0:memory_address={9'd0,ctx_chain};
        IDX_CHAIN1:memory_address={9'd0,ctx_chain}+16'd1;
        IDX_GROUP:memory_address={10'd0,ctx_group};
        IDX_CURSOR:memory_address={1'b0,ctx_cursor};
        IDX_REDUCE_LEFT:memory_address={8'd0,ctx_reduce_index,1'b0};
        IDX_REDUCE_RIGHT:memory_address={8'd0,ctx_reduce_index,1'b1};
        IDX_REDUCE_OUT:memory_address={9'd0,ctx_reduce_index};
        default:memory_address=imm[15:0];
    endcase
    wire [6:0] list_address=group_valid ? lane_list0[0] : memory_address[6:0];
    wire [255:0] list_value=list_address<68 ? node_memory_read : 256'd0;
    wire [6:0] cpu_load_address=a==0 ? memory_address[6:0]
        : {a==1 ? 3'b101 : 3'b110,memory_address[3:0]};
    assign node_memory_read_address=tree_active && phase==TREE_RUN ? tree_read_address
        : chain_active && chain_state==CHAIN_CAP ? 7'd123
        : group_valid
        ? (group_recipe[59:56]==12 ? list_address
            : {3'b111,group_recipe[59:56]==4 ? 4'd0 : result_object})
        : opcode==OP_LOAD ? cpu_load_address : {3'b111,node_source_address};
    always_comb begin
        node_memory_write=0;
        node_memory_write_address=0;
        node_memory_write_value=0;
        if(tree_memory_write) begin
            node_memory_write=1;
            node_memory_write_address=tree_write_address;
            node_memory_write_value=tree_write_value;
        end else if(scratch_write) begin
            node_memory_write=1;
            node_memory_write_address={3'b111,d[3:0]};
            node_memory_write_value=cpu_node_value;
        end else if(execute && opcode==OP_STORE) begin
            node_memory_write=1;
            node_memory_write_address=d==0 ? memory_address[6:0]
                : {d==1 ? 3'b101 : 3'b110,memory_address[3:0]};
            node_memory_write_value=read_node(a);
        end else if(result_write) begin
            node_memory_write=1;
            node_memory_write_address={3'b111,result_object};
            node_memory_write_value=trim_node(physical_value[255:0]);
        end else if(chain_capture_write) begin
            node_memory_write=1;
            node_memory_write_address=7'd123;
            node_memory_write_value=trim_node(physical_value[255:0]);
        end else if(chain_cap_commit) begin
            node_memory_write=1;
            node_memory_write_address=chain_slot ? 7'd120 : 7'd119;
            node_memory_write_value=node_memory_read;
        end else if(chain_result_commit) begin
            node_memory_write=1;
            node_memory_write_address=chain_slot ? 7'd117 : 7'd116;
            node_memory_write_value=trim_node(physical_value[255:0]);
        end
    end
    // The TREE controller shares the sole RAM read and write ports with the
    // instruction datapath and child CHAIN. Every state touches at most one
    // RAM source and one destination; RIGHT remains its existing fixed bus.
    always_comb begin
        tree_read_address=7'd116;
        if(group_valid) tree_read_address=group_recipe[59:56]==12
            ? physical_list0 : (group_mask[1] ? 7'd117 : 7'd116);
        if(tree_fors_reissue && tree_fors_next[1])
            tree_read_address=tree_fors_next[0] ? 7'd117 : 7'd116;
        case(tree_state)
            T_EMIT_CAP,T_SECRET_EMIT:tree_read_address=7'd119;
            T_MERGE_LEFT:tree_read_address=7'd80+{3'd0,ctx_level};
            T_FORS_RIGHT:tree_read_address=7'd117;
            T_FORS_RESULT:begin
                if(tree_fors_stage<2) tree_read_address=tree_fors_stage[0] ? 7'd117 : 7'd116;
                else tree_read_address=tree_target[0] ? 7'd116 : 7'd117;
            end
            T_AUTH_EMIT:tree_read_address=7'd96+{3'd0,ctx_level};
            default:begin end
        endcase
        tree_memory_write=0;tree_write_address=0;tree_write_value=0;
        tree_right_write=0;tree_right_value=node_memory_read;
        if(tree_active && phase==TREE_RUN && !error && !lane_fault && !rst) case(tree_state)
            T_INPUT_CHAIN,T_INPUT_SECRET:if(verify_valid) begin
                tree_memory_write=1;tree_write_address=7'd116;tree_write_value=trim_node(verify_data);
            end
            T_STORE_CHAIN:if(!(tree_selected && tree_flags[0])) begin
                tree_memory_write=1;tree_write_address=ctx_chain;tree_write_value=node_memory_read;
            end
            T_ZERO_LEAF:begin tree_memory_write=1;tree_write_address=7'd116;end
            T_WAIT:if(tree_response) begin
                tree_memory_write=1;tree_write_address=group_mask[1] ? 7'd117 : 7'd116;
                tree_write_value=trim_node(physical_value[255:0]);
            end
            T_CAPTURE:if(tree_capture_auth) begin
                tree_memory_write=1;tree_write_address=7'd96+{3'd0,ctx_level};tree_write_value=node_memory_read;
            end
            T_CHECK:if(ctx_index[0] && tree_skip_parent) begin
                tree_memory_write=1;tree_write_address=7'd116;
            end
            T_MERGE_RIGHT,T_FORS_RIGHT,T_VERIFY_RIGHT:tree_right_write=1;
            T_MERGE_LEFT:begin
                tree_memory_write=1;tree_write_address=7'd116;tree_write_value=node_memory_read;
            end
            T_SAVE:begin
                tree_memory_write=1;tree_write_address=7'd80+{3'd0,ctx_level};tree_write_value=node_memory_read;
            end
            T_FORS_RESULT:begin
                if(tree_pair_selected && tree_fors_stage<2 && tree_fors_stage[0]==tree_target[0]) begin
                    tree_memory_write=1;tree_write_address=7'd119;tree_write_value=node_memory_read;
                end else if(tree_pair_selected && tree_fors_stage==3) begin
                    tree_memory_write=1;tree_write_address=7'd96;tree_write_value=node_memory_read;
                end
            end
            T_VERIFY_INPUT:if(verify_valid) begin
                if(ctx_index[0]) begin
                    tree_memory_write=1;tree_write_address=7'd116;tree_write_value=trim_node(verify_data);
                end else begin tree_right_write=1;tree_right_value=trim_node(verify_data);end
            end
            T_RETURN:if(tree_flags[0]) begin
                tree_memory_write=1;tree_write_address=7'd116;tree_write_value=node[3];
            end
            default:begin end
        endcase
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
            COND_AUTH_MATCH:condition=ctx_index==(ctx_path^14'd1);
            COND_SAME_PARENT:condition=ctx_index[13:1]==ctx_path[13:1];
            COND_STEP_EQ_DIGIT:condition=ctx_step[a[0]]==ctx_digit[a[0]];
            COND_STEP_MORE:condition=ctx_step[a[0]]<15;
            COND_LANE_ENABLED:condition=ctx_mask[a[0]];
            COND_MASK_ZERO:condition=ctx_mask==0;
            COND_FORS_PAIR_TARGET:condition=ctx_cursor=={ctx_target[13:1],1'b0};
            COND_REDUCE_MORE:condition=ctx_reduce_index<ctx_reduce_span;
            COND_REDUCE_AGAIN:condition=ctx_reduce_span>1;
            COND_ROOT_EQUAL:condition=root_equal;
            default:condition=0;
        endcase
    end
    logic illegal;
    wire metadata_safe=typed_metadata(opcode);
    wire job_accept=phase==IDLE && job_valid && !error && config_valid
        && image_header[63:32]==32'h48425350 && image_header[31:27]==5'd4
        && job_operation<=2 && (job_operation==0 ? job_message_length==0
            : job_message_length>0 && job_message_length<=MAX_MESSAGE_BYTES);
    wire execute=phase==EXEC && ir_valid && !error && !lane_fault && !illegal;

    // A malformed instruction retires nothing and changes no context, node,
    // stream, or lane result. Fault control only cancels execution.
    always_comb begin
        retire=chain_complete || tree_complete;redirect=0;redirect_pc=imm[8:0];halt_fetch=0;illegal=0;
        if(phase==EXEC && ir_valid && !error && !lane_fault) begin
            illegal=!typed_encoding_valid(ir) || (group_valid && !metadata_safe && opcode!=OP_WAIT);
            retire=1;
            if(!illegal) case(opcode)
                OP_LAYER_NEXT:illegal=ctx_layer>=layers;
                OP_GROUP_NEXT:illegal=ctx_group>=fors_k || fors_offset_next>10'd320;
                OP_CURSOR_NEXT:illegal=cursor_next>{1'b0,cursor_limit};
                OP_CHAIN_NEXT:illegal=ctx_chain>=chain_count || chain_next>chain_count+8'd1;
                OP_HEIGHT:illegal=requested_height==0 || requested_height>14;
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
                    0,1:illegal=ctx_chain>=chain_count || (d==0 && ctx_cursor>=1024);
                    2:illegal=ctx_group>=fors_k || ctx_cursor>=(15'd1<<fors_a);
                    3:illegal=ctx_group>=fors_k || ctx_target>=(15'd1<<fors_a);
                    4:illegal=ctx_group>=fors_k;
                    5:illegal=ctx_level>ctx_height;
                    6:illegal=a==0 && ctx_cursor>=1024;
                    8:illegal=ctx_reduce_index>=ctx_reduce_span || ctx_level==0;
                    default:begin end
                endcase
                OP_REDUCE_INIT:illegal=cursor_limit>68 || ctx_height==0 || (d==1 && ctx_group>=fors_k);
                OP_REDUCE_NEXT:illegal=d==0 ? ctx_reduce_index>=ctx_reduce_span
                    : (ctx_reduce_span<=1 || ctx_level>=ctx_height);
                OP_PARSE:illegal=!hmsg_valid;
                OP_LOAD:illegal=memory_address>=(a==0 ? 68 : 16);
                OP_STORE:illegal=memory_address>=(d==0 ? 68 : 16);
                OP_HASH:illegal=(issue_mask!=2'b01 && issue_mask!=2'b10)
                    || (descriptor_data[59:56]!=1 && descriptor_data[59:56]!=2
                        && descriptor_data[59:56]!=3 && descriptor_data[59:56]!=4
                        && descriptor_data[59:56]!=12)
                    || (issue_mask[1] && descriptor_data[59:56]!=1 && descriptor_data[59:56]!=2)
                    || (issue_mask[1] && descriptor_data[59:56]==2 && descriptor_data[47:40]!=1);
                OP_CHAIN:begin
                    retire=0;
                    illegal=(issue_mask!=2'b01 && issue_mask!=2'b10)
                        || macro_chain_index>=chain_count
                        || (b==0 && ctx_cursor>=1024)
                        || (d!=CHAIN_FULL && (!digits_valid || !ctx_digit_valid[issue_mask[1]]));
                end
                OP_TREE:begin
                    retire=0;
                    illegal=a!=operation || ctx_layer>=layers || ctx_leaf>=(11'd1<<hp)
                        || (d==1 && ctx_group>=fors_k)
                        || (a!=TREE_ROOT && ctx_target>=(15'd1<<(d==0 ? hp : fors_a)))
                        || (d==0 && a!=TREE_ROOT && !digits_valid)
                        || (b[0] && ctx_layer+8'd1!=layers);
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
                        || (d==COND_STEP_EQ_DIGIT && !ctx_digit_valid[a[0]]);
                end
                default:begin end
            endcase
            if(illegal) begin retire=0;redirect=0;halt_fetch=1;end
        end
        if(lane_fault) halt_fetch=1;
    end
    assign job_ready=phase==IDLE && !error;
    assign message_ready=phase==MESSAGE;
    assign verify_ready=!error && !lane_fault && !rst &&
        ((phase==EXEC && ir_valid && opcode==OP_INPUT && !group_valid
            && operation==2 && !illegal)
        || (tree_active && phase==TREE_RUN && (tree_state==T_INPUT_CHAIN
            || tree_state==T_INPUT_SECRET || tree_state==T_VERIFY_INPUT)));
    assign out_bytes=node_bytes;
    assign busy=phase!=IDLE && phase!=FAILED;
    always_ff @(posedge clk) begin
        if(rst || job_accept) begin
            ctx_layer<=0;ctx_tree<=0;ctx_leaf<=0;ctx_group<=0;ctx_fors_offset<=0;ctx_target<=0;
            ctx_cursor<=0;ctx_chain<=0;ctx_height<=0;ctx_level<=0;
            ctx_index<=0;ctx_path<=0;ctx_fors_base<=0;ctx_mask<=0;
            ctx_reduce_index<=0;ctx_reduce_span<=0;ctx_digit_valid<=0;
            for(integer lane=0;lane<2;lane=lane+1) begin
                ctx_step[lane]<=0;ctx_digit[lane]<=0;
                addr_leaf[lane]<=0;addr_a[lane]<=0;addr_b[lane]<=0;
            end
        end else if(tree_cleanup) begin
            ctx_cursor<=0;ctx_chain<=0;ctx_height<=0;ctx_level<=0;
            ctx_index<=0;ctx_path<=0;ctx_fors_base<=0;ctx_mask<=1;
            ctx_reduce_index<=0;ctx_reduce_span<=0;ctx_digit_valid<=0;
            for(integer lane=0;lane<2;lane=lane+1) begin
                ctx_step[lane]<=0;ctx_digit[lane]<=0;
                addr_leaf[lane]<=0;addr_a[lane]<=0;addr_b[lane]<=0;
            end
        end else if(chain_complete || chain_child_complete) begin
            ctx_step[chain_slot]<=chain_terminal;
        end else if(tree_active && phase==TREE_RUN && !error && !lane_fault) begin
            case(tree_state)
                T_INIT:begin
                    ctx_cursor<=0;ctx_chain<=0;ctx_height<=tree_height;ctx_level<=0;
                    ctx_index<=0;ctx_path<=tree_target;ctx_fors_base<=tree_kind ? tree_group_base : 20'd0;
                    ctx_mask<=1;ctx_digit_valid<=0;ctx_reduce_index<=0;ctx_reduce_span<=0;
                    ctx_step[0]<=0;ctx_step[1]<=0;ctx_digit[0]<=0;ctx_digit[1]<=0;
                end
                T_LEAF:ctx_chain<=0;
                T_CHILD:begin
                    ctx_digit[0]<=read_digit(ctx_chain);
                    ctx_digit_valid<=tree_mode==TREE_VERIFY || tree_selected ? 2'b01 : 2'b00;
                    ctx_step[0]<=tree_mode==TREE_VERIFY ? read_digit(ctx_chain) : 4'd0;
                end
                T_STORE_CHAIN:ctx_chain<=ctx_chain+7'd1;
                T_ZERO_LEAF:begin
                    ctx_level<=0;ctx_index<=ctx_cursor[13:0];ctx_path<=tree_target;ctx_fors_base<=0;
                end
                T_WAIT:if(tree_response && group_recipe[59:56]==12 && tree_mode!=TREE_VERIFY) begin
                    ctx_level<=0;ctx_index<=ctx_cursor[13:0];ctx_path<=tree_target;ctx_fors_base<=0;
                end
                T_CHECK:if(ctx_index[0] && tree_skip_parent) begin
                    ctx_level<=ctx_level+4'd1;ctx_index<=ctx_index>>1;
                    ctx_path<=ctx_path>>1;ctx_fors_base<=ctx_fors_base>>1;
                end
                T_MERGE_LEFT:begin
                    ctx_level<=ctx_level+4'd1;ctx_index<=ctx_index>>1;
                    ctx_path<=ctx_path>>1;ctx_fors_base<=ctx_fors_base>>1;
                end
                T_FORS_RIGHT:begin
                    ctx_level<=1;ctx_index<=ctx_cursor[14:1];ctx_path<=tree_target>>1;
                    ctx_fors_base<=tree_group_base>>1;
                end
                T_NEXT_LEAF:ctx_cursor<=ctx_cursor+(tree_kind ? 15'd2 : 15'd1);
                T_AUTH_BEGIN:ctx_level<=0;
                T_AUTH_EMIT:ctx_level<=ctx_level+4'd1;
                T_VERIFY_INPUT:if(verify_valid) begin
                    ctx_level<=ctx_level+4'd1;ctx_index<=ctx_index>>1;
                    ctx_path<=ctx_path>>1;ctx_fors_base<=ctx_fors_base>>1;
                end
                T_VERIFY_BEGIN:begin
                    ctx_level<=0;ctx_index<=tree_target;ctx_path<=tree_target;
                    ctx_fors_base<=tree_kind ? tree_group_base : 20'd0;
                end
                default:begin end
            endcase
        end else if(execute) begin
            case(opcode)
                OP_LAYER_INIT:ctx_layer<=d==0 ? 5'd0 : layers[4:0]-5'd1;
                OP_LAYER_NEXT:ctx_layer<=ctx_layer+5'd1;
                OP_TREE_NEXT:begin
                    ctx_leaf<=ctx_tree[9:0]&((10'd1<<hp)-1'b1);
                    ctx_tree<=ctx_tree>>hp;
                end
                OP_GROUP_INIT:begin ctx_group<=0;ctx_fors_offset<=0;end
                OP_GROUP_NEXT:begin ctx_group<=ctx_group+6'd1;ctx_fors_offset<=fors_offset_next[8:0];end
                OP_CURSOR_INIT:ctx_cursor<=0;
                OP_CURSOR_NEXT:ctx_cursor<=cursor_next[14:0];
                OP_CHAIN_INIT:begin ctx_chain<=0;ctx_digit_valid<=0;end
                OP_CHAIN_NEXT:begin ctx_chain<=chain_next[6:0];ctx_digit_valid<=0;end
                OP_HEIGHT:ctx_height<=requested_height;
                OP_TARGET:ctx_target<=d==0 ? target_value : {4'd0,ctx_leaf};
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
                    ctx_level<=0;ctx_index<=begin_index[13:0];ctx_path<=ctx_target;
                    ctx_fors_base<=a==1 ? group_base : 20'd0;
                end
                OP_NODE_PARENT:begin
                    ctx_level<=ctx_level+4'd1;ctx_index<=ctx_index>>1;
                    ctx_path<=ctx_path>>1;ctx_fors_base<=ctx_fors_base>>1;
                end
                OP_LEVEL_INIT:ctx_level<=0;
                OP_LEVEL_NEXT:ctx_level<=ctx_level+4'd1;
                OP_ADRS:case(d)
                    0,1:begin
                        for(integer lane=0;lane<2;lane=lane+1) begin
                            addr_leaf[lane]<=d==0 ? ctx_cursor[9:0] : ctx_leaf;
                            addr_a[lane]<=ctx_chain+7'(lane);
                            addr_b[lane]<={16'd0,ctx_step[lane]};
                        end
                    end
                    2,3:begin
                        for(integer lane=0;lane<2;lane=lane+1) begin
                            addr_leaf[lane]<=ctx_leaf;addr_a[lane]<=0;
                            addr_b[lane]<=group_base+(d==2 ? {5'd0,ctx_cursor} : {6'd0,ctx_target})+(d==2 ? 20'(lane) : 20'd0);
                        end
                    end
                    4,5:begin
                        for(integer lane=0;lane<2;lane=lane+1) begin
                            addr_leaf[lane]<=d==4 ? ctx_leaf : 10'd0;
                            addr_a[lane]<={3'd0,ctx_level};
                            addr_b[lane]<=(d==4 ? ctx_fors_base : 20'd0)+{6'd0,ctx_index};
                        end
                    end
                    6,7:begin
                        for(integer lane=0;lane<2;lane=lane+1) begin
                            addr_leaf[lane]<=d==7 || a==1 ? ctx_leaf : ctx_cursor[9:0];
                            addr_a[lane]<=0;addr_b[lane]<=0;
                        end
                    end
                    8:begin
                        for(integer lane=0;lane<2;lane=lane+1) begin
                            addr_leaf[lane]<=a==1 ? ctx_leaf : 10'd0;
                            addr_a[lane]<={3'd0,ctx_level};
                            addr_b[lane]<=(a==1 ? ctx_fors_base : 20'd0)+{13'd0,ctx_reduce_index};
                        end
                    end
                    default:begin end
                endcase
                OP_REDUCE_INIT:begin
                    ctx_reduce_span<=cursor_limit[6:0];ctx_reduce_index<=0;
                    ctx_level<=0;ctx_fors_base<=d==1 ? group_base : 20'd0;
                end
                OP_REDUCE_NEXT:begin
                    if(d==0) ctx_reduce_index<=ctx_reduce_index+7'd1;
                    else begin
                        ctx_reduce_span<=ctx_reduce_span>>1;ctx_reduce_index<=0;
                        ctx_level<=ctx_level+4'd1;ctx_fors_base<=ctx_fors_base>>1;
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
            tree_count<=0;tree_busy_cycles<=0;tree_hashes<=0;tree_chains<=0;tree_input_wait_cycles<=0;tree_child_busy_cycles<=0;
        end else if(!error) begin
            if(chain_start) macro_count<=macro_count+32'd1;
            if(chain_active && !tree_owner) macro_busy_cycles<=macro_busy_cycles+32'd1;
            if(chain_issue && !tree_owner) macro_hashes<=macro_hashes+32'd1;
            if(tree_start) tree_count<=tree_count+32'd1;
            if(tree_active) tree_busy_cycles<=tree_busy_cycles+32'd1;
            if(chain_active && tree_owner) tree_child_busy_cycles<=tree_child_busy_cycles+32'd1;
            if(tree_issue) tree_hashes<=tree_hashes+32'd1;
            if(chain_child_start) tree_chains<=tree_chains+32'd1;
            if(tree_active && verify_ready && !verify_valid) tree_input_wait_cycles<=tree_input_wait_cycles+32'd1;
        end
    end
    always_ff @(posedge clk) begin
        if(rst) begin
            phase<=IDLE;operation<=0;done<=0;error<=0;error_code<=0;verify_pass<=0;
            out_valid<=0;out_data<=0;cycles<=0;hash_base<=0;permutation_base<=0;
            message_length<=0;message_received<=0;
            hmsg_digest<=0;hmsg_valid<=0;digits_valid<=0;digit_checksum<=0;
            root_equal<=0;root_compare_valid<=0;group_valid<=0;group_mask<=0;
            group_recipe<=0;group_layer<=0;group_tree<=0;
            group_leaf_value<=0;group_a_value<=0;group_b_value<=0;
            chain_state<=CHAIN_SEED;chain_mode<=0;chain_slot<=0;chain_digit<=0;
            chain_feedback<=0;chain_hash_stage<=0;chain_shadow_valid<=0;
            chain_f_bytes<=0;chain_f_blocks<=0;chain_expected_hashes<=0;
            tree_owner<=0;tree_kind<=0;tree_mode<=0;tree_flags<=0;tree_profile_valid<=0;tree_state<=T_PREFLIGHT;tree_resume<=T_RETURN;
            tree_node_words<=0;tree_height<=0;tree_chain_count<=0;tree_leaf_snapshot<=0;tree_target<=0;
            tree_group_base<=0;tree_recipe_id<=0;tree_recipe_index<=0;tree_fors_stage<=0;chain_child_started<=0;
            for(integer slot=0;slot<4;slot=slot+1) tree_recipe_blocks[slot]<=0;
        end else begin
            done<=0;out_valid<=0;
            if(chain_child_start) chain_child_started<=1;
            if(PROFILE_ENABLE && phase!=IDLE && phase!=FAILED) cycles<=cycles+1'b1;
            if(lane_fault) begin
                group_valid<=0;chain_shadow_valid<=0;fault(16'h3007);
            end else if(illegal) begin
                group_valid<=0;chain_shadow_valid<=0;fault(16'h3006);
            end else case(phase)
                IDLE:if(job_valid && !error) begin
                    if(!config_valid || image_header[63:32]!=32'h48425350 || image_header[31:27]!=5'd4)
                        fault(16'h3006);
                    else if(job_operation>2 || (job_operation==0 ? job_message_length!=0
                        : job_message_length==0 || job_message_length>87)) fault(16'h3002);
                    else begin
                        operation<=job_operation;verify_pass<=0;cycles<=0;
                        root_equal<=0;root_compare_valid<=0;
                        hash_base<=total_hashes;permutation_base<=total_permutations;
                        message_length<=job_message_length;message_received<=0;
                        hmsg_digest<=0;hmsg_valid<=0;digits_valid<=0;
                                    phase<=job_operation==0 ? LAUNCH : MESSAGE;
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
                            group_leaf_value<=addr_leaf[issue_mask[1]];
                            group_a_value<=addr_a[issue_mask[1]];
                            group_b_value<=addr_b[issue_mask[1]];
                        end
                        OP_CHAIN:begin
                            phase<=MACRO;chain_state<=CHAIN_SEED;
                            chain_mode<=d[1:0];chain_slot<=issue_mask[1];
                            chain_digit<=d==CHAIN_FULL ? 4'd0 : ctx_digit[issue_mask[1]];
                            chain_expected_hashes<=d==CHAIN_FULL || d==CHAIN_CAP_FULL ? 5'd16
                                : d==CHAIN_CAP_PREFIX ? 5'd1+{1'b0,ctx_digit[issue_mask[1]]}
                                : 5'd15-{1'b0,ctx_digit[issue_mask[1]]};
                            chain_hash_stage<=d==CHAIN_SUFFIX;chain_feedback<=0;chain_shadow_valid<=0;
                            group_valid<=0;group_mask<=issue_mask;
                            group_layer<=ctx_layer;group_tree<=ctx_tree;
                            group_leaf_value<=b==0 ? ctx_cursor[9:0] : ctx_leaf;
                            group_a_value<=macro_chain_index[6:0];
                            group_b_value<=d==CHAIN_SUFFIX ? {16'd0,ctx_digit[issue_mask[1]]} : 20'd0;
                        end
                        OP_TREE:begin
                            phase<=TREE_RUN;tree_owner<=1;tree_state<=T_PREFLIGHT;
                            tree_profile_valid<=config_valid;
                            tree_kind<=d[0];tree_mode<=a[1:0];tree_flags<=b[0];
                            tree_node_words<=n[5:3];tree_height<=d==0 ? hp[3:0] : fors_a[3:0];
                            tree_chain_count<=chain_count[6:0];tree_leaf_snapshot<=ctx_leaf;tree_target<=ctx_target;
                            tree_group_base<=group_base;tree_recipe_id<=d==0 ? 4'd7 : a==TREE_SIGN ? 4'd4 : 4'd5;
                            tree_recipe_index<=d==0 || a==TREE_SIGN ? 2'd0 : 2'd1;
                            group_valid<=0;group_mask<=1;group_layer<=ctx_layer;group_tree<=ctx_tree;
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
                            group_recipe<=descriptor_data;chain_state<=CHAIN_F;
                        end
                    end
                    CHAIN_F:begin
                        if(!chain_recipe_valid(descriptor_data,1'b0)) begin
                            chain_shadow_valid<=0;fault(16'h3006);
                        end else begin
                            chain_f_bytes<=descriptor_data[37:32];chain_f_blocks<=descriptor_data[29:24];
                            if(chain_mode==CHAIN_SUFFIX) group_recipe<=descriptor_data;
                            if(chain_mode==CHAIN_SUFFIX && chain_digit==15) chain_state<=CHAIN_DONE;
                            else begin group_valid<=1;chain_state<=CHAIN_ISSUE;end
                        end
                    end
                    CHAIN_ISSUE:if(chain_issue) chain_state<=CHAIN_RUN;
                    CHAIN_RUN:if(chain_response) begin
                        if(chain_capture_now) chain_shadow_valid<=1;
                        if(chain_at_end) begin
                            group_valid<=0;
                            // This check precedes every architectural commit.
                            if(chain_capture_mode && !(chain_shadow_valid || chain_capture_now)) begin
                                chain_shadow_valid<=0;fault(16'h3006);
                            end else chain_state<=chain_capture_mode ? CHAIN_CAP : CHAIN_RESULT;
                        end else begin
                            chain_feedback<=1;chain_hash_stage<=1;
                            group_recipe<=chain_f_recipe;
                            group_b_value<={16'd0,chain_next_step};
                            chain_state<=chain_issue ? CHAIN_RUN : CHAIN_ISSUE;
                        end
                    end
                    CHAIN_CAP:chain_state<=CHAIN_RESULT;
                    CHAIN_RESULT:chain_state<=CHAIN_DONE;
                    CHAIN_DONE:begin
                        chain_shadow_valid<=0;phase<=tree_owner ? TREE_RUN : EXEC;
                        if(tree_owner) tree_state<=tree_selected ? T_EMIT_CAP : T_STORE_CHAIN;
                    end
                    default:begin group_valid<=0;chain_shadow_valid<=0;fault(16'h3006);end
                endcase
                TREE_RUN:case(tree_state)
                    T_PREFLIGHT:begin
                        if(!tree_profile_valid || !tree_recipe_valid(descriptor_data,tree_recipe_id)) fault(16'h3006);
                        else begin
                            tree_recipe_blocks[tree_recipe_index]<=descriptor_data[29:24];
                            if(tree_recipe_id==(tree_kind ? 4'd6 : 4'd10)) tree_state<=T_INIT;
                            else begin tree_recipe_id<=tree_recipe_id+4'd1;tree_recipe_index<=tree_recipe_index+2'd1;end
                        end
                    end
                    T_INIT:begin
                        tree_fors_stage<=0;
                        if(tree_kind) tree_state<=tree_mode==TREE_VERIFY ? T_INPUT_SECRET : T_FORS_PREP;
                        else tree_state<=T_LEAF;
                    end
                    T_LEAF:tree_state<=tree_mode==TREE_VERIFY ? T_INPUT_CHAIN : T_CHILD;
                    T_INPUT_CHAIN:if(verify_valid) tree_state<=T_CHILD;
                    T_CHILD:begin
                        phase<=MACRO;chain_child_started<=0;
                        chain_mode<=tree_mode==TREE_VERIFY ? CHAIN_SUFFIX
                            : tree_selected ? (tree_flags[0] ? CHAIN_CAP_PREFIX : CHAIN_CAP_FULL) : CHAIN_FULL;
                        chain_slot<=0;chain_digit<=tree_mode==TREE_VERIFY || tree_selected ? read_digit(ctx_chain) : 4'd0;
                        chain_expected_hashes<=tree_mode==TREE_VERIFY ? 5'd15-{1'b0,read_digit(ctx_chain)}
                            : tree_selected && tree_flags[0] ? 5'd1+{1'b0,read_digit(ctx_chain)} : 5'd16;
                        chain_hash_stage<=tree_mode==TREE_VERIFY;chain_feedback<=0;chain_shadow_valid<=0;
                        chain_f_bytes<=tree_node_bytes;chain_f_blocks<=tree_recipe_blocks[1];
                        group_mask<=1;group_leaf_value<=tree_mode==TREE_VERIFY ? tree_leaf_snapshot : ctx_cursor[9:0];
                        group_a_value<=ctx_chain;group_b_value<=tree_mode==TREE_VERIFY ? {16'd0,read_digit(ctx_chain)} : 20'd0;
                        group_recipe<=tree_recipe(tree_mode==TREE_VERIFY ? 4'd8 : 4'd7);
                        if(tree_mode==TREE_VERIFY && read_digit(ctx_chain)==15) begin group_valid<=0;chain_state<=CHAIN_DONE;end
                        else begin group_valid<=1;chain_state<=CHAIN_ISSUE;end
                    end
                    T_EMIT_CAP:begin out_valid<=1;out_data<=node_memory_read;tree_state<=T_STORE_CHAIN;end
                    T_STORE_CHAIN:begin
                        if(ctx_chain+8'd1<tree_chain_count) tree_state<=tree_mode==TREE_VERIFY ? T_INPUT_CHAIN : T_CHILD;
                        else tree_state<=tree_selected && tree_flags[0] ? T_ZERO_LEAF : T_COMPRESS;
                    end
                    T_ZERO_LEAF:tree_state<=T_CAPTURE;
                    T_COMPRESS:begin
                        group_recipe<=tree_recipe(9);group_mask<=1;group_valid<=1;
                        group_leaf_value<=tree_mode==TREE_VERIFY ? tree_leaf_snapshot : ctx_cursor[9:0];
                        group_a_value<=0;group_b_value<=0;tree_state<=T_ISSUE;
                        tree_resume<=tree_mode==TREE_VERIFY ? T_VERIFY_BEGIN : T_CAPTURE;
                    end
                    T_ISSUE:if(physical_ready) tree_state<=T_WAIT;
                    T_WAIT:if(tree_response) begin
                        if(tree_fors_reissue) begin
                            group_recipe<=tree_fors_next_recipe;group_mask<=physical_mask;
                            group_b_value<=tree_fors_next_b;tree_fors_stage<=tree_fors_next;
                            tree_state<=physical_ready ? T_WAIT : T_ISSUE;
                        end else begin group_valid<=0;tree_state<=tree_resume;end
                    end
                    T_CAPTURE:tree_state<=T_CHECK;
                    T_CHECK:begin
                        if(ctx_index[0]) tree_state<=tree_skip_parent ? T_CAPTURE : T_MERGE_RIGHT;
                        else tree_state<=T_SAVE;
                    end
                    T_MERGE_RIGHT:tree_state<=T_MERGE_LEFT;
                    T_MERGE_LEFT:begin
                        group_recipe<=tree_recipe(tree_kind ? 4'd6 : 4'd10);group_mask<=1;group_valid<=1;
                        group_leaf_value<=tree_kind ? tree_leaf_snapshot : 10'd0;
                        group_a_value<={3'd0,ctx_level}+7'd1;
                        group_b_value<=(ctx_fors_base>>1)+{7'd0,ctx_index[13:1]};
                        tree_resume<=T_CAPTURE;tree_state<=T_ISSUE;
                    end
                    T_SAVE:tree_state<=T_NEXT_LEAF;
                    T_NEXT_LEAF:begin
                        if(ctx_cursor+(tree_kind ? 15'd2 : 15'd1)<tree_limit)
                            tree_state<=tree_kind ? T_FORS_PREP : T_LEAF;
                        else tree_state<=tree_mode==TREE_SIGN ? T_AUTH_BEGIN : T_RETURN;
                    end
                    T_AUTH_BEGIN:tree_state<=tree_kind ? T_SECRET_EMIT : T_AUTH_EMIT;
                    T_SECRET_EMIT:begin out_valid<=1;out_data<=node_memory_read;tree_state<=T_AUTH_EMIT;end
                    T_AUTH_EMIT:begin
                        out_valid<=1;out_data<=node_memory_read;
                        if(ctx_level+5'd1>=tree_height) tree_state<=T_RETURN;
                    end
                    T_RETURN:tree_state<=T_CLEANUP;
                    T_CLEANUP:begin root_equal<=0;root_compare_valid<=0;tree_state<=T_DONE;end
                    T_DONE:begin tree_owner<=0;phase<=EXEC;end
                    T_FORS_PREP:begin
                        group_recipe<=tree_recipe(tree_fors_stage[1] ? 4'd5 : 4'd4);
                        group_mask<=tree_fors_stage[0] ? 2'b10 : 2'b01;group_valid<=1;
                        group_leaf_value<=tree_leaf_snapshot;group_a_value<=0;
                        group_b_value<=tree_group_base+{5'd0,ctx_cursor}+{19'd0,tree_fors_stage[0]};
                        tree_resume<=T_FORS_RESULT;tree_state<=T_ISSUE;
                    end
                    T_FORS_RESULT:begin
                        if(tree_fors_stage==3) begin tree_fors_stage<=0;tree_state<=T_FORS_RIGHT;end
                        else begin tree_fors_stage<=tree_fors_stage+2'd1;tree_state<=T_FORS_PREP;end
                    end
                    T_FORS_RIGHT:begin
                        group_recipe<=tree_recipe(6);group_mask<=1;group_valid<=1;
                        group_leaf_value<=tree_leaf_snapshot;group_a_value<=1;
                        group_b_value<=(tree_group_base>>1)+{6'd0,ctx_cursor[14:1]};
                        tree_resume<=T_CAPTURE;tree_state<=T_ISSUE;
                    end
                    T_INPUT_SECRET:if(verify_valid) tree_state<=T_FORS_TARGET;
                    T_FORS_TARGET:begin
                        group_recipe<=tree_recipe(5);group_mask<=1;group_valid<=1;
                        group_leaf_value<=tree_leaf_snapshot;group_a_value<=0;
                        group_b_value<=tree_group_base+{6'd0,tree_target};
                        tree_resume<=T_VERIFY_BEGIN;tree_state<=T_ISSUE;
                    end
                    T_VERIFY_BEGIN:tree_state<=T_VERIFY_POSITION;
                    T_VERIFY_POSITION:tree_state<=ctx_index[0] ? T_VERIFY_RIGHT : T_VERIFY_INPUT;
                    T_VERIFY_RIGHT:tree_state<=T_VERIFY_INPUT;
                    T_VERIFY_INPUT:if(verify_valid) begin
                        group_recipe<=tree_recipe(tree_kind ? 4'd6 : 4'd10);group_mask<=1;group_valid<=1;
                        group_leaf_value<=tree_kind ? tree_leaf_snapshot : 10'd0;
                        group_a_value<={3'd0,ctx_level}+7'd1;
                        group_b_value<=(ctx_fors_base>>1)+{7'd0,ctx_index[13:1]};
                        tree_resume<=ctx_level+5'd1<tree_height ? T_VERIFY_POSITION : T_RETURN;
                        tree_state<=T_ISSUE;
                    end
                    default:begin group_valid<=0;fault(16'h3006);end
                endcase
                FINISH:begin done<=1;phase<=IDLE;end
                FAILED:group_valid<=0;
                default:fault(16'h3006);
            endcase
        end
    end
endmodule
`default_nettype wire
