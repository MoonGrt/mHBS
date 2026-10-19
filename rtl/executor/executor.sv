`timescale 1ns / 1ps
`default_nettype none
// Single-lane ABI 4 macro executor for SLH and standard SHAKE256 XMSS/LMS.
// verilog_format: off
module executor #(
    parameter integer UNROLL=1, PIPELINE=1
) (
`ifndef SYNTHESIS
    output logic [15:0] error_code,
    output logic [63:0] cycles,
    output wire [63:0] hash_count, permutation_count,
`endif
    input wire clk, rst,
    input wire [63:0] image_header, profile_descriptor,
    output wire [3:0] program_address, input wire [63:0] program_data,
    output wire [3:0] template_address, input wire [63:0] template_data,
    output wire [9:0] descriptor_addresses, input wire [127:0] descriptor_data,
    input wire [3:0] job_entry, input wire [1:0] job_operation,
    input wire job_valid, output wire job_ready, input wire [6:0] job_message_length,
    input wire [31:0] job_index, input wire [127:0] job_identifier,
    input wire [255:0] job_secret_seed, job_secret_prf, job_public_seed, job_public_root, job_randomizer,
    input wire message_valid, output wire message_ready, input wire [63:0] message_data,
    input wire verify_valid, output wire verify_ready,
    input wire [255:0] verify_data, output logic verify_pass,
    output wire out_valid, output wire [255:0] out_data,
    output wire [5:0] out_bytes, output wire busy, output logic done, error
);
// verilog_format: on
    localparam integer N = 32, W = 256, V = 392, INDEX_BITS = 8, MAX_MESSAGE_BYTES = 87;
    localparam integer DIGEST_BYTES = 49;
    // Six supported profiles need at most ceil(35*9/8)=40 FORS bytes.
    // Tree/leaf indices still consume the full V-bit transient Hmsg result.
    localparam integer FORS_DIGEST_BITS = 320;
    wire [4:0] config_code = profile_descriptor[4:0];
    wire decoded_stateful = config_code >= 5'h18 && config_code <= 5'h1d;
    wire decoded_xmss = decoded_stateful && config_code < 5'h1b;
`ifdef MHBS_SHA2
    wire valid_profile=profile_descriptor[63:6]==0 && profile_descriptor[5] &&
        (decoded_stateful || config_code==0 || config_code==4);
`else
    wire valid_profile=profile_descriptor[63:5]==0 && (decoded_stateful
        || config_code==0 || config_code==1 || config_code==2 || config_code==4 || config_code==5 || config_code==6);
`endif
    wire [4:0] decoded_height=(config_code==5'h18 || config_code==5'h1b) ? 5'd10
        : config_code==5'h19 ? 5'd16 : config_code==5'h1c ? 5'd15 : 5'd20;
    logic stateful, xmss, small_signature;
    logic [4:0] stateful_height;
    logic [1:0] profile_code;
    logic [5:0] node_bytes;
    wire [3:0] chain_max = 4'd15;
    wire [3:0] FORS_A=small_signature ? (profile_code==0 ? 4'd12 : 4'd14)
        : profile_code==0 ? 4'd6 : profile_code==1 ? 4'd8 : 4'd9;
    wire [7:0] LEN1 = {1'b0, node_bytes, 1'b0};
    // Two reads are sufficient: request recipe plus chain-step recipe.
    // Macro and tree/chain descriptors are already latched in setup states.
    typedef enum logic [6:0] {
        IDLE, MESSAGE, LAUNCH, FETCH, LOAD_DESCRIPTOR, DECODE,
        TREE_INIT, CHAIN_SETUP, CHAIN_STORE,
        CHAIN_OUTPUT0=10, CHAIN_NEXT=14, REDUCE_SETUP, LEAF_SETUP,
        PUSH_NODE, PARENT_SETUP, PARENT_DONE, AUTH_OUTPUT, TREE_FINISH,
        HASH_ISSUE, HASH_WAIT, HASH_RESULT, ROUTE, TRANSFORM,
        EMIT, EMIT_NEXT, OUTPUT_CHUNK, DRAIN, FINISH, FAILED,
        VERIFY_INPUT, VERIFY_RANDOM, VERIFY_CHAIN_INPUT,
        VERIFY_CHAIN_RUN, VERIFY_CHAIN_ADVANCE,
        // Explicit gaps preserve active state encodings used by cycle observers.
        PIPE_ISSUE, PIPE_WAIT, PIPE_LOAD, PIPE_CAPTURE_NEXT=42,
        LT_SETUP=44, LT_STORE, LT_COPY, LT_NEXT, LT_FINISH, SF_LEAF=50, SF_LEAF_DONE, SF_RANDOM,
        PIPE_VERIFY_INPUT, LT_PIPE_INIT, LT_PIPE_ISSUE, LT_PIPE_WAIT,
        FORS_PICK=58, FORS_AUTH0, FORS_BEGIN, FORS_LEFT, FORS_ISSUE=63, FORS_WAIT, FORS_LEVEL, FORS_AUTH1, FORS_PUSH,
        FORS_LEAF_NEXT, FORS_ROOT_NEXT, PUSH_STACK
    } state_t;
    state_t state, continuation;
    logic lane_request_active, batch_issue_phase, batch_verify_phase, pipe_response_accept;
    logic direct_writeback_phase;
    task automatic enter_state(input state_t next_state);
        begin
            state <= next_state;
            // Prepare interface controls with the state transition, so binary
            // state decoding does not cross recipe ready and return to prefetch.
            lane_request_active <= next_state == HASH_ISSUE;
            batch_issue_phase <= PIPELINE > 1 && (next_state == PIPE_ISSUE ||
                next_state == LT_PIPE_ISSUE || next_state == FORS_ISSUE);
            batch_verify_phase <= PIPELINE > 1 && next_state == PIPE_VERIFY_INPUT;
            pipe_response_accept <= PIPELINE > 1 && (next_state == PIPE_ISSUE ||
                next_state == PIPE_WAIT || next_state == PIPE_VERIFY_INPUT ||
                next_state == LT_PIPE_WAIT || next_state == FORS_WAIT);
            // Decode the destination on the transition edge, before these
            // shared phase controls fan out through the recipe formatter.
            // IDLE membership is empty, so the reset transition clears all four.
            pipe_mode <= PIPELINE > 1 && (next_state == PIPE_ISSUE || next_state == PIPE_WAIT ||
                next_state == PIPE_VERIFY_INPUT || next_state == LT_PIPE_ISSUE ||
                next_state == LT_PIPE_WAIT || next_state == FORS_LEFT ||
                next_state == FORS_ISSUE || next_state == FORS_WAIT);
            fors_pipe <= PIPELINE > 1 && (next_state == FORS_LEFT ||
                next_state == FORS_ISSUE || next_state == FORS_WAIT);
            lt_pipe <= PIPELINE > 1 && (next_state == LT_PIPE_ISSUE || next_state == LT_PIPE_WAIT);
            fors_leaves <= PIPELINE > 1 && indexing == 1 && !verifying &&
                (next_state == PIPE_ISSUE || next_state == PIPE_WAIT);
            // Direct-result ownership is stable for the whole batch. Prepare
            // it at the same transition edge as request/response controls;
            // algorithm and operation decoding no longer crosses RAM writes.
            direct_writeback_phase <= PIPELINE > 1 && pipe_direct &&
                (next_state == PIPE_ISSUE || next_state == PIPE_WAIT ||
                 next_state == PIPE_VERIFY_INPUT);
        end
    endtask
    // Abort outstanding execution on an error. The autonomous wrapper halts
    // until reset; this benchmark does not track index consumption.
    // The main controller uses return-state registers and need not synthesize
    // as a one-hot FSM. Never drive asynchronous reset from its binary decode.
    (* dont_touch="yes" *) logic abort_execution;
    wire execution_rst = rst || abort_execution;
    logic [1:0] operation;
    wire verifying = operation == 2;
    // Hash, output and Verify transfers are serialized. Their continuation
    // is consumed before another transfer starts, so one register is enough.
    // Boot loader owns immutable Job registers for this reset epoch.
    wire [255:0] secret_seed = job_secret_seed, secret_prf = job_secret_prf;
    wire [255:0] public_seed = job_public_seed, randomizer = job_randomizer;
    logic [MAX_MESSAGE_BYTES*8-1:0] message_buffer;
    logic [6:0] message_length, message_received;
    logic [W-1:0] value[0:3];
    logic [FORS_DIGEST_BITS-W-1:0] fors_digest_tail;
    logic [63:0] scalar_tree;
    logic [19:0] scalar_leaf;
    logic [11:0] checksum;
    logic [7:0] transform_index;
    logic [7:0] lt_count, lt_cursor;
    logic [3:0] lt_level;
    localparam integer FORS_BATCH = 4 * ((PIPELINE + 3) / 4);
    // FORS runs before WOTS. Its at most 35 roots use 0..34, so
    // the 24-node microgroup scratch can reuse dead endpoints 36..59.
    // Tree-stack/auth data remain independently live in 68..107.
    localparam integer FORS_SCRATCH = 36, WORKSPACE_DEPTH = 128;
    logic fors_level, fors_roots_pending;
    logic [4:0] fors_total, fors_offset, fors_root_cursor;
    logic [20:0] fors_base;
    logic [9:0] fors_digest_offset;
    logic [13:0] fors_target_prefetch;
    // A FORS microgroup keeps target/base stable while leaves and parents run.
    // Prepare its unsigned relative index on the existing setup edge. The
    // consumer then compares a bounded five-bit index instead of cascading
    // two full-width additions and a full-width range comparison.
    logic [20:0] fors_target_delta;
    wire fors_target_group = fors_target_delta < {16'd0, fors_total};
    wire [5:0] fors_wave_end = {1'b0, fors_offset} + 6'(PIPELINE);
    wire fors_target_wave = fors_target_group &&
        fors_target_delta[4:0] >= fors_offset &&
        {1'b0, fors_target_delta[4:0]} < fors_wave_end;
    wire [4:0] fors_capture_tag = fors_target_delta[4:0] - fors_offset;
    // Four-leaf microgroups have a four-aligned base. One shared root-index
    // addition also supplies its final leaf by restoring the two low bits.
    wire [20:0] fors_root_index = (fors_base >> 2) + 21'(fors_root_cursor);
    wire [4:0] fors_outputs = fors_total >> (fors_level ? 2 : 1);
    wire sign_only = stateful && !verifying && standalone_chain && macro_flags[2];
    logic [4:0] layer;
    logic [5:0] group_index;
    logic [3:0] macro_op, macro_flags;
    logic [4:0] macro_desc, macro_route;
    logic [63:0] saved_descriptor, saved_chain_descriptor;
    wire [63:0] descriptor = saved_descriptor;
    wire [63:0] route_descriptor = descriptor_data[127:64];

    logic seq_start, seq_complete;
    wire seq_ready, seq_done, cmd_valid;
    wire [47:0] cmd;
    // verilog_format: off
    sequencer sequencer (
        .clk,.rst(execution_rst),.start(seq_start),.entry(job_entry),.ready(seq_ready),.done(seq_done),
        .program_address,.program_data,.template_address,.template_data,
        .command_valid(cmd_valid),.command_ready(state==FETCH),.command_done(seq_complete),.command(cmd)
    );
    // verilog_format: on

    logic [4:0] parent_id;
    wire [63:0] chain_descriptor = saved_chain_descriptor;
    logic standalone_chain;
    logic [4:0] tree_height, node_level, auth_level;
    logic [1:0] indexing;
    logic [20:0] target, leaf_cursor, node_index;
    // Follow the target's path as the current node climbs the tree. Keeping
    // this coordinate beside node_index removes a variable barrel shift from
    // the shared workspace write-enable/address/data selection path.
    logic [20:0] target_at_level;
    logic auth_node_match, node_below_root;
    // The parent-path decision is stable while parent setup formats its task.
    // Shadow it with the node coordinate to keep a wide equality comparison
    // out of the shared state/clear enables without inserting a controller beat.
    logic target_parent_match;
    wire [20:0] tree_target = stateful ? {1'b0, job_index[19:0]}
        : descriptor[37:36] == 1 ? {7'd0, fors_target_prefetch} : {1'b0, scalar_leaf};
    logic [INDEX_BITS-1:0] chain_cursor, endpoint_count;
    localparam integer PIPE_BATCH = PIPELINE;
    localparam integer TAG_BITS   = PIPELINE > 1 ? $clog2(PIPELINE) : 1;
    localparam integer COUNT_BITS = $clog2(PIPELINE + 1);
    logic pipe_cache_valid, pipe_batch_used;
    logic pipe_rolling;
    logic [PIPE_BATCH-1:0] pipe_active;
    logic [7:0] pipe_next_chain, pipe_completed;
    logic [INDEX_BITS-1:0] batch_chain_prefetch;
    logic [4:0] batch_digit_prefetch;
    logic [7:0] pipe_chain_index[0:PIPE_BATCH-1];
    logic [TAG_BITS-1:0] roll_slot;
    logic roll_available;
    logic [PIPE_BATCH-1:0] roll_next_free;
    logic [TAG_BITS-1:0] roll_next_slot;
    // Prepare the next allocator result beside the ownership update. A tag
    // retired on this edge is first offered in the following cycle, matching
    // the ownership bitmap while removing its priority encoder from ready.
    wire [PIPE_BATCH-1:0] roll_free = ~pipe_active;
    always_comb begin
        roll_next_free = roll_free;
        if (pipe_valid) roll_next_free[pipe_tag] = 1'b1;
        if (pipe_selected && pipe_ready) roll_next_free[issue_slot] = 1'b0;
        roll_next_slot = 0;
        for (integer j = PIPE_BATCH - 1; j >= 0; j--)
            if (roll_next_free[j]) roll_next_slot = TAG_BITS'(j);
    end
    wire  [  TAG_BITS-1:0] issue_slot = pipe_rolling ? roll_slot : pipe_issue_slot;
    logic [  TAG_BITS-1:0] pipe_issue_slot;
    logic [COUNT_BITS-1:0] pipe_pair;
    logic [PIPE_BATCH-1:0] pipe_done_mask, pipe_expected_mask;
    wire [255:0] pipe_read_result, pipe_read_capture, pipe_response_result;
    logic [7:0] pipe_seed_domain, pipe_step_domain;
    // Stateful endpoint batches use the same single write port as SLH WOTS.
    // Sign-only and verification batches retain their CHAIN_STORE path.
    wire pipe_direct = PIPELINE > 1 && indexing != 1 && (stateful ? (!verifying && !sign_only) : operation == 1);
    logic fors_pipe, fors_leaves, lt_pipe, pipe_mode;
    wire pipe_ready, pipe_valid, pipe_selected;
    // The final response first commits its bitmap/count. The controller
    // observes only registered retirement, separating recipe return control
    // from the next execution phase and RAM-address preparation.
    wire lt_batch_complete =
        (pipe_done_mask & pipe_expected_mask) == pipe_expected_mask;
    wire [TAG_BITS-1:0] pipe_tag;
`ifndef SYNTHESIS
    wire [63:0] pipe_hashes, pipe_permutations;
