`timescale 1ns/1ps
`default_nettype none

// Testable generic parent layout: SHAKE256(left || right, 32 bytes).
module micro_hbs_tree_parent_shake #(
    parameter integer UNROLL = 2
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         req_valid,
    output logic        req_ready,
    input  wire [255:0] left_node,
    input  wire [255:0] right_node,
    output logic        rsp_valid,
    output logic [255:0] rsp_value,
    output logic        rsp_error
);
    wire shake_ready;
    wire [255:0] shake_digest;
    wire shake_done;
    wire shake_error;

    assign req_ready = shake_ready;
    assign rsp_valid = shake_done;
    assign rsp_value = shake_digest;
    assign rsp_error = shake_error;

    micro_hbs_shake256_single_block #(.UNROLL(UNROLL)) shake_lane (
        .clk,
        .rst_n,
        .start(req_valid && req_ready),
        .ready(shake_ready),
        .message({576'b0, right_node, left_node}),
        .message_length(8'd64),
        .digest(shake_digest),
        .done(shake_done),
        .error(shake_error)
    );
endmodule

`default_nettype wire
