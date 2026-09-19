`timescale 1ns/1ps
`default_nettype none

// Backwards-compatible Sign interface.  Algorithm control is supplied by the
// immutable Sign macro image; no signing scheduler is implemented here.
module micro_hbs_horizontal_slh_dsa_sign_top #(
    parameter integer UNROLL = 2,
    parameter integer MAX_MESSAGE_BYTES = 87,
    parameter bit PROFILE_ENABLE = 1'b0,
    parameter bit SWAP_PHYSICAL_LANES = 1'b0
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         job_valid,
    output wire         job_ready,
    input  wire [31:0]  job_message_length,
    input  wire [127:0] job_sk_seed,
    input  wire [127:0] job_sk_prf,
    input  wire [127:0] job_pk_seed,
    input  wire [127:0] job_pk_root,
    input  wire [127:0] job_opt_rand,
    input  wire         message_valid,
    output wire         message_ready,
    input  wire [63:0]  message_data,
    input  wire [7:0]   message_keep,
    input  wire         message_last,
    output wire         out_valid,
    input  wire         out_ready,
    output wire [63:0]  out_data,
    output wire [7:0]   out_keep,
    output wire         out_last,
    output wire         busy,
    output wire         done,
    output wire         error,
    output wire [15:0]  error_code,
    output wire [31:0]  hash_contexts,
    output wire [31:0]  keccak_permutations,
    output wire [31:0]  lane0_active_cycles,
    output wire [31:0]  lane1_active_cycles
);
    micro_hbs_horizontal_hbs_top #(
        .UNROLL(UNROLL),
        .MAX_MESSAGE_BYTES(MAX_MESSAGE_BYTES),
        .PROGRAM_TOKENS(11),
        .OUTPUT_BYTES(17088),
        .REQUIRE_MESSAGE(1'b1),
        .PROFILE_ENABLE(PROFILE_ENABLE),
        .SWAP_PHYSICAL_LANES(SWAP_PHYSICAL_LANES),
        .TOKEN_INIT_FILE(
            "rtl/microcode/slh_dsa_128f_sign_macro_tokens.mem"),
        .TEMPLATE_INIT_FILE(
            "rtl/microcode/slh_dsa_128f_sign_macro_templates.mem"),
        .DESCRIPTOR_INIT_FILE(
            "rtl/microcode/slh_dsa_128f_sign_macro_descriptors.mem")
    ) engine (.*);
endmodule

// Keygen emits SK || PK (96 bytes) and shares the complete execution
// datapath with the Sign wrapper above.
module micro_hbs_horizontal_slh_dsa_keygen_top #(
    parameter integer UNROLL = 2,
    parameter bit PROFILE_ENABLE = 1'b0,
    parameter bit SWAP_PHYSICAL_LANES = 1'b0
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         job_valid,
    output wire         job_ready,
    input  wire [127:0] job_sk_seed,
    input  wire [127:0] job_sk_prf,
    input  wire [127:0] job_pk_seed,
    output wire         out_valid,
    input  wire         out_ready,
    output wire [63:0]  out_data,
    output wire [7:0]   out_keep,
    output wire         out_last,
    output wire         busy,
    output wire         done,
    output wire         error,
    output wire [15:0]  error_code,
    output wire [31:0]  hash_contexts,
    output wire [31:0]  keccak_permutations,
    output wire [31:0]  lane0_active_cycles,
    output wire [31:0]  lane1_active_cycles
);
    wire unused_message_ready;
    micro_hbs_horizontal_hbs_top #(
        .UNROLL(UNROLL),
        .PROGRAM_TOKENS(3),
        .OUTPUT_BYTES(96),
        .REQUIRE_MESSAGE(1'b0),
        .PROFILE_ENABLE(PROFILE_ENABLE),
        .SWAP_PHYSICAL_LANES(SWAP_PHYSICAL_LANES),
        .TOKEN_INIT_FILE(
            "rtl/microcode/slh_dsa_128f_keygen_macro_tokens.mem"),
        .TEMPLATE_INIT_FILE(
            "rtl/microcode/slh_dsa_128f_keygen_macro_templates.mem"),
        .DESCRIPTOR_INIT_FILE(
            "rtl/microcode/slh_dsa_128f_keygen_macro_descriptors.mem")
    ) engine (
        .clk, .rst_n, .job_valid, .job_ready,
        .job_message_length(32'd0),
        .job_sk_seed, .job_sk_prf, .job_pk_seed,
        .job_pk_root(128'd0), .job_opt_rand(128'd0),
        .message_valid(1'b0), .message_ready(unused_message_ready),
        .message_data(64'd0), .message_keep(8'd0),
        .message_last(1'b0),
        .out_valid, .out_ready, .out_data, .out_keep, .out_last,
        .busy, .done, .error, .error_code,
        .hash_contexts, .keccak_permutations,
        .lane0_active_cycles, .lane1_active_cycles
    );
endmodule

`default_nettype wire