`endif
    wire  [255:0] selected_capture = pipe_batch_used ? pipe_read_capture : lane_capture;
    logic [255:0] node_value;
    localparam integer STACK_BASE = 68, AUTH_BASE = 88;

    logic [4:0] hash_recipe_id;
    assign descriptor_addresses = {
        state == CHAIN_SETUP ? chain_descriptor[48:44] : macro_route, hash_recipe_id[4:0]
    };
    always @* begin
        hash_recipe_id = macro_desc;
        case (state)
            TREE_INIT: hash_recipe_id = {1'b0, saved_descriptor[58:52]};
            EMIT: hash_recipe_id = emit_base + emit_cursor;
            CHAIN_SETUP: hash_recipe_id = chain_descriptor[59:52];
            VERIFY_CHAIN_RUN: hash_recipe_id = chain_descriptor[48:44];
            REDUCE_SETUP, LT_PIPE_INIT: hash_recipe_id = chain_descriptor[43:36];
            LT_SETUP: if (PIPELINE == 1) hash_recipe_id = chain_descriptor[43:36];
            SF_LEAF: hash_recipe_id = chain_descriptor[35:28];
            PARENT_SETUP: hash_recipe_id = parent_id;
            default: begin
            end
        endcase
    end
    logic [63:0] task_recipe, task_step;
    logic task_chain;
    logic task_capture;
    logic [4:0] task_steps, task_capture_after;
    logic [19:0] task_leaf;
    logic [INDEX_BITS-1:0] task_a;
    // Every supported address fits 21 bits: LMS leaves are 2^h+q,
    // h<=20; FORS uses a six-bit group and at most a fourteen-bit leaf.
    // Extend at the recipe boundary rather than carrying eleven dead bits.
    logic [20:0] task_b;
    wire [19:0] fors_tree_base = {14'd0, group_index} << FORS_A;
    wire [20:0] fors_chain_address = {1'b0, fors_tree_base}
        + (verifying ? target : leaf_cursor);
    wire [4:0] parent_level = node_level + 5'd1;
    wire [20:0] parent_index = node_index >> 1;
    wire [20:0] parent_address = parent_index
        + (indexing == 1 ? ({1'b0, fors_tree_base} >> parent_level)
           : indexing == 2 ? (21'd1 << (tree_height - parent_level)) : 21'd0);
    wire [20:0] batch_address = fors_pipe
        ? ({1'b0, fors_tree_base} >> (fors_level ? 2 : 1))
          + (fors_base >> (fors_level ? 2 : 1))
          + 21'(fors_offset) + 21'(pipe_issue_slot)
        : lt_pipe ? 21'(lt_cursor >> 1) + 21'(pipe_issue_slot)
        : indexing == 1 ? {1'b0, fors_tree_base} + batch_leaf_index : 21'd0;
    // Parent operands stay unchanged until the successful parent response
    // is consumed. Other recipes do not consume the right input, so no
    // duplicate parent-right register is needed.
    wire [255:0] parent_right = verifying && continuation==PARENT_DONE && !node_index[0] ? emit_value : node_value;
    // A scalar input is dead when its result arrives. Parent setup loads
    // the left operand into result; LMS leaves and Verify chains already
    // have their input there. The right node remains independently live.
    wire verify_step_needed = task_b[3:0] != chain_max;
    wire lane_ready, lane_valid, lane_error;
    wire [V-1:0] lane_value;
    wire [255:0] lane_capture;
    wire [INDEX_BITS-1:0] lane_list_next;
`ifndef SYNTHESIS
    wire [63:0] lane_hashes, lane_permutations;
    logic [63:0] hash_base, permutation_base;
`endif

    logic [V-1:0] result;
    // ROUTE consumes these registers before it can update any source. Keep
    // the original staging cycle, but remember only the source selection.
    localparam logic [1:0] ROUTE_HASH = 0, ROUTE_NODE = 1, ROUTE_SAVED = 2, ROUTE_EMIT = 3;
    logic [1:0] route_source;
    wire [V-1:0] route_value = route_source==ROUTE_HASH ? result
        : {{(V-W){1'b0}}, (route_source==ROUTE_NODE ? node_value
                        : route_source==ROUTE_SAVED ? value[3] : emit_value)};
    // Captures remain stable until CHAIN_OUTPUT0 consumes them.
`ifndef SYNTHESIS
    wire [63:0] total_hashes = lane_hashes + pipe_hashes;
    wire [63:0] total_permutations = lane_permutations + pipe_permutations;
    assign hash_count = total_hashes - hash_base;
    assign permutation_count = total_permutations - permutation_base;
`endif

    logic endpoint_write;
    logic [INDEX_BITS-1:0] endpoint_address;
    wire [INDEX_BITS-1:0] endpoint_read0, endpoint_read1;
    logic [255:0] endpoint_data;
    wire [255:0] endpoint_value0, endpoint_value1;
    // All list producers are mutually exclusive. A single write port serves
    // WOTS completions, FORS roots and in-place L-tree reduction.
    wire root_write = state == ROUTE && macro_route != 0 && route_descriptor[53];
    // verilog_format: off
    (* keep_hierarchy="yes" *) value #(.WIDTH(W),.DEPTH(WORKSPACE_DEPTH),.ADDRESS_BITS(INDEX_BITS)) endpoints (
        .clk,.write_enable(endpoint_write),.write_address(endpoint_address),.write_data(endpoint_data),
        .read0(endpoint_read0),.read1(endpoint_read1),.value0(endpoint_value0),.value1(endpoint_value1)
    );
    // verilog_format: on
    wire [INDEX_BITS-1:0] batch_chain_index = batch_chain_prefetch;
    // Response consumption already has a registered phase flag. Direct
    // writeback needs the published response tag; deferred reads use pipe_pair.
    // Avoid decoding indexing/algorithm/direct mode on the context RAM address.
    wire [TAG_BITS-1:0] context_read_tag = state == FORS_PICK ?
        TAG_BITS'(fors_capture_tag) :
        pipe_response_accept ? pipe_tag : TAG_BITS'(pipe_pair);
    wire [20:0] batch_leaf_index=leaf_cursor+21'(fors_leaves ? fors_offset : 0)+21'(pipe_issue_slot);
    assign pipe_selected=PIPELINE>1 && (batch_issue_phase || (batch_verify_phase && verify_valid))
        && (fors_pipe || (pipe_rolling ? (pipe_next_chain<endpoint_count && roll_available) : pipe_expected_mask[pipe_issue_slot]));
    // verilog_format: off
    recipe #(.N(N),.DIGEST_BYTES(DIGEST_BYTES),.INDEX_BITS(INDEX_BITS),
        .UNROLL(UNROLL),.PIPELINE(PIPELINE),.MAX_MESSAGE_BYTES(MAX_MESSAGE_BYTES),
        .SHARED_STATE(1'b1),.RECIPE_MASK(16'hfffe)) lane (
`ifndef SYNTHESIS
        .hash_count(lane_hashes),
        .permutation_count(lane_permutations),
        .batch_hashes(pipe_hashes),.batch_permutations(pipe_permutations),
