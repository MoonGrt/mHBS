`timescale 1ns/1ps
`default_nettype none

// Runtime-selected three-family integration top.  This convergence milestone
// centralizes the public contract and stateful cache lifetime and gives the
// SLH and stateful frontends one shared pair of physical Keccak lanes.  The
// One physical program ROM and sequencer now drive both frontends.  Descriptor
// prefetch and the two materializer FSMs are still being converged; until that
// work passes its PPA gates this top is not the production replacement for the
// reference products.
module micro_hbs_unified_top #(
    parameter integer UNROLL = 2,
    parameter integer MAX_MESSAGE_BYTES = 87,
    parameter bit PROFILE_ENABLE = 1'b0,
    parameter bit SWAP_PHYSICAL_LANES = 1'b0
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         job_valid,
    output wire         job_ready,
    input  wire [1:0]   job_algorithm,
    input  wire [1:0]   job_operation,
    input  wire [31:0]  job_message_length,
    input  wire [10:0]  job_initial_q,
    input  wire [255:0] job_secret_seed,
    input  wire [255:0] job_secret_prf,
    input  wire [255:0] job_public_seed,
    input  wire [255:0] job_public_root,
    input  wire [255:0] job_randomizer,
    input  wire [127:0] job_identifier,
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
    output wire [31:0]  hash_contexts,
    output wire [31:0]  keccak_permutations,
    output wire [31:0]  lane0_active_cycles,
    output wire [31:0]  lane1_active_cycles,
    output wire         tree_cache_valid
);
    localparam logic [1:0] ALG_SLH  = 2'd0;
    localparam logic [1:0] ALG_XMSS = 2'd1;
    localparam logic [1:0] ALG_LMS  = 2'd2;
    localparam logic [1:0] OP_KEYGEN = 2'd0;
    localparam logic [1:0] OP_SIGN = 2'd1;
    localparam logic [15:0] ERR_ALGORITHM = 16'h2701;
    localparam logic [15:0] ERR_OPERATION = 16'h2702;
    localparam logic [15:0] ERR_SLH_WIDTH = 16'h2703;

    typedef enum logic [1:0] {U_IDLE, U_SLH, U_STATEFUL, U_REJECT} state_t;
    state_t state;
    logic invalidate_stateful;
    logic [1:0] active_algorithm, active_operation;

    wire legal_algorithm = job_algorithm != 2'd3;
    wire legal_operation = job_operation == OP_KEYGEN
        || job_operation == OP_SIGN;
    wire request_is_slh = job_algorithm == ALG_SLH;
    wire request_is_stateful = job_algorithm == ALG_XMSS
        || job_algorithm == ALG_LMS;
    wire legal_slh_width = !request_is_slh
        || (job_secret_seed[255:128] == 0
            && job_secret_prf[255:128] == 0
            && job_public_seed[255:128] == 0
            && job_public_root[255:128] == 0
            && job_randomizer[255:128] == 0);

    wire slh_job_ready, slh_message_ready, slh_out_valid, slh_out_last;
    wire slh_busy, slh_done, slh_error;
    wire [63:0] slh_out_data;
    wire [7:0] slh_out_keep;
    wire [15:0] slh_error_code;
    wire [31:0] slh_contexts, slh_permutations;
    wire [31:0] slh_lane0_cycles, slh_lane1_cycles;

    wire stateful_job_ready, stateful_message_ready;
    wire stateful_commit_valid, stateful_out_valid, stateful_out_last;
    wire stateful_busy, stateful_done, stateful_error;
    wire [10:0] stateful_next_q;
    wire [63:0] stateful_out_data;
    wire [7:0] stateful_out_keep;
    wire [15:0] stateful_error_code;
    wire [31:0] stateful_contexts, stateful_permutations;
    wire [31:0] stateful_lane0_cycles, stateful_lane1_cycles;
    logic [31:0] final_contexts, final_permutations;
    logic [31:0] final_lane0_cycles, final_lane1_cycles;

    wire [1:0] slh_context_valid, slh_context_ready;
    wire slh_chain_enable, slh_chain_prefix, slh_chain_preserve;
    wire [2:0] slh_chain_domain;
    wire [9:0] slh_chain_count, slh_capture_after;
    wire [1:0] slh_capture_enable, slh_block_valid, slh_block_ready;
    wire [255:0] slh_block_data;
    wire [1:0] slh_block_last, slh_response_valid, slh_capture_valid;
    wire [543:0] slh_response_digest;
    wire [255:0] slh_capture_digest;
    wire [1:0] slh_shake_error;

    wire [1:0] state_context_valid, state_context_ready;
    wire [1:0] state_fast_valid, state_fast_ready;
    wire [2175:0] state_fast_data;
    wire [1:0] state_block_valid, state_block_ready, state_block_last;
    wire [255:0] state_block_data;
    wire [1:0] state_response_valid, state_finish_valid;
    wire [543:0] state_response_digest, state_finish_digest;
    wire [1:0] state_shake_error;

    wire slh_program_start, slh_program_ready, slh_program_done;
    wire slh_program_error, slh_program_task_done;
    wire [7:0] slh_program_error_code;
    wire slh_program_command0_ready, slh_program_command1_ready;
    wire [2:0] slh_program_task_event;
    wire state_program_start, state_program_ready, state_program_done;
    wire state_program_error, state_program_task_done;
    wire [7:0] state_program_error_code;
    wire state_program_command_ready;
    wire [2:0] state_program_task_event;
    wire program_lane0_valid, program_lane1_valid;
    wire [47:0] program_lane0_command, program_lane1_command;
    wire [63:0] program_lane0_descriptor;
    wire [2:0] program_lane0_event, program_lane1_event;
    wire program_done, program_busy, program_error;
    wire [7:0] program_error_code;
    wire state_descriptor_request_valid;
    wire state_descriptor_request_ready;
    wire [7:0] state_descriptor_request_index;
    wire state_descriptor_response_valid;
    wire [63:0] state_descriptor_response_data;

    wire select_slh = state == U_SLH;
    wire select_stateful = state == U_STATEFUL;
    wire program_lane0_ready = select_slh ? slh_program_command0_ready
        : (select_stateful ? state_program_command_ready : 1'b0);
    wire program_lane1_ready = select_slh ? slh_program_command1_ready
        : (select_stateful ? 1'b1 : 1'b0);

    micro_hbs_unified_task_sequencer unified_program (
        .clk, .rst_n,
        .job_valid(slh_program_start || state_program_start),
        .job_ready(), .job_algorithm(active_algorithm),
        .job_operation(active_operation), .done(program_done),
        .busy(program_busy), .error(program_error),
        .error_code(program_error_code),
        .lane0_valid(program_lane0_valid),
        .lane0_ready(program_lane0_ready),
        .lane0_command(program_lane0_command),
        .lane0_descriptor(program_lane0_descriptor),
        .lane0_event(program_lane0_event),
        .lane1_valid(program_lane1_valid),
        .lane1_ready(program_lane1_ready),
        .lane1_command(program_lane1_command),
        .lane1_event(program_lane1_event),
        .lane0_done_valid(select_slh ? slh_program_task_done
                                    : state_program_task_done),
        .lane0_done_event(select_slh ? slh_program_task_event
                                    : state_program_task_event),
        .lane1_done_valid(1'b0), .lane1_done_event(3'b0),
        .descriptor_request_valid(state_descriptor_request_valid
                                  && select_stateful),
        .descriptor_request_ready(state_descriptor_request_ready),
        .descriptor_request_index(state_descriptor_request_index),
        .descriptor_response_valid(state_descriptor_response_valid),
        .descriptor_response_data(state_descriptor_response_data),
        .descriptor_base(),
        .descriptor_count(), .profile_n_bytes(), .profile_height(),
        .profile_stateful(), .pending_events(), .retired_words(),
        .retired_tokens()
    );


    assign slh_program_ready = !program_busy && !program_error;
    assign state_program_ready = !program_busy && !program_error;
    assign slh_program_done = select_slh && program_done;
    assign state_program_done = select_stateful && program_done;
    assign slh_program_error = select_slh && program_error;
    assign state_program_error = select_stateful && program_error;
    assign slh_program_error_code = program_error_code;
    assign state_program_error_code = program_error_code;
    assign job_ready = state == U_IDLE
        && (!job_valid || !legal_algorithm || !legal_operation
            || !legal_slh_width
            || (request_is_slh ? slh_job_ready
                               : (request_is_stateful
                                  && stateful_job_ready)));
    wire accept_request = job_valid && job_ready;

    assign message_ready = select_slh ? slh_message_ready
        : (select_stateful ? stateful_message_ready : 1'b0);
    assign state_commit_valid = select_stateful && stateful_commit_valid;
    assign state_next_q = select_stateful ? stateful_next_q : 11'b0;
    assign out_valid = select_slh ? slh_out_valid
        : (select_stateful ? stateful_out_valid : 1'b0);
    assign out_data = select_slh ? slh_out_data
        : (select_stateful ? stateful_out_data : 64'b0);
    assign out_keep = select_slh ? slh_out_keep
        : (select_stateful ? stateful_out_keep : 8'b0);
    assign out_last = select_slh ? slh_out_last
        : (select_stateful ? stateful_out_last : 1'b0);
    assign busy = state != U_IDLE;
    assign hash_contexts = select_slh ? slh_contexts
        : (select_stateful ? stateful_contexts : final_contexts);
    assign keccak_permutations = select_slh ? slh_permutations
        : (select_stateful ? stateful_permutations : final_permutations);
    assign lane0_active_cycles = select_slh ? slh_lane0_cycles
        : (select_stateful ? stateful_lane0_cycles : final_lane0_cycles);
    assign lane1_active_cycles = select_slh ? slh_lane1_cycles
        : (select_stateful ? stateful_lane1_cycles : final_lane1_cycles);

    micro_hbs_horizontal_hbs_top #(
        .UNROLL(UNROLL), .MAX_MESSAGE_BYTES(MAX_MESSAGE_BYTES),
        .PROGRAM_TOKENS(14), .DUAL_OPERATION(1'b1),
        .PROFILE_ENABLE(PROFILE_ENABLE),
        .SWAP_PHYSICAL_LANES(1'b0),
        .EXTERNAL_SHAKE(1'b1),
        .EXTERNAL_PROGRAM(1'b1),
        .TOKEN_INIT_FILE("rtl/microcode/slh_dsa_128f_unified_tokens.mem"),
        .TEMPLATE_INIT_FILE(
            "rtl/microcode/slh_dsa_128f_unified_templates.mem"),
        .DESCRIPTOR_INIT_FILE(
            "rtl/microcode/slh_dsa_128f_unified_descriptors.mem")
    ) slh_engine (
        .clk, .rst_n,
        .job_valid(accept_request && request_is_slh
                   && legal_operation && legal_slh_width),
        .job_ready(slh_job_ready), .job_operation(job_operation[0]),
        .job_message_length,
        .job_sk_seed(job_secret_seed[127:0]),
        .job_sk_prf(job_secret_prf[127:0]),
        .job_pk_seed(job_public_seed[127:0]),
        .job_pk_root(job_public_root[127:0]),
        .job_opt_rand(job_randomizer[127:0]),
        .message_valid(message_valid && select_slh),
        .message_ready(slh_message_ready), .message_data, .message_keep,
        .message_last, .out_valid(slh_out_valid),
        .out_ready(out_ready && select_slh), .out_data(slh_out_data),
        .out_keep(slh_out_keep), .out_last(slh_out_last),
        .busy(slh_busy), .done(slh_done), .error(slh_error),
        .error_code(slh_error_code), .hash_contexts(slh_contexts),
        .keccak_permutations(slh_permutations),
        .lane0_active_cycles(slh_lane0_cycles),
        .lane1_active_cycles(slh_lane1_cycles),
        .external_context_valid(slh_context_valid),
        .external_context_ready(slh_context_ready),
        .external_chain_enable(slh_chain_enable),
        .external_chain_prefix(slh_chain_prefix),
        .external_chain_prefix_preserve_counter(slh_chain_preserve),
        .external_chain_prefix_domain(slh_chain_domain),
        .external_chain_count(slh_chain_count),
        .external_capture_enable(slh_capture_enable),
        .external_capture_after(slh_capture_after),
        .external_block_valid(slh_block_valid),
        .external_block_ready(slh_block_ready),
        .external_block_data(slh_block_data),
        .external_block_last(slh_block_last),
        .external_response_valid(slh_response_valid),
        .external_response_digest(slh_response_digest),
        .external_capture_digest(slh_capture_digest),
        .external_capture_valid(slh_capture_valid),
        .external_shake_error(slh_shake_error),
        .external_program_start(slh_program_start),
        .external_program_ready(slh_program_ready),
        .external_program_done(slh_program_done),
        .external_program_error(slh_program_error),
        .external_program_error_code(slh_program_error_code),
        .external_command0_valid(program_lane0_valid && select_slh),
        .external_command0_ready(slh_program_command0_ready),
        .external_command0(program_lane0_command),
        .external_command0_event(program_lane0_event),
        .external_command1_valid(program_lane1_valid && select_slh),
        .external_command1_ready(slh_program_command1_ready),
        .external_command1(program_lane1_command),
        .external_command1_event(program_lane1_event),
        .external_task_done(slh_program_task_done),
        .external_task_event(slh_program_task_event)
    );

    micro_hbs_horizontal_stateful_hbs_top #(
        .UNROLL(UNROLL), .MAX_MESSAGE_BYTES(MAX_MESSAGE_BYTES),
        .PROFILE_ENABLE(PROFILE_ENABLE),
        .SWAP_PHYSICAL_LANES(1'b0),
        .EXTERNAL_SHAKE(1'b1),
        .EXTERNAL_PROGRAM(1'b1),
        .TOKEN_INIT_FILE("rtl/microcode/stateful_hbs_unified_tokens.mem"),
        .TEMPLATE_INIT_FILE(
            "rtl/microcode/stateful_hbs_unified_templates.mem"),
        .DESCRIPTOR_INIT_FILE(
            "rtl/microcode/stateful_hbs_unified_descriptors.mem")
    ) stateful_engine (
        .clk, .rst_n,
        .job_valid(accept_request && request_is_stateful
                   && legal_operation),
        .job_ready(stateful_job_ready),
        .invalidate_state(invalidate_stateful),
        .job_family(job_algorithm == ALG_LMS),
        .job_operation(job_operation[0]), .job_message_length,
        .job_initial_q, .job_secret_seed, .job_secret_prf,
        .job_public_seed, .job_identifier, .job_randomizer,
        .message_valid(message_valid && select_stateful),
        .message_ready(stateful_message_ready), .message_data,
        .message_keep, .message_last,
        .state_commit_valid(stateful_commit_valid),
        .state_commit_ready(state_commit_ready && select_stateful),
        .state_next_q(stateful_next_q), .out_valid(stateful_out_valid),
        .out_ready(out_ready && select_stateful),
        .out_data(stateful_out_data), .out_keep(stateful_out_keep),
        .out_last(stateful_out_last), .busy(stateful_busy),
        .done(stateful_done), .error(stateful_error),
        .error_code(stateful_error_code),
        .hash_contexts(stateful_contexts),
        .keccak_permutations(stateful_permutations),
        .lane0_active_cycles(stateful_lane0_cycles),
        .lane1_active_cycles(stateful_lane1_cycles), .tree_cache_valid,
        .external_context_valid(state_context_valid),
        .external_context_ready(state_context_ready),
        .external_fast_block_valid(state_fast_valid),
        .external_fast_block_ready(state_fast_ready),
        .external_fast_block_data(state_fast_data),
        .external_block_valid(state_block_valid),
        .external_block_ready(state_block_ready),
        .external_block_data(state_block_data),
        .external_block_last(state_block_last),
        .external_response_valid(state_response_valid),
        .external_response_digest(state_response_digest),
        .external_finish_valid(state_finish_valid),
        .external_finish_digest(state_finish_digest),
        .external_shake_error(state_shake_error),
        .external_program_start(state_program_start),
        .external_program_ready(state_program_ready),
        .external_program_done(state_program_done),
        .external_program_error(state_program_error),
        .external_program_error_code(state_program_error_code),
        .external_command_valid(program_lane0_valid && select_stateful),
        .external_command_ready(state_program_command_ready),
        .external_command(program_lane0_command),
        .external_command_descriptor(program_lane0_descriptor),
        .external_command_event(program_lane0_event),
        .external_task_done(state_program_task_done),
        .external_task_event(state_program_task_event),
        .external_descriptor_request_valid(state_descriptor_request_valid),
        .external_descriptor_request_ready(state_descriptor_request_ready),
        .external_descriptor_request_index(state_descriptor_request_index),
        .external_descriptor_response_valid(state_descriptor_response_valid),
        .external_descriptor_response_data(state_descriptor_response_data)
    );

    // The only two Keccak instances in the unified hierarchy.  Both accept
    // the full raw SLH service and the n=32 recipe primitive service.  The
    // job selector is latched, so a lane cannot change owner mid-context.
    genvar physical_lane;
    generate for (physical_lane = 0; physical_lane < 2;
                  physical_lane = physical_lane + 1) begin : shared_lanes
        localparam integer LOGICAL_LANE = SWAP_PHYSICAL_LANES
            ? 1-physical_lane : physical_lane;
        wire lane_context_ready, lane_fast_ready, lane_block_ready;
        wire lane_response_valid, lane_finish_valid, lane_capture_valid;
        wire [271:0] lane_response_digest, lane_finish_digest;
        wire [127:0] lane_capture_digest;
        wire lane_error;

        assign slh_context_ready[LOGICAL_LANE]
            = select_slh && lane_context_ready;
        assign slh_block_ready[LOGICAL_LANE]
            = select_slh && lane_block_ready;
        assign slh_response_valid[LOGICAL_LANE]
            = select_slh && lane_response_valid;
        assign slh_response_digest[LOGICAL_LANE*272 +: 272]
            = lane_response_digest;
        assign slh_capture_digest[LOGICAL_LANE*128 +: 128]
            = lane_capture_digest;
        assign slh_capture_valid[LOGICAL_LANE]
            = select_slh && lane_capture_valid;
        assign slh_shake_error[LOGICAL_LANE]
            = select_slh && lane_error;

        assign state_context_ready[LOGICAL_LANE]
            = select_stateful && lane_context_ready;
        assign state_fast_ready[LOGICAL_LANE]
            = select_stateful && lane_fast_ready;
        assign state_block_ready[LOGICAL_LANE]
            = select_stateful && lane_block_ready;
        assign state_response_valid[LOGICAL_LANE]
            = select_stateful && lane_response_valid;
        assign state_response_digest[LOGICAL_LANE*272 +: 272]
            = lane_response_digest;
        assign state_finish_valid[LOGICAL_LANE]
            = select_stateful && lane_finish_valid;
        assign state_finish_digest[LOGICAL_LANE*272 +: 272]
            = lane_finish_digest;
        assign state_shake_error[LOGICAL_LANE]
            = select_stateful && lane_error;

        (* keep_hierarchy = "yes" *)
        micro_hbs_compact_shake_context_lane #(.UNROLL(UNROLL)) lane (
            .clk, .rst_n,
            .context_valid(select_slh
                ? slh_context_valid[LOGICAL_LANE]
                : state_context_valid[LOGICAL_LANE]),
            .context_ready(lane_context_ready),
            .fast_block_valid(select_stateful
                && state_fast_valid[LOGICAL_LANE]),
            .fast_block_ready(lane_fast_ready),
            .fast_block_data(state_fast_data[
                LOGICAL_LANE*1088 +: 1088]),
            .chain_enable(select_slh && slh_chain_enable),
            .chain_prefix(slh_chain_prefix),
            .chain_prefix_preserve_counter(slh_chain_preserve),
            .chain_prefix_domain(slh_chain_domain),
            .chain_count(slh_chain_count[LOGICAL_LANE*5 +: 5]),
            .capture_enable(select_slh
                && slh_capture_enable[LOGICAL_LANE]),
            .capture_after(slh_capture_after[LOGICAL_LANE*5 +: 5]),
            .block_valid(select_slh ? slh_block_valid[LOGICAL_LANE]
                                    : state_block_valid[LOGICAL_LANE]),
            .block_ready(lane_block_ready),
            .block_data(select_slh
                ? slh_block_data[LOGICAL_LANE*128 +: 128]
                : state_block_data[LOGICAL_LANE*128 +: 128]),
            .block_last(select_slh ? slh_block_last[LOGICAL_LANE]
                                   : state_block_last[LOGICAL_LANE]),
            .response_valid(lane_response_valid),
            .response_digest(lane_response_digest),
            .finish_valid(lane_finish_valid),
            .finish_digest(lane_finish_digest),
            .capture_digest(lane_capture_digest),
            .capture_valid(lane_capture_valid), .error(lane_error)
        );
    end endgenerate

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= U_IDLE;
            invalidate_stateful <= 0;
            active_algorithm <= 0;
            active_operation <= 0;
            done <= 0;
            error <= 0;
            error_code <= 0;
            final_contexts <= 0;
            final_permutations <= 0;
            final_lane0_cycles <= 0;
            final_lane1_cycles <= 0;
        end else begin
            done <= 0;
            invalidate_stateful <= 0;
            case (state)
                U_IDLE: begin
                    if (!job_valid) begin
                        error <= 0;
                        error_code <= 0;
                    end else if (job_ready) begin
                        if (!legal_algorithm) begin
                            error <= 1;
                            error_code <= ERR_ALGORITHM;
                            state <= U_REJECT;
                        end else if (!legal_operation) begin
                            error <= 1;
                            error_code <= ERR_OPERATION;
                            state <= U_REJECT;
                        end else if (!legal_slh_width) begin
                            error <= 1;
                            error_code <= ERR_SLH_WIDTH;
                            state <= U_REJECT;
                        end else begin
                            active_algorithm <= job_algorithm;
                            active_operation <= job_operation;
                            error <= 0;
                            error_code <= 0;
                            final_contexts <= 0;
                            final_permutations <= 0;
                            final_lane0_cycles <= 0;
                            final_lane1_cycles <= 0;
                            if (request_is_slh) begin
                                invalidate_stateful <= 1;
                                state <= U_SLH;
                            end else
                                state <= U_STATEFUL;
                        end
                    end
                end
                U_SLH: begin
                    if (slh_error) begin
                        error <= 1;
                        error_code <= slh_error_code;
                        state <= U_REJECT;
                    end else if (slh_done) begin
                        final_contexts <= slh_contexts;
                        final_permutations <= slh_permutations;
                        final_lane0_cycles <= slh_lane0_cycles;
                        final_lane1_cycles <= slh_lane1_cycles;
                        done <= 1;
                        state <= U_IDLE;
                    end
                end
                U_STATEFUL: begin
                    if (stateful_error) begin
                        error <= 1;
                        error_code <= stateful_error_code;
                        state <= U_REJECT;
                    end else if (stateful_done) begin
                        final_contexts <= stateful_contexts;
                        final_permutations <= stateful_permutations;
                        final_lane0_cycles <= stateful_lane0_cycles;
                        final_lane1_cycles <= stateful_lane1_cycles;
                        done <= 1;
                        state <= U_IDLE;
                    end
                end
                U_REJECT: if (!job_valid) state <= U_IDLE;
                default: begin
                    error <= 1;
                    error_code <= ERR_ALGORITHM;
                    state <= U_REJECT;
                end
            endcase
        end
    end

    wire unused_busy = slh_busy ^ stateful_busy;
endmodule

`default_nettype wire
