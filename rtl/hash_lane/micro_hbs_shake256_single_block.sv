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
    output logic [255:0] digest,
    output logic         done,
    output logic         error
);
    logic active;
    logic permutation_start;
    logic [1599:0] padded_state;
    wire permutation_ready;
    wire [1599:0] permutation_result;
    wire permutation_done;
    wire [5:0] permutation_rounds;
    integer byte_index;

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
        .state_out(permutation_result),
        .done(permutation_done),
        .rounds_executed(permutation_rounds)
    );

    assign ready = !active && permutation_ready;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            active <= 1'b0;
            permutation_start <= 1'b0;
            padded_state <= '0;
            digest <= '0;
            done <= 1'b0;
            error <= 1'b0;
        end else begin
            permutation_start <= 1'b0;
            done <= 1'b0;
            error <= 1'b0;
            if (start && ready) begin
                if (message_length > 135) begin
                    error <= 1'b1;
                end else begin
                    padded_state <= pad_shake256(message, message_length);
                    permutation_start <= 1'b1;
                    active <= 1'b1;
                end
            end else if (active && permutation_done) begin
                for (byte_index = 0; byte_index < 32; byte_index = byte_index + 1)
                    digest[8*byte_index +: 8] <= permutation_result[8*byte_index +: 8];
                active <= 1'b0;
                done <= 1'b1;
            end
        end
    end
endmodule

`default_nettype wire