`endif
        .clk,.rst(execution_rst),.node_bytes,
        .batch_mode(pipe_mode),.batch_request_valid(pipe_selected),.batch_request_ready(pipe_ready),
        .batch_request_tag(issue_slot),
        .batch_steps(lt_pipe || fors_pipe ? 5'd0 : stateful && verifying ? {1'b0,chain_max}-batch_digit_prefetch
        : (sign_only || (macro_flags[3] && leaf_cursor==target)) ? batch_digit_prefetch : chain_descriptor[19:15]),
        .batch_family(stateful ? (xmss ? 2'd1 : 2'd2) : 2'd0),
        .batch_no_seed(lt_pipe || fors_pipe || (stateful && verifying)),.batch_start(stateful && verifying ? 4'(batch_digit_prefetch) : 4'd0),
        .batch_initial_value(fors_pipe || lt_pipe ? endpoint_value0 : verify_data),
        .batch_fixed_shape(fors_pipe ? 4'd2 : lt_pipe ? 4'd8 : 4'd0),.batch_pair(lt_pipe || fors_pipe),.batch_right(endpoint_value1),
        .batch_capture_after(indexing==1 ? 5'd0 : batch_digit_prefetch),
        .batch_capture_enable(!fors_pipe && !lt_pipe && !verifying && macro_flags[0] && (indexing==1 ? batch_leaf_index==target : leaf_cursor==target)),
        .batch_leaf(lt_pipe ? leaf_cursor[19:0] : indexing==1 ? scalar_leaf : leaf_cursor[19:0]),
        .batch_a(fors_pipe ? (fors_level ? 8'd2 : 8'd1) : lt_pipe ? {4'd0,lt_level} : indexing==1 ? 8'd0 : batch_chain_index),
        .batch_b({11'd0, batch_address}),
        .batch_seed_domain(pipe_seed_domain),.batch_step_domain(pipe_step_domain),
        .batch_response_valid(pipe_valid),.batch_response_ready(pipe_response_accept),.batch_response_tag(pipe_tag),
        .batch_response_digest(pipe_response_result),.batch_response_capture(),
        // Direct writeback and deferred consumption never overlap.
        // Select their tag before reading the context RAM, removing a
        // second 256-bit digest/key read port and its output selectors.
        .batch_read_tag(context_read_tag),
        .batch_read_digest(pipe_read_result),.batch_read_capture(pipe_read_capture),
        .request_valid(lane_request_active),
        .request_ready(lane_ready), .request_recipe(task_recipe), .request_step_recipe(task_step),
        .request_chain(task_chain), .request_steps(task_steps),
        .request_capture_after(task_capture_after),
        .request_capture(task_capture),
        .secret_seed,.secret_prf,.public_seed,.root(value[3][W-1:0]),
        .randomizer((task_recipe[59:56]==4 || task_recipe[59:56]==6 || (verifying && stateful)) ? value[0][W-1:0] : randomizer),
        .identifier(job_identifier),.message_buffer,.message_length,
        .request_layer(layer),.request_tree(scalar_tree),.request_leaf(task_leaf),
        .request_a(task_a),.request_b({11'd0, task_b}),.request_left(result[W-1:0]),.request_right(parent_right),
        .list_index0(),.list_index1(),.list_next_index0(lane_list_next),
        .list_data0(endpoint_value0),.list_data1(endpoint_value1),
        .response_valid(lane_valid),.response_ready(state==HASH_WAIT),
        .response_value(lane_value),.response_capture(lane_capture),.error(lane_error)
    );
    // verilog_format: on
`ifndef SYNTHESIS
    initial
        if(UNROLL<1 || PIPELINE<1 || PIPELINE>24 ||
        UNROLL*PIPELINE>24 || 24%(UNROLL*PIPELINE)!=0)
            $fatal(1, "Unsupported P/U configuration");

