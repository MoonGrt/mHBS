`timescale 1ns/1ps
`default_nettype none
// One ABI 4 SLH macro executor for n=16/24/32.
module uhbs_hbs #(
    parameter integer UNROLL=2, LANES=2,
    parameter bit PROFILE_ENABLE=0, SWAP_PHYSICAL_LANES=0
) (
    input wire [63:0] image_header, profile_descriptor,
    output wire [4:0] program_address,
    output wire [3:0] template_address,
    input wire [63:0] program_data, template_data,
    input wire [4:0] job_entry,
    output wire [9:0] descriptor_addresses,
    input wire [127:0] descriptor_data,
    input wire clk, rst,
    input wire job_valid, output wire job_ready, input wire job_operation,
    input wire [6:0] job_message_length,
    input wire [255:0] job_secret_seed, job_secret_prf, job_public_seed, job_randomizer, job_public_root,
    input wire message_valid, output wire message_ready,
    input wire [63:0] message_data,
    output wire out_valid, input wire out_ready, output wire [63:0] out_data,
    output wire [7:0] out_keep, output wire out_last,
    output wire busy, output logic done, error, output logic [15:0] error_code,
    output wire [31:0] hash_count, permutation_count,
    output logic [31:0] cycles
);
    localparam integer N=32, W=256, V=392, INDEX_BITS=7, MAX_MESSAGE_BYTES=87;
    localparam integer DIGEST_BYTES=49;
    wire [1:0] profile_code=profile_descriptor[1:0];
    wire [5:0] node_bytes=profile_code==0 ? 6'd16
        : profile_code==1 ? 6'd24 : 6'd32;
    wire [3:0] FORS_A=profile_code==0 ? 4'd6 : profile_code==1 ? 4'd8 : 4'd9;
    wire [3:0] HP=profile_code[1] ? 4'd4 : 4'd3;
    wire [7:0] LEN1={1'b0,node_bytes,1'b0};
    wire [5:0] FORS_BYTES=node_bytes==16 ? 25 : node_bytes==24 ? 33 : 40;
    localparam integer TREE_BYTES=8;
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
    typedef enum logic [5:0] {
        IDLE, MESSAGE, LAUNCH, FETCH, LOAD_DESCRIPTOR, DECODE,
        TREE_INIT, CHAIN_SETUP, CHAIN_STORE, CHAIN_STORE2,
        CHAIN_OUTPUT0, CHAIN_OUTPUT1, CHAIN_OUTPUT2, CHAIN_OUTPUT3,
        CHAIN_NEXT, REDUCE_SETUP, LEAF_SETUP,
        PUSH_NODE, PARENT_SETUP, PARENT_DONE, AUTH_OUTPUT, TREE_FINISH,
        HASH_ISSUE, HASH_WAIT, HASH_RESULT, ROUTE, TRANSFORM,
        EMIT, EMIT_NEXT, OUTPUT_CHUNK, DRAIN, FINISH, FAILED
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
    logic operation;
    // Boot loader owns immutable Job registers for this reset epoch.
    wire [255:0] secret_seed=job_secret_seed, secret_prf=job_secret_prf;
    wire [255:0] public_seed=job_public_seed, randomizer=job_randomizer;
    logic [MAX_MESSAGE_BYTES*8-1:0] message_buffer;
    logic [6:0] message_length, message_received;
    logic [V-1:0] value [0:3];
    logic [63:0] scalar_tree;
    logic [9:0] scalar_leaf;
    logic [11:0] checksum;
    logic [6:0] transform_index;
    logic [17:0] output_bytes, emitted;
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
    uhbs_program_sequencer sequencer (
        .clk,.rst(execution_rst),.start(seq_start),.entry(job_entry),.ready(seq_ready),.done(seq_done),
        .program_address,.program_data,.template_address,.template_data,
        .command_valid(cmd_valid),.command_ready(state==FETCH),.command_done(seq_complete),.command(cmd)
    );

    logic [4:0] chain_id, parent_id;
    wire [63:0] chain_descriptor = saved_chain_descriptor;
    logic standalone_chain, fors_pair_pending;
    logic [3:0] tree_height, node_level, auth_level;
    logic [1:0] indexing;
    logic [9:0] target, leaf_cursor, node_index;
    logic [INDEX_BITS-1:0] chain_cursor, endpoint_count;
    logic [3:0] chain_batch_mask;
    always_comb begin
        chain_batch_mask=0;
        for(int lane_index=0; lane_index<4; lane_index=lane_index+1)
            if(lane_index<LANES && (indexing!=1 || lane_index<2) &&
               (indexing==1 || chain_cursor+lane_index<endpoint_count))
                chain_batch_mask[lane_index]=1;
    end
    logic [255:0] node_value;
    (* ram_style="distributed" *) logic [255:0] stack [0:15];
    (* ram_style="distributed" *) logic [255:0] auth_path [0:15];

    logic [4:0] hash_recipe_id;
    assign descriptor_addresses={state==CHAIN_SETUP ? chain_descriptor[48:44] : macro_route,hash_recipe_id[4:0]};
    always @* begin
        hash_recipe_id=macro_desc;
        case(state)
            TREE_INIT: hash_recipe_id={1'b0,saved_descriptor[58:52]};
            EMIT: hash_recipe_id=emit_base+emit_cursor;
            CHAIN_SETUP: hash_recipe_id=chain_descriptor[59:52];
            REDUCE_SETUP: hash_recipe_id=chain_descriptor[43:36];
            PARENT_SETUP: hash_recipe_id=parent_id;
            default: begin end
        endcase
    end
    logic [63:0] task_recipe, task_step;
    logic task_chain;
    logic [3:0] task_capture;
    logic [4:0] task_steps [0:3], task_capture_after [0:3];
    logic [9:0] task_leaf [0:3];
    logic [INDEX_BITS-1:0] task_a [0:3];
    logic [31:0] task_b [0:3];
    logic [255:0] task_left [0:3], task_right [0:3];
    logic [3:0] active_mask, launch_pending, response_pending;
    wire [3:0] lane_ready, lane_valid, lane_error;
    wire [V-1:0] lane_value [0:3];
    wire [255:0] lane_capture [0:3];
    wire [INDEX_BITS-1:0] lane_list0 [0:3], lane_list1 [0:3];
    wire [31:0] lane_hashes [0:3], lane_permutations [0:3];
    logic [31:0] hash_base, permutation_base;
    logic [V-1:0] result [0:3], route_value;
    logic [255:0] capture [0:3];
    wire [31:0] total_hashes = (lane_hashes[0]+lane_hashes[1])+(lane_hashes[2]+lane_hashes[3]);
    wire [31:0] total_permutations = (lane_permutations[0]+lane_permutations[1])+
        (lane_permutations[2]+lane_permutations[3]);
    assign hash_count = total_hashes-hash_base;
    assign permutation_count = total_permutations-permutation_base;

    logic endpoint_write0, endpoint_write1;
    logic [INDEX_BITS-1:0] endpoint_address0, endpoint_address1, endpoint_read0, endpoint_read1;
    logic [255:0] endpoint_data0, endpoint_data1;
    wire [255:0] endpoint_value0, endpoint_value1;
    logic task_list_roots;
    wire list_roots = task_list_roots;
    wire [255:0] root_value0, root_value1;
    wire [INDEX_BITS-1:0] root_read0 = lane_list0[0], root_read1 = lane_list1[0];
    uhbs_value_store #(.WIDTH(W),.DEPTH(68),.ADDRESS_BITS(INDEX_BITS)) endpoints (
        .clk, .write0(endpoint_write0), .write1(endpoint_write1),
        .address0(endpoint_address0), .address1(endpoint_address1),
        .data0(endpoint_data0), .data1(endpoint_data1),
        .read0(endpoint_read0), .read1(endpoint_read1),
        .value0(endpoint_value0), .value1(endpoint_value1)
    );
    generate begin: g_roots
    uhbs_root_store roots (
        .clk, .write(state==ROUTE && macro_route!=0 && route_descriptor[53]),
        .address(group_index), .data(route_value[W-1:0]),
        .read0(root_read0[5:0]), .read1(root_read1[5:0]), .value0(root_value0), .value1(root_value1)
    );
    end endgenerate
    genvar physical;
    generate for (physical=0; physical<LANES; physical=physical+1) begin: lanes
        localparam integer L=SWAP_PHYSICAL_LANES ? LANES-1-physical : physical;
        uhbs_recipe_lane #(.N(N),.DIGEST_BYTES(DIGEST_BYTES),.INDEX_BITS(INDEX_BITS),.UNROLL(UNROLL),.MAX_MESSAGE_BYTES(MAX_MESSAGE_BYTES),
            .RECIPE_MASK(L==0 ? 16'h101e : 16'h0006),
            .PROFILE_ENABLE(PROFILE_ENABLE)) lane (
            .clk,.rst(execution_rst),.node_bytes,.request_valid(state==HASH_ISSUE && launch_pending[L]),
            .request_ready(lane_ready[L]), .request_recipe(task_recipe), .request_step_recipe(task_step),
            .request_chain(task_chain), .request_steps(task_steps[L]),
            .request_capture_after(task_capture_after[L]),
            .request_capture(task_capture[L]),
            .secret_seed,.secret_prf,.public_seed,.root(value[3][W-1:0]),
            .randomizer(task_recipe[59:56]==4 ? value[0][W-1:0] : randomizer),
            .identifier(128'd0),.message_buffer,.message_length,
            .request_layer(layer),.request_tree(scalar_tree),.request_leaf(task_leaf[L]),
            .request_a(task_a[L]),.request_b(task_b[L]),.request_left(task_left[L]),.request_right(task_right[L]),
            .list_index0(lane_list0[L]),.list_index1(lane_list1[L]),
            .list_data0(list_roots ? root_value0 : endpoint_value0),
            .list_data1(list_roots ? root_value1 : endpoint_value1),
            .response_valid(lane_valid[L]),.response_ready(state==HASH_WAIT && response_pending[L]),
            .response_value(lane_value[L]),.response_capture(lane_capture[L]),.error(lane_error[L]),
            .hash_count(lane_hashes[L]),.permutation_count(lane_permutations[L])
        );
    end
    for (physical=LANES; physical<4; physical=physical+1) begin: unused_lane
        assign lane_ready[physical]=1; assign lane_valid[physical]=0; assign lane_error[physical]=0;
        assign lane_value[physical]=0; assign lane_capture[physical]=0;
        assign lane_list0[physical]=0; assign lane_list1[physical]=0;
        assign lane_hashes[physical]=0; assign lane_permutations[physical]=0;
    end endgenerate
    initial if(LANES!=1 && LANES!=2 && LANES!=4) $error("LANES must be 1, 2 or 4");

    logic [255:0] emit_value;
    logic [5:0] emit_length, emit_offset;
    logic [7:0] emit_base;
    logic [3:0] emit_count, emit_cursor;
    wire [63:0] emit_descriptor = descriptors[3];
    wire [5:0] emit_remaining=emit_length-emit_offset;
    wire [3:0] emit_chunk_bytes = emit_remaining>8 ? 8 : emit_remaining[3:0];
    wire pack_ready, pack_idle;
    // Each result chunk is transferred directly; keep marks its valid bytes.
    assign pack_ready=out_ready;
    assign pack_idle=1'b1;
    assign out_valid=state==OUTPUT_CHUNK;
    assign out_data=emit_value[{emit_offset[4:3],6'b0} +:64];
    assign out_keep=8'hff >> (8-emit_chunk_bytes);
    assign out_last=emitted+emit_chunk_bytes==output_bytes;
    assign job_ready=state==IDLE;
    assign message_ready=state==MESSAGE;
    assign busy=state!=IDLE;

    function automatic [31:0] be32(input [31:0] x);
        be32={x[7:0],x[15:8],x[23:16],x[31:24]};
    endfunction
    function automatic [4:0] digit(input [7:0] index);
        reg [7:0] checksum_index;
        begin
            checksum_index=index-LEN1;
            digit=0;
            if(index<LEN1) begin
                digit={1'b0,value[2][{(index[5:0]^6'd1),2'b0} +:4]};
            end else begin
                case(checksum_index)
                    0:digit={1'b0,checksum[11:8]}; 1:digit={1'b0,checksum[7:4]};
                    2:digit={1'b0,checksum[3:0]}; default:digit=0;
                endcase
            end
        end
    endfunction
    wire [V-1:0] fors_bitstream;
    genvar fb;
    generate for(fb=0;fb<V;fb=fb+1) begin: fors_bit_order
        assign fors_bitstream[fb]=value[1][(fb/8)*8+7-(fb%8)];
    end endgenerate
    function automatic [8:0] fors_target(input [5:0] group_number);
        reg [9:0] offset;
        reg [8:0] segment;
        begin
            offset=FORS_A==6 ? ({group_number,2'b0}+{group_number,1'b0})
                : FORS_A==8 ? {group_number,3'b0} : ({group_number,3'b0}+group_number);
            segment=fors_bitstream >> offset;
            case(FORS_A)
                6:fors_target={3'd0,segment[0],segment[1],segment[2],segment[3],segment[4],segment[5]};
                8:fors_target={1'b0,segment[0],segment[1],segment[2],segment[3],segment[4],segment[5],segment[6],segment[7]};
                default:fors_target={segment[0],segment[1],segment[2],segment[3],segment[4],segment[5],segment[6],segment[7],segment[8]};
            endcase
        end
    endfunction
    function automatic [63:0] parsed_tree(input [V-1:0] digest);
        reg [63:0] bytes;
        integer j;
        begin
            case(node_bytes)
                16:bytes=digest[200 +:64];
                24:bytes=digest[264 +:64];
                default:bytes=digest[320 +:64];
            endcase
            for(j=0;j<8;j=j+1) parsed_tree[(7-j)*8 +:8]=bytes[j*8 +:8];
            if(node_bytes!=32) parsed_tree[63]=0;
        end
    endfunction
    task automatic fail(input [15:0] code);
        begin error<=1; error_code<=code; abort_execution<=1; enter_state(FAILED); end
    endtask
    task automatic complete_macro;
        begin seq_complete<=1; enter_state(FETCH); end
    endtask
    task automatic route_result(input [V-1:0] v);
        begin route_value<=v; enter_state(ROUTE); end
    endtask
    task automatic start_output(input [255:0] v, input [5:0] length, input state_t ret);
        begin emit_value<=v; emit_length<=length; emit_offset<=0; output_return<=ret; enter_state(OUTPUT_CHUNK); end
    endtask
    task automatic start_hash(input [63:0] selected_recipe, input [3:0] mask, input state_t ret);
        begin
            task_recipe<=selected_recipe; active_mask<=mask;
            task_list_roots<=selected_recipe[59:56]==12 && selected_recipe[55:48]==4;
            launch_pending<=mask; response_pending<=mask;
            hash_return<=ret; enter_state(HASH_ISSUE);
        end
    endtask

    always_comb begin
        endpoint_write0=0; endpoint_write1=0;
        endpoint_address0=chain_cursor; endpoint_address1=chain_cursor+1'b1;
        endpoint_data0=result[0][W-1:0]; endpoint_data1=result[1][W-1:0];
        endpoint_read0=lane_list0[0]; endpoint_read1=lane_list1[0];
        if (state==CHAIN_STORE) begin
            endpoint_write0=active_mask[0]; endpoint_write1=active_mask[1];
        end
        if (state==CHAIN_STORE2) begin
            endpoint_write0=active_mask[2]; endpoint_write1=active_mask[3];
            endpoint_address0=chain_cursor+2'd2; endpoint_address1=chain_cursor+2'd3;
            endpoint_data0=result[2][W-1:0]; endpoint_data1=result[3][W-1:0];
        end
    end

    // Validity is owned by the tree controller; data arrays have no reset.
    // Isolating these writes permits distributed RAM inference.
    always_ff @(posedge clk) begin
        if(state==PUSH_NODE && node_level<tree_height) begin
            if(node_index==((target>>node_level)^1)) auth_path[node_level]<=node_value;
            if(!node_index[0]) stack[node_level]<=node_value;
        end
    end

    integer i;
    reg [255:0] emit_source;
    always_comb begin
        case(emit_descriptor[59:56])
            0: emit_source=secret_seed;
            1: emit_source=secret_prf;
            2: emit_source=public_seed;
            3: emit_source=value[3][W-1:0];
            4: emit_source=randomizer;
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
            macro_op<=0; macro_desc<=0; macro_route<=0; macro_flags<=0;
            active_mask<=0; launch_pending<=0; response_pending<=0;
            task_chain<=0; task_capture<=0;
            hash_base<=0; permutation_base<=0; emitted<=0; layer<=0;
            task_recipe<=0; task_step<=0; task_list_roots<=0; message_received<=0;
            fors_pair_pending<=0;
            for(i=0;i<4;i=i+1) begin
                task_steps[i]<=0; task_capture_after[i]<=0;
                task_leaf[i]<=0; task_a[i]<=0; task_b[i]<=0;
            end
        end else begin
            done<=0; seq_start<=0; seq_complete<=0; abort_execution<=0;
            if(state!=IDLE && state!=FAILED) cycles<=cycles+1;
            case(state)
                IDLE: if(job_valid) begin
                    error<=0; error_code<=0; cycles<=0; operation<=job_operation;
                    message_length<=job_message_length; message_received<=0;
                    scalar_tree<=0; scalar_leaf<=0; layer<=0; group_index<=0;
                    emitted<=0; output_bytes<=job_operation ? image_header[17:0] : image_header[35:18];
                    hash_base<=total_hashes; permutation_base<=total_permutations;
                    value[3]<={{(V-W){1'b0}},job_public_root};
                    if(job_operation) begin
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
                        if(emitted!=output_bytes) fail(16'h3005);
                        else enter_state(DRAIN);
                    end else if(cmd_valid) begin
                        macro_op<=cmd[47:44]; macro_desc<=cmd[43:36]; macro_route<=cmd[35:28];
                        macro_flags<=cmd[27:24]; layer<=cmd[23:19]; group_index<=cmd[18:13];
                        task_chain<=0; task_capture<=0;
                        for(i=0;i<4;i=i+1) task_steps[i]<=0;
                        enter_state(LOAD_DESCRIPTOR);
                    end
                end
                LOAD_DESCRIPTOR: begin saved_descriptor<=descriptors[0];enter_state(DECODE);end
                DECODE: begin
                    case(macro_op)
                    1: begin
                           task_leaf[0]<=scalar_leaf;
                           task_a[0]<=0; task_b[0]<=0;
                           start_hash(saved_descriptor,2'b01,HASH_RESULT);
                       end
                    2: begin
                           chain_id<=macro_desc; standalone_chain<=1; indexing<=0;
                           leaf_cursor<=0; target<=0; chain_cursor<=0;
                           endpoint_count<=descriptor[27:20];saved_chain_descriptor<=descriptor; enter_state(CHAIN_SETUP);
                       end
                    3: enter_state(TREE_INIT);
                    4: begin checksum<=0; transform_index<=0; enter_state(TRANSFORM); end
                    5: begin emit_base<=descriptor[59:52]; emit_count<=descriptor[51:48]; emit_cursor<=0; enter_state(EMIT); end
                    default: fail(16'h3006);
                endcase
                end
                TREE_INIT: begin
                    saved_chain_descriptor<=descriptors[6];
                    fors_pair_pending<=0;
                    chain_id<=descriptor[59:52]; parent_id<=descriptor[51:44]; tree_height<=descriptor[43:40];
                    indexing<=descriptor[33:32]; standalone_chain<=0;
                    target<=descriptor[37:36]==1 ? fors_target(group_index)
                        : scalar_leaf;
                    leaf_cursor<=0; chain_cursor<=0; node_level<=0; auth_level<=0;
                    endpoint_count<=descriptors[6][27:20];
                    enter_state(CHAIN_SETUP);
                end
                CHAIN_SETUP: begin
                    task_chain<=1; task_step<=descriptors[5];
                    for(i=0;i<4;i=i+1) begin
                        task_capture[i]<=(indexing==1 ? leaf_cursor+i==target : leaf_cursor==target) && macro_flags[0];
                        task_leaf[i]<=indexing==1 ? scalar_leaf : leaf_cursor;
                        task_a[i]<=indexing==1 ? 0 : chain_cursor+i;
                        task_b[i]<=indexing==1 ? (group_index<<FORS_A)+leaf_cursor+i : 0;
                        task_steps[i]<=(macro_flags[3] && leaf_cursor==target)
                            ? digit(chain_cursor+i) : chain_descriptor[19:15];
                        task_capture_after[i]<=indexing==1 ? 0 : digit(chain_cursor+i);
                    end
                    start_hash(descriptors[4],chain_batch_mask,CHAIN_STORE);
                end
                CHAIN_STORE: begin
                    if(standalone_chain && chain_cursor==0)node_value<=result[0][W-1:0];
                    task_chain<=0;
                    if(|active_mask[3:2]) enter_state(CHAIN_STORE2);
                    else if(macro_flags[0] && (leaf_cursor==target || (indexing==1 && active_mask[1] && leaf_cursor+1==target))) enter_state(CHAIN_OUTPUT0);
                    else enter_state(CHAIN_NEXT);
                end
                CHAIN_STORE2: begin
                    if(macro_flags[0] && leaf_cursor==target) enter_state(CHAIN_OUTPUT0);
                    else enter_state(CHAIN_NEXT);
                end
                CHAIN_OUTPUT0: start_output(indexing==1 && active_mask[1] && target[0]
                    ? capture[1] : capture[0],node_bytes,
                    active_mask[1] && indexing!=1 ? CHAIN_OUTPUT1 : CHAIN_NEXT);
                CHAIN_OUTPUT1: start_output(capture[1],node_bytes,
                    active_mask[2] ? CHAIN_OUTPUT2 : CHAIN_NEXT);
                CHAIN_OUTPUT2: start_output(capture[2],node_bytes,
                    active_mask[3] ? CHAIN_OUTPUT3 : CHAIN_NEXT);
                CHAIN_OUTPUT3: start_output(capture[3],node_bytes,CHAIN_NEXT);
                CHAIN_NEXT: begin
                    if(indexing!=1 && chain_cursor+LANES<endpoint_count) begin chain_cursor<=chain_cursor+LANES; enter_state(CHAIN_SETUP); end
                    else if(standalone_chain && chain_descriptor[13:12]==0)
                        route_result({{(V-W){1'b0}},node_value});
                    else if(macro_flags[3] && leaf_cursor==target) begin
                        node_value<=0; node_level<=0; node_index<=leaf_cursor; enter_state(PUSH_NODE);
                    end else if(chain_descriptor[13:12]==0) begin
                        fors_pair_pending<=indexing==1 && active_mask[1];
                        node_value<=result[0][W-1:0]; node_level<=0; node_index<=leaf_cursor; enter_state(PUSH_NODE);
                    end else begin
                        enter_state(REDUCE_SETUP);
                    end
                end
                REDUCE_SETUP: begin
                    task_chain<=0; task_capture<=0; task_steps[0]<=0;
                    task_leaf[0]<=leaf_cursor; task_a[0]<=0; task_b[0]<=0;
                    start_hash(descriptors[4],2'b01,LEAF_SETUP);
                end
                LEAF_SETUP: if(standalone_chain)route_result(result[0]);
                    else begin node_value<=result[0][W-1:0]; node_level<=0; node_index<=leaf_cursor; enter_state(PUSH_NODE); end
                PUSH_NODE: begin
                    if(node_level==tree_height) begin
                        auth_level<=0;
                        if(macro_flags[1]) enter_state(AUTH_OUTPUT);
                        else enter_state(TREE_FINISH);
                    end else if(node_index[0]) enter_state(PARENT_SETUP);
                    else if(fors_pair_pending) begin
                        node_value<=result[1][W-1:0]; node_level<=0;
                        node_index<=leaf_cursor+1'b1; leaf_cursor<=leaf_cursor+1'b1;
                        fors_pair_pending<=0;
                    end else begin
                        leaf_cursor<=leaf_cursor+1'b1; chain_cursor<=0; enter_state(CHAIN_SETUP);
                    end
                end
                PARENT_SETUP: begin
                    if(macro_flags[3] && (node_index>>1)==(target>>(node_level+1))) begin
                        node_value<=0; node_index<=node_index>>1; node_level<=node_level+1'b1; enter_state(PUSH_NODE);
                    end else begin
                        task_chain<=0; task_capture<=0; task_steps[0]<=0;
                        task_leaf[0]<=indexing==1 ? scalar_leaf : 0;
                        task_a[0]<=descriptors[7][59:56]==8 ? node_level : node_level+1'b1;
                        task_b[0]<=indexing==1 ? ((group_index<<FORS_A)>>(node_level+1))+(node_index>>1)
                            : indexing==2 ? (1<<(tree_height-node_level-1))+(node_index>>1) : (node_index>>1);
                        task_left[0]<=stack[node_level]; task_right[0]<=node_value;
                        start_hash(descriptors[4],2'b01,PARENT_DONE);
                    end
                end
                PARENT_DONE: begin
                    node_value<=result[0][W-1:0]; node_index<=node_index>>1; node_level<=node_level+1'b1; enter_state(PUSH_NODE);
                end
                AUTH_OUTPUT: begin
                    if(auth_level<tree_height) begin
                        start_output(auth_path[auth_level],node_bytes,AUTH_OUTPUT); auth_level<=auth_level+1'b1;
                    end else enter_state(TREE_FINISH);
                end
                TREE_FINISH: route_result(macro_flags[3] ? value[3] : {{(V-W){1'b0}},node_value});
                HASH_ISSUE: begin
                    launch_pending<=launch_pending & ~lane_ready;
                    if((launch_pending & ~lane_ready)==0) enter_state(HASH_WAIT);
                end
                HASH_WAIT: begin
                    for(i=0;i<4;i=i+1) if(response_pending[i] && lane_valid[i]) begin
                        result[i]<=lane_value[i]; capture[i]<=lane_capture[i];
                    end
                    response_pending<=response_pending & ~lane_valid;
                    if((lane_error & response_pending & lane_valid)!=0) fail(16'h3007);
                    else if((response_pending & ~lane_valid)==0) enter_state(hash_return);
                end
                HASH_RESULT: route_result(result[0]);
                ROUTE: begin
                    if(macro_route==0) complete_macro();
                    else begin
                        if(!route_descriptor[53]) value[route_descriptor[57:56]]<=route_value;
                        if(route_descriptor[54]) begin
                            scalar_tree <= parsed_tree(route_value);
                            scalar_leaf <= node_bytes==16 ? {7'b0,route_value[264 +:3]} : node_bytes==24 ? {7'b0,route_value[328 +:3]} : {6'b0,route_value[384 +:4]};
                        end
                        if(route_descriptor[55]) start_output(route_value[W-1:0],node_bytes,FETCH);
                        else enter_state(FETCH);
                        seq_complete<=1;
                    end
                end
                TRANSFORM: begin
                    if(descriptor[59:56]==2) begin
                        scalar_leaf<=scalar_tree & ((1<<descriptor[43:40])-1);
                        scalar_tree<=scalar_tree>>descriptor[43:40]; complete_macro();
                    end else if(descriptor[59:56]==1) begin
                        checksum<=checksum+15-digit(transform_index);
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
                OUTPUT_CHUNK: if(pack_ready) begin
                    emitted<=emitted+emit_chunk_bytes;
                    if(emit_remaining<=8) enter_state(output_return);
                    else emit_offset<=emit_offset+8;
                end
                DRAIN: if(pack_idle) enter_state(FINISH);
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
