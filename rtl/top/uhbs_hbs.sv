`timescale 1ns/1ps
`default_nettype none
// One ABI 4 macro executor for n=16/24/32. Algorithm selection is confined
// to immutable image data. The same chain iterator and stack tree reducer
// serve all profiles; stateful images retain the selected authentication path.
module uhbs_hbs #(
    parameter integer N=16, UNROLL=2, LANES=2, MAX_MESSAGE_BYTES=87,
    parameter integer PROGRAM_TOKENS=14, PROGRAM_TEMPLATES=11,
    parameter [15:0] RECIPE_MASK=16'hffff,
    parameter [15:0] CHAIN_RECIPE_MASK=RECIPE_MASK,
    parameter bit STATEFUL=0, PROFILE_ENABLE=0, SWAP_PHYSICAL_LANES=0,
    parameter integer OMEGA=4, CHAIN_COUNT=N==16 ? 35 : 67,
    parameter integer DIGEST_BYTES=N==16 ? 34 : 32,
    parameter integer FORS_A=STATEFUL ? 0 : 6, FORS_K=STATEFUL ? 0 : 33,
    parameter integer TREE_BITS=STATEFUL ? 0 : 63, HP=STATEFUL ? 10 : 3,
    parameter TOKEN_INIT_FILE="rtl/microcode/uhbs_slh_128f_tokens.mem",
    parameter TEMPLATE_INIT_FILE="rtl/microcode/uhbs_slh_128f_templates.mem",
    parameter DESCRIPTOR_INIT_FILE="rtl/microcode/uhbs_slh_128f_descriptors.mem"
) (
    input wire clk, rst_n,
    input wire job_valid, output wire job_ready, input wire job_operation,
    input wire [6:0] job_message_length, input wire [10:0] job_initial_q,
    input wire [N*8-1:0] job_secret_seed, job_secret_prf, job_public_seed, job_randomizer,
    input wire [127:0] job_identifier,
    input wire message_valid, output wire message_ready,
    input wire [63:0] message_data, input wire [7:0] message_keep, input wire message_last,
    output wire state_commit_valid, input wire state_commit_ready,
    output wire [10:0] state_next_q,
    output wire out_valid, input wire out_ready, output wire [63:0] out_data,
    output wire [7:0] out_keep, output wire out_last,
    output wire busy, output logic done, error, output logic [15:0] error_code,
    output wire [31:0] hash_count, permutation_count,
    output logic [31:0] cycles,
    output logic tree_cache_valid
);
    localparam integer W=N*8, V=DIGEST_BYTES*8;
    localparam integer INDEX_BITS=CHAIN_COUNT>127 ? 8 : 7;
    localparam integer LEN1=8*N/OMEGA, LEN2=OMEGA==2 ? 5 : 3;
    localparam integer FORS_BYTES=(FORS_A*FORS_K+7)/8, TREE_BYTES=(TREE_BITS+7)/8;
    localparam integer FORS_INDEX_BITS=FORS_A>0 ? FORS_A : 1;
    typedef enum logic [5:0] {
        IDLE, MESSAGE, RESERVE, LAUNCH, FETCH, DECODE,
        TREE_INIT, CHAIN_SETUP, CHAIN_STORE, CHAIN_OUTPUT0, CHAIN_OUTPUT1,
        CHAIN_NEXT, REDUCE_SETUP, REDUCE_STORE, LEAF_SETUP, LEAF_DONE,
        PUSH_NODE, PARENT_SETUP, PARENT_DONE, AUTH_OUTPUT, TREE_FINISH,
        HASH_ISSUE, HASH_WAIT, HASH_RESULT, ROUTE, TRANSFORM,
        EMIT, EMIT_NEXT, OUTPUT_CHUNK, DRAIN, FINISH, FAILED
    } state_t;
    state_t state, hash_return, output_return;
    // Abort outstanding execution on an error; keep the index guard alive so
    // a committed q remains burned when Keygen is retried.
    // The main controller uses return-state registers and need not synthesize
    // as a one-hot FSM. Never drive asynchronous reset from its binary decode.
    (* dont_touch="yes" *) logic abort_execution;
    wire execution_rst_n=rst_n && !abort_execution;
    (* rom_style="distributed" *) logic [63:0] descriptors [0:127];
    initial $readmemh(DESCRIPTOR_INIT_FILE,descriptors);
    logic operation;
    logic [N*8-1:0] secret_seed, secret_prf, public_seed, randomizer;
    logic [127:0] identifier;
    logic [MAX_MESSAGE_BYTES*8-1:0] message_buffer;
    logic [6:0] message_length, message_received;
    logic [V-1:0] value [0:3];
    logic [63:0] scalar_tree;
    logic [9:0] scalar_leaf, active_q, cache_q;
    logic [11:0] checksum;
    logic [6:0] transform_index;
    logic [17:0] output_bytes, emitted;
    logic [4:0] layer;
    logic [5:0] group_index;
    logic [3:0] macro_op, macro_flags;
    logic [7:0] macro_desc, macro_route;
    wire [63:0] descriptor = descriptors[macro_desc];
    wire [63:0] route_descriptor = descriptors[macro_route];

    logic seq_start, seq_complete;
    wire seq_ready, seq_done, seq_error, cmd_valid, cmd1_valid;
    wire [47:0] cmd, cmd1;
    wire [2:0] event0, event1;
    wire [7:0] seq_error_code;
    wire [8:0] entry = operation ? descriptors[0][46:38] : descriptors[0][55:47];
    uhbs_static_task_sequencer #(.PROGRAM_TOKENS(PROGRAM_TOKENS),
        .PROGRAM_TEMPLATES(PROGRAM_TEMPLATES), .TOKEN_INIT_FILE(TOKEN_INIT_FILE),
        .TEMPLATE_INIT_FILE(TEMPLATE_INIT_FILE)) sequencer (
        .clk, .rst_n(execution_rst_n), .job_valid(seq_start), .job_ready(seq_ready), .job_entry(entry),
        .done(seq_done), .busy(), .error(seq_error), .error_code(seq_error_code),
        .lane0_valid(cmd_valid), .lane0_ready(state==FETCH), .lane0_command(cmd), .lane0_event(event0),
        .lane1_valid(cmd1_valid), .lane1_ready(1'b0), .lane1_command(cmd1), .lane1_event(event1),
        .lane0_done_valid(seq_complete), .lane0_done_event(3'd0),
        .lane1_done_valid(1'b0), .lane1_done_event(3'd0),
        .program_counter(), .pending_events(), .retired_words(), .retired_tokens()
    );

    wire guard_grant, guard_error, guard_initialized;
    wire [9:0] guard_q;
    wire [10:0] guard_current_q;
    wire [15:0] guard_error_code;
    logic reservation_issued;
    // Cache invalidation must never make a committed index reusable.
    logic index_started;
    generate if (STATEFUL) begin: g_guard
        uhbs_stateful_index_guard guard (
            .clk, .rst_n, .initialize_valid(state==FINISH && !operation), .initialize_ready(),
            .initial_q({1'b0,active_q}), .invalidate(state==FAILED),
            .sign_valid(state==RESERVE && !reservation_issued), .sign_ready(),
            .sign_grant(guard_grant), .sign_q(guard_q),
            .state_commit_valid, .state_commit_ready, .state_next_q,
            .initialized(guard_initialized), .current_q(guard_current_q),
            .error(guard_error), .error_code(guard_error_code)
        );
    end else begin: g_no_guard
        assign guard_grant=0; assign guard_error=0; assign guard_initialized=0;
        assign guard_q=0; assign guard_current_q=0; assign guard_error_code=0;
        assign state_commit_valid=0; assign state_next_q=0;
    end endgenerate

    logic [7:0] chain_id, parent_id;
    wire [63:0] chain_descriptor = descriptors[chain_id];
    logic standalone_chain, fors_pair_pending;
    logic [3:0] tree_height, node_level, auth_level;
    logic [1:0] indexing;
    logic cache_build;
    logic [9:0] target, leaf_cursor, node_index;
    logic [INDEX_BITS-1:0] chain_cursor, endpoint_count, reduction_count, reduction_cursor;
    logic [3:0] reduction_level;
    logic [N*8-1:0] node_value;
    (* ram_style="distributed" *) logic [N*8-1:0] stack [0:15];
    (* ram_style="distributed" *) logic [N*8-1:0] auth_path [0:15];

    logic [63:0] task_recipe, task_step;
    logic task_chain, task_capture0, task_capture1;
    logic [4:0] task_steps [0:1], task_capture_after [0:1];
    logic [9:0] task_leaf [0:1];
    logic [INDEX_BITS-1:0] task_a [0:1];
    logic [31:0] task_b [0:1];
    logic [N*8-1:0] task_left [0:1], task_right [0:1];
    logic [1:0] active_mask, launch_pending, response_pending;
    wire [1:0] lane_ready, lane_valid, lane_error;
    wire [V-1:0] lane_value [0:1];
    wire [N*8-1:0] lane_capture [0:1];
    wire [INDEX_BITS-1:0] lane_list0 [0:1], lane_list1 [0:1];
    wire [31:0] lane_hashes [0:1], lane_permutations [0:1];
    logic [31:0] hash_base, permutation_base;
    logic [V-1:0] result [0:1], route_value;
    logic [N*8-1:0] capture [0:1];
    wire [31:0] total_hashes = lane_hashes[0]+lane_hashes[1];
    wire [31:0] total_permutations = lane_permutations[0]+lane_permutations[1];
    assign hash_count = total_hashes-hash_base;
    assign permutation_count = total_permutations-permutation_base;

    logic endpoint_write0, endpoint_write1;
    logic [INDEX_BITS-1:0] endpoint_address0, endpoint_address1, endpoint_read0, endpoint_read1;
    logic [N*8-1:0] endpoint_data0, endpoint_data1;
    wire [N*8-1:0] endpoint_value0, endpoint_value1;
    logic task_list_roots;
    wire list_roots = !STATEFUL && task_list_roots;
    wire [N*8-1:0] root_value0, root_value1;
    wire [INDEX_BITS-1:0] root_read0 = lane_list0[0], root_read1 = lane_list1[0];
    uhbs_value_store #(.WIDTH(W),.DEPTH(1 << $clog2(CHAIN_COUNT)),.ADDRESS_BITS(INDEX_BITS)) endpoints (
        .clk, .write0(endpoint_write0), .write1(endpoint_write1),
        .address0(endpoint_address0), .address1(endpoint_address1),
        .data0(endpoint_data0), .data1(endpoint_data1),
        .read0(endpoint_read0), .read1(endpoint_read1),
        .value0(endpoint_value0), .value1(endpoint_value1)
    );
    generate if(!STATEFUL) begin: g_roots
    uhbs_value_store #(.WIDTH(W),.DEPTH(64),.ADDRESS_BITS(INDEX_BITS)) roots (
        .clk, .write0(state==ROUTE && macro_route!=0 && route_descriptor[53]), .write1(1'b0),
        .address0(INDEX_BITS'(group_index)), .address1({INDEX_BITS{1'b0}}), .data0(route_value[W-1:0]), .data1({W{1'b0}}),
        .read0(root_read0), .read1(root_read1), .value0(root_value0), .value1(root_value1)
    );
    end else begin: g_no_roots
        assign root_value0=0; assign root_value1=0;
    end endgenerate
    genvar physical;
    generate for (physical=0; physical<LANES; physical=physical+1) begin: lanes
        localparam integer L=SWAP_PHYSICAL_LANES ? LANES-1-physical : physical;
        uhbs_recipe_lane #(.N(N),.DIGEST_BYTES(DIGEST_BYTES),.INDEX_BITS(INDEX_BITS),.UNROLL(UNROLL),.MAX_MESSAGE_BYTES(MAX_MESSAGE_BYTES),
            .RECIPE_MASK(L==0 ? RECIPE_MASK : CHAIN_RECIPE_MASK),
            .PROFILE_ENABLE(PROFILE_ENABLE)) lane (
            .clk,.rst_n(execution_rst_n),.request_valid(state==HASH_ISSUE && launch_pending[L]),
            .request_ready(lane_ready[L]), .request_recipe(task_recipe), .request_step_recipe(task_step),
            .request_chain(task_chain), .request_steps(task_steps[L]),
            .request_capture_after(task_capture_after[L]),
            .request_capture(L==0 ? task_capture0 : task_capture1),
            .secret_seed,.secret_prf,.public_seed,.root(value[3][W-1:0]),
            .randomizer(task_recipe[59:56]==4 || task_recipe[59:56]==6 ? value[0][W-1:0] : randomizer),
            .identifier,.message_buffer,.message_length,
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
    if(LANES==1) begin: unused_lane
        assign lane_ready[1]=1; assign lane_valid[1]=0; assign lane_error[1]=0;
        assign lane_value[1]=0; assign lane_capture[1]=0;
        assign lane_list0[1]=0; assign lane_list1[1]=0;
        assign lane_hashes[1]=0; assign lane_permutations[1]=0;
    end endgenerate
    initial if(LANES<1 || LANES>2) $error("LANES must be one or two");

    logic [N*8-1:0] emit_value;
    logic [5:0] emit_length, emit_offset;
    logic [7:0] emit_base;
    logic [3:0] emit_count, emit_cursor;
    wire [63:0] emit_descriptor = descriptors[emit_base+emit_cursor];
    wire [5:0] emit_remaining=emit_length-emit_offset;
    wire [3:0] emit_chunk_bytes = emit_remaining>8 ? 8 : emit_remaining[3:0];
    wire pack_ready, pack_idle;
    // Each result chunk is transferred directly; keep marks its valid bytes.
    assign pack_ready=out_ready;
    assign pack_idle=1'b1;
    assign out_valid=state==OUTPUT_CHUNK;
    assign out_data=emit_value >> (emit_offset*8);
    assign out_keep=8'hff >> (8-emit_chunk_bytes);
    assign out_last=emitted+emit_chunk_bytes==output_bytes;
    assign job_ready=state==IDLE;
    assign message_ready=state==MESSAGE;
    assign busy=state!=IDLE;

    function automatic [31:0] be32(input [31:0] x);
        be32={x[7:0],x[15:8],x[23:16],x[31:24]};
    endfunction
    function automatic [4:0] digit(input integer index);
        begin
            if(index<LEN1)
                digit=value[2][(index/(8/OMEGA))*8+8-OMEGA-(index%(8/OMEGA))*OMEGA +: OMEGA];
            else digit=(checksum >> ((LEN1+LEN2-1-index)*OMEGA)) & ((1<<OMEGA)-1);
        end
    endfunction
    function automatic [FORS_INDEX_BITS-1:0] fors_target(input [5:0] group_number);
        integer k;
        begin
            fors_target=0;
            for(k=0;k<FORS_A;k=k+1)
                fors_target=(fors_target<<1)|value[1][8*((group_number*FORS_A+k)/8)+7-((group_number*FORS_A+k)%8)];
        end
    endfunction
    function automatic [63:0] parsed_tree(input [V-1:0] digest);
        integer j;
        begin
            parsed_tree=0;
            for(j=0;j<TREE_BYTES;j=j+1)
                parsed_tree=(parsed_tree<<8)|digest[(FORS_BYTES+j)*8 +: 8];
            parsed_tree=parsed_tree & (64'hffffffffffffffff >> (64-TREE_BITS));
        end
    endfunction
    task automatic fail(input [15:0] code);
        begin error<=1; error_code<=code; tree_cache_valid<=0; abort_execution<=1; state<=FAILED; end
    endtask
    task automatic complete_macro;
        begin seq_complete<=1; state<=FETCH; end
    endtask
    task automatic route_result(input [V-1:0] v);
        begin route_value<=v; state<=ROUTE; end
    endtask
    task automatic start_output(input [N*8-1:0] v, input [5:0] length, input state_t ret);
        begin emit_value<=v; emit_length<=length; emit_offset<=0; output_return<=ret; state<=OUTPUT_CHUNK; end
    endtask
    task automatic start_hash(input [7:0] rid, input [1:0] mask, input state_t ret);
        begin
            task_recipe<=descriptors[rid]; active_mask<=mask;
            task_list_roots<=!STATEFUL && descriptors[rid][59:56]==12 && descriptors[rid][55:48]==4;
            launch_pending<=mask; response_pending<=mask;
            hash_return<=ret; state<=HASH_ISSUE;
        end
    endtask

    always_comb begin
        endpoint_write0=0; endpoint_write1=0;
        endpoint_address0=chain_cursor; endpoint_address1=chain_cursor+1'b1;
        endpoint_data0=result[0][W-1:0]; endpoint_data1=result[1][W-1:0];
        endpoint_read0=lane_list0[0]; endpoint_read1=lane_list1[0];
        if (state==CHAIN_STORE && !macro_flags[2]) begin
            endpoint_write0=active_mask[0]; endpoint_write1=active_mask[1];
        end
        if (state==REDUCE_SETUP) begin
            endpoint_read0=reduction_cursor*2; endpoint_read1=reduction_cursor*2+1;
            if (reduction_cursor*2+1>=reduction_count) begin
                endpoint_write0=1; endpoint_address0=reduction_cursor;
                endpoint_data0=endpoint_value0;
            end
        end
        if (state==REDUCE_STORE) begin
            endpoint_write0=1; endpoint_address0=reduction_cursor;
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

    integer i, received_count;
    reg [N*8-1:0] emit_source;
    always_comb begin
        received_count=message_keep[0]+message_keep[1]+message_keep[2]+message_keep[3]
            +message_keep[4]+message_keep[5]+message_keep[6]+message_keep[7];
        case(emit_descriptor[59:56])
            0: emit_source=secret_seed;
            1: emit_source=secret_prf;
            2: emit_source=public_seed;
            3: emit_source=value[3][W-1:0];
            4: emit_source=descriptors[2][59:56]==5 ? value[0][W-1:0] : randomizer;
            5: emit_source=identifier;
            6: emit_source=be32(active_q);
            7: emit_source=be32(emit_descriptor[31:0]);
            default: emit_source=0;
        endcase
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; done<=0; error<=0; error_code<=0; cycles<=0;
            abort_execution<=0;
            tree_cache_valid<=0; seq_start<=0; seq_complete<=0;
            operation<=0; scalar_tree<=0; scalar_leaf<=0; active_q<=0; cache_q<=0;
            macro_op<=0; macro_desc<=0; macro_route<=0; macro_flags<=0;
            active_mask<=0; launch_pending<=0; response_pending<=0;
            task_chain<=0; task_capture0<=0; task_capture1<=0;
            hash_base<=0; permutation_base<=0; emitted<=0; layer<=0;
            task_recipe<=0; task_step<=0; task_list_roots<=0; message_received<=0;
            reservation_issued<=0; index_started<=0; fors_pair_pending<=0;
            for(i=0;i<2;i=i+1) begin
                task_steps[i]<=0; task_capture_after[i]<=0;
                task_leaf[i]<=0; task_a[i]<=0; task_b[i]<=0;
            end
        end else begin
            done<=0; seq_start<=0; seq_complete<=0; abort_execution<=0;
            if(state!=IDLE && state!=FAILED) cycles<=cycles+1;
            if(seq_error && state!=IDLE && state!=FAILED) fail({8'h31,seq_error_code});
            else if(STATEFUL && guard_error && state==RESERVE) fail(guard_error_code);
            else case(state)
                IDLE: if(job_valid) begin
                    error<=0; error_code<=0; cycles<=0; operation<=job_operation;
                    secret_seed<=job_secret_seed; secret_prf<=job_secret_prf;
                    public_seed<=job_public_seed; randomizer<=job_randomizer; identifier<=job_identifier;
                    message_length<=job_message_length; message_received<=0;
                    scalar_tree<=0; scalar_leaf<=0; layer<=0; group_index<=0;
                    emitted<=0; output_bytes<=job_operation ? descriptors[0][17:0] : descriptors[0][35:18];
                    hash_base<=total_hashes; permutation_base<=total_permutations;
                    reservation_issued<=0;
                    if(descriptors[0][63:56]!=8'ha4 || descriptors[1][55:48]!=N || descriptors[1][47:44]!=OMEGA
                            || descriptors[1][43:40]!=HP || descriptors[1][39:36]!=FORS_A
                            || descriptors[1][23:18]!=FORS_K || descriptors[1][12:7]!=DIGEST_BYTES
                        || descriptors[1][59]!=STATEFUL) fail(16'h3001);
                    else if(job_operation) begin
                        if(job_message_length==0 || job_message_length>MAX_MESSAGE_BYTES) fail(16'h3002);
                        else if(STATEFUL && (!tree_cache_valid || guard_current_q!=cache_q)) fail(16'h3003);
                        else begin
                            active_q<=guard_current_q[9:0]; state<=MESSAGE;
                        end
                    end else begin
                        tree_cache_valid<=0;
                        active_q<=STATEFUL && index_started ? guard_current_q[9:0] : job_initial_q[9:0];
                        if(STATEFUL && (job_initial_q>=1024 || (index_started && guard_current_q>=1024))) fail(16'h3004);
                        else state<=LAUNCH;
                    end
                end
                MESSAGE: if(message_valid) begin
                    if(message_keep==0 || (message_keep & (message_keep+1'b1))!=0
                        || message_received+received_count>message_length
                        || (message_last != (message_received+received_count==message_length))) fail(16'h3002);
                    else begin
                        for(i=0;i<8;i=i+1) if(message_keep[i])
                            message_buffer[(message_received+i)*8 +: 8]<=message_data[i*8 +: 8];
                        message_received<=message_received+received_count;
                        if(message_last) state<=STATEFUL ? RESERVE : LAUNCH;
                    end
                end
                RESERVE: begin
                    reservation_issued<=1;
                    if(guard_grant) begin active_q<=guard_q; state<=LAUNCH; end
                end
                LAUNCH: if(seq_ready) begin seq_start<=1; state<=FETCH; end
                FETCH: begin
                    if(seq_done) begin
                        if(emitted!=output_bytes) fail(16'h3005);
                        else state<=DRAIN;
                    end else if(cmd_valid) begin
                        macro_op<=cmd[47:44]; macro_desc<=cmd[43:36]; macro_route<=cmd[35:28];
                        macro_flags<=cmd[27:24]; layer<=cmd[23:19]; group_index<=cmd[18:13];
                        task_chain<=0; task_capture0<=0; task_capture1<=0;
                        task_steps[0]<=0; task_steps[1]<=0;
                        if(cmd[43:36]>=128 || cmd[35:28]>=128 || cmd1_valid) fail(16'h3006);
                        else state<=DECODE;
                    end
                end
                DECODE: case(macro_op)
                    1: if(descriptor[63:60]!=1) fail(16'h3006);
                       else begin
                           task_leaf[0]<=STATEFUL ? active_q : scalar_leaf;
                           task_a[0]<=0; task_b[0]<=0;
                           start_hash(macro_desc,2'b01,HASH_RESULT);
                       end
                    2: if(descriptor[63:60]!=4) fail(16'h3006);
                       else begin
                           chain_id<=macro_desc; standalone_chain<=1; indexing<=0;
                           leaf_cursor<=active_q; target<=active_q; chain_cursor<=0;
                           endpoint_count<=descriptor[27:20]; state<=CHAIN_SETUP;
                       end
                    3: if(descriptor[63:60]!=5 || descriptor[43:40]>10 || descriptor[29]) fail(16'h3006);
                       else state<=TREE_INIT;
                    4: if(descriptor[63:60]!=8) fail(16'h3006);
                       else begin checksum<=0; transform_index<=0; state<=TRANSFORM; end
                    5: if(descriptor[63:60]!=9) fail(16'h3006);
                       else begin emit_base<=descriptor[59:52]; emit_count<=descriptor[51:48]; emit_cursor<=0; state<=EMIT; end
                    default: fail(16'h3006);
                endcase
                TREE_INIT: begin
                    fors_pair_pending<=0;
                    chain_id<=descriptor[59:52]; parent_id<=descriptor[51:44]; tree_height<=descriptor[43:40];
                    indexing<=descriptor[33:32]; cache_build<=descriptor[31]; standalone_chain<=0;
                    target<=descriptor[37:36]==1 ? fors_target(group_index)
                        : descriptor[37:36]==2 ? active_q : scalar_leaf;
                    leaf_cursor<=0; chain_cursor<=0; node_level<=0; auth_level<=0;
                    endpoint_count<=descriptors[descriptor[59:52]][27:20];
                    if(descriptor[30]) begin
                        if(!tree_cache_valid || active_q!=cache_q) fail(16'h3003);
                        else state<=AUTH_OUTPUT;
                    end else state<=CHAIN_SETUP;
                end
                CHAIN_SETUP: begin
                    task_chain<=1; task_step<=descriptors[chain_descriptor[51:44]];
                    task_capture0<=leaf_cursor==target && macro_flags[0];
                    task_capture1<=(indexing==1 ? leaf_cursor+1==target : leaf_cursor==target) && macro_flags[0];
                    for(i=0;i<2;i=i+1) begin
                        task_leaf[i]<=indexing==1 ? scalar_leaf : leaf_cursor;
                        task_a[i]<=indexing==1 ? 0 : chain_cursor+i;
                        task_b[i]<=indexing==1 ? (group_index<<FORS_A)+leaf_cursor+i : 0;
                        task_steps[i]<=macro_flags[2] || (macro_flags[3] && leaf_cursor==target)
                            ? digit(chain_cursor+i) : chain_descriptor[19:15];
                        task_capture_after[i]<=indexing==1 ? 0 : digit(chain_cursor+i);
                    end
                    start_hash(chain_descriptor[59:52],LANES==2 && (indexing==1 || chain_cursor+1<endpoint_count) ? 2'b11 : 2'b01,CHAIN_STORE);
                end
                CHAIN_STORE: begin
                    task_chain<=0;
                    if(macro_flags[2] || (macro_flags[0] && (leaf_cursor==target || (indexing==1 && LANES==2 && leaf_cursor+1==target)))) state<=CHAIN_OUTPUT0;
                    else state<=CHAIN_NEXT;
                end
                CHAIN_OUTPUT0: start_output(macro_flags[2] ? result[0][W-1:0]
                    : indexing==1 && LANES==2 && target[0] ? capture[1] : capture[0],N,
                    active_mask[1] && indexing!=1 ? CHAIN_OUTPUT1 : CHAIN_NEXT);
                CHAIN_OUTPUT1: start_output(macro_flags[2] ? result[1][W-1:0] : capture[1],N,CHAIN_NEXT);
                CHAIN_NEXT: begin
                    if(chain_cursor+LANES<endpoint_count) begin chain_cursor<=chain_cursor+LANES; state<=CHAIN_SETUP; end
                    else if(standalone_chain) complete_macro();
                    else if(macro_flags[3] && leaf_cursor==target) begin
                        node_value<=0; node_level<=0; node_index<=leaf_cursor; state<=PUSH_NODE;
                    end else if(chain_descriptor[13:12]==0) begin
                        fors_pair_pending<=indexing==1 && active_mask[1];
                        node_value<=result[0][W-1:0]; node_level<=0; node_index<=leaf_cursor; state<=PUSH_NODE;
                    end else begin
                        reduction_count<=endpoint_count; reduction_cursor<=0; reduction_level<=0;
                        state<=REDUCE_SETUP;
                    end
                end
                REDUCE_SETUP: begin
                    task_chain<=0; task_capture0<=0; task_capture1<=0; task_steps[0]<=0;
                    task_leaf[0]<=leaf_cursor; task_a[0]<=0; task_b[0]<=0;
                    if(chain_descriptor[13:12]==1) start_hash(chain_descriptor[43:36],2'b01,LEAF_SETUP);
                    else if(reduction_cursor*2+1>=reduction_count) begin
                        reduction_count<=(reduction_count+1)>>1; reduction_cursor<=0;
                        reduction_level<=reduction_level+1'b1;
                    end else begin
                        task_a[0]<=reduction_level; task_b[0]<=reduction_cursor;
                        task_left[0]<=endpoint_value0; task_right[0]<=endpoint_value1;
                        start_hash(chain_descriptor[43:36],2'b01,REDUCE_STORE);
                    end
                end
                REDUCE_STORE: begin
                    if(reduction_count==2) state<=LEAF_SETUP;
                    else if((reduction_cursor+1)*2<reduction_count) begin
                        reduction_cursor<=reduction_cursor+1'b1; state<=REDUCE_SETUP;
                    end else begin
                        reduction_count<=(reduction_count+1)>>1; reduction_cursor<=0;
                        reduction_level<=reduction_level+1'b1; state<=REDUCE_SETUP;
                    end
                end
                LEAF_SETUP: begin
                    if(chain_descriptor[35:28]!=0) begin
                        task_left[0]<=result[0][W-1:0]; task_b[0]<=(1<<tree_height)+leaf_cursor;
                        start_hash(chain_descriptor[35:28],2'b01,LEAF_DONE);
                    end else begin node_value<=result[0][W-1:0]; node_level<=0; node_index<=leaf_cursor; state<=PUSH_NODE; end
                end
                LEAF_DONE: begin node_value<=result[0][W-1:0]; node_level<=0; node_index<=leaf_cursor; state<=PUSH_NODE; end
                PUSH_NODE: begin
                    if(node_level==tree_height) begin
                        if(cache_build) begin tree_cache_valid<=1; cache_q<=active_q; end
                        auth_level<=0;
                        if(macro_flags[1]) state<=AUTH_OUTPUT;
                        else state<=TREE_FINISH;
                    end else if(node_index[0]) state<=PARENT_SETUP;
                    else if(fors_pair_pending) begin
                        node_value<=result[1][W-1:0]; node_level<=0;
                        node_index<=leaf_cursor+1'b1; leaf_cursor<=leaf_cursor+1'b1;
                        fors_pair_pending<=0;
                    end else begin
                        leaf_cursor<=leaf_cursor+1'b1; chain_cursor<=0; state<=CHAIN_SETUP;
                    end
                end
                PARENT_SETUP: begin
                    if(macro_flags[3] && (node_index>>1)==(target>>(node_level+1))) begin
                        node_value<=0; node_index<=node_index>>1; node_level<=node_level+1'b1; state<=PUSH_NODE;
                    end else begin
                        task_chain<=0; task_capture0<=0; task_capture1<=0; task_steps[0]<=0;
                        task_leaf[0]<=indexing==1 ? scalar_leaf : 0;
                        task_a[0]<=descriptors[parent_id][59:56]==8 ? node_level : node_level+1'b1;
                        task_b[0]<=indexing==1 ? ((group_index<<FORS_A)>>(node_level+1))+(node_index>>1)
                            : indexing==2 ? (1<<(tree_height-node_level-1))+(node_index>>1) : (node_index>>1);
                        task_left[0]<=stack[node_level]; task_right[0]<=node_value;
                        start_hash(parent_id,2'b01,PARENT_DONE);
                    end
                end
                PARENT_DONE: begin
                    node_value<=result[0][W-1:0]; node_index<=node_index>>1; node_level<=node_level+1'b1; state<=PUSH_NODE;
                end
                AUTH_OUTPUT: begin
                    if(auth_level<tree_height) begin
                        start_output(auth_path[auth_level],N,AUTH_OUTPUT); auth_level<=auth_level+1'b1;
                    end else if(descriptor[30]) complete_macro();
                    else state<=TREE_FINISH;
                end
                TREE_FINISH: route_result(macro_flags[3] ? value[3] : {{(V-W){1'b0}},node_value});
                HASH_ISSUE: begin
                    launch_pending<=launch_pending & ~lane_ready;
                    if((launch_pending & ~lane_ready)==0) state<=HASH_WAIT;
                end
                HASH_WAIT: begin
                    for(i=0;i<2;i=i+1) if(response_pending[i] && lane_valid[i]) begin
                        result[i]<=lane_value[i]; capture[i]<=lane_capture[i];
                    end
                    response_pending<=response_pending & ~lane_valid;
                    if((lane_error & response_pending & lane_valid)!=0) fail(16'h3007);
                    else if((response_pending & ~lane_valid)==0) state<=hash_return;
                end
                HASH_RESULT: route_result(result[0]);
                ROUTE: begin
                    if(macro_route==0) complete_macro();
                    else if(route_descriptor[63:60]!=6) fail(16'h3006);
                    else begin
                        if(!route_descriptor[53]) value[route_descriptor[57:56]]<=route_value;
                        if(route_descriptor[54]) begin
                            scalar_tree <= parsed_tree(route_value);
                            scalar_leaf <= route_value[(FORS_BYTES+TREE_BYTES)*8 +: HP];
                        end
                        if(route_descriptor[55]) start_output(route_value[W-1:0],N,FETCH);
                        else state<=FETCH;
                        seq_complete<=1;
                    end
                end
                TRANSFORM: begin
                    if(descriptor[59:56]==2) begin
                        scalar_leaf<=scalar_tree & ((1<<descriptor[43:40])-1);
                        scalar_tree<=scalar_tree>>descriptor[43:40]; complete_macro();
                    end else if(descriptor[59:56]==1) begin
                        checksum<=checksum+((1<<OMEGA)-1)-digit(transform_index);
                        if(transform_index+1==LEN1) complete_macro();
                        else transform_index<=transform_index+1'b1;
                    end else fail(16'h3006);
                end
                EMIT: begin
                    if(emit_descriptor[63:60]!=2 || emit_descriptor[55:48]==0 || emit_descriptor[55:48]>N) fail(16'h3006);
                    else start_output(emit_source,emit_descriptor[53:48],EMIT_NEXT);
                end
                EMIT_NEXT: begin
                    if(emit_cursor+1<emit_count) begin emit_cursor<=emit_cursor+1'b1; state<=EMIT; end
                    else complete_macro();
                end
                OUTPUT_CHUNK: if(pack_ready) begin
                    emitted<=emitted+emit_chunk_bytes;
                    if(emit_remaining<=8) state<=output_return;
                    else emit_offset<=emit_offset+8;
                end
                DRAIN: if(pack_idle) state<=FINISH;
                FINISH: begin
                    if(STATEFUL && !operation) index_started<=1;
                    done<=1; state<=IDLE;
                end
                FAILED: state<=IDLE;
                default: fail(16'h3006);
            endcase
        end
    end
endmodule
`default_nettype wire