`endif

    // Verify never emits output: share its input-node latch with the output latch.
    logic [255:0] emit_value;
    logic [  5:0] emit_length;
    logic [  7:0] emit_base;
    logic [3:0] emit_count, emit_cursor;
    wire [63:0] emit_descriptor = descriptor_data[63:0];
    // One node per valid cycle, low byte first. The receiver uses done to
    // delimit the job and out_bytes to discard unused high bytes.
    assign out_valid = state == OUTPUT_CHUNK;
    assign out_data = emit_value;
    assign out_bytes = emit_length;
    assign job_ready = state == IDLE;
    assign message_ready = state == MESSAGE;
    assign verify_ready=verifying && (state==VERIFY_INPUT || (state==PIPE_VERIFY_INPUT && pipe_ready));
    assign busy = state != IDLE;

    function automatic [31:0] be32(input [31:0] x);
        be32 = {x[7:0], x[15:8], x[23:16], x[31:24]};
    endfunction
    function automatic [4:0] digit(input [7:0] index);
        reg [7:0] checksum_index;
        begin
            checksum_index = index - LEN1;
            digit = 0;
            if (index < LEN1) begin
                digit = {1'b0, value[2][{(index[5:0]^6'd1), 2'b0}+:4]};
            end else begin
                case (checksum_index)
                    0: digit = {1'b0, checksum[11:8]};
                    1: digit = {1'b0, checksum[7:4]};
                    2: digit = {1'b0, checksum[3:0]};
                    default: digit = 0;
                endcase
            end
        end
    endfunction
    // Scalar setup uses the chain digit; batch requests use a digit prepared
    // on the preceding acceptance edge. The checksum loop only visits message
    // digits, so it bypasses the state/index/checksum-digit selection network.
    wire [4:0] shared_digit = digit(chain_cursor);
    wire [3:0] transform_digit = value[2][{(transform_index[5:0] ^ 6'd1), 2'b0}+:4];
    wire [3:0] checksum_increment = ~transform_digit;
`ifndef SYNTHESIS
    always @(posedge clk) begin : debug_checksum_increment
        if (!execution_rst && state == TRANSFORM && descriptor[59:56] == 1) begin
            if (transform_index >= LEN1 || {1'b0, transform_digit} !== digit(transform_index))
                $fatal(1, "checksum loop exceeded message digits");
            if ({1'b0, checksum_increment} !== 5'd15 - digit(transform_index))
                $fatal(1, "checksum nibble complement changed its value");
        end
    end
`endif
    wire [FORS_DIGEST_BITS-1:0] fors_digest = {fors_digest_tail, value[1]};
    wire [FORS_DIGEST_BITS-1:0] fors_bitstream;
    genvar fb;
    generate
        for (fb = 0; fb < FORS_DIGEST_BITS; fb = fb + 1) begin : fors_bit_order
            assign fors_bitstream[fb] = fors_digest[(fb/8)*8+7-(fb%8)];
        end
    endgenerate
    function automatic [9:0] fors_group_offset(input [5:0] group_number);
        begin
            case (FORS_A)
                6: fors_group_offset = ({group_number, 2'b0} + {group_number, 1'b0});
                8: fors_group_offset = {group_number, 3'b0};
                9: fors_group_offset = ({group_number, 3'b0} + group_number);
                12: fors_group_offset = ({group_number, 3'b0} + {group_number, 2'b0});
                default: fors_group_offset = ({group_number, 4'b0} - {group_number, 1'b0});
            endcase
        end
    endfunction
    function automatic [13:0] fors_target(input [9:0] offset);
        reg [13:0] segment;
        begin
            segment = fors_bitstream >> offset;
            // verilog_format: off
            case (FORS_A)
                6: fors_target = {8'd0,segment[0],segment[1],segment[2],segment[3],segment[4],segment[5]};
                8: fors_target = {6'd0,segment[0],segment[1],segment[2],segment[3],segment[4],segment[5],segment[6],segment[7]};
                9: fors_target = {5'd0,segment[0],segment[1],segment[2],segment[3],segment[4],segment[5],segment[6],segment[7],segment[8]};
                12: fors_target = {2'd0,segment[0],segment[1],segment[2],segment[3],segment[4],segment[5],segment[6],segment[7],segment[8],segment[9],segment[10],segment[11]};
                default: fors_target = {segment[0],segment[1],segment[2],segment[3],segment[4],segment[5],segment[6],segment[7],segment[8],segment[9],segment[10],segment[11],segment[12],segment[13]};
            endcase
            // verilog_format: on
        end
    endfunction
    function automatic [63:0] parsed_tree(input [V-1:0] digest);
        reg [63:0] bytes;
        integer j;
        begin
            if (small_signature) begin
                case (node_bytes)
                    16: bytes = {digest[168+:56], 8'd0};
                    24: bytes = {digest[240+:56], 8'd0};
                    default: bytes = {digest[312+:56], 8'd0};
                endcase
            end else
                case (node_bytes)
                    16: bytes = digest[200+:64];
                    24: bytes = digest[264+:64];
                    default: bytes = digest[320+:64];
                endcase
            for (j = 0; j < 8; j = j + 1) parsed_tree[(7-j)*8+:8] = bytes[j*8+:8];
            if (small_signature && node_bytes != 32) parsed_tree[63:54] = 0;
            else if (!small_signature && node_bytes != 32) parsed_tree[63] = 0;
        end
    endfunction
    function automatic [9:0] parsed_leaf(input [V-1:0] digest);
        begin
            if (small_signature) begin
                case (node_bytes)
                    16: parsed_leaf = {1'b0, digest[224], digest[232+:8]};
                    24: parsed_leaf = {1'b0, digest[296], digest[304+:8]};
                    default: parsed_leaf = {2'b0, digest[368+:8]};
                endcase
            end else
                parsed_leaf=node_bytes==16 ? {7'b0,digest[264 +:3]}
                : node_bytes==24 ? {7'b0,digest[328 +:3]} : {6'b0,digest[384 +:4]};
        end
    endfunction
    task automatic fail;
        begin
            error <= 1;
            abort_execution <= 1;
            enter_state(FAILED);
        end
    endtask
    task automatic complete_macro;
        begin
            seq_complete <= 1;
            enter_state(FETCH);
        end
    endtask
    task automatic route_result(input [1:0] source);
        begin
            route_source <= source;
            enter_state(ROUTE);
        end
    endtask
    task automatic start_output(input [255:0] v, input [5:0] length, input state_t ret);
        begin
            emit_value <= v;
            emit_length <= length;
            continuation <= ret;
            enter_state(OUTPUT_CHUNK);
        end
    endtask
    // All slots have completed before this transition. Their capture data
    // stays intact until the final output beat, then the whole batch is free.
    task automatic advance_direct_batch;
        begin
            if (chain_cursor + PIPELINE < endpoint_count) begin
                chain_cursor <= chain_cursor + PIPELINE;
                batch_chain_prefetch <= chain_cursor + INDEX_BITS'(PIPELINE);
                batch_digit_prefetch <= digit(chain_cursor + INDEX_BITS'(PIPELINE));
                pipe_pair <= 0;
                pipe_issue_slot <= 0;
                pipe_done_mask <= 0;
                for (integer q = 0; q < PIPE_BATCH; q = q + 1)
                pipe_expected_mask[q] <= 32'(chain_cursor) + PIPELINE + q < endpoint_count;
                enter_state(PIPE_ISSUE);
            end else begin
                chain_cursor <= endpoint_count - 1'b1;
                enter_state(CHAIN_NEXT);
            end
        end
    endtask
    task automatic start_hash(input [63:0] selected_recipe, input state_t ret);
        begin
            task_recipe <= selected_recipe;
            continuation <= ret;
            enter_state(HASH_ISSUE);
        end
    endtask
    task automatic read_verify_node(input state_t ret);
        begin
            continuation <= ret;
            enter_state(VERIFY_INPUT);
        end
    endtask

    // A response belongs to exactly one writeback phase. Authentication and
    // stack writes intentionally meet in PUSH_NODE; authenticate first, then
    // PUSH_STACK commits the remaining node through this same write port.
    wire write_auth = auth_write;
    wire write_stack = stack_write && !auth_write;
    wire write_fors = (fors_leaves || fors_pipe) && pipe_valid &&
        (fors_leaves || state == FORS_WAIT);
    wire write_ltree = lt_pipe && pipe_valid && state == LT_PIPE_WAIT;
    wire write_direct = direct_writeback_phase && pipe_valid;
    wire write_chain = state == CHAIN_STORE && indexing != 1;
    wire write_scalar_ltree = PIPELINE == 1 && state == LT_STORE;
    wire write_copy = state == LT_COPY;
    wire write_root = root_write;
    wire write_auth_from_ram = write_auth && (state == FORS_AUTH0 || state == FORS_AUTH1);
    wire write_node = write_stack || (write_auth && !write_auth_from_ram);
    wire write_from_ram = write_copy || write_auth_from_ram;
    wire write_response = write_fors || write_ltree || write_direct;
    wire write_result = write_chain || write_scalar_ltree;
    wire [INDEX_BITS-1:0] direct_write_address = pipe_rolling
        ? pipe_chain_index[pipe_tag] : chain_cursor + INDEX_BITS'(pipe_tag);
    // Form a parallel mux from mutually exclusive owners. Grouping identical
    // data sources avoids repeating the 256-bit response and node selectors.
    always_comb begin
        endpoint_write = write_auth || write_stack || write_response ||
            write_result || write_copy || write_root;
        endpoint_address =
            ({INDEX_BITS{write_auth}} & (INDEX_BITS'(AUTH_BASE) + INDEX_BITS'(auth_write_level))) |
            ({INDEX_BITS{write_stack}} & (INDEX_BITS'(STACK_BASE) + INDEX_BITS'(node_level))) |
            ({INDEX_BITS{write_fors}} & (INDEX_BITS'(FORS_SCRATCH) + INDEX_BITS'(fors_offset) + INDEX_BITS'(pipe_tag))) |
            ({INDEX_BITS{write_ltree}} & ((lt_cursor >> 1) + INDEX_BITS'(pipe_tag))) |
            ({INDEX_BITS{write_direct}} & direct_write_address) |
            ({INDEX_BITS{write_chain}} & chain_cursor) |
            ({INDEX_BITS{write_scalar_ltree || write_copy}} & (lt_cursor >> 1)) |
            ({INDEX_BITS{write_root}} & INDEX_BITS'(group_index));
        endpoint_data =
            ({W{write_node}} & node_value) |
            ({W{write_from_ram}} & endpoint_value0) |
            ({W{write_response}} & pipe_response_result) |
            ({W{write_result}} & result[W-1:0]) |
            ({W{write_root}} & route_value[W-1:0]);
    end
`ifndef SYNTHESIS
    // Keep the old priority form as a simulation-only equivalence oracle.
    logic reference_endpoint_write;
    logic [INDEX_BITS-1:0] reference_endpoint_address;
    logic [W-1:0] reference_endpoint_data;
    always_comb begin
        reference_endpoint_write = 0;
        reference_endpoint_address = chain_cursor;
        reference_endpoint_data = result[W-1:0];
        if (auth_write) begin
            reference_endpoint_write = 1;
            reference_endpoint_address = INDEX_BITS'(AUTH_BASE) + INDEX_BITS'(auth_write_level);
            reference_endpoint_data = auth_write_data;
        end else if (stack_write) begin
            reference_endpoint_write = 1;
            reference_endpoint_address = INDEX_BITS'(STACK_BASE) + INDEX_BITS'(node_level);
            reference_endpoint_data = node_value;
        end else if (fors_leaves || fors_pipe) begin
            reference_endpoint_write = pipe_valid && (fors_leaves || state == FORS_WAIT);
            reference_endpoint_address=INDEX_BITS'(FORS_SCRATCH)+INDEX_BITS'(fors_offset)+INDEX_BITS'(pipe_tag);
            reference_endpoint_data = pipe_response_result;
        end else if (lt_pipe) begin
            reference_endpoint_write = pipe_valid && state == LT_PIPE_WAIT;
            reference_endpoint_address = (lt_cursor >> 1) + INDEX_BITS'(pipe_tag);
            reference_endpoint_data = pipe_response_result;
        end else if (pipe_direct && pipe_mode) begin
            reference_endpoint_write = pipe_valid;
            reference_endpoint_address=pipe_rolling ? pipe_chain_index[pipe_tag] : chain_cursor+INDEX_BITS'(pipe_tag);
            reference_endpoint_data = pipe_response_result;
        end else if (state == CHAIN_STORE && indexing != 1) begin
            reference_endpoint_write = 1;
        end else if (PIPELINE == 1 && state == LT_STORE) begin
            reference_endpoint_write = 1;
            reference_endpoint_address = lt_cursor >> 1;
        end else if (state == LT_COPY) begin
            reference_endpoint_write = 1;
            reference_endpoint_address = lt_cursor >> 1;
            reference_endpoint_data = endpoint_value0;
        end else if (root_write) begin
            reference_endpoint_write = 1;
            reference_endpoint_address = INDEX_BITS'(group_index);
            reference_endpoint_data = route_value[W-1:0];
        end
    end

    always @(posedge clk) begin : debug_writeback_ownership
        if (!execution_rst) begin
            if (!$onehot0({write_auth, write_stack, write_fors, write_ltree,
                write_direct, write_chain, write_scalar_ltree, write_copy, write_root}))
                $fatal(1, "multiple workspace write owners");
            if (direct_writeback_phase !== (pipe_mode && pipe_direct &&
                !fors_leaves && !fors_pipe && !lt_pipe))
                $fatal(1, "registered direct writeback ownership differs from phase");
            if (endpoint_write !== reference_endpoint_write ||
                (endpoint_write && (endpoint_address !== reference_endpoint_address ||
                 endpoint_data !== reference_endpoint_data)))
                $fatal(1, "workspace write differs from priority reference");
        end
    end
`endif

    generate
        begin : read_addresses
            logic [INDEX_BITS-1:0] address, adjacent_address, next_address, next_adjacent_address;
            function automatic [INDEX_BITS-1:0] adjacent(input [INDEX_BITS-1:0] selected);
                adjacent = selected == INDEX_BITS'(WORKSPACE_DEPTH - 1)
                    ? INDEX_BITS'(WORKSPACE_DEPTH - 2) : selected + 1'b1;
            endfunction
            // Form each address pair before the state/ready selection. In
            // particular, ready must not cross the full address mux followed
            // by an incrementer before reaching the adjacent-address register.
            wire [INDEX_BITS-1:0] lt_issue_address =
                lt_cursor + ((INDEX_BITS'(pipe_issue_slot) + 1'b1) << 1);
            wire [INDEX_BITS-1:0] lt_next_address = lt_cursor + INDEX_BITS'(2 * PIPELINE);
            wire [INDEX_BITS-1:0] fors_leaf_address = INDEX_BITS'(FORS_SCRATCH)
                + INDEX_BITS'(fors_target_delta ^ 21'd1);
            wire [INDEX_BITS-1:0] fors_auth_address = INDEX_BITS'(FORS_SCRATCH)
                + INDEX_BITS'((fors_target_delta >> 1) ^ 21'd1);
            wire [INDEX_BITS-1:0] fors_issue_offset =
                (INDEX_BITS'(fors_offset) + INDEX_BITS'(pipe_issue_slot) + 1'b1) << 1;
            wire [INDEX_BITS-1:0] fors_next_offset =
                (INDEX_BITS'(fors_offset) + INDEX_BITS'(PIPELINE)) << 1;
            always_comb begin
                next_address = address;
                next_adjacent_address = adjacent_address;
                case (state)
                    REDUCE_SETUP, TREE_INIT, LT_COPY: begin
                        next_address = 0;
                        next_adjacent_address = 1;
                    end
                    PUSH_NODE: begin
                        next_address = node_level == tree_height
                            ? INDEX_BITS'(AUTH_BASE) : INDEX_BITS'(STACK_BASE) + INDEX_BITS'(node_level);
                        next_adjacent_address = node_level == tree_height
                            ? INDEX_BITS'(AUTH_BASE + 1) : INDEX_BITS'(STACK_BASE + 1) + INDEX_BITS'(node_level);
                    end
                    AUTH_OUTPUT: begin
                        next_address = INDEX_BITS'(AUTH_BASE + 1) + INDEX_BITS'(auth_level);
                        next_adjacent_address = INDEX_BITS'(AUTH_BASE + 2) + INDEX_BITS'(auth_level);
                    end
                    HASH_ISSUE, HASH_WAIT: begin
                        next_address = lane_list_next;
                        next_adjacent_address = adjacent(lane_list_next);
                    end
                    LT_PIPE_INIT: begin
                        next_address = {lt_cursor[INDEX_BITS-1:1], 1'b0};
                        next_adjacent_address = {lt_cursor[INDEX_BITS-1:1], 1'b1};
                    end
                    LT_NEXT: if (PIPELINE == 1) begin
                        next_address = 0;
                        next_adjacent_address = 1;
                    end
                    LT_PIPE_ISSUE: if (pipe_ready) begin
                        next_address = lt_issue_address;
                        next_adjacent_address = adjacent(lt_issue_address);
                    end
                    LT_PIPE_WAIT: if (lt_batch_complete) begin
                        if (lt_cursor + 2 * PIPELINE < lt_count) begin
                            next_address = lt_next_address;
                            next_adjacent_address = adjacent(lt_next_address);
                        end else if (lt_count[0]) begin
                            next_address = lt_count - 1'b1;
                            // An odd count minus one is even, including wrap.
                            next_adjacent_address = lt_count;
                        end else begin
                            next_address = 0;
                            next_adjacent_address = 1;
                        end
                    end
                    FORS_LEAF_NEXT: begin
                        next_address = fors_target_group ? fors_leaf_address : INDEX_BITS'(FORS_SCRATCH);
                        next_adjacent_address = fors_target_group ? adjacent(fors_leaf_address) : INDEX_BITS'(FORS_SCRATCH + 1);
                    end
                    FORS_AUTH0, FORS_BEGIN, FORS_AUTH1, FORS_LEVEL: begin
                        next_address = INDEX_BITS'(FORS_SCRATCH);
                        next_adjacent_address = INDEX_BITS'(FORS_SCRATCH + 1);
                    end
                    FORS_ISSUE: if (pipe_ready) begin
                        if (pipe_issue_slot + 1 >= PIPELINE || (pipe_expected_mask >> (pipe_issue_slot + 1)) == 0) begin
                            next_address = INDEX_BITS'(FORS_SCRATCH);
                            next_adjacent_address = INDEX_BITS'(FORS_SCRATCH + 1);
                        end else begin
                            next_address = INDEX_BITS'(FORS_SCRATCH) + fors_issue_offset;
                            // Both FORS wave addresses are even; construct the
                            // low one bit before the ready/state selection.
                            next_adjacent_address = INDEX_BITS'(FORS_SCRATCH + 1) + fors_issue_offset;
                        end
                    end
                    FORS_WAIT: begin
                        if (fors_offset + PIPELINE < fors_outputs) begin
                            next_address = INDEX_BITS'(FORS_SCRATCH) + fors_next_offset;
                            next_adjacent_address = INDEX_BITS'(FORS_SCRATCH + 1) + fors_next_offset;
                        end else if (fors_level) begin
                            next_address = INDEX_BITS'(FORS_SCRATCH);
                            next_adjacent_address = INDEX_BITS'(FORS_SCRATCH + 1);
                        end else begin
                            next_address = fors_target_group ? fors_auth_address : INDEX_BITS'(FORS_SCRATCH);
                            next_adjacent_address = fors_target_group ? adjacent(fors_auth_address) : INDEX_BITS'(FORS_SCRATCH + 1);
                        end
                    end
                    FORS_ROOT_NEXT: begin
                        next_address = INDEX_BITS'(FORS_SCRATCH + 1) + INDEX_BITS'(fors_root_cursor);
                        next_adjacent_address = INDEX_BITS'(FORS_SCRATCH + 2) + INDEX_BITS'(fors_root_cursor);
                    end
                    default: begin end
                endcase
            end
            always_ff @(posedge clk) begin
                if (rst) begin
                    address <= 0;
                    adjacent_address <= 1;
                end else begin
                    address <= next_address;
                    adjacent_address <= next_adjacent_address;
                end
            end
            assign endpoint_read0 = address;
            assign endpoint_read1 = adjacent_address;
        end
    endgenerate

    // Validity is owned by the tree controller; data arrays have no reset.
    // Isolating these writes permits distributed RAM inference.
    wire auth_write=!verifying && macro_flags[1] && ((state==PUSH_NODE && node_below_root && auth_node_match)
        || state==FORS_AUTH0 || state==FORS_AUTH1);
    wire [4:0] auth_write_level=state==FORS_AUTH0 ? 5'd0 : state==FORS_AUTH1 ? 5'd1 : node_level;
    wire [255:0] auth_write_data=state==FORS_AUTH0 || state==FORS_AUTH1 ? endpoint_value0 : node_value;
    wire stack_write=(state==PUSH_NODE || state==PUSH_STACK) && node_below_root && !node_index[0] && !verifying;
`ifndef SYNTHESIS
    initial begin : workspace_capacity
        if (FORS_BATCH > 24 || FORS_SCRATCH <= 35 ||
            FORS_SCRATCH + FORS_BATCH > STACK_BASE || AUTH_BASE + 20 > WORKSPACE_DEPTH)
            $fatal(1, "workspace regions exceed preserved algorithm capacities");
    end
    always @(posedge clk)
        if (!execution_rst) begin
            if (endpoint_write && endpoint_address >= WORKSPACE_DEPTH)
                $fatal(1, "workspace write out of range");
            if (endpoint_read0 >= WORKSPACE_DEPTH || endpoint_read1 >= WORKSPACE_DEPTH)
                $fatal(1, "workspace read out of range");
            if ((lt_pipe && state == LT_PIPE_ISSUE) || (fors_pipe && state != FORS_WAIT))
                if (endpoint_write) $fatal(1, "reduction write before batch inputs accepted");
        end
    always @(posedge clk) begin : debug_target_path
        if (!execution_rst && (state == PUSH_NODE || state == PUSH_STACK ||
            state == PARENT_SETUP || state == PARENT_DONE)) begin
            if (target_at_level !== (target >> node_level))
                $fatal(1, "tree target coordinate is not aligned with node level");
            if (auth_node_match !== (node_index == (target_at_level ^ 21'd1)))
                $fatal(1, "authentication-node match is not aligned with node index");
            if (target_parent_match !== (node_index[20:1] == target_at_level[20:1]))
                $fatal(1, "target-parent match is not aligned with node index");
            if (node_below_root !== (node_level < tree_height))
                $fatal(1, "tree height eligibility is not aligned with node level");
        end
        if (!execution_rst && endpoint_read1 !==
            (endpoint_read0 == INDEX_BITS'(WORKSPACE_DEPTH - 1)
                ? INDEX_BITS'(WORKSPACE_DEPTH - 2) : endpoint_read0 + 1'b1))
            $fatal(1, "registered adjacent workspace address is not aligned");
    end
    // These invariants justify the bounded FORS range and leaf-index logic.
    always @(posedge clk) begin : debug_fors_relative_index
        if (!execution_rst && state == FORS_PICK) begin
            if (fors_base[1:0] != 0 || fors_total == 0 || fors_total > FORS_BATCH)
                $fatal(1, "invalid FORS microgroup geometry");
            if (fors_target_delta !== target - fors_base)
                $fatal(1, "FORS target-relative index changed inside a microgroup");
        end
    end
    // Every state transition prepares these flags on the same edge.
    always @(posedge clk) begin : phase_control_equivalence
        if (!rst) begin
            if (lane_request_active !== (state == HASH_ISSUE))
                $fatal(1, "registered scalar request differs from execution state");
            if (batch_issue_phase !== (PIPELINE > 1 && (state == PIPE_ISSUE ||
                state == LT_PIPE_ISSUE || state == FORS_ISSUE)))
                $fatal(1, "registered batch request differs from execution state");
            if (batch_verify_phase !== (PIPELINE > 1 && state == PIPE_VERIFY_INPUT))
                $fatal(1, "registered batch verify differs from execution state");
            if (pipe_response_accept !== (pipe_mode && state != LT_PIPE_ISSUE &&
                (!fors_pipe || state == FORS_WAIT)))
                $fatal(1, "registered batch response ready differs from execution state");
            if (fors_pipe !== (PIPELINE > 1 &&
                (state == FORS_LEFT || state == FORS_ISSUE || state == FORS_WAIT)))
                $fatal(1, "registered FORS phase differs from execution state");
            if (fors_leaves !== (PIPELINE > 1 && indexing == 1 && !verifying &&
                (state == PIPE_ISSUE || state == PIPE_WAIT)))
                $fatal(1, "registered FORS leaf phase differs from execution state");
            if (lt_pipe !== (PIPELINE > 1 &&
                (state == LT_PIPE_ISSUE || state == LT_PIPE_WAIT)))
                $fatal(1, "registered L-tree phase differs from execution state");
            if (pipe_mode !== (PIPELINE > 1 &&
                (state == PIPE_ISSUE || state == PIPE_WAIT || state == PIPE_VERIFY_INPUT ||
                 state == LT_PIPE_ISSUE || state == LT_PIPE_WAIT || state == FORS_LEFT ||
                 state == FORS_ISSUE || state == FORS_WAIT)))
                $fatal(1, "registered batch mode differs from execution state");
        end
    end
    always @(posedge clk) begin : rolling_allocator_equivalence
        if (!execution_rst && pipe_rolling && pipe_mode) begin
            if (roll_available !== (|roll_free))
                $fatal(1, "prepared rolling availability differs from ownership bitmap");
            if (roll_available) begin
                if (!roll_free[roll_slot])
                    $fatal(1, "prepared rolling slot is still active");
                for (integer j = 0; j < PIPE_BATCH; j++)
                    if (j < roll_slot && roll_free[j])
                        $fatal(1, "prepared rolling slot does not preserve allocation order");
            end
        end
    end
    // Check prepared metadata at acceptance, including rolling reuse and stalls.
    always @(posedge clk) begin : batch_prefetch_equivalence
        if (!execution_rst && state == TREE_INIT && !stateful && descriptor[37:36] == 1)
            if (fors_target_prefetch !== fors_target(fors_group_offset(group_index)))
                $fatal(1, "prefetched FORS target differs at tree initialization");
        if (!execution_rst && PIPELINE > 1 && pipe_selected && pipe_ready &&
            !fors_pipe && !lt_pipe && indexing != 1) begin
            if (batch_chain_index !== (pipe_rolling ? pipe_next_chain :
                chain_cursor + INDEX_BITS'(pipe_issue_slot)))
                $fatal(1, "prefetched chain index differs at acceptance");
            if (batch_digit_prefetch !== digit(pipe_rolling ? pipe_next_chain :
                chain_cursor + INDEX_BITS'(pipe_issue_slot)))
                $fatal(1, "prefetched WOTS digit differs at acceptance");
        end
    end
`endif

    reg [255:0] emit_source;
    always_comb begin
        case (emit_descriptor[59:56])
            0: emit_source = secret_seed;
            1: emit_source = secret_prf;
            2: emit_source = public_seed;
            3: emit_source = value[3][W-1:0];
            4: emit_source = xmss ? value[0] : randomizer;
            5: emit_source = {128'd0, job_identifier};
            6: emit_source = {224'd0, be32(job_index)};
            7: emit_source = be32(emit_descriptor[31:0]);
            default: emit_source = 0;
        endcase
    end

`ifndef SYNTHESIS
    // Diagnostic classification observes the same pre-edge state as the FSM.
    // It does not drive error handling, state transitions, or reset.
    logic [15:0] diagnostic_reason;
    always_comb begin : debug_failure_reason
        diagnostic_reason = 0;
        // verilog_format: off
        case (state)
            IDLE:
            if (job_valid) begin
                if (!valid_profile) diagnostic_reason = 16'h3009;
                else if (decoded_stateful && job_index >= (32'd1 << decoded_height))
                    diagnostic_reason = 16'h3008;
            end
            DECODE: if (macro_op < 1 || macro_op > 5) diagnostic_reason = 16'h3006;
            CHAIN_SETUP:
            if(endpoint_count==0 || endpoint_count>67 ||
                (!standalone_chain && (tree_height>20 || (indexing==1 && tree_height<2))))
                diagnostic_reason = 16'h300a;
            HASH_WAIT: if (lane_valid && lane_error) diagnostic_reason = 16'h3007;
            TRANSFORM: if (descriptor[59:56] != 1 && descriptor[59:56] != 2) diagnostic_reason = 16'h3006;
            TREE_INIT,AUTH_OUTPUT,CHAIN_NEXT,CHAIN_OUTPUT0,CHAIN_STORE,
            DRAIN,EMIT,EMIT_NEXT,FAILED,FETCH,FINISH,
            FORS_AUTH0,FORS_AUTH1,FORS_BEGIN,FORS_ISSUE,FORS_LEAF_NEXT,FORS_LEFT,FORS_LEVEL,FORS_PICK,FORS_PUSH,FORS_ROOT_NEXT,FORS_WAIT,
            HASH_ISSUE,HASH_RESULT,LAUNCH,LEAF_SETUP,LOAD_DESCRIPTOR,
            LT_SETUP,LT_STORE,LT_NEXT,LT_COPY,LT_FINISH,LT_PIPE_INIT,LT_PIPE_ISSUE,LT_PIPE_WAIT,
            MESSAGE,OUTPUT_CHUNK,PARENT_DONE,PARENT_SETUP,
            PIPE_ISSUE,PIPE_LOAD,PIPE_VERIFY_INPUT,PIPE_WAIT,PUSH_NODE,PUSH_STACK,REDUCE_SETUP,
            ROUTE,SF_LEAF,SF_LEAF_DONE,SF_RANDOM,TREE_FINISH,TREE_INIT,
            VERIFY_CHAIN_ADVANCE,VERIFY_CHAIN_INPUT,VERIFY_CHAIN_RUN,VERIFY_INPUT,VERIFY_RANDOM: diagnostic_reason = 0;
            default: diagnostic_reason = 16'h3006;
        endcase
        // verilog_format: on
    end
    always_ff @(posedge clk) begin : debug_statistics
        if (rst) begin
            cycles <= 0;
            hash_base <= 0;
            permutation_base <= 0;
            error_code <= 0;
        end else begin
            if (state == IDLE && job_valid) begin
                cycles <= 0;
                hash_base <= total_hashes;
                permutation_base <= total_permutations;
                error_code <= 0;
            end else if (state != IDLE && state != FAILED) cycles <= cycles + 1'b1;
            if (diagnostic_reason != 0) error_code <= diagnostic_reason;
        end
    end
`endif

    always_ff @(posedge clk) begin
        if (rst) begin
            enter_state(IDLE);
            done <= 0;
            error <= 0;

            abort_execution <= 0;
            seq_start <= 0;
            seq_complete <= 0;
            stateful <= 0;
            xmss <= 0;
            small_signature <= 0;
            stateful_height <= 10;
            profile_code <= 0;
            node_bytes <= 16;
            operation <= 0;
            scalar_tree <= 0;
            scalar_leaf <= 0;
            verify_pass <= 0;
            continuation <= IDLE;
            macro_op <= 0;
            macro_desc <= 0;
            macro_route <= 0;
            macro_flags <= 0;
            task_chain <= 0;
            task_capture <= 0;

            layer <= 0;
            task_recipe <= 0;
            task_step <= 0;
            message_received <= 0;
            lt_count <= 0;
            lt_cursor <= 0;
            lt_level <= 0;
            fors_total <= 0;
            fors_offset <= 0;
            fors_root_cursor <= 0;
            fors_level <= 0;
            fors_roots_pending <= 0;
            fors_base <= 0;
            fors_target_delta <= 0;
            fors_digest_offset <= 0;
            fors_target_prefetch <= 0;
            pipe_cache_valid <= 0;
            pipe_batch_used <= 0;
            pipe_pair <= 0;
            pipe_issue_slot <= 0;
            pipe_rolling <= 0;
            pipe_active <= 0;
            roll_slot <= 0;
            roll_available <= 1;
            pipe_next_chain <= 0;
            pipe_completed <= 0;
            batch_chain_prefetch <= 0;
            batch_digit_prefetch <= 0;
            pipe_done_mask <= 0;
            pipe_expected_mask <= 0;

            task_steps <= 0;
            task_capture_after <= 0;
            task_leaf <= 0;
            task_a <= 0;
            task_b <= 0;
        end else begin
            done <= 0;
            seq_start <= 0;
            seq_complete <= 0;
            abort_execution <= 0;

            if (pipe_rolling && pipe_mode) begin
                roll_slot <= roll_next_slot;
                roll_available <= |roll_next_free;
                if (pipe_valid) begin
                    pipe_active[pipe_tag] <= 0;
                    pipe_completed <= pipe_completed + 1'b1;
                end
                if (pipe_selected && pipe_ready) begin
                    pipe_active[issue_slot] <= 1;
                    pipe_chain_index[issue_slot] <= pipe_next_chain;
                    pipe_next_chain <= pipe_next_chain + 1'b1;
                end
            end
            if (pipe_mode) begin
                if(pipe_valid && pipe_response_accept)begin
                    pipe_done_mask[pipe_tag] <= 1;
                    if(!lt_pipe && pipe_direct && (pipe_rolling ? pipe_chain_index[pipe_tag]==0 : chain_cursor==0 && pipe_tag==0) && standalone_chain)
                        node_value <= pipe_response_result;
                end
            end
            case (state)
                IDLE:
                if (job_valid) begin
                    error <= 0;
                    operation <= job_operation;
                    stateful <= decoded_stateful;
                    xmss <= decoded_xmss;
                    stateful_height <= decoded_height;
                    small_signature <= !decoded_stateful && config_code[2];
                    profile_code <= config_code[1:0];
                    node_bytes<=decoded_stateful ? 6'd32 : config_code[1:0]==0 ? 6'd16 : config_code[1:0]==1 ? 6'd24 : 6'd32;
                    verify_pass <= 0;
                    message_length <= job_message_length;
                    message_received <= 0;
                    scalar_tree <= 0;
                    scalar_leaf <= decoded_stateful ? job_index[19:0] : 0;
                    layer <= 0;
                    group_index <= 0;

                    value[3] <= job_public_root;
                    if (!valid_profile) fail();
                    else if (decoded_stateful && job_index >= (32'd1 << decoded_height)) fail();
                    else if (job_operation && job_message_length != 0) begin
                        enter_state(MESSAGE);
                    end else begin
                        enter_state(LAUNCH);
                    end
                end
                MESSAGE:
                if (message_valid) begin
                    // The offline-validated private ROM stream always supplies full
                    // eight-byte beats; its last word is already zero padded.
                    message_buffer[{message_received[6:3], 6'b0}+:64] <= message_data;
                    message_received <= message_received + 7'd8;
                    if (message_received + 7'd8 >= message_length) enter_state(LAUNCH);
                end
                LAUNCH:
                if (seq_ready) begin
                    seq_start <= 1;
                    enter_state(FETCH);
                end
                FETCH: begin
                    if (seq_done) begin
                        if (verifying) begin
                            verify_pass <= value[2][127:0]==job_public_root[127:0]
                                    && (node_bytes==16 || value[2][191:128]==job_public_root[191:128])
                                    && (node_bytes!=32 || value[2][255:192]==job_public_root[255:192]);
                            enter_state(DRAIN);
                        end else enter_state(DRAIN);
                    end else if (cmd_valid) begin
                        macro_op <= cmd[47:44];
                        macro_desc <= cmd[43:36];
                        macro_route <= cmd[35:28];
                        macro_flags <= cmd[27:24];
                        layer <= cmd[23:19];
                        group_index <= cmd[18:13];
                        task_chain <= 0;
                        task_capture <= 0;
                        pipe_cache_valid <= 0;
                        pipe_batch_used <= 0;
                        task_steps <= 0;
                        enter_state(LOAD_DESCRIPTOR);
                    end
                end
                LOAD_DESCRIPTOR: begin
                    saved_descriptor <= descriptor_data[63:0];
                    // Group coordinates already settled in FETCH. Split the
                    // offset arithmetic from the digest selector using these
                    // existing descriptor/decode cycles; TREE_INIT never waits.
                    fors_digest_offset <= fors_group_offset(group_index);
                    enter_state(DECODE);
                end
                DECODE: begin
                    fors_target_prefetch <= fors_target(fors_digest_offset);
                    case (macro_op)
                        1: begin
                            task_leaf <= scalar_leaf;
                            task_a <= 0;
                            task_b <= 0;
                            // The sign program starts with PRF_msg. Verification
                            // supplies that R as the first external node.
                            if(verifying && stateful && (saved_descriptor[59:56]==5 || saved_descriptor[59:56]==11))
                                read_verify_node(SF_RANDOM);
                            else if (verifying && saved_descriptor[59:56] == 3)
                                read_verify_node(VERIFY_RANDOM);
                            else start_hash(saved_descriptor, HASH_RESULT);
                        end
                        2: begin
                            standalone_chain <= 1;
                            indexing <= 0;
                            leaf_cursor <= stateful ? job_index[19:0] : 0;
                            target <= stateful ? job_index[19:0] : 0;
                            target_at_level <= stateful ? job_index[19:0] : 0;
                            chain_cursor <= 0;
                            endpoint_count <= descriptor[27:20];
                            saved_chain_descriptor <= descriptor;
                            enter_state(CHAIN_SETUP);
                        end
                        3: enter_state(TREE_INIT);
                        4: begin
                            checksum <= 0;
                            transform_index <= 0;
                            enter_state(TRANSFORM);
                        end
                        5:
                        if (verifying && stateful) complete_macro();
                        else begin
                            emit_base   <= descriptor[59:52];
                            emit_count  <= descriptor[51:48];
                            emit_cursor <= 0;
                            enter_state(EMIT);
                        end
                        default: fail();
                    endcase
                end
                TREE_INIT: begin
                    fors_roots_pending <= 0;
                    pipe_cache_valid <= 0;
                    pipe_batch_used <= 0;
                    saved_chain_descriptor <= descriptor_data[63:0];

                    parent_id <= descriptor[51:44];
                    tree_height <= {descriptor[39], descriptor[43:40]};
                    indexing <= descriptor[33:32];
                    standalone_chain <= 0;
                    target <= tree_target;
                    target_at_level <= tree_target;
                    auth_node_match <= {1'b0, job_index[19:0]} == (tree_target ^ 21'd1);
                    target_parent_match <= {1'b0, job_index[19:1]} == tree_target[20:1];
                    node_below_root <= {descriptor[39], descriptor[43:40]} != 0;
                    leaf_cursor <= verifying ? scalar_leaf : 0;
                    chain_cursor <= 0;
                    node_level <= 0;
                    auth_level <= 0;
                    endpoint_count <= descriptor_data[27:20];
                    if (stateful && verifying) begin
                        node_value <= value[2];
                        node_index <= job_index[19:0];
                        enter_state(PUSH_NODE);
                    end else enter_state(CHAIN_SETUP);
                end
                CHAIN_SETUP: begin
                    // This setup edge already precedes every new chain batch.
                    // The prefetched index and digit remain stable on stalls.
                    batch_chain_prefetch <= chain_cursor;
                    batch_digit_prefetch <= digit(chain_cursor);
                    if(endpoint_count==0 || endpoint_count>67 || (!standalone_chain && (tree_height>20 || (indexing==1 && tree_height<2))))
                        fail();
                    else begin
                        if (PIPELINE > 1 && indexing == 1 && !verifying) begin
                            fors_base <= leaf_cursor;
                            fors_target_delta <= target - leaf_cursor;
                            fors_offset <= 0;
                            fors_roots_pending <= 0;
                            fors_total<=((21'd1<<tree_height)-leaf_cursor)<FORS_BATCH ? 5'((21'd1<<tree_height)-leaf_cursor) : 5'(FORS_BATCH);
                        end
                        if (PIPELINE > 1 && !pipe_cache_valid) begin
                            pipe_rolling<=pipe_direct && !(macro_flags[0] && leaf_cursor==target);
                            pipe_active <= 0;
                            roll_slot <= 0;
                            roll_available <= 1;
                            pipe_next_chain <= chain_cursor;
                            pipe_completed <= 0;
                        end
                        if (stateful && PIPELINE > 1) begin
                            if (pipe_cache_valid) begin
                                pipe_pair <= pipe_pair + 1'b1;
                                enter_state(PIPE_LOAD);
                            end else begin
                                pipe_pair <= 0;
                                pipe_issue_slot <= 0;
                                pipe_done_mask <= 0;
                                for (integer q = 0; q < PIPE_BATCH; q = q + 1)
                                pipe_expected_mask[q] <= 32'(chain_cursor) + q < endpoint_count;
                                pipe_seed_domain <= descriptor_data[55:48];
                                pipe_step_domain <= descriptor_data[119:112];
                                enter_state(verifying ? PIPE_VERIFY_INPUT : PIPE_ISSUE);
                            end
                        end else if (verifying) begin
                            task_chain <= 0;
                            task_capture <= 0;
                            task_step <= descriptor_data[127:64];
                            task_steps <= 0;
                            task_leaf <= scalar_leaf;
                            task_a <= indexing == 1 ? 0 : chain_cursor;
                            task_b <= indexing == 1 ? fors_chain_address : 21'(shared_digit);
                            read_verify_node(VERIFY_CHAIN_INPUT);
                        end else if(!stateful && PIPELINE>1 && descriptor_data[59:56]==1 && descriptor_data[123:120]==2)begin
                            if (pipe_cache_valid) begin
                                pipe_pair <= pipe_pair + 1'b1;
                                enter_state(PIPE_LOAD);
                            end else begin
                                pipe_pair <= 0;
                                pipe_issue_slot <= 0;
                                pipe_done_mask <= 0;
                                for (integer q = 0; q < PIPE_BATCH; q = q + 1)
                                pipe_expected_mask[q]<=indexing==1 ? (q<FORS_BATCH && 32'(leaf_cursor)+q < (32'd1<<tree_height))
                                    : (32'(chain_cursor)+q < endpoint_count);
                                pipe_seed_domain <= descriptor_data[55:48];
                                pipe_step_domain <= descriptor_data[119:112];
                                enter_state(PIPE_ISSUE);
                            end
                        end else begin
                            pipe_batch_used <= 0;
                            task_chain <= 1;
                            task_step <= descriptor_data[127:64];

                            task_capture<=(indexing==1 ? leaf_cursor==target : leaf_cursor==target) && macro_flags[0];
                            task_leaf <= indexing == 1 ? scalar_leaf : leaf_cursor;
                            task_a <= indexing == 1 ? 0 : chain_cursor;
                            task_b <= indexing == 1 ? fors_chain_address : 21'd0;
                            task_steps<=(sign_only || (macro_flags[3] && leaf_cursor==target))
                            ? shared_digit : chain_descriptor[19:15];
                            task_capture_after <= indexing == 1 ? 0 : shared_digit;
                            start_hash(descriptor_data[63:0], CHAIN_STORE);
                        end
                    end
                end
                PIPE_ISSUE: begin
                    if ((pipe_rolling && pipe_selected && pipe_ready) ||
                        (!pipe_rolling && (!pipe_expected_mask[pipe_issue_slot] || pipe_ready))) begin
                        batch_chain_prefetch <= batch_chain_index + 1'b1;
                        batch_digit_prefetch <= digit(batch_chain_index + INDEX_BITS'(1));
                    end
                    if (pipe_rolling) begin
                        if (pipe_completed >= endpoint_count) begin
                            pipe_rolling <= 0;
                            pipe_batch_used <= 1;
                            pipe_cache_valid <= 0;
                            chain_cursor <= endpoint_count - 1'b1;
                            enter_state(CHAIN_NEXT);
                        end
                    end else if (!pipe_expected_mask[pipe_issue_slot] || pipe_ready) begin
                        if(pipe_issue_slot+1>=PIPELINE ||
                           (pipe_direct && (pipe_expected_mask>>(pipe_issue_slot+1))==0))
                            enter_state(PIPE_WAIT);
                        else pipe_issue_slot <= pipe_issue_slot + 1'b1;
                    end
                end
                PIPE_VERIFY_INPUT:
                if (verify_valid && pipe_ready) begin
                    batch_chain_prefetch <= batch_chain_index + 1'b1;
                    batch_digit_prefetch <= digit(batch_chain_index + INDEX_BITS'(1));
                    if(pipe_issue_slot+1>=PIPELINE || (pipe_expected_mask>>(pipe_issue_slot+1))==0)
                        enter_state(PIPE_WAIT);
                    else pipe_issue_slot <= pipe_issue_slot + 1'b1;
                end
                PIPE_WAIT:
                if ((pipe_done_mask & pipe_expected_mask) == pipe_expected_mask) begin
                    if (pipe_direct) begin
                        pipe_cache_valid <= 0;
                        pipe_batch_used <= 1;
                        pipe_pair <= 0;
                        if (macro_flags[0] && leaf_cursor == target) begin
                            start_output(pipe_read_capture, node_bytes, PIPE_CAPTURE_NEXT);
                            pipe_pair <= 1;
                        end else advance_direct_batch();
                    end else if (indexing == 1 && !verifying) begin
                        pipe_cache_valid <= 0;
                        pipe_batch_used  <= 1;
                        enter_state(FORS_PICK);
                    end else enter_state(PIPE_LOAD);
                end
                FORS_PICK: begin
                    if (fors_target_wave && macro_flags[0])
                        start_output(pipe_read_capture, node_bytes, FORS_LEAF_NEXT);
                    else enter_state(FORS_LEAF_NEXT);
                end
                FORS_LEAF_NEXT: begin
                    if (fors_offset + PIPELINE < fors_total) begin
                        fors_offset   <= fors_offset + 5'(PIPELINE);
                        pipe_issue_slot <= 0;
                        pipe_done_mask  <= 0;
                        for (integer q = 0; q < PIPE_BATCH; q++)
                        pipe_expected_mask[q] <= 32'(fors_offset) + PIPELINE + q < fors_total;
                        enter_state(PIPE_ISSUE);
                    end else if (fors_target_group) enter_state(FORS_AUTH0);
                    else enter_state(FORS_BEGIN);
                end
                FORS_AUTH0: enter_state(FORS_BEGIN);
                FORS_BEGIN: begin
                    fors_level <= 0;
                    fors_offset <= 0;
                    pipe_issue_slot <= 0;
                    pipe_done_mask <= 0;
                    for (integer q = 0; q < PIPE_BATCH; q++)
                    pipe_expected_mask[q] <= q < (fors_total >> 1);
                    pipe_seed_domain <= 3;
                    pipe_step_domain <= 3;
                    enter_state(FORS_LEFT);
                end
                FORS_LEFT: enter_state(FORS_ISSUE);
                FORS_ISSUE:
                if (pipe_ready) begin
                    if(pipe_issue_slot+1>=PIPELINE || (pipe_expected_mask>>(pipe_issue_slot+1))==0)
                        enter_state(FORS_WAIT);
                    else begin
                        pipe_issue_slot <= pipe_issue_slot + 1'b1;
                    end
                end
                FORS_WAIT:
                if(lt_batch_complete)begin
                    if (fors_offset + PIPELINE < fors_outputs) begin
                        fors_offset   <= fors_offset + 5'(PIPELINE);
                        pipe_issue_slot <= 0;
                        pipe_done_mask  <= 0;
                        for (integer q = 0; q < PIPE_BATCH; q++)
                        pipe_expected_mask[q] <= 32'(fors_offset) + PIPELINE + q < fors_outputs;
                        enter_state(FORS_LEFT);
                    end else if (fors_level) begin
                        fors_root_cursor <= 0;
                        enter_state(FORS_PUSH);
                    end else enter_state(fors_target_group ? FORS_AUTH1 : FORS_LEVEL);
                end
                FORS_AUTH1: enter_state(FORS_LEVEL);
                FORS_LEVEL: begin
                    fors_level <= 1;
                    fors_offset <= 0;
                    pipe_issue_slot <= 0;
                    pipe_done_mask <= 0;
                    for (integer q = 0; q < PIPE_BATCH; q++)
                    pipe_expected_mask[q] <= q < (fors_total >> 2);
                    enter_state(FORS_LEFT);
                end
                FORS_PUSH: begin
                    node_value <= endpoint_value0;
                    node_level <= 2;
                    target_at_level <= target >> 2;
                    auth_node_match <= fors_root_index == ((target >> 2) ^ 21'd1);
                    target_parent_match <= fors_root_index[20:1] == {2'b0, target[20:3]};
                    node_below_root <= 5'd2 < tree_height;
                    node_index <= fors_root_index;
                    leaf_cursor <= {fors_root_index[18:0], 2'b11};
                    fors_roots_pending <= 1;
                    pipe_cache_valid <= 0;
                    pipe_batch_used <= 0;
                    enter_state(PUSH_NODE);
                end
                FORS_ROOT_NEXT: begin
                    if (fors_root_cursor + 1 < (fors_total >> 2)) begin
                        fors_root_cursor <= fors_root_cursor + 1'b1;
                        enter_state(FORS_PUSH);
                    end else begin
                        fors_roots_pending <= 0;
                        leaf_cursor <= fors_base + 21'(fors_total);
                        chain_cursor <= 0;
                        enter_state(CHAIN_SETUP);
                    end
                end
                PIPE_LOAD: begin
                    pipe_batch_used <= 1;
                    pipe_cache_valid<=pipe_pair+1<PIPELINE && ((pipe_expected_mask>>(pipe_pair+1))!=0);
                    result <= {{(V - W) {1'b0}}, pipe_read_result};
                    enter_state(CHAIN_STORE);
                end
                CHAIN_STORE: begin
                    if (standalone_chain && chain_cursor == 0) node_value <= result[W-1:0];
                    task_chain <= 0;
                    if (sign_only || (!verifying && macro_flags[0] && leaf_cursor == target))
                        enter_state(CHAIN_OUTPUT0);
                    else enter_state(CHAIN_NEXT);
                end
                CHAIN_OUTPUT0:
                start_output(sign_only ? result[W-1:0] : selected_capture, node_bytes, CHAIN_NEXT);
                CHAIN_NEXT: begin
                    if (indexing != 1 && chain_cursor + 1 < endpoint_count) begin
                        chain_cursor <= chain_cursor + 1;
                        enter_state(CHAIN_SETUP);
                    end else if (sign_only) complete_macro();
                    else if (stateful && chain_descriptor[13:12] == 2) begin
                        lt_count  <= endpoint_count;
                        lt_cursor <= 0;
                        lt_level  <= 0;
                        enter_state(LT_PIPE_INIT);
                    end else if (standalone_chain && chain_descriptor[13:12] == 0)
                        route_result(ROUTE_NODE);
                    else if (!verifying && macro_flags[3] && leaf_cursor == target) begin
                        node_value <= 0;
                        node_level <= 0;
                        target_at_level <= target;
                        auth_node_match <= leaf_cursor == (target ^ 21'd1);
                        target_parent_match <= leaf_cursor[20:1] == target[20:1];
                        node_below_root <= tree_height != 0;
                        node_index <= leaf_cursor;
                        enter_state(PUSH_NODE);
                    end else if (chain_descriptor[13:12] == 0) begin
                        node_value <= result[W-1:0];
                        node_level <= 0;
                        target_at_level <= target;
                        auth_node_match <= leaf_cursor == (target ^ 21'd1);
                        target_parent_match <= leaf_cursor[20:1] == target[20:1];
                        node_below_root <= tree_height != 0;
                        node_index <= leaf_cursor;
                        enter_state(PUSH_NODE);
                    end else begin
                        enter_state(REDUCE_SETUP);
                    end
                end
                REDUCE_SETUP: begin
                    task_chain <= 0;
                    task_capture <= 0;
                    task_steps <= 0;
                    task_leaf <= leaf_cursor;
                    task_a <= 0;
                    task_b <= 0;
                    start_hash(descriptor_data[63:0], stateful ? SF_LEAF : LEAF_SETUP);
                end
                LT_PIPE_INIT: begin
                    pipe_rolling <= 0;
                    if (lt_cursor + 1 >= lt_count) enter_state(LT_COPY);
                    else if (PIPELINE == 1) enter_state(LT_SETUP);
                    else begin
                        pipe_issue_slot  <= 0;
                        pipe_done_mask   <= 0;
                        pipe_seed_domain <= descriptor_data[55:48];
                        pipe_step_domain <= descriptor_data[55:48];
                        for (integer q = 0; q < PIPE_BATCH; q++)
                        pipe_expected_mask[q] <= 32'(lt_cursor) + 2 * q + 1 < lt_count;
                        enter_state(LT_PIPE_ISSUE);
                    end
                end
                LT_PIPE_ISSUE:
                if (pipe_ready) begin
                    if(pipe_issue_slot+1>=PIPELINE || (pipe_expected_mask>>(pipe_issue_slot+1))==0)
                        enter_state(LT_PIPE_WAIT);
                    else pipe_issue_slot <= pipe_issue_slot + 1'b1;
                end
                // The last response or odd-tail copy commits on this edge.
                // Both use the same layer advance; INIT/COPY/FINISH observes
                // the committed RAM value without an extra advance cycle.
                LT_PIPE_WAIT, LT_COPY: if (PIPELINE == 1 && state == LT_COPY) enter_state(LT_NEXT);
                else if (state == LT_COPY || lt_batch_complete) begin
                    if (state != LT_COPY && lt_cursor + 2 * PIPELINE < lt_count) begin
                        lt_cursor <= lt_cursor + 2 * PIPELINE;
                        enter_state(LT_PIPE_INIT);
                    end else if (state != LT_COPY && lt_count[0]) begin
                        lt_cursor <= lt_count - 1'b1;
                        enter_state(LT_COPY);
                    end else if (lt_count <= 2) enter_state(LT_FINISH);
                    else begin
                        lt_count  <= (lt_count + 1) >> 1;
                        lt_cursor <= 0;
                        lt_level  <= lt_level + 1'b1;
                        enter_state(LT_PIPE_INIT);
                    end
                end
                LT_SETUP: if (PIPELINE == 1) begin
                    task_chain <= 0;
                    task_capture <= 0;
                    task_steps <= 0;
                    task_leaf <= leaf_cursor;
                    task_a <= {4'd0, lt_level};
                    task_b <= 21'(lt_cursor >> 1);
                    result <= {{(V - W) {1'b0}}, endpoint_value0};
                    node_value <= endpoint_value1;
                    start_hash(descriptor_data[63:0], LT_STORE);
                end else fail();
                LT_STORE: if (PIPELINE == 1) enter_state(LT_NEXT);
                else fail();
                LT_NEXT: if (PIPELINE == 1) begin
                    if (lt_cursor + 2 < lt_count) begin
                        lt_cursor <= lt_cursor + 2;
                        enter_state(LT_PIPE_INIT);
                    end else if (lt_count <= 2) enter_state(LT_FINISH);
                    else begin
                        lt_count <= (lt_count + 1) >> 1;
                        lt_cursor <= 0;
                        lt_level <= lt_level + 1'b1;
                        enter_state(LT_PIPE_INIT);
                    end
                end else fail();
                LT_FINISH: begin
                    node_value <= endpoint_value0;
                    if (verifying && standalone_chain) begin
                        value[2] <= endpoint_value0;
                        complete_macro();
                    end else begin
                        node_index <= leaf_cursor;
                        node_level <= 0;
                        target_at_level <= target;
                        auth_node_match <= leaf_cursor == (target ^ 21'd1);
                        target_parent_match <= leaf_cursor[20:1] == target[20:1];
                        node_below_root <= tree_height != 0;
                        enter_state(PUSH_NODE);
                    end
                end
                SF_LEAF: begin
                    task_chain <= 0;
                    task_capture <= 0;
                    task_steps <= 0;
                    task_leaf <= leaf_cursor;
                    task_a <= 0;
                    task_b <= (21'd1 << stateful_height) + leaf_cursor;
                    start_hash(descriptor_data[63:0], SF_LEAF_DONE);
                end
                SF_LEAF_DONE: begin
                    node_value <= result[W-1:0];
                    if (verifying && standalone_chain) begin
                        value[2] <= result[W-1:0];
                        complete_macro();
                    end else begin
                        node_index <= leaf_cursor;
                        node_level <= 0;
                        target_at_level <= target;
                        auth_node_match <= leaf_cursor == (target ^ 21'd1);
                        target_parent_match <= leaf_cursor[20:1] == target[20:1];
                        node_below_root <= tree_height != 0;
                        enter_state(PUSH_NODE);
                    end
                end
                SF_RANDOM: begin
                    value[0] <= emit_value;
                    if (xmss) complete_macro();
                    else start_hash(saved_descriptor, HASH_RESULT);
                end
                LEAF_SETUP:
                if (standalone_chain) route_result(ROUTE_HASH);
                else begin
                    node_value <= result[W-1:0];
                    node_level <= 0;
                    target_at_level <= target;
                    auth_node_match <= (verifying ? target : leaf_cursor) == (target ^ 21'd1);
                    target_parent_match <= verifying || leaf_cursor[20:1] == target[20:1];
                    node_below_root <= tree_height != 0;
                    node_index <= verifying ? target : leaf_cursor;
                    enter_state(PUSH_NODE);
                end
                PUSH_NODE, PUSH_STACK: begin
                    if (state == PUSH_NODE && auth_write && stack_write) enter_state(PUSH_STACK);
                    else begin
                        if (node_level == tree_height) begin
                            auth_level <= 0;
                            if (!verifying && macro_flags[1]) enter_state(AUTH_OUTPUT);
                            else enter_state(TREE_FINISH);
                        end else if (verifying) read_verify_node(PARENT_SETUP);
                        else if (node_index[0]) enter_state(PARENT_SETUP);
                        else begin
                            if (fors_roots_pending) enter_state(FORS_ROOT_NEXT);
                            else begin
                                leaf_cursor  <= leaf_cursor + 1'b1;
                                chain_cursor <= 0;
                                enter_state(CHAIN_SETUP);
                            end
                        end
                    end
                end
                PARENT_SETUP: begin
                    if(!verifying && macro_flags[3] && target_parent_match) begin
                        node_value <= 0;
                        node_index <= node_index >> 1;
                        node_level <= node_level + 1'b1;
                        target_at_level <= target_at_level >> 1;
                        auth_node_match <= (node_index >> 1) == ((target_at_level >> 1) ^ 21'd1);
                        target_parent_match <= node_index[20:2] == target_at_level[20:2];
                        node_below_root <= node_level + 5'd1 < tree_height;
                        enter_state(PUSH_NODE);
                    end else begin
                        task_chain <= 0;
                        task_capture <= 0;
                        task_steps <= 0;
                        task_leaf <= indexing == 1 ? scalar_leaf : 0;
                        task_a <= descriptor_data[59:56] == 8 ? node_level : node_level + 1'b1;
                        task_b <= parent_address;
                        result[W-1:0]<=verifying ? (node_index[0] ? emit_value : node_value) : endpoint_value0;
                        start_hash(descriptor_data[63:0], PARENT_DONE);
                    end
                end
                PARENT_DONE: begin
                    node_value <= result[W-1:0];
                    node_index <= node_index >> 1;
                    node_level <= node_level + 1'b1;
                    target_at_level <= target_at_level >> 1;
                    auth_node_match <= (node_index >> 1) == ((target_at_level >> 1) ^ 21'd1);
                    target_parent_match <= node_index[20:2] == target_at_level[20:2];
                    node_below_root <= node_level + 5'd1 < tree_height;
                    enter_state(PUSH_NODE);
                end
                AUTH_OUTPUT: begin
                    if (auth_level < tree_height) begin
                        start_output(endpoint_value0, node_bytes, AUTH_OUTPUT);
                        auth_level <= auth_level + 1'b1;
                    end else enter_state(TREE_FINISH);
                end
                TREE_FINISH: begin
                    if (stateful && verifying) value[2] <= node_value;
                    route_result(!verifying && macro_flags[3] ? ROUTE_SAVED : ROUTE_NODE);
                end
                HASH_ISSUE: if (lane_ready) enter_state(HASH_WAIT);
                HASH_WAIT:
                if (lane_valid) begin
                    result <= lane_value;
                    if (lane_error) fail();
                    else enter_state(continuation);
                end
                HASH_RESULT: route_result(ROUTE_HASH);
                ROUTE: begin
                    if (macro_route == 0) complete_macro();
                    else begin
                        if (!route_descriptor[53]) begin
                            value[route_descriptor[57:56]] <= route_value[W-1:0];
                            if (route_descriptor[57:56] == 1)
                                fors_digest_tail <= route_value[FORS_DIGEST_BITS-1:W];
                        end
                        if (route_descriptor[54]) begin
                            scalar_tree <= parsed_tree(route_value);
                            scalar_leaf <= parsed_leaf(route_value);
                        end
                        if (!verifying && route_descriptor[55])
                            start_output(route_value[W-1:0], node_bytes, FETCH);
                        else enter_state(FETCH);
                        seq_complete <= 1;
                    end
                end
                TRANSFORM: begin
                    if (descriptor[59:56] == 2) begin
                        scalar_leaf <= scalar_tree & ((1 << descriptor[43:40]) - 1);
                        scalar_tree <= scalar_tree >> descriptor[43:40];
                        complete_macro();
                    end else if (descriptor[59:56] == 1) begin
                        checksum <= checksum + {8'd0, checksum_increment};
                        if (transform_index + 1 == LEN1) complete_macro();
                        else transform_index <= transform_index + 1'b1;
                    end else fail();
                end
                EMIT: begin
                    start_output(emit_source, emit_descriptor[53:48], EMIT_NEXT);
                end
                EMIT_NEXT: begin
                    if (emit_cursor + 1 < emit_count) begin
                        emit_cursor <= emit_cursor + 1'b1;
                        enter_state(EMIT);
                    end else complete_macro();
                end
                VERIFY_INPUT:
                if (verify_valid) begin
                    emit_value <= verify_data;
                    enter_state(continuation);
                end
                VERIFY_RANDOM: route_result(ROUTE_EMIT);
                VERIFY_CHAIN_INPUT: begin
                    // A WOTS digit of 15 already is an endpoint: zero hashes.
                    result <= {{(V - W) {1'b0}}, emit_value};
                    if (indexing == 1) start_hash(task_step, LEAF_SETUP);
                    else enter_state(VERIFY_CHAIN_RUN);
                end
                VERIFY_CHAIN_RUN: begin
                    if (!verify_step_needed) begin
                        enter_state(CHAIN_STORE);
                    end else start_hash(descriptor_data[63:0], VERIFY_CHAIN_ADVANCE);
                end
                VERIFY_CHAIN_ADVANCE: begin
                    task_b <= {17'd0, task_b[3:0] + 4'd1};
                    enter_state(VERIFY_CHAIN_RUN);
                end
                OUTPUT_CHUNK: begin
                    if (pipe_direct && continuation == PIPE_CAPTURE_NEXT) begin
                        if (pipe_pair < PIPELINE && (pipe_expected_mask >> pipe_pair) != 0) begin
                            emit_value <= pipe_read_capture;
                            pipe_pair  <= pipe_pair + 1'b1;
                        end else advance_direct_batch();
                    end else enter_state(continuation);
                end
                DRAIN: enter_state(FINISH);
                FINISH: begin
                    done <= 1;
                    enter_state(IDLE);
                end
                FAILED: enter_state(IDLE);
                default: fail();
            endcase
        end
    end
endmodule
`default_nettype wire
