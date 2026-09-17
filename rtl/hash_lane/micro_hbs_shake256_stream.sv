`timescale 1ns/1ps
`default_nettype none

// Internal SHAKE256 absorb engine. A composer, not software, supplies full rate
// blocks followed by exactly one final block containing 0..135 message bytes.
module micro_hbs_shake256_stream #(
    parameter integer UNROLL = 1
) (
    input  wire          clk,
    input  wire          rst_n,
    input  wire          hash_start,
    output logic         hash_ready,
    input  wire          block_valid,
    output logic         block_ready,
    input  wire [1087:0] block_data,
    input  wire [7:0]    block_bytes,
    input  wire          block_last,
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
    output logic [1087:0] rate_output,
    output logic         digest_valid,
    output wire [255:0]  capture_digest,
    output wire          capture_valid,
    output logic         error
);
    typedef enum logic [1:0] {S_IDLE, S_ABSORB, S_PERMUTE} state_t;
    state_t state;
    logic [1599:0] sponge_state;
    logic [1599:0] permutation_input;
    logic permutation_start;
    logic final_pending;
    wire permutation_ready;
    wire [1599:0] permutation_result;
    wire permutation_done;
    wire [5:0] permutation_rounds;
    integer byte_index;

    function automatic [1599:0] absorb_full_block;
        input [1599:0] current_state;
        input [1087:0] input_block;
        reg [1599:0] result;
        begin
            result = current_state;
            result[1087:0] = current_state[1087:0] ^ input_block;
            absorb_full_block = result;
        end
    endfunction

    function automatic [1599:0] absorb_final_block;
        input [1599:0] current_state;
        input [1087:0] input_block;
        input [7:0] input_length;
        reg [1599:0] result;
        integer i;
        begin
            result = current_state;
            for (i = 0; i < 136; i = i + 1)
                if (i < input_length)
                    result[8*i +: 8] = current_state[8*i +: 8] ^ input_block[8*i +: 8];
            result[8*input_length +: 8] = result[8*input_length +: 8] ^ 8'h1f;
            result[8*135 +: 8] = result[8*135 +: 8] ^ 8'h80;
            absorb_final_block = result;
        end
    endfunction

    micro_hbs_keccak_f1600 #(.UNROLL(UNROLL)) permutation (
        .clk,
        .rst_n,
        .start(permutation_start),
        .ready(permutation_ready),
        .state_in(permutation_input),
        .chain_enable(repeat_enable && final_pending),
        .chain_prefix(repeat_prefix && final_pending),
        .chain_prefix_preserve_counter(repeat_prefix_preserve_counter),
        .chain_prefix_domain(repeat_prefix_domain),
        .chain_count(repeat_count),
        .chain_counter_offset(repeat_counter_offset),
        .chain_feedback_offset(repeat_feedback_offset),
        .chain_feedback_bytes(repeat_feedback_bytes),
        .chain_counter_start(repeat_counter_start),
        .capture_enable(capture_enable && final_pending), .capture_after,
        .state_out(permutation_result),
        .done(permutation_done), .capture_digest, .capture_valid,
        .rounds_executed(permutation_rounds)
    );

    assign hash_ready = (state == S_IDLE) && permutation_ready;
    assign block_ready = (state == S_ABSORB) && permutation_ready;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            sponge_state <= '0;
            permutation_input <= '0;
            permutation_start <= 1'b0;
            final_pending <= 1'b0;
            digest <= '0;
            rate_output <= '0;
            digest_valid <= 1'b0;
            error <= 1'b0;
        end else begin
            permutation_start <= 1'b0;
            digest_valid <= 1'b0;
            error <= 1'b0;
            case (state)
                S_IDLE: begin
                    if (hash_start) begin
                        sponge_state <= '0;
                        state <= S_ABSORB;
                    end
                end
                S_ABSORB: begin
                    if (hash_start) begin
                        error <= 1'b1;
                        state <= S_IDLE;
                    end else if (block_valid) begin
                        if ((!block_last && block_bytes != 136)
                            || (block_last && block_bytes > 135)) begin
                            error <= 1'b1;
                            state <= S_IDLE;
                        end else begin
                            if (block_last)
                                permutation_input <= absorb_final_block(
                                    sponge_state, block_data, block_bytes);
                            else
                                permutation_input <= absorb_full_block(sponge_state, block_data);
                            final_pending <= block_last;
                            permutation_start <= 1'b1;
                            state <= S_PERMUTE;
                        end
                    end
                end
                S_PERMUTE: begin
                    if (permutation_done) begin
                        if (final_pending) begin
                            rate_output <= permutation_result[1087:0];
                            for (byte_index = 0; byte_index < 32; byte_index = byte_index + 1)
                                digest[8*byte_index +: 8] <= permutation_result[8*byte_index +: 8];
                            digest_valid <= 1'b1;
                            state <= S_IDLE;
                        end else begin
                            sponge_state <= permutation_result;
                            state <= S_ABSORB;
                        end
                    end
                end
                default: begin
                    error <= 1'b1;
                    state <= S_IDLE;
                end
            endcase
        end
    end
endmodule

`default_nettype wire
