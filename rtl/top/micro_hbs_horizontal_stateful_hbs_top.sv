`timescale 1ns/1ps
`default_nettype none

// Dual-entry, descriptor-checked stateful HBS core.  The static image profile
// selects the byte recipes and output layout; there is no algorithm-select
// parameter or run-time opcode.  Algorithm ordering is supplied by macrocode.
module micro_hbs_horizontal_stateful_hbs_top #(
    parameter integer UNROLL = 2,
    parameter integer MAX_MESSAGE_BYTES = 87,
    parameter bit PROFILE_ENABLE = 1'b0,
    parameter bit SWAP_PHYSICAL_LANES = 1'b0,
    parameter TOKEN_INIT_FILE =
        "rtl/microcode/xmss_shake256_h10_w4_tokens.mem",
    parameter TEMPLATE_INIT_FILE =
        "rtl/microcode/xmss_shake256_h10_w4_templates.mem",
    parameter DESCRIPTOR_INIT_FILE =
        "rtl/microcode/xmss_shake256_h10_w4_descriptors.mem"
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         job_valid,
    output wire         job_ready,
    input  wire         job_operation,
    input  wire [31:0]  job_message_length,
    input  wire [10:0]  job_initial_q,
    input  wire [255:0] job_secret_seed,
    input  wire [255:0] job_secret_prf,
    input  wire [255:0] job_public_seed,
    input  wire [127:0] job_identifier,
    input  wire [255:0] job_randomizer,
    input  wire         message_valid,
    output wire         message_ready,
    input  wire [63:0]  message_data,
    input  wire [7:0]   message_keep,
    input  wire         message_last,
    output wire         state_commit_valid,
    input  wire         state_commit_ready,
    output wire [10:0]  state_next_q,
    output wire         out_valid,
    input  wire         out_ready,
    output wire [63:0]  out_data,
    output wire [7:0]   out_keep,
    output wire         out_last,
    output wire         busy,
    output logic        done,
    output logic        error,
    output logic [15:0] error_code,
    output logic [31:0] hash_contexts,
    output logic [31:0] keccak_permutations,
    output logic [31:0] lane0_active_cycles,
    output logic [31:0] lane1_active_cycles,
    output wire         tree_cache_valid
);
    localparam logic OP_KEYGEN = 1'b0;
    localparam logic OP_SIGN = 1'b1;
    localparam logic [3:0] MACRO_HASH      = 4'd1;
    localparam logic [3:0] MACRO_CHAIN     = 4'd2;
    localparam logic [3:0] MACRO_TREE_PUSH = 4'd3;
    localparam logic [3:0] MACRO_TRANSFORM = 4'd4;
    localparam logic [3:0] MACRO_EMIT      = 4'd5;
    localparam logic [3:0] DESC_EMIT       = 4'd9;
    localparam logic [3:0] DESC_PROFILE    = 4'd11;
    localparam logic [3:0] DESC_RECIPE     = 4'd12;
    localparam logic [3:0] DESC_CHAIN      = 4'd4;
    localparam logic [3:0] DESC_TREE_PUSH  = 4'd5;
    localparam logic [3:0] DESC_TRANSFORM  = 4'd8;

    localparam logic [3:0] SHAPE_MASKED_PARENT = 4'd4;
    localparam logic [3:0] SHAPE_PREFIX_LIST   = 4'd7;
    localparam logic [3:0] SHAPE_PREFIX_VALUE  = 4'd8;

    localparam logic [15:0] ERR_JOB         = 16'h2601;
    localparam logic [15:0] ERR_MESSAGE     = 16'h2602;
    localparam logic [15:0] ERR_DESCRIPTOR  = 16'h2603;
    localparam logic [15:0] ERR_LANE        = 16'h2604;
    localparam logic [15:0] ERR_CACHE       = 16'h2605;
    localparam logic [15:0] ERR_SEQUENCER   = 16'h2606;
    typedef enum logic [3:0] {
        F_IDLE, F_MESSAGE, F_RESERVE, F_START, F_RUN,
        F_INITIALIZE, F_DRAIN, F_ERROR
    } front_state_t;
    front_state_t front_state;

    typedef enum logic [5:0] {
        M_IDLE,
        M_BUILD_START, M_LEAF_CHAIN_PREP, M_LEAF_CHAIN_WAIT,
        M_LTREE_READ_REQ, M_LTREE_READ_WAIT, M_LTREE_PUSH_START,
        M_LTREE_PUSH_WAIT, M_LTREE_PUSH_PARENT_WAIT,
        M_LIST_PREP, M_LIST_WAIT, M_LEAF_FINAL_PREP, M_LEAF_FINAL_WAIT,
        M_STORE_LEAF, M_TREE_PUSH_START, M_TREE_PUSH_WAIT,
        M_TREE_PUSH_PARENT_WAIT,
        M_COMMIT_DRAIN, M_COMMIT_PULSE, M_COMMIT_WAIT,
        M_SIGN_HASH_A_PREP, M_SIGN_HASH_A_WAIT,
        M_SIGN_HASH_B_PREP, M_SIGN_HASH_B_WAIT,
        M_TRANSFORM_WORK,
        M_HEADER_NEXT, M_HEADER_WAIT,
        M_SIGN_CHAIN_PREP, M_SIGN_CHAIN_WAIT,
        M_SIGN_CHAIN_EMIT0, M_SIGN_CHAIN_EMIT0_WAIT,
        M_SIGN_CHAIN_EMIT1, M_SIGN_CHAIN_EMIT1_WAIT,
        M_AUTH_TYPE, M_AUTH_TYPE_WAIT, M_AUTH_READ_REQ,
        M_AUTH_READ_WAIT, M_AUTH_EMIT, M_AUTH_EMIT_WAIT,
        M_KEYGEN_EMIT_NEXT, M_KEYGEN_EMIT_WAIT,
        M_COMPLETE, M_ERROR
    } macro_state_t;
    macro_state_t macro_state;

    logic [63:0] descriptor_memory [0:63];
    initial $readmemh(DESCRIPTOR_INIT_FILE, descriptor_memory);
    wire [3:0] image_family = descriptor_memory[1][59:56];
    wire image_is_xmss = image_family == 4'd1;
    wire image_is_lms = image_family == 4'd2;
    wire [3:0] profile_chain_recipe = descriptor_memory[1][28:25];
    wire [3:0] profile_parent_recipe = descriptor_memory[1][24:21];
    wire [3:0] profile_hash_a_recipe = descriptor_memory[1][20:17];
    wire [3:0] profile_hash_b_recipe = descriptor_memory[1][16:13];
    wire profile_list_reduce = descriptor_memory[1][12];
    wire profile_auth_prefix = descriptor_memory[1][11];
    wire [5:0] profile_constant_base = descriptor_memory[1][10:5];
    wire [31:0] profile_outer_type
        = descriptor_memory[profile_constant_base][31:0];
    wire [31:0] profile_chain_type
        = descriptor_memory[profile_constant_base + 1'b1][31:0];
    logic [7:0] active_emit_layout;

    logic active_operation;
    logic [10:0] initial_q_saved;
    logic [255:0] secret_seed, secret_prf, public_seed, root_value;
    logic [127:0] identifier;
    logic [255:0] external_randomizer, signature_randomizer;
    logic [MAX_MESSAGE_BYTES*8-1:0] message_buffer;
    logic [6:0] message_length, message_received;
    logic [9:0] active_q;
    logic [255:0] message_digest;
    logic [3:0] chain_digits [0:66];
    logic endpoint_write0_valid, endpoint_write1_valid;
    logic [6:0] endpoint_write0_index, endpoint_write1_index;
    logic [255:0] endpoint_write0_data, endpoint_write1_data;
    logic [6:0] endpoint_read_address;
    wire [255:0] endpoint_read_data;
    wire endpoint_write_idle;

    logic ucode_start, ucode_task_done;
    wire ucode_ready, ucode_done, ucode_busy, ucode_error;
    wire [7:0] ucode_error_code;
    wire command_valid;
    wire [47:0] command;
    wire [2:0] command_event;
    wire command_ready = macro_state == M_IDLE;
    wire [3:0] command_macro = command[47:44];
    wire [7:0] command_descriptor = command[43:36];
    wire [23:0] command_coordinate = command[23:0];
    wire [3:0] command_descriptor_kind
        = descriptor_memory[command_descriptor][63:60];
    wire [63:0] command_descriptor_word
        = descriptor_memory[command_descriptor];
    wire [8:0] image_keygen_entry = descriptor_memory[0][55:47];
    wire [8:0] image_sign_entry = descriptor_memory[0][46:38];
    logic [8:0] selected_entry;
    logic macro_error;
    logic [15:0] macro_error_code;

    logic guard_initialize, guard_invalidate, guard_sign_valid;
    logic reservation_issued;
    wire guard_initialize_ready, guard_sign_ready, guard_sign_grant;
    wire [9:0] guard_sign_q;
    wire guard_initialized, guard_error;
    wire [10:0] guard_current_q;
    wire [15:0] guard_error_code;

    logic cache_build_start, cache_build_abort, cache_build_commit;
    wire cache_build_ready, cache_build_active;
    wire cache_store_ready;
    logic cache_lookup_valid, cache_lookup_allow;
    logic [10:0] cache_lookup_address;
    wire cache_lookup_ready, cache_lookup_rsp_valid, cache_lookup_hit;
    wire [255:0] cache_lookup_data;
    wire cache_error;
    wire [15:0] cache_error_code;
    wire [11:0] cache_tree_writes;
    wire [2:0] cache_queued_writes;

    wire reducer_push_ready, reducer_push_done;
    wire reducer_parent_valid;
    wire [0:0] reducer_parent_context;
    wire [3:0] reducer_parent_level;
    wire [9:0] reducer_parent_index;
    wire [255:0] reducer_parent_left, reducer_parent_right;
    wire reducer_cache_valid;
    wire [0:0] reducer_cache_context;
    wire [3:0] reducer_cache_level;
    wire [9:0] reducer_cache_index;
    wire [255:0] reducer_cache_value;
    wire reducer_root_valid;
    wire [0:0] reducer_root_context;
    wire [255:0] reducer_root_value;
    wire reducer_error;

    logic [1:0] batch_mask;
    logic batch_start;
    wire batch_ready;
    logic batch_done;
    logic [1:0] launch_pending, response_pending;
    logic [3:0] lane_recipe [0:1];
    logic [9:0] lane_q [0:1];
    logic [6:0] lane_item [0:1];
    logic [4:0] lane_steps [0:1];
    logic [255:0] lane_address [0:1];
    logic [255:0] lane_left [0:1];
    logic [255:0] lane_right [0:1];
    logic [255:0] lane_randomizer [0:1];
    wire [1:0] lane_request_ready, lane_response_valid, lane_error;
    wire [255:0] lane_response_value [0:1];
    logic [255:0] batch_result [0:1];
    wire [31:0] lane_context_count [0:1];
    wire [31:0] lane_permutation_count [0:1];
    wire [31:0] lane_active_count [0:1];
    wire [6:0] lane_endpoint_index [0:1];
    logic [31:0] context_base, permutation_base;
    logic [31:0] lane_active_base [0:1];

    logic emit_start;
    logic [255:0] emit_start_data;
    logic [5:0] emit_start_length;
    logic emit_start_last;
    logic emit_active, emit_done;
    logic [255:0] emit_data;
    logic [5:0] emit_length, emit_index;
    logic emit_last;
    wire packer_in_ready, packer_idle;
    wire packer_in_valid = emit_active;
    wire [7:0] packer_in_byte = emit_data[emit_index*8 +: 8];
    wire packer_in_last = emit_last && emit_index + 1'b1 == emit_length;

    logic [9:0] leaf_cursor;
    logic [6:0] chain_cursor;
    logic [6:0] ltree_push_cursor;
    logic [255:0] leaf_value, list_value;
    logic [1:0] parent_batch_tasks;
    logic [1:0] header_segment;
    logic [3:0] auth_level;
    logic [255:0] auth_value;
    logic [3:0] keygen_segment;
    integer loader_byte;
    integer transform_index;
    integer checksum_work;

    function automatic [31:0] packed_be32(input [31:0] value);
        packed_be32 = {value[7:0], value[15:8], value[23:16], value[31:24]};
    endfunction

    function automatic [10:0] tree_address(
        input integer height, input integer node_index
    );
        tree_address = ((1 << (10-height)) - 1) + node_index;
    endfunction

    function automatic [255:0] xmss_address(
        input [7:0] address_type,
        input [9:0] ots,
        input [7:0] field5,
        input [9:0] field6
    );
        reg [255:0] result;
        begin
            result = '0;
            result[15*8 +: 8] = address_type;
            result[18*8 +: 8] = {6'b0, ots[9:8]};
            result[19*8 +: 8] = ots[7:0];
            result[23*8 +: 8] = field5;
            result[26*8 +: 8] = {6'b0, field6[9:8]};
            result[27*8 +: 8] = field6[7:0];
            xmss_address = result;
        end
    endfunction

    function automatic [255:0] lms_parent_address(
        input integer level, input integer node_index
    );
        reg [31:0] number;
        reg [255:0] result;
        begin
            number = (1 << (10-level)) + node_index;
            result = '0;
            result[31:0] = packed_be32(number);
            lms_parent_address = result;
        end
    endfunction

    function automatic logic descriptor_matches(
        input [3:0] macro_code, input [3:0] kind
    );
        begin
            case (macro_code)
                MACRO_HASH: descriptor_matches = kind == DESC_RECIPE;
                MACRO_CHAIN: descriptor_matches = kind == DESC_CHAIN;
                MACRO_TREE_PUSH:
                    descriptor_matches = kind == DESC_TREE_PUSH;
                MACRO_TRANSFORM: descriptor_matches = kind == DESC_TRANSFORM;
                MACRO_EMIT: descriptor_matches = kind == DESC_EMIT;
                default: descriptor_matches = 1'b0;
            endcase
        end
    endfunction

    assign job_ready = front_state == F_IDLE;
    assign message_ready = front_state == F_MESSAGE;
    assign busy = front_state != F_IDLE;
    wire cache_valid_wire;
    assign tree_cache_valid = cache_valid_wire;

    micro_hbs_stateful_index_guard index_guard (
        .clk, .rst_n,
        .initialize_valid(guard_initialize),
        .initialize_ready(guard_initialize_ready),
        .initial_q(initial_q_saved), .invalidate(guard_invalidate),
        .sign_valid(guard_sign_valid), .sign_ready(guard_sign_ready),
        .sign_grant(guard_sign_grant), .sign_q(guard_sign_q),
        .state_commit_valid, .state_commit_ready, .state_next_q,
        .initialized(guard_initialized), .current_q(guard_current_q),
        .error(guard_error), .error_code(guard_error_code)
    );

    micro_hbs_full_tree_cache256 tree_cache (
        .clk, .rst_n, .build_start(cache_build_start),
        .build_ready(cache_build_ready), .build_abort(cache_build_abort),
        .build_commit(cache_build_commit), .cache_valid(cache_valid_wire),
        .build_active(cache_build_active),
        .store0_valid(reducer_cache_valid), .store0_tree_node(1'b1),
        .store0_address(tree_address(reducer_cache_level,
                                     reducer_cache_index)),
        .store0_data(reducer_cache_value),
        .store1_valid(1'b0), .store1_tree_node(1'b0),
        .store1_address(11'b0), .store1_data(256'b0),
        .store_ready(cache_store_ready),
        .lookup_valid(cache_lookup_valid), .lookup_ready(cache_lookup_ready),
        .lookup_address(cache_lookup_address),
        .lookup_allow_uncommitted(cache_lookup_allow),
        .lookup_rsp_valid(cache_lookup_rsp_valid), .lookup_hit(cache_lookup_hit),
        .lookup_data(cache_lookup_data), .error(cache_error),
        .error_code(cache_error_code), .tree_writes(cache_tree_writes),
        .queued_writes(cache_queued_writes)
    );

    micro_hbs_endpoint_scratch256 endpoint_scratch (
        .clk, .rst_n, .write0_valid(endpoint_write0_valid),
        .write0_index(endpoint_write0_index),
        .write0_data(endpoint_write0_data),
        .write1_valid(endpoint_write1_valid),
        .write1_index(endpoint_write1_index),
        .write1_data(endpoint_write1_data),
        .write_idle(endpoint_write_idle),
        .read_index(endpoint_read_address), .read_data(endpoint_read_data)
    );

    wire reducer_outer_push = macro_state == M_TREE_PUSH_START;
    wire reducer_ltree_push = macro_state == M_LTREE_PUSH_START;
    wire reducer_parent_accept = (macro_state == M_TREE_PUSH_WAIT
        || macro_state == M_LTREE_PUSH_WAIT) && batch_ready;
    wire reducer_parent_response = (macro_state == M_TREE_PUSH_PARENT_WAIT
        || macro_state == M_LTREE_PUSH_PARENT_WAIT) && batch_done;

    micro_hbs_tree_push_reducer #(
        .VALUE_BITS(256), .TREE_HEIGHT(10), .CONTEXTS(2)
    ) tree_reducer (
        .clk, .rst_n,
        .push_valid(reducer_outer_push || reducer_ltree_push),
        .push_ready(reducer_push_ready),
        .push_context(reducer_outer_push),
        .push_clear(reducer_outer_push ? leaf_cursor == 0
                                      : ltree_push_cursor == 0),
        .push_last(reducer_outer_push ? leaf_cursor == 1023
                                     : ltree_push_cursor == 66),
        .push_promote_odd(reducer_ltree_push),
        .push_root_height(reducer_outer_push ? 4'd10 : 4'd7),
        .push_index(reducer_outer_push ? leaf_cursor
                                      : {3'b0, ltree_push_cursor}),
        .push_value(leaf_value),
        .push_target_index(10'b0), .push_capture_auth(1'b0),
        .push_cache_all(reducer_outer_push), .push_done(reducer_push_done),
        .parent_valid(reducer_parent_valid),
        .parent_ready(reducer_parent_accept),
        .parent_context(reducer_parent_context),
        .parent_level(reducer_parent_level),
        .parent_index(reducer_parent_index),
        .parent_left(reducer_parent_left),
        .parent_right(reducer_parent_right),
        .parent_response_valid(reducer_parent_response),
        .parent_response_value(batch_result[0]),
        .cache_valid(reducer_cache_valid), .cache_ready(cache_store_ready),
        .cache_context(reducer_cache_context),
        .cache_level(reducer_cache_level),
        .cache_index(reducer_cache_index),
        .cache_value(reducer_cache_value),
        .auth_valid(), .auth_ready(1'b1), .auth_context(), .auth_level(),
        .auth_value(), .root_valid(reducer_root_valid), .root_ready(1'b1),
        .root_context(reducer_root_context), .root_value(reducer_root_value),
        .error(reducer_error)
    );

    micro_hbs_byte_output_packer output_packer (
        .clk, .rst_n, .clear(front_state == F_IDLE && job_valid),
        .in_valid(packer_in_valid), .in_ready(packer_in_ready),
        .in_byte(packer_in_byte), .in_last(packer_in_last),
        .out_valid, .out_ready, .out_data, .out_keep, .out_last,
        .idle(packer_idle)
    );

    micro_hbs_static_task_sequencer #(
        .PROGRAM_TOKENS(13), .PROGRAM_TEMPLATES(9),
        .TOKEN_INIT_FILE(TOKEN_INIT_FILE),
        .TEMPLATE_INIT_FILE(TEMPLATE_INIT_FILE)
    ) macro_sequencer (
        .clk, .rst_n, .job_valid(ucode_start), .job_ready(ucode_ready),
        .job_entry(selected_entry), .done(ucode_done), .busy(ucode_busy),
        .error(ucode_error), .error_code(ucode_error_code),
        .lane0_valid(command_valid), .lane0_ready(command_ready),
        .lane0_command(command), .lane0_event(command_event),
        .lane1_valid(), .lane1_ready(1'b1), .lane1_command(), .lane1_event(),
        .lane0_done_valid(ucode_task_done), .lane0_done_event(3'd0),
        .lane1_done_valid(1'b0), .lane1_done_event(3'd0),
        .program_counter(), .pending_events(), .retired_words(),
        .retired_tokens()
    );

    genvar physical_lane;
    generate for (physical_lane = 0; physical_lane < 2;
                  physical_lane = physical_lane + 1) begin : lanes
        localparam integer LOGICAL_LANE = SWAP_PHYSICAL_LANES
            ? 1-physical_lane : physical_lane;
        micro_hbs_stateful_recipe_lane #(
            .UNROLL(UNROLL), .MAX_MESSAGE_BYTES(MAX_MESSAGE_BYTES)
        ) lane (
            .clk, .rst_n,
            .request_valid(launch_pending[LOGICAL_LANE]),
            .request_ready(lane_request_ready[LOGICAL_LANE]),
            .request_recipe(lane_recipe[LOGICAL_LANE]),
            .request_secret_seed(secret_seed),
            .request_secret_prf(secret_prf),
            .request_public_seed(public_seed), .request_root(root_value),
            .request_identifier(identifier),
            .request_randomizer(lane_randomizer[LOGICAL_LANE]),
            .request_message(message_buffer),
            .request_message_length(message_length),
            .request_q(lane_q[LOGICAL_LANE]),
            .request_item(lane_item[LOGICAL_LANE]),
            .request_steps(lane_steps[LOGICAL_LANE]),
            .request_address(lane_address[LOGICAL_LANE]),
            .request_left(lane_left[LOGICAL_LANE]),
            .request_right(lane_right[LOGICAL_LANE]),
            .endpoint_read_index(lane_endpoint_index[LOGICAL_LANE]),
            .endpoint_read_data(endpoint_read_data),
            .response_valid(lane_response_valid[LOGICAL_LANE]),
            .response_ready(1'b1),
            .response_value(lane_response_value[LOGICAL_LANE]),
            .error(lane_error[LOGICAL_LANE]),
            .hash_contexts(lane_context_count[LOGICAL_LANE]),
            .permutations(lane_permutation_count[LOGICAL_LANE]),
            .active_cycles(lane_active_count[LOGICAL_LANE])
        );
    end endgenerate

    always_comb begin
        endpoint_read_address = lane_endpoint_index[0];
        if (macro_state == M_LTREE_READ_REQ
                 || macro_state == M_LTREE_READ_WAIT)
            endpoint_read_address = ltree_push_cursor;
    end
    assign batch_ready = launch_pending == 0 && response_pending == 0;

    // Physical-lane dispatcher.  Arguments are prepared by the macro
    // materializer; completion order is hidden behind batch_result[0:1].
    integer dispatch_lane;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            launch_pending <= 0;
            response_pending <= 0;
            batch_done <= 0;
        end else begin
            batch_done <= 0;
            if (batch_start && batch_ready) begin
                launch_pending <= batch_mask;
                response_pending <= batch_mask;
            end
            for (dispatch_lane = 0; dispatch_lane < 2;
                 dispatch_lane = dispatch_lane + 1) begin
                if (launch_pending[dispatch_lane]
                    && lane_request_ready[dispatch_lane])
                    launch_pending[dispatch_lane] <= 1'b0;
                if (response_pending[dispatch_lane]
                    && lane_response_valid[dispatch_lane]) begin
                    batch_result[dispatch_lane]
                        <= lane_response_value[dispatch_lane];
                    response_pending[dispatch_lane] <= 1'b0;
                end
            end
            // Complete a batch when every still-pending lane responds in this
            // cycle.  This also handles both lanes finishing together.
            if (response_pending != 0
                && (response_pending & ~lane_response_valid) == 0)
                batch_done <= 1'b1;
        end
    end

    // Byte-segment emitter; partial words deliberately span macro segments.
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            emit_active <= 0;
            emit_done <= 0;
        end else begin
            emit_done <= 0;
            if (emit_start && !emit_active) begin
                emit_data <= emit_start_data;
                emit_length <= emit_start_length;
                emit_index <= 0;
                emit_last <= emit_start_last;
                emit_active <= 1;
            end else if (emit_active && packer_in_ready) begin
                if (emit_index + 1'b1 == emit_length) begin
                    emit_active <= 0;
                    emit_done <= 1;
                end else
                    emit_index <= emit_index + 1'b1;
            end
        end
    end

    // Front-end job, message, and durable-state transaction control.
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            front_state <= F_IDLE;
            ucode_start <= 0;
            guard_initialize <= 0;
            guard_invalidate <= 0;
            guard_sign_valid <= 0;
            reservation_issued <= 0;
            done <= 0;
            error <= 0;
            error_code <= 0;
            context_base <= 0;
            permutation_base <= 0;
            lane_active_base[0] <= 0;
            lane_active_base[1] <= 0;
        end else begin
            ucode_start <= 0;
            guard_initialize <= 0;
            guard_invalidate <= 0;
            guard_sign_valid <= 0;
            done <= 0;

            if (cache_error || reducer_error || |lane_error
                || ucode_error || macro_error) begin
                error <= 1;
                error_code <= cache_error || reducer_error ? cache_error_code
                    : (|lane_error ? ERR_LANE
                       : (ucode_error ? ERR_SEQUENCER + ucode_error_code
                                      : macro_error_code));
                front_state <= F_ERROR;
            end else case (front_state)
                F_IDLE: begin
                    if (job_valid) begin
                        if (job_initial_q > 1024
                            || (job_operation == OP_SIGN
                                && (job_message_length == 0
                                    || job_message_length > MAX_MESSAGE_BYTES))) begin
                            error <= 1;
                            error_code <= ERR_JOB;
                            front_state <= F_ERROR;
                        end else begin
                            active_operation <= job_operation;
                            initial_q_saved <= job_initial_q;
                            secret_seed <= job_secret_seed;
                            secret_prf <= job_secret_prf;
                            public_seed <= job_public_seed;
                            identifier <= job_identifier;
                            external_randomizer <= job_randomizer;
                            message_length <= job_message_length[6:0];
                            message_received <= 0;
                            message_buffer <= 0;
                            context_base <= lane_context_count[0]
                                + lane_context_count[1];
                            permutation_base <= lane_permutation_count[0]
                                + lane_permutation_count[1];
                            lane_active_base[0] <= lane_active_count[0];
                            lane_active_base[1] <= lane_active_count[1];
                            error <= 0;
                            error_code <= 0;
                            reservation_issued <= 0;
                            if (job_operation == OP_KEYGEN) begin
                                guard_invalidate <= 1;
                                selected_entry <= image_keygen_entry;
                                front_state <= F_START;
                            end else if (!cache_valid_wire
                                         || !guard_initialized) begin
                                error <= 1;
                                error_code <= guard_initialized
                                    ? ERR_CACHE : 16'h2501;
                                front_state <= F_ERROR;
                            end else
                                front_state <= F_MESSAGE;
                        end
                    end
                end
                F_MESSAGE: begin
                    if (message_valid) begin
                        for (loader_byte = 0; loader_byte < 8;
                             loader_byte = loader_byte + 1)
                            if (message_keep[loader_byte]
                                && message_received + loader_byte
                                   < MAX_MESSAGE_BYTES)
                                message_buffer[
                                    (message_received+loader_byte)*8 +: 8]
                                    <= message_data[loader_byte*8 +: 8];
                        message_received <= message_received
                            + message_keep[0] + message_keep[1]
                            + message_keep[2] + message_keep[3]
                            + message_keep[4] + message_keep[5]
                            + message_keep[6] + message_keep[7];
                        if (message_last) begin
                            if (message_received
                                + message_keep[0] + message_keep[1]
                                + message_keep[2] + message_keep[3]
                                + message_keep[4] + message_keep[5]
                                + message_keep[6] + message_keep[7]
                                != message_length) begin
                                error <= 1;
                                error_code <= ERR_MESSAGE;
                                front_state <= F_ERROR;
                            end else
                                front_state <= F_RESERVE;
                        end
                    end
                end
                F_RESERVE: begin
                    if (!reservation_issued && guard_sign_ready) begin
                        guard_sign_valid <= 1;
                        reservation_issued <= 1;
                    end
                    if (guard_sign_grant) begin
                        active_q <= guard_sign_q;
                        selected_entry <= image_sign_entry;
                        front_state <= F_START;
                    end else if (guard_error) begin
                        error <= 1;
                        error_code <= guard_error_code;
                        front_state <= F_ERROR;
                    end
                end
                F_START: if (ucode_ready) begin
                    ucode_start <= 1;
                    front_state <= F_RUN;
                end
                F_RUN: if (ucode_done) begin
                    if (active_operation == OP_KEYGEN)
                        front_state <= F_INITIALIZE;
                    else
                        front_state <= F_DRAIN;
                end
                F_INITIALIZE: if (guard_initialize_ready) begin
                    guard_initialize <= 1;
                    front_state <= F_DRAIN;
                end
                F_DRAIN: if (packer_idle && !emit_active) begin
                    done <= 1;
                    front_state <= F_IDLE;
                end
                F_ERROR: begin
                    guard_invalidate <= active_operation == OP_KEYGEN;
                    if (!job_valid)
                        front_state <= F_IDLE;
                end
                default: front_state <= F_ERROR;
            endcase
        end
    end

    always_comb begin
        hash_contexts = PROFILE_ENABLE
            ? lane_context_count[0] + lane_context_count[1] - context_base : 0;
        keccak_permutations = PROFILE_ENABLE
            ? lane_permutation_count[0] + lane_permutation_count[1]
                - permutation_base : 0;
        lane0_active_cycles = PROFILE_ENABLE
            ? lane_active_count[0] - lane_active_base[0] : 0;
        lane1_active_cycles = PROFILE_ENABLE
            ? lane_active_count[1] - lane_active_base[1] : 0;
    end

    task automatic prepare_lane(
        input integer lane,
        input logic [3:0] recipe_value,
        input logic [9:0] q_value,
        input logic [6:0] item_value,
        input logic [4:0] steps_value,
        input logic [255:0] address_value,
        input logic [255:0] left_input,
        input logic [255:0] right_input,
        input logic [255:0] random_input
    );
        begin
            lane_recipe[lane] <= recipe_value;
            lane_q[lane] <= q_value;
            lane_item[lane] <= item_value;
            lane_steps[lane] <= steps_value;
            lane_address[lane] <= address_value;
            lane_left[lane] <= left_input;
            lane_right[lane] <= right_input;
            lane_randomizer[lane] <= random_input;
        end
    endtask

    task automatic start_segment(
        input logic [255:0] data_value,
        input logic [5:0] length_value,
        input logic last_value
    );
        begin
            emit_start_data <= data_value;
            emit_start_length <= length_value;
            emit_start_last <= last_value;
            emit_start <= 1;
        end
    endtask

    // Macro materializer and generic TREE/CHAIN iterators.
    always_ff @(posedge clk or negedge rst_n) begin : materializer
        logic [1:0] current_batch;
        logic [31:0] q_word;
        if (!rst_n) begin
            macro_state <= M_IDLE;
            ucode_task_done <= 0;
            batch_start <= 0;
            batch_mask <= 0;
            emit_start <= 0;
            cache_build_start <= 0;
            cache_build_abort <= 0;
            cache_build_commit <= 0;
            cache_lookup_valid <= 0;
            macro_error <= 0;
            macro_error_code <= 0;
            endpoint_write0_valid <= 0;
            endpoint_write1_valid <= 0;
        end else begin
            ucode_task_done <= 0;
            batch_start <= 0;
            emit_start <= 0;
            cache_build_start <= 0;
            cache_build_abort <= 0;
            cache_build_commit <= 0;
            cache_lookup_valid <= 0;
            endpoint_write0_valid <= 0;
            endpoint_write1_valid <= 0;

            if (front_state == F_IDLE && !job_valid) begin
                macro_error <= 0;
                macro_error_code <= 0;
                if (macro_state == M_ERROR)
                    macro_state <= M_IDLE;
            end

            if (front_state == F_ERROR && cache_build_active) begin
                cache_build_abort <= 1;
                macro_state <= M_ERROR;
            end else case (macro_state)
                M_IDLE: begin
                    if (command_valid && command_ready) begin
                        if (descriptor_memory[1][63:60] != DESC_PROFILE
                            || (!image_is_xmss && !image_is_lms)
                            || !descriptor_matches(command_macro,
                                                command_descriptor_kind)) begin
                            macro_error <= 1;
                            macro_error_code <= ERR_DESCRIPTOR;
                            macro_state <= M_ERROR;
                        end else case (command_macro)
                            MACRO_TREE_PUSH: begin
                                if (command_descriptor_word[41])
                                    macro_state <= M_BUILD_START;
                                else if (command_descriptor_word[40]) begin
                                    leaf_cursor <= command_coordinate[9:0];
                                    macro_state <= M_TREE_PUSH_START;
                                end
                                else begin
                                    auth_level <= 0;
                                    macro_state <= profile_auth_prefix
                                        ? M_AUTH_TYPE : M_AUTH_READ_REQ;
                                end
                            end
                            MACRO_HASH:
                                macro_state <= M_SIGN_HASH_A_PREP;
                            MACRO_TRANSFORM:
                                macro_state <= M_TRANSFORM_WORK;
                            MACRO_CHAIN: begin
                                if (command_descriptor_word[39]) begin
                                    leaf_cursor <= command_coordinate[9:0];
                                    chain_cursor <= 0;
                                    macro_state <= M_LEAF_CHAIN_PREP;
                                end else begin
                                    header_segment <= 0;
                                    macro_state <= M_HEADER_NEXT;
                                end
                            end
                            MACRO_EMIT: begin
                                active_emit_layout
                                    <= command_descriptor_word[59:52];
                                if (command_descriptor_word[51]) begin
                                    keygen_segment <= 0;
                                    macro_state <= M_KEYGEN_EMIT_NEXT;
                                end else
                                    macro_state <= M_COMPLETE;
                            end
                            default: begin
                                macro_error <= 1;
                                macro_error_code <= ERR_DESCRIPTOR;
                                macro_state <= M_ERROR;
                            end
                        endcase
                    end
                end
                M_BUILD_START: begin
                    if (cache_build_ready) begin
                        cache_build_start <= 1;
                        macro_state <= M_COMPLETE;
                    end
                end
                M_LEAF_CHAIN_PREP: if (batch_ready) begin
                    current_batch = chain_cursor + 1 < 67 ? 2 : 1;
                    prepare_lane(0, profile_chain_recipe,
                                 leaf_cursor, chain_cursor, 5'd15,
                                 xmss_address(0, leaf_cursor,
                                              chain_cursor, 0),
                                 0, 0, external_randomizer);
                    if (current_batch == 2)
                        prepare_lane(1, profile_chain_recipe,
                                     leaf_cursor, chain_cursor+1'b1, 5'd15,
                                     xmss_address(0, leaf_cursor,
                                                  chain_cursor+1'b1, 0),
                                     0, 0, external_randomizer);
                    batch_mask <= current_batch == 2 ? 2'b11 : 2'b01;
                    batch_start <= 1;
                    macro_state <= M_LEAF_CHAIN_WAIT;
                end
                M_LEAF_CHAIN_WAIT: if (batch_done) begin
                    endpoint_write0_valid <= 1;
                    endpoint_write0_index <= chain_cursor;
                    endpoint_write0_data <= batch_result[0];
                    if (chain_cursor + 1 < 67) begin
                        endpoint_write1_valid <= 1;
                        endpoint_write1_index <= chain_cursor + 1'b1;
                        endpoint_write1_data <= batch_result[1];
                    end
                    if (chain_cursor + 2 >= 67) begin
                        chain_cursor <= 0;
                        if (!profile_list_reduce) begin
                            ltree_push_cursor <= 0;
                            macro_state <= M_LTREE_READ_REQ;
                        end else
                            macro_state <= M_LIST_PREP;
                    end else begin
                        chain_cursor <= chain_cursor + 2;
                        macro_state <= M_LEAF_CHAIN_PREP;
                    end
                end
                M_LTREE_READ_REQ: begin
                    if (endpoint_write_idle)
                        macro_state <= M_LTREE_READ_WAIT;
                end
                M_LTREE_READ_WAIT: begin
                    leaf_value <= endpoint_read_data;
                    macro_state <= M_LTREE_PUSH_START;
                end
                M_LTREE_PUSH_START: if (reducer_push_ready)
                    macro_state <= M_LTREE_PUSH_WAIT;
                M_LTREE_PUSH_WAIT: begin
                    if (reducer_root_valid)
                        leaf_value <= reducer_root_value;
                    if (reducer_parent_valid && batch_ready) begin
                        prepare_lane(0, profile_parent_recipe,
                            leaf_cursor, 0, 0,
                            xmss_address(1, leaf_cursor,
                                reducer_parent_level,
                                reducer_parent_index),
                            reducer_parent_left, reducer_parent_right, 0);
                        batch_mask <= 2'b01;
                        batch_start <= 1;
                        macro_state <= M_LTREE_PUSH_PARENT_WAIT;
                    end else if (reducer_push_done) begin
                        if (ltree_push_cursor == 66)
                            macro_state <= M_STORE_LEAF;
                        else begin
                            ltree_push_cursor <= ltree_push_cursor + 1'b1;
                            macro_state <= M_LTREE_READ_REQ;
                        end
                    end
                end
                M_LTREE_PUSH_PARENT_WAIT: if (batch_done)
                    macro_state <= M_LTREE_PUSH_WAIT;
                M_LIST_PREP: if (endpoint_write_idle && batch_ready) begin
                    prepare_lane(0, SHAPE_PREFIX_LIST, leaf_cursor, 0, 0,
                                 0, 0, 0, 0);
                    batch_mask <= 2'b01;
                    batch_start <= 1;
                    macro_state <= M_LIST_WAIT;
                end
                M_LIST_WAIT: if (batch_done) begin
                    list_value <= batch_result[0];
                    macro_state <= M_LEAF_FINAL_PREP;
                end
                M_LEAF_FINAL_PREP: if (batch_ready) begin
                    prepare_lane(0, SHAPE_PREFIX_VALUE, leaf_cursor, 0, 0,
                                 0, list_value, 0, 0);
                    batch_mask <= 2'b01;
                    batch_start <= 1;
                    macro_state <= M_LEAF_FINAL_WAIT;
                end
                M_LEAF_FINAL_WAIT: if (batch_done) begin
                    leaf_value <= batch_result[0];
                    macro_state <= M_STORE_LEAF;
                end
                M_STORE_LEAF: macro_state <= M_COMPLETE;
                M_TREE_PUSH_START: if (reducer_push_ready)
                    macro_state <= M_TREE_PUSH_WAIT;
                M_TREE_PUSH_WAIT: begin
                    if (reducer_root_valid)
                        root_value <= reducer_root_value;
                    if (reducer_parent_valid && batch_ready) begin
                        prepare_lane(0, profile_parent_recipe,
                            0, 0, 0,
                            profile_parent_recipe == SHAPE_MASKED_PARENT
                                ? xmss_address(2, 0,
                                    reducer_parent_level,
                                    reducer_parent_index)
                                : lms_parent_address(
                                    reducer_parent_level + 1'b1,
                                    reducer_parent_index),
                            reducer_parent_left, reducer_parent_right, 0);
                        batch_mask <= 2'b01;
                        batch_start <= 1;
                        macro_state <= M_TREE_PUSH_PARENT_WAIT;
                    end else if (reducer_push_done) begin
                        if (leaf_cursor == 1023)
                            macro_state <= M_COMMIT_DRAIN;
                        else
                            macro_state <= M_COMPLETE;
                    end
                end
                M_TREE_PUSH_PARENT_WAIT: if (batch_done)
                    macro_state <= M_TREE_PUSH_WAIT;
                M_COMMIT_DRAIN: if (cache_queued_writes == 0
                                     && cache_tree_writes == 2047)
                    macro_state <= M_COMMIT_PULSE;
                M_COMMIT_PULSE: begin
                    cache_build_commit <= 1;
                    macro_state <= M_COMMIT_WAIT;
                end
                M_COMMIT_WAIT: if (cache_valid_wire)
                    macro_state <= M_COMPLETE;
                M_SIGN_HASH_A_PREP: if (batch_ready) begin
                    prepare_lane(0, profile_hash_a_recipe,
                                 active_q, 0, 0, 0, 0, 0,
                                 profile_hash_b_recipe != 0
                                     ? 0 : external_randomizer);
                    batch_mask <= 2'b01;
                    batch_start <= 1;
                    macro_state <= M_SIGN_HASH_A_WAIT;
                end
                M_SIGN_HASH_A_WAIT: if (batch_done) begin
                    if (profile_hash_b_recipe != 0) begin
                        signature_randomizer <= batch_result[0];
                        macro_state <= M_SIGN_HASH_B_PREP;
                    end else begin
                        signature_randomizer <= external_randomizer;
                        message_digest <= batch_result[0];
                        macro_state <= M_COMPLETE;
                    end
                end
                M_SIGN_HASH_B_PREP: if (batch_ready) begin
                    prepare_lane(0, profile_hash_b_recipe, active_q, 0, 0,
                                 0, 0, 0, signature_randomizer);
                    batch_mask <= 2'b01;
                    batch_start <= 1;
                    macro_state <= M_SIGN_HASH_B_WAIT;
                end
                M_SIGN_HASH_B_WAIT: if (batch_done) begin
                    message_digest <= batch_result[0];
                    macro_state <= M_COMPLETE;
                end
                M_TRANSFORM_WORK: begin
                    checksum_work = 0;
                    for (transform_index = 0; transform_index < 64;
                         transform_index = transform_index + 1) begin
                        if (!transform_index[0])
                            chain_digits[transform_index]
                                <= message_digest[(transform_index/2)*8+4 +: 4];
                        else
                            chain_digits[transform_index]
                                <= message_digest[(transform_index/2)*8 +: 4];
                        checksum_work = checksum_work + 15
                            - (!transform_index[0]
                                ? message_digest[(transform_index/2)*8+4 +: 4]
                                : message_digest[(transform_index/2)*8 +: 4]);
                    end
                    checksum_work = checksum_work << 4;
                    chain_digits[64] <= checksum_work[15:12];
                    chain_digits[65] <= checksum_work[11:8];
                    chain_digits[66] <= checksum_work[7:4];
                    macro_state <= M_COMPLETE;
                end
                M_HEADER_NEXT: begin
                    if (!emit_active) begin
                        q_word = active_q;
                        if (header_segment == 0) begin
                            start_segment({224'b0, packed_be32(q_word)}, 4, 0);
                            header_segment <= 1;
                            macro_state <= M_HEADER_WAIT;
                        end else if (profile_auth_prefix
                                    && header_segment == 1) begin
                            start_segment({224'b0,
                                           packed_be32(profile_chain_type)},
                                          4, 0);
                            header_segment <= 2;
                            macro_state <= M_HEADER_WAIT;
                        end else begin
                            start_segment(signature_randomizer, 32, 0);
                            header_segment <= profile_auth_prefix ? 3 : 2;
                            macro_state <= M_HEADER_WAIT;
                        end
                    end
                end
                M_HEADER_WAIT: if (emit_done) begin
                    if ((!profile_auth_prefix && header_segment == 2)
                        || (profile_auth_prefix && header_segment == 3)) begin
                        chain_cursor <= 0;
                        macro_state <= M_SIGN_CHAIN_PREP;
                    end else
                        macro_state <= M_HEADER_NEXT;
                end
                M_SIGN_CHAIN_PREP: if (batch_ready) begin
                    current_batch = chain_cursor + 1 < 67 ? 2 : 1;
                    prepare_lane(0, profile_chain_recipe,
                                 active_q, chain_cursor,
                                 chain_digits[chain_cursor],
                                 xmss_address(0, active_q,
                                              chain_cursor, 0),
                                 0, 0, external_randomizer);
                    if (current_batch == 2)
                        prepare_lane(1, profile_chain_recipe,
                                     active_q, chain_cursor+1'b1,
                                     chain_digits[chain_cursor+1],
                                     xmss_address(0, active_q,
                                                  chain_cursor+1'b1, 0),
                                     0, 0, external_randomizer);
                    parent_batch_tasks <= current_batch;
                    batch_mask <= current_batch == 2 ? 2'b11 : 2'b01;
                    batch_start <= 1;
                    macro_state <= M_SIGN_CHAIN_WAIT;
                end
                M_SIGN_CHAIN_WAIT: if (batch_done)
                    macro_state <= M_SIGN_CHAIN_EMIT0;
                M_SIGN_CHAIN_EMIT0: if (!emit_active) begin
                    start_segment(batch_result[0], 32, 0);
                    macro_state <= M_SIGN_CHAIN_EMIT0_WAIT;
                end
                M_SIGN_CHAIN_EMIT0_WAIT: if (emit_done)
                    macro_state <= parent_batch_tasks == 2
                        ? M_SIGN_CHAIN_EMIT1 : M_SIGN_CHAIN_EMIT1_WAIT;
                M_SIGN_CHAIN_EMIT1: if (!emit_active) begin
                    start_segment(batch_result[1], 32, 0);
                    macro_state <= M_SIGN_CHAIN_EMIT1_WAIT;
                end
                M_SIGN_CHAIN_EMIT1_WAIT: begin
                    if ((parent_batch_tasks == 1 && !emit_active)
                        || (parent_batch_tasks == 2 && emit_done)) begin
                        if (chain_cursor + parent_batch_tasks >= 67)
                            macro_state <= M_COMPLETE;
                        else begin
                            chain_cursor <= chain_cursor + parent_batch_tasks;
                            macro_state <= M_SIGN_CHAIN_PREP;
                        end
                    end
                end
                M_AUTH_TYPE: if (!emit_active) begin
                    start_segment({224'b0, packed_be32(profile_outer_type)},
                                  4, 0);
                    macro_state <= M_AUTH_TYPE_WAIT;
                end
                M_AUTH_TYPE_WAIT: if (emit_done)
                    macro_state <= M_AUTH_READ_REQ;
                M_AUTH_READ_REQ: if (cache_lookup_ready) begin
                    cache_lookup_valid <= 1;
                    cache_lookup_allow <= 0;
                    cache_lookup_address <= tree_address(
                        auth_level, (active_q >> auth_level) ^ 1'b1);
                    macro_state <= M_AUTH_READ_WAIT;
                end
                M_AUTH_READ_WAIT: if (cache_lookup_rsp_valid) begin
                    if (!cache_lookup_hit) begin
                        macro_error <= 1;
                        macro_error_code <= ERR_CACHE;
                        macro_state <= M_ERROR;
                    end else begin
                        auth_value <= cache_lookup_data;
                        macro_state <= M_AUTH_EMIT;
                    end
                end
                M_AUTH_EMIT: if (!emit_active) begin
                    start_segment(auth_value, 32, auth_level == 9);
                    macro_state <= M_AUTH_EMIT_WAIT;
                end
                M_AUTH_EMIT_WAIT: if (emit_done) begin
                    if (auth_level == 9)
                        macro_state <= M_COMPLETE;
                    else begin
                        auth_level <= auth_level + 1'b1;
                        macro_state <= M_AUTH_READ_REQ;
                    end
                end
                M_KEYGEN_EMIT_NEXT: if (!emit_active) begin
                    q_word = initial_q_saved;
                    if (active_emit_layout == 8'd1) begin
                        case (keygen_segment)
                            0: start_segment({224'b0, packed_be32(q_word)},4,0);
                            1: start_segment(secret_seed,32,0);
                            2: start_segment(secret_prf,32,0);
                            3: start_segment(root_value,32,0);
                            4: start_segment(public_seed,32,0);
                            5: start_segment(root_value,32,0);
                            default: start_segment(public_seed,32,1);
                        endcase
                    end else begin
                        case (keygen_segment)
                            0: start_segment({224'b0, packed_be32(q_word)},4,0);
                            1: start_segment({128'b0, identifier},16,0);
                            2: start_segment(secret_seed,32,0);
                            3: start_segment(root_value,32,0);
                            4: start_segment({224'b0,
                                packed_be32(profile_outer_type)},4,0);
                            5: start_segment({224'b0,
                                packed_be32(profile_chain_type)},4,0);
                            6: start_segment({128'b0, identifier},16,0);
                            default: start_segment(root_value,32,1);
                        endcase
                    end
                    macro_state <= M_KEYGEN_EMIT_WAIT;
                end
                M_KEYGEN_EMIT_WAIT: if (emit_done) begin
                    if ((active_emit_layout == 8'd1 && keygen_segment == 6)
                        || (active_emit_layout == 8'd2
                            && keygen_segment == 7))
                        macro_state <= M_COMPLETE;
                    else begin
                        keygen_segment <= keygen_segment + 1'b1;
                        macro_state <= M_KEYGEN_EMIT_NEXT;
                    end
                end
                M_COMPLETE: begin
                    ucode_task_done <= 1;
                    macro_state <= M_IDLE;
                end
                M_ERROR: begin
                    macro_error <= 1;
                    if (macro_error_code == 0)
                        macro_error_code <= ERR_CACHE;
                end
                default: begin
                    macro_error <= 1;
                    macro_error_code <= ERR_DESCRIPTOR;
                    macro_state <= M_ERROR;
                end
            endcase
        end
    end
endmodule

`default_nettype wire
