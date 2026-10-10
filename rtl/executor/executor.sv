`timescale 1ns/1ps
`default_nettype none
// Single-lane ABI 4 macro executor for SLH and experimental XMSS/LMS.
module executor #(
    parameter integer UNROLL=2, PIPELINE=1,
    parameter bit PROFILE_ENABLE=0
) (
    input wire [63:0] image_header, profile_descriptor,
    output wire [3:0] program_address,
    output wire [3:0] template_address,
    input wire [63:0] program_data, template_data,
    input wire [3:0] job_entry,
    output wire [9:0] descriptor_addresses,
    input wire [127:0] descriptor_data,
    input wire clk, rst,
    input wire job_valid, output wire job_ready, input wire [1:0] job_operation,
    input wire [6:0] job_message_length,
    input wire [31:0] job_index, input wire [127:0] job_identifier,
    input wire [255:0] job_secret_seed, job_secret_prf, job_public_seed, job_randomizer, job_public_root,
    input wire message_valid, output wire message_ready,
    input wire [63:0] message_data,
    input wire verify_valid, output wire verify_ready,
    input wire [255:0] verify_data,
    output logic verify_pass,
    output wire out_valid, output wire [255:0] out_data,
    output wire [5:0] out_bytes,
    output wire busy, output logic done, error, output logic [15:0] error_code,
    output wire [63:0] hash_count, permutation_count,
    output logic [63:0] cycles
);
    localparam integer N=32, W=256, V=392, INDEX_BITS=8, MAX_MESSAGE_BYTES=87;
    localparam integer DIGEST_BYTES=49;
    // Six supported profiles need at most ceil(35*9/8)=40 FORS bytes.
    // Tree/leaf indices still consume the full V-bit transient Hmsg result.
    localparam integer FORS_DIGEST_BITS=320;
    wire stateful=profile_descriptor>=64'h18 && profile_descriptor<=64'h1d;
    wire xmss=stateful && profile_descriptor<64'h1b;
    wire valid_profile=stateful || profile_descriptor==0 || profile_descriptor==1
        || profile_descriptor==2 || profile_descriptor==4 || profile_descriptor==5 || profile_descriptor==6;
    wire [4:0] stateful_height=(profile_descriptor==64'h18 || profile_descriptor==64'h1b) ? 5'd10
        : profile_descriptor==64'h19 ? 5'd16 : profile_descriptor==64'h1c ? 5'd15 : 5'd20;
    wire omega2=1'b0;
    wire [3:0] chain_max=4'd15;
    wire [1:0] profile_code=profile_descriptor[1:0];
    wire small_signature=!stateful && profile_descriptor[2];
    wire [5:0] node_bytes=stateful ? 6'd32 : profile_code==0 ? 6'd16
        : profile_code==1 ? 6'd24 : 6'd32;
    wire [3:0] FORS_A=small_signature ? (profile_code==0 ? 4'd12 : 4'd14)
        : profile_code==0 ? 4'd6 : profile_code==1 ? 4'd8 : 4'd9;
    wire [3:0] HP=small_signature ? (profile_code[1] ? 4'd8 : 4'd9)
        : profile_code[1] ? 4'd4 : 4'd3;
    wire [7:0] LEN1=omega2 ? 8'd128 : {1'b0,node_bytes,1'b0};
    wire [63:0] descriptors [0:7];
    // Two reads are sufficient: request recipe plus chain-step recipe.
    // Macro and tree/chain descriptors are already latched in setup states.
    assign descriptors[0]=descriptor_data[63:0];
    assign descriptors[1]=descriptor_data[127:64];
    assign descriptors[2]=64'd0;
    assign descriptors[3]=descriptor_data[63:0];
    assign descriptors[4]=descriptor_data[63:0];
    assign descriptors[5]=descriptor_data[127:64];
    assign descriptors[6]=descriptor_data[63:0];
    assign descriptors[7]=descriptor_data[63:0];
    localparam bit P4_OPT=PIPELINE==4 && UNROLL==1;
    typedef enum logic [6:0] {
        IDLE, MESSAGE, LAUNCH, FETCH, LOAD_DESCRIPTOR, DECODE,
        TREE_INIT, CHAIN_SETUP, CHAIN_STORE,
        CHAIN_OUTPUT0=10,
        CHAIN_NEXT=14, REDUCE_SETUP, LEAF_SETUP,
        PUSH_NODE, PARENT_SETUP, PARENT_DONE, AUTH_OUTPUT, TREE_FINISH,
        HASH_ISSUE, HASH_WAIT, HASH_RESULT, ROUTE, TRANSFORM,
        EMIT, EMIT_NEXT, OUTPUT_CHUNK, DRAIN, FINISH, FAILED,
        VERIFY_INPUT, VERIFY_RANDOM, VERIFY_CHAIN_INPUT,
        VERIFY_CHAIN_RUN, VERIFY_CHAIN_ADVANCE,
        // Keep retired enum positions stable for historical cycle observers.
        PIPE_ISSUE, PIPE_WAIT, PIPE_LOAD, PIPE_CAPTURE, PIPE_CAPTURE_NEXT, PIPE_ADVANCE,
        LT_SETUP, LT_STORE, LT_COPY, LT_NEXT, LT_FINISH, SF_REDUCED, SF_LEAF, SF_LEAF_DONE, SF_RANDOM,
        PIPE_VERIFY_INPUT, LT_PIPE_INIT,LT_PIPE_ISSUE,LT_PIPE_WAIT,LT_PIPE_ADVANCE,
        FORS_PICK,FORS_AUTH0,FORS_BEGIN,FORS_LEFT,FORS_RIGHT,FORS_ISSUE,FORS_WAIT,FORS_LEVEL,FORS_AUTH1,FORS_PUSH
    } state_t;
    state_t state, hash_return, output_return;
    task automatic enter_state(input state_t next_state);
        begin state<=next_state;end
    endtask
    // Abort outstanding execution on an error. The autonomous wrapper halts
    // until reset; this benchmark does not track index consumption.
    // The main controller uses return-state registers and need not synthesize
    // as a one-hot FSM. Never drive asynchronous reset from its binary decode.
    (* dont_touch="yes" *) logic abort_execution;
    wire execution_rst=rst || abort_execution;
    logic [1:0] operation;
    wire verifying = operation==2;
    state_t verify_return;
    // Boot loader owns immutable Job registers for this reset epoch.
    wire [255:0] secret_seed=job_secret_seed, secret_prf=job_secret_prf;
    wire [255:0] public_seed=job_public_seed, randomizer=job_randomizer;
    logic [MAX_MESSAGE_BYTES*8-1:0] message_buffer;
    logic [6:0] message_length, message_received;
    logic [W-1:0] value [0:3];
    logic [FORS_DIGEST_BITS-W-1:0] fors_digest_tail;
    logic [63:0] scalar_tree;
    logic [19:0] scalar_leaf;
    logic [11:0] checksum;
    logic [7:0] transform_index;
    logic [7:0] lt_count,lt_cursor;
    logic [3:0] lt_level;
    logic fors_level,fors_pair_cursor;
    wire fors_target_group=target>=leaf_cursor && target<leaf_cursor+4;
    wire sign_only=stateful && !verifying && standalone_chain && macro_flags[2];
    logic [4:0] layer;
    logic [5:0] group_index;
    logic [3:0] macro_op, macro_flags;
    logic [4:0] macro_desc, macro_route;
    logic [63:0] saved_descriptor, saved_chain_descriptor;
    wire [63:0] descriptor = saved_descriptor;
    wire [63:0] route_descriptor = descriptors[1];

    logic seq_start, seq_complete;
    wire seq_ready,seq_done,cmd_valid;
    wire [47:0] cmd;
    sequencer sequencer (
        .clk,.rst(execution_rst),.start(seq_start),.entry(job_entry),.ready(seq_ready),.done(seq_done),
        .program_address,.program_data,.template_address,.template_data,
        .command_valid(cmd_valid),.command_ready(state==FETCH),.command_done(seq_complete),.command(cmd)
    );

    logic [4:0] chain_id, parent_id;
    wire [63:0] chain_descriptor = saved_chain_descriptor;
    logic standalone_chain;
    logic [4:0] tree_height, node_level, auth_level;
    logic [1:0] indexing;
    logic [20:0] target, leaf_cursor, node_index;
    logic [INDEX_BITS-1:0] chain_cursor, endpoint_count;
    localparam integer PIPE_BATCH=PIPELINE;
    localparam integer TAG_BITS=PIPELINE>1 ? $clog2(PIPELINE) : 1;
    localparam integer COUNT_BITS=$clog2(PIPELINE+1);
    logic pipe_cache_valid,pipe_batch_used;
    logic pipe_rolling;
    logic [PIPE_BATCH-1:0] pipe_active;
    logic [7:0] pipe_next_chain,pipe_completed;
    logic [7:0] pipe_chain_index[0:PIPE_BATCH-1];
    logic [TAG_BITS-1:0] roll_slot;
    wire [PIPE_BATCH-1:0] roll_free=~pipe_active | (pipe_valid ? (PIPE_BATCH'(1)<<pipe_tag) : '0);
    always_comb begin
        roll_slot=0;
        for(integer j=PIPE_BATCH-1;j>=0;j--)if(roll_free[j])roll_slot=TAG_BITS'(j);
    end
    wire [TAG_BITS-1:0] issue_slot=pipe_rolling ? roll_slot : pipe_issue_slot;
    logic [TAG_BITS-1:0] pipe_issue_slot;
    logic [COUNT_BITS-1:0] pipe_pair;
    logic [PIPE_BATCH-1:0] pipe_done_mask,pipe_expected_mask;
    wire [255:0] pipe_read_result,pipe_read_capture;
    logic [7:0] pipe_seed_domain,pipe_step_domain;
    // Stateful endpoint batches use the same single write port as SLH WOTS.
    // Sign-only and verification batches retain their CHAIN_STORE path.
    wire pipe_direct=PIPELINE>1 && indexing!=1
        && (stateful ? (!verifying && !sign_only) : operation==1);
    wire fors_pipe=P4_OPT && (state==FORS_LEFT || state==FORS_RIGHT || state==FORS_ISSUE || state==FORS_WAIT);
    wire fors_read=P4_OPT && (state==FORS_PICK || state==FORS_AUTH0 || state==FORS_AUTH1 || state==FORS_LEFT || state==FORS_RIGHT || state==FORS_PUSH);
    wire [TAG_BITS-1:0] fors_read_slot=state==FORS_PICK ? TAG_BITS'(target[1:0]) : state==FORS_AUTH0 ? TAG_BITS'(target[1:0]^2'd1)
        : state==FORS_AUTH1 ? TAG_BITS'(!target[1]) : state==FORS_PUSH ? TAG_BITS'(0)
        : TAG_BITS'((fors_level ? 2'd0 : {fors_pair_cursor,1'b0})+(state==FORS_RIGHT));
    wire lt_pipe=P4_OPT && (state==LT_PIPE_ISSUE || state==LT_PIPE_WAIT);
    wire pipe_mode=PIPELINE>1 && (state==PIPE_ISSUE || state==PIPE_WAIT || state==PIPE_VERIFY_INPUT || lt_pipe || fors_pipe);
    wire pipe_ready,pipe_valid,pipe_selected;
    wire [TAG_BITS-1:0] pipe_tag;
    wire [63:0] pipe_hashes,pipe_permutations;
    wire [255:0] selected_capture=pipe_batch_used ? pipe_read_capture : lane_capture;
    logic [255:0] node_value;
    (* ram_style="distributed" *) logic [255:0] stack [0:19];
    (* ram_style="distributed" *) logic [255:0] auth_path [0:19];

    logic [4:0] hash_recipe_id;
    assign descriptor_addresses={state==CHAIN_SETUP ? chain_descriptor[48:44] : macro_route,hash_recipe_id[4:0]};
    always @* begin
        hash_recipe_id=macro_desc;
        case(state)
            TREE_INIT: hash_recipe_id={1'b0,saved_descriptor[58:52]};
            EMIT: hash_recipe_id=emit_base+emit_cursor;
            CHAIN_SETUP: hash_recipe_id=chain_descriptor[59:52];
            VERIFY_CHAIN_RUN: hash_recipe_id=chain_descriptor[48:44];
            REDUCE_SETUP,LT_SETUP,LT_PIPE_INIT: hash_recipe_id=chain_descriptor[43:36];
            SF_LEAF: hash_recipe_id=chain_descriptor[35:28];
            PARENT_SETUP: hash_recipe_id=parent_id;
            default: begin end
        endcase
    end
    logic [63:0] task_recipe, task_step;
    logic task_chain;
    logic task_capture;
    logic [4:0] task_steps, task_capture_after;
    logic [19:0] task_leaf;
    logic [INDEX_BITS-1:0] task_a;
    logic [31:0] task_b;
    logic [255:0] task_left0;
    // Parent operands stay unchanged through HASH_ISSUE/HASH_WAIT and are
    // updated only in PARENT_DONE. Other recipes do not consume the right
    // input, so no duplicate parent-right register is needed.
    wire [255:0] parent_right = verifying && hash_return==PARENT_DONE && !node_index[0] ? emit_value : node_value;
    // Results stay stable for each outstanding request. Only verification
    // leaf/chain hashes take their input from these existing result registers.
    wire verify_chain_source = verifying &&
        (hash_return==VERIFY_CHAIN_ADVANCE || (hash_return==LEAF_SETUP && indexing==1));
    wire verify_step_needed=task_b[3:0]!=chain_max;
    wire lane_ready,lane_valid,lane_error;
    wire [V-1:0] lane_value;
    wire [255:0] lane_capture;
    wire [INDEX_BITS-1:0] lane_list0, lane_list1,lane_list_next;
    wire [63:0] lane_hashes, lane_permutations;
    logic [63:0] hash_base, permutation_base;
    logic [V-1:0] result;
    // ROUTE consumes these registers before it can update any source. Keep
    // the original staging cycle, but remember only the source selection.
    localparam logic [1:0] ROUTE_HASH=0, ROUTE_NODE=1, ROUTE_SAVED=2, ROUTE_EMIT=3;
    logic [1:0] route_source;
    wire [V-1:0] route_value = route_source==ROUTE_HASH ? result
        : {{(V-W){1'b0}}, (route_source==ROUTE_NODE ? node_value
                        : route_source==ROUTE_SAVED ? value[3] : emit_value)};
    // The sponge retains capture through response and output stalls. No new
    // request is issued before CHAIN_OUTPUT0 has consumed the capture.
    wire [63:0] total_hashes = lane_hashes+pipe_hashes;
    wire [63:0] total_permutations = lane_permutations+pipe_permutations;
    assign hash_count = PROFILE_ENABLE ? total_hashes-hash_base : 32'd0;
    assign permutation_count = PROFILE_ENABLE ? total_permutations-permutation_base : 32'd0;

    logic endpoint_write;
    logic [INDEX_BITS-1:0] endpoint_address,endpoint_read0_raw,endpoint_read1_raw;
    wire [INDEX_BITS-1:0] endpoint_read0,endpoint_read1;
    logic [255:0] endpoint_data;
    wire [255:0] endpoint_value0,endpoint_value1;
    // All list producers are mutually exclusive. A single write port serves
    // WOTS completions, FORS roots and in-place L-tree reduction.
    wire root_write=state==ROUTE && macro_route!=0 && route_descriptor[53];
    (* keep_hierarchy="yes" *) value #(.WIDTH(W),.DEPTH(136),.ADDRESS_BITS(INDEX_BITS)) endpoints (
        .clk,.write_enable(endpoint_write),.write_address(endpoint_address),.write_data(endpoint_data),
        .read0(endpoint_read0),.read1(endpoint_read1),.value0(endpoint_value0),.value1(endpoint_value1)
    );
    wire [INDEX_BITS-1:0] batch_chain_index=pipe_rolling ? pipe_next_chain : chain_cursor+INDEX_BITS'(pipe_issue_slot);
    wire [20:0] batch_leaf_index=leaf_cursor+21'(pipe_issue_slot);
    assign pipe_selected=(state==PIPE_ISSUE || state==LT_PIPE_ISSUE || state==FORS_ISSUE || (state==PIPE_VERIFY_INPUT && verify_valid))
        && (fors_pipe || (pipe_rolling ? (pipe_next_chain<endpoint_count && |roll_free) : pipe_expected_mask[pipe_issue_slot]));
        recipe #(.N(N),.DIGEST_BYTES(DIGEST_BYTES),.INDEX_BITS(INDEX_BITS),.UNROLL(UNROLL),.PIPELINE(PIPELINE),.MAX_MESSAGE_BYTES(MAX_MESSAGE_BYTES),
            .SHARED_STATE(1'b1),.RECIPE_MASK(16'hfffe),
            .PROFILE_ENABLE(PROFILE_ENABLE)) lane (
            .clk,.rst(execution_rst),.node_bytes,
            .batch_mode(pipe_mode),.batch_request_valid(pipe_selected),.batch_request_ready(pipe_ready),
            .batch_request_tag(fors_pipe ? TAG_BITS'(fors_pair_cursor) : issue_slot),
            .batch_steps(lt_pipe || fors_pipe ? 5'd0 : stateful && verifying ? {1'b0,chain_max}-digit(batch_chain_index)
                : (sign_only || (macro_flags[3] && leaf_cursor==target)) ? digit(batch_chain_index) : chain_descriptor[19:15]),
            .batch_family(stateful ? (xmss ? 2'd1 : 2'd2) : 2'd0),
            .batch_no_seed(lt_pipe || fors_pipe || (stateful && verifying)),.batch_start(stateful && verifying ? 4'(digit(batch_chain_index)) : 4'd0),
            .batch_initial_value(fors_pipe ? task_left0 : lt_pipe ? endpoint_value0 : verify_data),
            .batch_fixed_shape(fors_pipe ? 4'd2 : lt_pipe ? 4'd8 : 4'd0),.batch_pair(lt_pipe || fors_pipe),.batch_right(fors_pipe ? node_value : endpoint_value1),
            .batch_capture_after(indexing==1 ? 5'd0 : digit(batch_chain_index)),
            .batch_capture_enable(!fors_pipe && !lt_pipe && !verifying && macro_flags[0] && (indexing==1 ? batch_leaf_index==target : leaf_cursor==target)),
            .batch_leaf(lt_pipe ? leaf_cursor[19:0] : indexing==1 ? scalar_leaf : leaf_cursor[19:0]),
            .batch_a(fors_pipe ? (fors_level ? 8'd2 : 8'd1) : lt_pipe ? {4'd0,lt_level} : indexing==1 ? 8'd0 : batch_chain_index),
            .batch_b(fors_pipe ? ((32'(group_index)<<FORS_A)>>(fors_level ? 2 : 1))+(32'(leaf_cursor)>>(fors_level ? 2 : 1))+32'(fors_pair_cursor) : lt_pipe ? 32'(lt_cursor>>1)+32'(pipe_issue_slot) : indexing==1 ? (32'(group_index)<<FORS_A)+32'(batch_leaf_index) : 32'd0),
            .batch_seed_domain(pipe_seed_domain),.batch_step_domain(pipe_step_domain),
            .batch_response_valid(pipe_valid),.batch_response_ready(pipe_mode && state!=LT_PIPE_ISSUE && (!fors_pipe || state==FORS_WAIT)),.batch_response_tag(pipe_tag),
            .batch_response_digest(),.batch_response_capture(),
            // Direct writeback and deferred consumption never overlap.
            // Select their tag before reading the context RAM, removing a
            // second 256-bit digest/key read port and its output selectors.
            .batch_read_tag(fors_read ? fors_read_slot : (lt_pipe || pipe_direct) && pipe_mode ? pipe_tag : TAG_BITS'(pipe_pair)),
            .batch_read_digest(pipe_read_result),.batch_read_capture(pipe_read_capture),
            .batch_hashes(pipe_hashes),.batch_permutations(pipe_permutations),
            .request_valid(state==HASH_ISSUE),
            .request_ready(lane_ready), .request_recipe(task_recipe), .request_step_recipe(task_step),
            .request_chain(task_chain), .request_steps(task_steps),
            .request_capture_after(task_capture_after),
            .request_capture(task_capture),
            .secret_seed,.secret_prf,.public_seed,.root(value[3][W-1:0]),
            .randomizer((task_recipe[59:56]==4 || task_recipe[59:56]==6 || (verifying && stateful)) ? value[0][W-1:0] : randomizer),
            .identifier(job_identifier),.message_buffer,.message_length,
            .request_layer(layer),.request_tree(scalar_tree),.request_leaf(task_leaf),
            .request_a(task_a),.request_b(task_b),.request_left(verify_chain_source ? result[W-1:0] : task_left0),.request_right(parent_right),
            .list_index0(lane_list0),.list_index1(lane_list1),.list_next_index0(lane_list_next),
            .list_data0(endpoint_value0),
            .list_data1(endpoint_value1),
            .response_valid(lane_valid),.response_ready(state==HASH_WAIT),
            .response_value(lane_value),.response_capture(lane_capture),.error(lane_error),
            .hash_count(lane_hashes),.permutation_count(lane_permutations)
        );
    initial if(UNROLL<1 || PIPELINE<1 || PIPELINE>12 ||
        UNROLL*PIPELINE>24 || 24%(UNROLL*PIPELINE)!=0) $fatal(1,"Unsupported P/U configuration");

    // Verify never emits output: share its input-node latch with the output latch.
    logic [255:0] emit_value;
    logic [5:0] emit_length;
    logic [7:0] emit_base;
    logic [3:0] emit_count, emit_cursor;
    wire [63:0] emit_descriptor = descriptors[3];
    // One node per valid cycle, low byte first. The receiver uses done to
    // delimit the job and out_bytes to discard unused high bytes.
    assign out_valid=state==OUTPUT_CHUNK;
    assign out_data=emit_value;
    assign out_bytes=emit_length;
    assign job_ready=state==IDLE;
    assign message_ready=state==MESSAGE;
    assign verify_ready=verifying && (state==VERIFY_INPUT || (state==PIPE_VERIFY_INPUT && pipe_ready));
    assign busy=state!=IDLE;

    function automatic [31:0] be32(input [31:0] x);
        be32={x[7:0],x[15:8],x[23:16],x[31:24]};
    endfunction
    function automatic [4:0] digit(input [7:0] index);
        reg [7:0] checksum_index;
        begin
            checksum_index=index-LEN1;
            digit=0;
            if(index<LEN1 && omega2) begin
                digit={3'd0,value[2][{index[6:2],3'b0}+{1'b0,(index[1:0]^2'd3),1'b0} +:2]};
            end else if(index<LEN1) begin
                digit={1'b0,value[2][{(index[5:0]^6'd1),2'b0} +:4]};
            end else if(omega2) begin
                case(checksum_index)
                    0:digit={3'd0,checksum[9:8]};1:digit={3'd0,checksum[7:6]};
                    2:digit={3'd0,checksum[5:4]};3:digit={3'd0,checksum[3:2]};
                    4:digit={3'd0,checksum[1:0]};default:digit=0;
                endcase
            end else begin
                case(checksum_index)
                    0:digit={1'b0,checksum[11:8]}; 1:digit={1'b0,checksum[7:4]};
                    2:digit={1'b0,checksum[3:0]}; default:digit=0;
                endcase
            end
        end
    endfunction
    wire [FORS_DIGEST_BITS-1:0] fors_digest={fors_digest_tail,value[1]};
    wire [FORS_DIGEST_BITS-1:0] fors_bitstream;
    genvar fb;
    generate for(fb=0;fb<FORS_DIGEST_BITS;fb=fb+1) begin: fors_bit_order
        assign fors_bitstream[fb]=fors_digest[(fb/8)*8+7-(fb%8)];
    end endgenerate
    function automatic [13:0] fors_target(input [5:0] group_number);
        reg [9:0] offset;
        reg [13:0] segment;
        begin
            case(FORS_A)
                6:offset=({group_number,2'b0}+{group_number,1'b0});
                8:offset={group_number,3'b0};
                9:offset=({group_number,3'b0}+group_number);
                12:offset=({group_number,3'b0}+{group_number,2'b0});
                default:offset=({group_number,4'b0}-{group_number,1'b0});
            endcase
            segment=fors_bitstream >> offset;
            case(FORS_A)
                6:fors_target={8'd0,segment[0],segment[1],segment[2],segment[3],segment[4],segment[5]};
                8:fors_target={6'd0,segment[0],segment[1],segment[2],segment[3],segment[4],segment[5],segment[6],segment[7]};
                9:fors_target={5'd0,segment[0],segment[1],segment[2],segment[3],segment[4],segment[5],segment[6],segment[7],segment[8]};
                12:fors_target={2'd0,segment[0],segment[1],segment[2],segment[3],segment[4],segment[5],segment[6],segment[7],segment[8],segment[9],segment[10],segment[11]};
                default:fors_target={segment[0],segment[1],segment[2],segment[3],segment[4],segment[5],segment[6],segment[7],segment[8],segment[9],segment[10],segment[11],segment[12],segment[13]};
            endcase
        end
    endfunction
    function automatic [63:0] parsed_tree(input [V-1:0] digest);
        reg [63:0] bytes;
        integer j;
        begin
            if(small_signature) begin
                case(node_bytes)
                    16:bytes={digest[168 +:56],8'd0};
                    24:bytes={digest[240 +:56],8'd0};
                    default:bytes={digest[312 +:56],8'd0};
                endcase
            end else case(node_bytes)
                16:bytes=digest[200 +:64];
                24:bytes=digest[264 +:64];
                default:bytes=digest[320 +:64];
            endcase
            for(j=0;j<8;j=j+1) parsed_tree[(7-j)*8 +:8]=bytes[j*8 +:8];
            if(small_signature && node_bytes!=32) parsed_tree[63:54]=0;
            else if(!small_signature && node_bytes!=32) parsed_tree[63]=0;
        end
    endfunction
    function automatic [9:0] parsed_leaf(input [V-1:0] digest);
        begin
            if(small_signature) begin
                case(node_bytes)
                    16:parsed_leaf={1'b0,digest[224],digest[232 +:8]};
                    24:parsed_leaf={1'b0,digest[296],digest[304 +:8]};
                    default:parsed_leaf={2'b0,digest[368 +:8]};
                endcase
            end else parsed_leaf=node_bytes==16 ? {7'b0,digest[264 +:3]}
                : node_bytes==24 ? {7'b0,digest[328 +:3]} : {6'b0,digest[384 +:4]};
        end
    endfunction
    task automatic fail(input [15:0] code);
        begin error<=1; error_code<=code; abort_execution<=1; enter_state(FAILED); end
    endtask
    task automatic complete_macro;
        begin seq_complete<=1; enter_state(FETCH); end
    endtask
    task automatic route_result(input [1:0] source);
        begin route_source<=source; enter_state(ROUTE); end
    endtask
    task automatic start_output(input [255:0] v, input [5:0] length, input state_t ret);
        begin emit_value<=v; emit_length<=length; output_return<=ret; enter_state(OUTPUT_CHUNK); end
    endtask
    // All slots have completed before this transition. Their capture data
    // stays intact until the final output beat, then the whole batch is free.
    task automatic advance_direct_batch;
        begin
            if(chain_cursor+PIPELINE<endpoint_count)begin
                chain_cursor<=chain_cursor+PIPELINE;
                pipe_pair<=0;pipe_issue_slot<=0;pipe_done_mask<=0;
                for(integer q=0;q<PIPE_BATCH;q=q+1)
                    pipe_expected_mask[q]<=32'(chain_cursor)+PIPELINE+q<endpoint_count;
                enter_state(PIPE_ISSUE);
            end else begin
                chain_cursor<=endpoint_count-1'b1;enter_state(CHAIN_NEXT);
            end
        end
    endtask
    task automatic start_hash(input [63:0] selected_recipe, input state_t ret);
        begin
            task_recipe<=selected_recipe;
            hash_return<=ret; enter_state(HASH_ISSUE);
        end
    endtask
    task automatic read_verify_node(input state_t ret);
        begin
            verify_return<=ret;
            enter_state(VERIFY_INPUT);
        end
    endtask

    always_comb begin
        endpoint_write=0;endpoint_address=chain_cursor;endpoint_data=result[W-1:0];
        endpoint_read0_raw=lane_list0;endpoint_read1_raw=lane_list1;
        if(lt_pipe)begin
            endpoint_write=pipe_valid && state==LT_PIPE_WAIT;
            endpoint_address=(lt_cursor>>1)+INDEX_BITS'(pipe_tag);endpoint_data=pipe_read_result;
        end else if(pipe_direct && pipe_mode)begin
            endpoint_write=pipe_valid;
            endpoint_address=pipe_rolling ? pipe_chain_index[pipe_tag] : chain_cursor+INDEX_BITS'(pipe_tag);endpoint_data=pipe_read_result;
        end else if(state==CHAIN_STORE && indexing!=1)begin
            endpoint_write=1;
        end else if(state==LT_STORE || state==LT_COPY)begin
            endpoint_write=1;endpoint_address=lt_cursor>>1;
            endpoint_data=state==LT_COPY ? endpoint_value0 : result[W-1:0];
        end else if(root_write)begin
            endpoint_write=1;endpoint_address=INDEX_BITS'(group_index);endpoint_data=route_value[W-1:0];
        end

        if(state==LT_PIPE_ISSUE)begin
            endpoint_read0_raw=lt_cursor+(INDEX_BITS'(pipe_issue_slot)<<1);endpoint_read1_raw=endpoint_read0_raw+1'b1;
        end else if(state==LT_SETUP || state==LT_COPY)begin
            endpoint_read0_raw=lt_cursor;endpoint_read1_raw=lt_cursor+1'b1;
        end else if(state==LT_FINISH)begin endpoint_read0_raw=0;endpoint_read1_raw=1;end
    end

    generate if(P4_OPT)begin: read_addresses
        logic [INDEX_BITS-1:0] address;
        always_ff @(posedge clk)begin
            if(rst)address<=0;
            else if(state==REDUCE_SETUP || state==TREE_INIT)address<=0;
            else if(state==HASH_ISSUE || state==HASH_WAIT)address<=lane_list_next;
            else if(state==LT_PIPE_INIT)address<={lt_cursor[INDEX_BITS-1:1],1'b0};
            else if(state==LT_PIPE_ISSUE && pipe_ready)address<=lt_cursor+((INDEX_BITS'(pipe_issue_slot)+1'b1)<<1);
            else if(state==LT_PIPE_ADVANCE)begin
                if(lt_cursor+2*PIPELINE<lt_count)address<=lt_cursor+2*PIPELINE;
                else if(lt_count[0])address<=lt_count-1'b1;
                else address<=0;
            end else if(state==LT_NEXT)address<=0;
        end
        assign endpoint_read0=address;assign endpoint_read1=address+1'b1;
    end else begin
        assign endpoint_read0=endpoint_read0_raw;assign endpoint_read1=endpoint_read1_raw;
    end endgenerate

    // Validity is owned by the tree controller; data arrays have no reset.
    // Isolating these writes permits distributed RAM inference.
    wire auth_write=(state==PUSH_NODE && node_level<tree_height && node_index==((target>>node_level)^1))
        || state==FORS_AUTH0 || state==FORS_AUTH1;
    wire [4:0] auth_write_level=state==FORS_AUTH0 ? 5'd0 : state==FORS_AUTH1 ? 5'd1 : node_level;
    wire [255:0] auth_write_data=state==FORS_AUTH0 || state==FORS_AUTH1 ? pipe_read_result : node_value;
    always_ff @(posedge clk)begin
        if(auth_write)auth_path[auth_write_level]<=auth_write_data;
        if(state==PUSH_NODE && node_level<tree_height && !node_index[0])stack[node_level]<=node_value;
    end

    reg [255:0] emit_source;
    always_comb begin
        case(emit_descriptor[59:56])
            0: emit_source=secret_seed;
            1: emit_source=secret_prf;
            2: emit_source=public_seed;
            3: emit_source=value[3][W-1:0];
            4: emit_source=xmss ? value[0] : randomizer;
            5: emit_source={128'd0,job_identifier};
            6: emit_source={224'd0,be32(job_index)};
            7: emit_source=be32(emit_descriptor[31:0]);
            default: emit_source=0;
        endcase
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            enter_state(IDLE); done<=0; error<=0; error_code<=0; cycles<=0;
            abort_execution<=0;
            seq_start<=0; seq_complete<=0;
            operation<=0; scalar_tree<=0; scalar_leaf<=0;
            verify_pass<=0;
            verify_return<=IDLE;
            macro_op<=0; macro_desc<=0; macro_route<=0; macro_flags<=0;
            task_chain<=0; task_capture<=0;
            hash_base<=0; permutation_base<=0; layer<=0;
            task_recipe<=0; task_step<=0; message_received<=0;
            lt_count<=0;lt_cursor<=0;lt_level<=0;fors_level<=0;fors_pair_cursor<=0;
            pipe_cache_valid<=0;pipe_batch_used<=0;pipe_pair<=0;pipe_issue_slot<=0;
            pipe_rolling<=0;pipe_active<=0;pipe_next_chain<=0;pipe_completed<=0;
            pipe_done_mask<=0;pipe_expected_mask<=0;

                task_steps<=0; task_capture_after<=0;
                task_leaf<=0; task_a<=0; task_b<=0;
        end else begin
            done<=0; seq_start<=0; seq_complete<=0; abort_execution<=0;
            if(PROFILE_ENABLE && state!=IDLE && state!=FAILED) cycles<=cycles+1;
            if(P4_OPT && pipe_rolling && pipe_mode)begin
                if(pipe_valid)begin pipe_active[pipe_tag]<=0;pipe_completed<=pipe_completed+1'b1;end
                if(pipe_selected && pipe_ready)begin
                    pipe_active[issue_slot]<=1;pipe_chain_index[issue_slot]<=pipe_next_chain;
                    pipe_next_chain<=pipe_next_chain+1'b1;
                end
            end
            if(PIPELINE>1 && pipe_mode)begin
                if(pipe_valid && state!=LT_PIPE_ISSUE && (!fors_pipe || state==FORS_WAIT))begin
                    pipe_done_mask[pipe_tag]<=1;
                    if(!lt_pipe && pipe_direct && (pipe_rolling ? pipe_chain_index[pipe_tag]==0 : chain_cursor==0 && pipe_tag==0) && standalone_chain)
                        node_value<=pipe_read_result;
                end
            end
            case(state)
                IDLE: if(job_valid) begin
                    error<=0; error_code<=0; cycles<=0; operation<=job_operation;
                    verify_pass<=0;
                    message_length<=job_message_length; message_received<=0;
                    scalar_tree<=0; scalar_leaf<=stateful ? job_index[19:0] : 0; layer<=0; group_index<=0;
                    if(PROFILE_ENABLE) begin hash_base<=total_hashes; permutation_base<=total_permutations; end
                    value[3]<=job_public_root;
                    if(!valid_profile)fail(16'h3009);
                    else if(stateful && job_index>=(32'd1<<stateful_height))fail(16'h3008);
                    else if(job_operation) begin
                        enter_state(MESSAGE);
                    end else begin
                        enter_state(LAUNCH);
                    end
                end
                MESSAGE: if(message_valid) begin
                    // The offline-validated private ROM stream always supplies full
                    // eight-byte beats; its last word is already zero padded.
                    message_buffer[{message_received[6:3],6'b0} +:64]<=message_data;
                    message_received<=message_received+7'd8;
                    if(message_received+7'd8>=message_length) enter_state(LAUNCH);
                end
                LAUNCH: if(seq_ready) begin seq_start<=1; enter_state(FETCH); end
                FETCH: begin
                    if(seq_done) begin
                        if(verifying) begin
                                verify_pass <= value[2][127:0]==job_public_root[127:0]
                                    && (node_bytes==16 || value[2][191:128]==job_public_root[191:128])
                                    && (node_bytes!=32 || value[2][255:192]==job_public_root[255:192]);
                                enter_state(DRAIN);
                        end else enter_state(DRAIN);
                    end else if(cmd_valid) begin
                        macro_op<=cmd[47:44]; macro_desc<=cmd[43:36]; macro_route<=cmd[35:28];
                        macro_flags<=cmd[27:24]; layer<=cmd[23:19]; group_index<=cmd[18:13];
                        task_chain<=0; task_capture<=0;pipe_cache_valid<=0;pipe_batch_used<=0;
                        task_steps<=0;
                        enter_state(LOAD_DESCRIPTOR);
                    end
                end
                LOAD_DESCRIPTOR: begin saved_descriptor<=descriptors[0];enter_state(DECODE);end
                DECODE: begin
                    case(macro_op)
                    1: begin
                           task_leaf<=scalar_leaf;
                           task_a<=0; task_b<=0;
                           // The sign program starts with PRF_msg. Verification
                           // supplies that R as the first external node.
                           if(verifying && stateful && (saved_descriptor[59:56]==5 || saved_descriptor[59:56]==11))
                               read_verify_node(SF_RANDOM);
                           else if(verifying && saved_descriptor[59:56]==3)
                               read_verify_node(VERIFY_RANDOM);
                           else start_hash(saved_descriptor,HASH_RESULT);
                       end
                    2: begin
                           chain_id<=macro_desc; standalone_chain<=1; indexing<=0;
                           leaf_cursor<=stateful ? job_index[19:0] : 0; target<=stateful ? job_index[19:0] : 0; chain_cursor<=0;
                           endpoint_count<=descriptor[27:20];saved_chain_descriptor<=descriptor; enter_state(CHAIN_SETUP);
                       end
                    3: enter_state(TREE_INIT);
                    4: begin checksum<=0; transform_index<=0; enter_state(TRANSFORM); end
                    5: if(verifying && stateful)complete_macro(); else begin emit_base<=descriptor[59:52]; emit_count<=descriptor[51:48]; emit_cursor<=0; enter_state(EMIT); end
                    default: fail(16'h3006);
                endcase
                end
                TREE_INIT: begin
                    pipe_cache_valid<=0;pipe_batch_used<=0;
                    saved_chain_descriptor<=descriptors[6];

                    chain_id<=descriptor[59:52]; parent_id<=descriptor[51:44]; tree_height<={descriptor[39],descriptor[43:40]};
                    indexing<=descriptor[33:32]; standalone_chain<=0;
                    target<=stateful ? {1'b0,job_index[19:0]} : descriptor[37:36]==1 ? fors_target(group_index)
                        : scalar_leaf;
                    leaf_cursor<=verifying ? scalar_leaf : 0;
                    chain_cursor<=0; node_level<=0; auth_level<=0;
                    endpoint_count<=descriptors[6][27:20];
                    if(stateful && verifying)begin
                        node_value<=value[2];node_index<=job_index[19:0];enter_state(PUSH_NODE);
                    end else enter_state(CHAIN_SETUP);
                end
                CHAIN_SETUP: begin
                    if(P4_OPT && !pipe_cache_valid)begin
                        pipe_rolling<=pipe_direct && !(macro_flags[0] && leaf_cursor==target);
                        pipe_active<=0;pipe_next_chain<=chain_cursor;pipe_completed<=0;
                    end
                    if(stateful && PIPELINE>1)begin
                        if(pipe_cache_valid)begin pipe_pair<=pipe_pair+1'b1;enter_state(PIPE_LOAD);end
                        else begin
                            pipe_pair<=0;pipe_issue_slot<=0;pipe_done_mask<=0;
                            for(integer q=0;q<PIPE_BATCH;q=q+1)
                                pipe_expected_mask[q]<=32'(chain_cursor)+q<endpoint_count;
                            pipe_seed_domain<=descriptors[4][55:48];pipe_step_domain<=descriptors[5][55:48];
                            enter_state(verifying ? PIPE_VERIFY_INPUT : PIPE_ISSUE);
                        end
                    end else if(verifying) begin
                        task_chain<=0; task_capture<=0; task_step<=descriptors[5];

                            task_steps<=0;
                            task_leaf<=scalar_leaf;
                            task_a<=indexing==1 ? 0 : chain_cursor;
                            task_b<=indexing==1 ? (group_index<<FORS_A)+target : digit(chain_cursor);
                        read_verify_node(VERIFY_CHAIN_INPUT);
                    end else if(!stateful && PIPELINE>1 && descriptors[4][59:56]==1 && descriptors[5][59:56]==2)begin
                        if(pipe_cache_valid)begin pipe_pair<=pipe_pair+1'b1;enter_state(PIPE_LOAD);end
                        else begin
                            pipe_pair<=0;pipe_issue_slot<=0;pipe_done_mask<=0;
                            for(integer q=0;q<PIPE_BATCH;q=q+1)
                                pipe_expected_mask[q]<=indexing==1 ? (32'(leaf_cursor)+q < (32'd1<<tree_height))
                                    : (32'(chain_cursor)+q < endpoint_count);
                            pipe_seed_domain<=descriptors[4][55:48];pipe_step_domain<=descriptors[5][55:48];
                            enter_state(PIPE_ISSUE);
                        end
                    end else begin
                    pipe_batch_used<=0;
                    task_chain<=1; task_step<=descriptors[5];

                        task_capture<=(indexing==1 ? leaf_cursor==target : leaf_cursor==target) && macro_flags[0];
                        task_leaf<=indexing==1 ? scalar_leaf : leaf_cursor;
                        task_a<=indexing==1 ? 0 : chain_cursor;
                        task_b<=indexing==1 ? (group_index<<FORS_A)+leaf_cursor : 0;
                        task_steps<=(sign_only || (macro_flags[3] && leaf_cursor==target))
                            ? digit(chain_cursor) : chain_descriptor[19:15];
                        task_capture_after<=indexing==1 ? 0 : digit(chain_cursor);
                    start_hash(descriptors[4],CHAIN_STORE);
                    end
                end
                PIPE_ISSUE: begin
                    if(pipe_rolling)begin
                        if(pipe_valid && pipe_completed+1>=endpoint_count)begin
                            pipe_rolling<=0;pipe_batch_used<=1;pipe_cache_valid<=0;
                            chain_cursor<=endpoint_count-1'b1;enter_state(CHAIN_NEXT);
                        end
                    end else if(!pipe_expected_mask[pipe_issue_slot] || pipe_ready)begin
                        if(pipe_issue_slot+1>=PIPELINE ||
                           (pipe_direct && (pipe_expected_mask>>(pipe_issue_slot+1))==0))enter_state(PIPE_WAIT);
                        else pipe_issue_slot<=pipe_issue_slot+1'b1;
                    end
                end
                PIPE_VERIFY_INPUT: if(verify_valid && pipe_ready)begin
                    if(pipe_issue_slot+1>=PIPELINE || (pipe_expected_mask>>(pipe_issue_slot+1))==0)
                        enter_state(PIPE_WAIT);
                    else pipe_issue_slot<=pipe_issue_slot+1'b1;
                end
                PIPE_WAIT: if(pipe_direct && !(macro_flags[0] && leaf_cursor==target)
                    && ((pipe_done_mask | (pipe_valid ? (PIPE_BATCH'(1)<<pipe_tag) : '0))
                        & pipe_expected_mask)==pipe_expected_mask)begin
                    // The final response writes the endpoint on this edge.
                    // Captures retain the registered completion path so a
                    // one-slot tail never reads capture RAM before its write.
                    pipe_cache_valid<=0;pipe_batch_used<=1;pipe_pair<=0;
                    advance_direct_batch();
                end else if((pipe_done_mask & pipe_expected_mask)==pipe_expected_mask)begin
                    if(pipe_direct)begin
                        pipe_cache_valid<=0;pipe_batch_used<=1;pipe_pair<=0;
                        if(macro_flags[0] && leaf_cursor==target)begin
                            start_output(pipe_read_capture,node_bytes,PIPE_CAPTURE_NEXT);
                            pipe_pair<=1;
                        end else advance_direct_batch();
                    end else if(P4_OPT && indexing==1 && pipe_expected_mask=={PIPE_BATCH{1'b1}} && !verifying)begin pipe_cache_valid<=0;pipe_batch_used<=1;enter_state(FORS_PICK);end
                    else enter_state(PIPE_LOAD);
                end
                FORS_PICK:begin
                    if(fors_target_group && macro_flags[0])start_output(pipe_read_capture,node_bytes,FORS_AUTH0);
                    else if(fors_target_group)enter_state(FORS_AUTH0);
                    else enter_state(FORS_BEGIN);
                end
                FORS_AUTH0:enter_state(FORS_BEGIN);
                FORS_BEGIN:begin
                    fors_level<=0;fors_pair_cursor<=0;pipe_done_mask<=0;pipe_expected_mask<=PIPE_BATCH'(3);
                    pipe_seed_domain<=3;pipe_step_domain<=3;enter_state(FORS_LEFT);
                end
                FORS_LEFT:begin task_left0<=pipe_read_result;enter_state(FORS_RIGHT);end
                FORS_RIGHT:begin node_value<=pipe_read_result;enter_state(FORS_ISSUE);end
                FORS_ISSUE:if(pipe_ready)begin
                    if(!fors_level && !fors_pair_cursor)begin fors_pair_cursor<=1;enter_state(FORS_LEFT);end
                    else enter_state(FORS_WAIT);
                end
                FORS_WAIT:if(((pipe_done_mask | (pipe_valid ? (PIPE_BATCH'(1)<<pipe_tag) : '0)) & pipe_expected_mask)==pipe_expected_mask)
                    enter_state(fors_level ? FORS_PUSH : (fors_target_group ? FORS_AUTH1 : FORS_LEVEL));
                FORS_AUTH1:enter_state(FORS_LEVEL);
                FORS_LEVEL:begin fors_level<=1;fors_pair_cursor<=0;pipe_done_mask<=0;pipe_expected_mask<=PIPE_BATCH'(1);enter_state(FORS_LEFT);end
                FORS_PUSH:begin
                    node_value<=pipe_read_result;node_level<=2;node_index<=leaf_cursor>>2;
                    leaf_cursor<=leaf_cursor+3;pipe_cache_valid<=0;pipe_batch_used<=0;
                    enter_state(PUSH_NODE);
                end
                PIPE_LOAD: begin
                    pipe_batch_used<=1;
                    pipe_cache_valid<=pipe_pair+1<PIPELINE && ((pipe_expected_mask>>(pipe_pair+1))!=0);
                    result<={{(V-W){1'b0}},pipe_read_result};
                    enter_state(CHAIN_STORE);
                end
                CHAIN_STORE: begin
                    if(standalone_chain && chain_cursor==0)node_value<=result[W-1:0];
                    task_chain<=0;
                    if(sign_only || (!verifying && macro_flags[0] && leaf_cursor==target)) enter_state(CHAIN_OUTPUT0);
                    else enter_state(CHAIN_NEXT);
                end
                CHAIN_OUTPUT0: start_output(sign_only ? result[W-1:0] : selected_capture,node_bytes,CHAIN_NEXT);
                CHAIN_NEXT: begin
                    if(indexing!=1 && chain_cursor+1<endpoint_count) begin chain_cursor<=chain_cursor+1; enter_state(CHAIN_SETUP); end
                    else if(sign_only)complete_macro();
                    else if(stateful && chain_descriptor[13:12]==2)begin
                        lt_count<=endpoint_count;lt_cursor<=0;lt_level<=0;enter_state(LT_SETUP);
                    end else if(standalone_chain && chain_descriptor[13:12]==0)
                        route_result(ROUTE_NODE);
                    else if(!verifying && macro_flags[3] && leaf_cursor==target) begin
                        node_value<=0; node_level<=0; node_index<=leaf_cursor; enter_state(PUSH_NODE);
                    end else if(chain_descriptor[13:12]==0) begin
                        node_value<=result[W-1:0]; node_level<=0; node_index<=leaf_cursor; enter_state(PUSH_NODE);
                    end else begin
                        enter_state(REDUCE_SETUP);
                    end
                end
                REDUCE_SETUP: begin
                    task_chain<=0; task_capture<=0; task_steps<=0;
                    task_leaf<=leaf_cursor; task_a<=0; task_b<=0;
                    start_hash(descriptors[4],stateful ? SF_REDUCED : LEAF_SETUP);
                end
                LT_SETUP: begin
                    if(P4_OPT)enter_state(LT_PIPE_INIT);
                    else if(lt_cursor+1>=lt_count)enter_state(LT_COPY);
                    else begin
                        task_chain<=0;task_capture<=0;task_steps<=0;
                        task_leaf<=leaf_cursor;task_a<=lt_level;task_b<=lt_cursor>>1;
                        task_left0<=endpoint_value0;node_value<=endpoint_value1;
                        start_hash(descriptors[4],LT_STORE);
                    end
                end
                LT_PIPE_INIT:begin
                    pipe_rolling<=0;
                    if(lt_cursor+1>=lt_count)enter_state(LT_COPY);
                    else begin
                        pipe_issue_slot<=0;pipe_done_mask<=0;
                        pipe_seed_domain<=descriptors[4][55:48];pipe_step_domain<=descriptors[4][55:48];
                        for(integer q=0;q<PIPE_BATCH;q++)pipe_expected_mask[q]<=32'(lt_cursor)+2*q+1<lt_count;
                        enter_state(LT_PIPE_ISSUE);
                    end
                end
                LT_PIPE_ISSUE:if(pipe_ready)begin
                    if(pipe_issue_slot+1>=PIPELINE || (pipe_expected_mask>>(pipe_issue_slot+1))==0)enter_state(LT_PIPE_WAIT);
                    else pipe_issue_slot<=pipe_issue_slot+1'b1;
                end
                LT_PIPE_WAIT:if(((pipe_done_mask | (pipe_valid ? (PIPE_BATCH'(1)<<pipe_tag) : '0)) & pipe_expected_mask)==pipe_expected_mask)
                    enter_state(LT_PIPE_ADVANCE);
                LT_PIPE_ADVANCE:begin
                    if(lt_cursor+2*PIPELINE<lt_count)begin lt_cursor<=lt_cursor+2*PIPELINE;enter_state(LT_PIPE_INIT);end
                    else if(lt_count[0])begin lt_cursor<=lt_count-1'b1;enter_state(LT_COPY);end
                    else if(lt_count<=2)enter_state(LT_FINISH);
                    else begin lt_count<=(lt_count+1)>>1;lt_cursor<=0;lt_level<=lt_level+1'b1;enter_state(LT_PIPE_INIT);end
                end
                LT_STORE,LT_COPY:enter_state(LT_NEXT);
                LT_NEXT:begin
                    if(lt_cursor+2<lt_count)begin lt_cursor<=lt_cursor+2;enter_state(LT_SETUP);end
                    else if(lt_count<=2)enter_state(LT_FINISH);
                    else begin lt_count<=(lt_count+1)>>1;lt_cursor<=0;lt_level<=lt_level+1'b1;enter_state(LT_SETUP);end
                end
                LT_FINISH:begin
                    node_value<=endpoint_value0;
                    if(verifying && standalone_chain)begin value[2]<=endpoint_value0;complete_macro();end
                    else begin node_index<=leaf_cursor;node_level<=0;enter_state(PUSH_NODE);end
                end
                SF_REDUCED:enter_state(SF_LEAF);
                SF_LEAF:begin
                    task_chain<=0;task_capture<=0;task_steps<=0;
                    task_leaf<=leaf_cursor;task_a<=0;task_b<=(32'd1<<stateful_height)+32'(leaf_cursor);
                    task_left0<=result[W-1:0];start_hash(descriptors[0],SF_LEAF_DONE);
                end
                SF_LEAF_DONE:begin
                    node_value<=result[W-1:0];
                    if(verifying && standalone_chain)begin value[2]<=result[W-1:0];complete_macro();end
                    else begin node_index<=leaf_cursor;node_level<=0;enter_state(PUSH_NODE);end
                end
                SF_RANDOM:begin
                    value[0]<=emit_value;
                    if(xmss)complete_macro();else start_hash(saved_descriptor,HASH_RESULT);
                end
                LEAF_SETUP: if(standalone_chain)route_result(ROUTE_HASH);
                    else begin node_value<=result[W-1:0]; node_level<=0;
                        node_index<=verifying ? target : leaf_cursor; enter_state(PUSH_NODE); end
                PUSH_NODE: begin
                    if(node_level==tree_height) begin
                        auth_level<=0;
                        if(!verifying && macro_flags[1]) enter_state(AUTH_OUTPUT);
                        else enter_state(TREE_FINISH);
                    end else if(verifying) read_verify_node(PARENT_SETUP);
                    else if(node_index[0]) enter_state(PARENT_SETUP);
                    else begin
                        leaf_cursor<=leaf_cursor+1'b1; chain_cursor<=0; enter_state(CHAIN_SETUP);
                    end
                end
                PARENT_SETUP: begin
                    if(!verifying && macro_flags[3] && (node_index>>1)==(target>>(node_level+1))) begin
                        node_value<=0; node_index<=node_index>>1; node_level<=node_level+1'b1; enter_state(PUSH_NODE);
                    end else begin
                        task_chain<=0; task_capture<=0; task_steps<=0;
                        task_leaf<=indexing==1 ? scalar_leaf : 0;
                        task_a<=descriptors[7][59:56]==8 ? node_level : node_level+1'b1;
                        task_b<=indexing==1 ? ((group_index<<FORS_A)>>(node_level+1))+(node_index>>1)
                            : indexing==2 ? (1<<(tree_height-node_level-1))+(node_index>>1) : (node_index>>1);
                        task_left0<=verifying ? (node_index[0] ? emit_value : node_value) : stack[node_level];
                        start_hash(descriptors[4],PARENT_DONE);
                    end
                end
                PARENT_DONE: begin
                    node_value<=result[W-1:0]; node_index<=node_index>>1; node_level<=node_level+1'b1; enter_state(PUSH_NODE);
                end
                AUTH_OUTPUT: begin
                    if(auth_level<tree_height) begin
                        start_output(auth_path[auth_level],node_bytes,AUTH_OUTPUT); auth_level<=auth_level+1'b1;
                    end else enter_state(TREE_FINISH);
                end
                TREE_FINISH: begin
                    if(stateful && verifying)value[2]<=node_value;
                    route_result(!verifying && macro_flags[3] ? ROUTE_SAVED : ROUTE_NODE);
                end
                HASH_ISSUE: if(lane_ready)enter_state(HASH_WAIT);
                HASH_WAIT: if(lane_valid)begin
                    result<=lane_value;
                    if(lane_error)fail(16'h3007);
                    else enter_state(hash_return);
                end
                HASH_RESULT: route_result(ROUTE_HASH);
                ROUTE: begin
                    if(macro_route==0) complete_macro();
                    else begin
                        if(!route_descriptor[53]) begin
                            value[route_descriptor[57:56]]<=route_value[W-1:0];
                            if(route_descriptor[57:56]==1)
                                fors_digest_tail<=route_value[FORS_DIGEST_BITS-1:W];
                        end
                        if(route_descriptor[54]) begin
                            scalar_tree <= parsed_tree(route_value);
                            scalar_leaf <= parsed_leaf(route_value);
                        end
                        if(!verifying && route_descriptor[55]) start_output(route_value[W-1:0],node_bytes,FETCH);
                        else enter_state(FETCH);
                        seq_complete<=1;
                    end
                end
                TRANSFORM: begin
                    if(descriptor[59:56]==2) begin
                        scalar_leaf<=scalar_tree & ((1<<descriptor[43:40])-1);
                        scalar_tree<=scalar_tree>>descriptor[43:40]; complete_macro();
                    end else if(descriptor[59:56]==1) begin
                        checksum<=checksum+chain_max-digit(transform_index);
                        if(transform_index+1==LEN1) complete_macro();
                        else transform_index<=transform_index+1'b1;
                    end else fail(16'h3006);
                end
                EMIT: begin
                    start_output(emit_source,emit_descriptor[53:48],EMIT_NEXT);
                end
                EMIT_NEXT: begin
                    if(emit_cursor+1<emit_count) begin emit_cursor<=emit_cursor+1'b1; enter_state(EMIT); end
                    else complete_macro();
                end
                VERIFY_INPUT: if(verify_valid) begin
                    emit_value<=verify_data;
                    enter_state(verify_return);
                end
                VERIFY_RANDOM: route_result(ROUTE_EMIT);
                VERIFY_CHAIN_INPUT: begin
                    // A WOTS digit of 15 already is an endpoint: zero hashes.
                    result<={{(V-W){1'b0}},emit_value};
                    if(indexing==1) start_hash(task_step,LEAF_SETUP);
                    else enter_state(VERIFY_CHAIN_RUN);
                end
                VERIFY_CHAIN_RUN: begin
                    if(!verify_step_needed) begin
                        enter_state(CHAIN_STORE);
                    end else start_hash(descriptors[0],VERIFY_CHAIN_ADVANCE);
                end
                VERIFY_CHAIN_ADVANCE: begin
                    task_b<={28'd0,task_b[3:0]+4'd1};
                    enter_state(VERIFY_CHAIN_RUN);
                end
                OUTPUT_CHUNK: begin
                    if(pipe_direct && output_return==PIPE_CAPTURE_NEXT)begin
                        if(pipe_pair<PIPELINE && (pipe_expected_mask>>pipe_pair)!=0)begin
                            emit_value<=pipe_read_capture;pipe_pair<=pipe_pair+1'b1;
                        end else advance_direct_batch();
                    end else enter_state(output_return);
                end
                DRAIN: enter_state(FINISH);
                FINISH: begin
                    done<=1; enter_state(IDLE);
                end
                FAILED: enter_state(IDLE);
                default: fail(16'h3006);
            endcase
        end
    end
endmodule
`default_nettype wire
