`timescale 1ns/1ps
`default_nettype none
// Generated fixed-job demonstration wrapper. Regenerate with generate_unified_tops.py.
// Algorithm control is supplied solely by the ABI 4 immutable image.
module uhbs_lms_top #(
    parameter integer UNROLL=2, LANES=1, MESSAGE_BYTES=20, INITIAL_Q=5,
    parameter [255:0] SECRET = 256'h3f3e3d3c3b3a393837363534333231302f2e2d2c2b2a29282726252423222120,
    parameter [255:0] PRF = 256'h0000000000000000000000000000000000000000000000000000000000000000,
    parameter [255:0] PUBLIC = 256'h0000000000000000000000000000000000000000000000000000000000000000,
    parameter [255:0] RANDOM = 256'h5f5e5d5c5b5a595857565554535251504f4e4d4c4b4a49484746454443424140,
    parameter [127:0] IDENTIFIER=128'h0f0e0d0c0b0a09080706050403020100,
    parameter bit PROFILE_ENABLE=0, SWAP_PHYSICAL_LANES=0
) (
    input wire clk, rst_n, start,
    output wire ready, busy, keygen_done, done,
    output wire [31:0] keygen_cycles, sign_cycles,
    input wire message_valid, output wire message_ready,
    input wire [63:0] message_data, input wire [7:0] message_keep, input wire message_last,
    output wire state_commit_valid, input wire state_commit_ready,
    output wire [10:0] state_next_q,
    output wire out_valid, input wire out_ready, output wire [63:0] out_data,
    output wire [7:0] out_keep, output wire out_last, output wire result_kind,
    output wire error, output wire [15:0] error_code,
    output wire [31:0] hash_count, permutation_count,
    output wire tree_cache_valid
);
    wire job_valid, job_ready, operation, core_done;
    wire [31:0] core_cycles;
    assign result_kind=operation;
    uhbs_job_sequence sequence_control (
        .clk,.rst_n,.start,.ready,.busy,.job_valid,.job_ready,.job_operation(operation),
        .core_done,.core_error(error),.core_cycles,.keygen_done,.done,.keygen_cycles,.sign_cycles
    );
    uhbs_hbs #(.N(32),.STATEFUL(1'b1),
        .OMEGA(4),.CHAIN_COUNT(67),.DIGEST_BYTES(32),
        .FORS_A(0),.FORS_K(0),.TREE_BITS(0),.HP(10),.UNROLL(UNROLL),.LANES(LANES),
        .RECIPE_MASK(16'hee00),
        .CHAIN_RECIPE_MASK(16'h0600),.MAX_MESSAGE_BYTES(MESSAGE_BYTES),
        .PROGRAM_TOKENS(10),.PROGRAM_TEMPLATES(8),
        .PROFILE_ENABLE(PROFILE_ENABLE),.SWAP_PHYSICAL_LANES(SWAP_PHYSICAL_LANES),
        .TOKEN_INIT_FILE("rtl/microcode/uhbs_lms_omega4_tokens.mem"),
        .TEMPLATE_INIT_FILE("rtl/microcode/uhbs_lms_omega4_templates.mem"),
        .DESCRIPTOR_INIT_FILE("rtl/microcode/uhbs_lms_omega4_descriptors.mem")
    ) core (
        .clk,.rst_n,.job_valid,.job_ready,.job_operation(operation),
        .job_message_length(7'(MESSAGE_BYTES)),.job_initial_q(11'(INITIAL_Q)),
        .job_secret_seed(SECRET),.job_secret_prf(PRF),.job_public_seed(PUBLIC),
        .job_randomizer(RANDOM),.job_identifier(IDENTIFIER),
        .message_valid,.message_ready,.message_data,.message_keep,.message_last,
        .state_commit_valid,.state_commit_ready,.state_next_q,
        .out_valid,.out_ready,.out_data,.out_keep,.out_last,
        .busy(),.done(core_done),.error,.error_code,.hash_count,.permutation_count,
        .cycles(core_cycles),.tree_cache_valid
    );
endmodule
`default_nettype wire
