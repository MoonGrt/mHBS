`timescale 1ns/1ps
`default_nettype none

// Non-standard SHAKE256/256 LMS research-profile product wrapper.  It retains
// RFC 8554 byte encodings and domain separation but uses private-use typecodes.
module micro_hbs_horizontal_lms_top #(
    parameter integer UNROLL = 2,
    parameter bit PROFILE_ENABLE = 1'b0,
    parameter bit SWAP_PHYSICAL_LANES = 1'b0
) (
    input wire clk, input wire rst_n,
    input wire job_valid, output wire job_ready,
    input wire job_operation, input wire [31:0] job_message_length,
    input wire [10:0] job_initial_q,
    input wire [127:0] job_identifier,
    input wire [255:0] job_seed,
    input wire [255:0] job_randomizer,
    input wire message_valid, output wire message_ready,
    input wire [63:0] message_data, input wire [7:0] message_keep,
    input wire message_last,
    output wire state_commit_valid, input wire state_commit_ready,
    output wire [10:0] state_next_q,
    output wire out_valid, input wire out_ready,
    output wire [63:0] out_data, output wire [7:0] out_keep,
    output wire out_last, output wire busy, output wire done,
    output wire error, output wire [15:0] error_code,
    output wire [31:0] hash_contexts,
    output wire [31:0] keccak_permutations,
    output wire [31:0] lane0_active_cycles,
    output wire [31:0] lane1_active_cycles,
    output wire tree_cache_valid
);
    (* keep_hierarchy = "yes" *)
    micro_hbs_horizontal_stateful_hbs_top #(
        .UNROLL(UNROLL), .PROFILE_ENABLE(PROFILE_ENABLE),
        .SWAP_PHYSICAL_LANES(SWAP_PHYSICAL_LANES),
        .TOKEN_INIT_FILE("rtl/microcode/stateful_hbs_unified_tokens.mem"),
        .TEMPLATE_INIT_FILE("rtl/microcode/stateful_hbs_unified_templates.mem"),
        .DESCRIPTOR_INIT_FILE("rtl/microcode/stateful_hbs_unified_descriptors.mem")
    ) core (
        .clk, .rst_n, .job_valid, .job_ready, .invalidate_state(1'b0),
        .job_family(1'b1), .job_operation,
        .job_message_length, .job_initial_q, .job_secret_seed(job_seed),
        .job_secret_prf(256'b0), .job_public_seed(256'b0),
        .job_identifier, .job_randomizer, .message_valid, .message_ready,
        .message_data, .message_keep, .message_last, .state_commit_valid,
        .state_commit_ready, .state_next_q, .out_valid, .out_ready,
        .out_data, .out_keep, .out_last, .busy, .done, .error,
        .error_code, .hash_contexts, .keccak_permutations,
        .lane0_active_cycles, .lane1_active_cycles, .tree_cache_valid,
        .external_descriptor_request_valid(),
        .external_descriptor_request_ready(1'b0),
        .external_descriptor_request_index(),
        .external_descriptor_response_valid(1'b0),
        .external_descriptor_response_data(64'b0),
        .external_command_descriptor(64'b0)
    );
endmodule

`default_nettype wire
