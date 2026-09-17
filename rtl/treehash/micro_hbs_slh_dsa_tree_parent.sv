`timescale 1ns/1ps
`default_nettype none

// FIPS 205 SLH-DSA SHAKE parent composer for n=16.
//
// For the SHAKE instantiations, FIPS 205 H and T_l use
//   SHAKE256(PK.seed || ADRS || M, n).
// A Merkle parent has M = left || right, so the input is exactly 80 bytes.
// Unlike the SHA2 instantiations, the SHAKE instantiations use the complete
// 32-byte ADRS; there is no compressed-ADRS transform.  This is also not the
// RFC 8391 randomized H construction: no prefix, KEY, or bitmasks are added.
// Packed byte strings follow the project convention (byte zero in bits 7:0).
//
// One request may be outstanding.  The response is buffered until rsp_ready.
// Any SHAKE error produces an error response with an all-zero parent.
module micro_hbs_slh_dsa_tree_parent #(
    parameter integer UNROLL = 2
) (
    input  wire         clk,
    input  wire         rst_n,

    input  wire         req_valid,
    output logic        req_ready,
    input  wire [127:0] req_public_seed,
    input  wire [255:0] req_address,
    input  wire [127:0] req_left_node,
    input  wire [127:0] req_right_node,

    output logic        rsp_valid,
    input  wire         rsp_ready,
    output logic [127:0] rsp_parent,
    output logic        rsp_error
);
    typedef enum logic [1:0] {S_IDLE, S_HASH, S_RESPONSE} state_t;
    state_t state;

    wire shake_ready;
    wire [255:0] shake_digest;
    wire shake_done;
    wire shake_error;
    wire shake_start;
    wire [7:0] shake_length;
    wire [1087:0] shake_message;

    assign req_ready = (state == S_IDLE) && shake_ready;
    assign shake_start = req_valid && req_ready;
    assign shake_length = 8'd80;
    assign shake_message = {
        448'b0,
        req_right_node,
        req_left_node,
        req_address,
        req_public_seed
    };
    assign rsp_valid = (state == S_RESPONSE);

    micro_hbs_shake256_single_block #(.UNROLL(UNROLL)) shake_lane (
        .clk,
        .rst_n,
        .start(shake_start),
        .ready(shake_ready),
        .message(shake_message),
        .message_length(shake_length),
        .repeat_enable(1'b0), .repeat_prefix(1'b0),
        .repeat_prefix_preserve_counter(1'b0),
        .repeat_prefix_domain(3'b0), .repeat_count(8'd1),
        .repeat_counter_offset(8'b0), .repeat_feedback_offset(8'b0),
        .repeat_feedback_bytes(6'b0), .repeat_counter_start(32'b0),
        .capture_enable(1'b0), .capture_after(8'b0),
        .capture_digest(), .capture_valid(),
        .digest(shake_digest),
        .done(shake_done),
        .error(shake_error)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            rsp_parent <= '0;
            rsp_error <= 1'b0;
        end else begin
            case (state)
                S_IDLE: begin
                    if (shake_start) begin
                        rsp_parent <= '0;
                        rsp_error <= 1'b0;
                        state <= S_HASH;
                    end
                end

                S_HASH: begin
                    if (shake_error) begin
                        rsp_parent <= '0;
                        rsp_error <= 1'b1;
                        state <= S_RESPONSE;
                    end else if (shake_done) begin
                        rsp_parent <= shake_digest[127:0];
                        rsp_error <= 1'b0;
                        state <= S_RESPONSE;
                    end
                end

                S_RESPONSE: begin
                    if (rsp_ready) begin
                        rsp_parent <= '0;
                        rsp_error <= 1'b0;
                        state <= S_IDLE;
                    end
                end

                default: begin
                    rsp_parent <= '0;
                    rsp_error <= 1'b1;
                    state <= S_RESPONSE;
                end
            endcase
        end
    end
endmodule

`default_nettype wire
