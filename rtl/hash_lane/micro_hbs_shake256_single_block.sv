`timescale 1ns/1ps
`default_nettype none

// SHAKE256 for one final rate block (0..135 message bytes, 32-byte output).
// This is a real cryptographic vertical slice, but not yet the multi-block HIL.
module micro_hbs_shake256_single_block #(
    parameter integer UNROLL = 1
) (
    input  wire          clk,
    input  wire          rst_n,
    input  wire          start,
    output logic         ready,
    input  wire [1087:0] message,
    input  wire [7:0]    message_length,
    input  wire          repeat_enable,
    input  wire          repeat_prefix,
    input  wire          repeat_prefix_preserve_counter,
    input  wire [2:0]    repeat_prefix_domain,
    input  wire [7:0]    repeat_count,
    input  wire [7:0]    repeat_counter_offset,
    input  wire [7:0]    repeat_feedback_offset,
    input  wire [5:0]    repeat_feedback_bytes,
    input  wire [31:0]   repeat_counter_start,
    input  wire          capture_enable,
    input  wire [7:0]    capture_after,
    output logic [255:0] digest,
    output logic         done,
    output logic [255:0] capture_digest,
    output logic         capture_valid,
    output logic         error
);
    wire permutation_start = start && ready && message_length <= 135;
    wire [1599:0] padded_state = pad_shake256(message, message_length);
    wire permutation_ready;
    wire [1599:0] permutation_result;
    wire permutation_done;
    wire [5:0] permutation_rounds;

    function automatic [1599:0] pad_shake256;
        input [1087:0] input_message;
        input [7:0] input_length;
        reg [1599:0] result;
        integer i;
        begin
            result = '0;
            for (i = 0; i < 136; i = i + 1)
                if (i < input_length)
                    result[8*i +: 8] = input_message[8*i +: 8];
            result[8*input_length +: 8] = result[8*input_length +: 8] ^ 8'h1f;
            result[8*135 +: 8] = result[8*135 +: 8] ^ 8'h80;
            pad_shake256 = result;
        end
    endfunction

    micro_hbs_keccak_f1600 #(.UNROLL(UNROLL)) permutation (
        .clk,
        .rst_n,
        .start(permutation_start),
        .ready(permutation_ready),
        .state_in(padded_state),
        .chain_enable(repeat_enable),
        .chain_prefix(repeat_prefix),
        .chain_prefix_preserve_counter(repeat_prefix_preserve_counter),
        .chain_prefix_domain(repeat_prefix_domain),
        .chain_count(repeat_count),
        .chain_counter_offset(repeat_counter_offset),
        .chain_feedback_offset(repeat_feedback_offset),
        .chain_feedback_bytes(repeat_feedback_bytes),
        .chain_counter_start(repeat_counter_start),
        .capture_enable, .capture_after,
        .state_out(permutation_result),
        .done(permutation_done),
        .capture_digest, .capture_valid,
        .rounds_executed(permutation_rounds)
    );

    assign ready = permutation_ready;
    assign digest = permutation_result[255:0];
    assign done = permutation_done;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            error <= 1'b0;
        end else begin
            error <= 1'b0;
            if (start && ready && message_length > 135)
                error <= 1'b1;
        end
    end
endmodule

`default_nettype wire
