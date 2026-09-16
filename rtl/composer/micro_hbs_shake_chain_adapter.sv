`timescale 1ns/1ps
`default_nettype none

// Minimal capability-selected composer/feedback adapter for the first real
// sequencer-to-SHAKE vertical slice. Layout 0 means SHAKE256(chain_value, 32).
module micro_hbs_shake_chain_adapter #(
    parameter integer UNROLL = 2
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         load_initial_value,
    input  wire [255:0] initial_value,
    input  wire         req_valid,
    output logic        req_ready,
    input  wire [15:0]  layout_id,
    output logic        rsp_valid,
    output logic        rsp_error,
    output logic [15:0] rsp_error_code,
    output logic [255:0] chain_value
);
    localparam logic [15:0] LAYOUT_SHAKE256_CHAIN32 = 16'h0000;
    localparam logic [15:0] ERR_UNSUPPORTED_LAYOUT = 16'h0101;

    wire shake_ready;
    wire [255:0] shake_digest;
    wire shake_done;
    wire shake_error;
    wire accept_request;
    wire shake_start;

    assign req_ready = shake_ready;
    assign accept_request = req_valid && req_ready;
    assign shake_start = accept_request && (layout_id == LAYOUT_SHAKE256_CHAIN32);

    micro_hbs_shake256_single_block #(.UNROLL(UNROLL)) shake_lane (
        .clk,
        .rst_n,
        .start(shake_start),
        .ready(shake_ready),
        .message({832'b0, chain_value}),
        .message_length(8'd32),
        .digest(shake_digest),
        .done(shake_done),
        .error(shake_error)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            chain_value <= '0;
            rsp_valid <= 1'b0;
            rsp_error <= 1'b0;
            rsp_error_code <= '0;
        end else begin
            rsp_valid <= 1'b0;
            rsp_error <= 1'b0;
            rsp_error_code <= '0;
            if (load_initial_value) begin
                chain_value <= initial_value;
            end else if (shake_done) begin
                chain_value <= shake_digest;
                rsp_valid <= 1'b1;
            end
            if (accept_request && layout_id != LAYOUT_SHAKE256_CHAIN32) begin
                rsp_error <= 1'b1;
                rsp_error_code <= ERR_UNSUPPORTED_LAYOUT;
            end else if (shake_error) begin
                rsp_error <= 1'b1;
                rsp_error_code <= 16'h0102;
            end
        end
    end
endmodule

`default_nettype wire
