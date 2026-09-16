`timescale 1ns/1ps
`default_nettype none

// RFC 8554 LMS SHA256/256 internal-node composer.
// Preimage: I || u32(r) || u16(D_INTR) || left || right, D_INTR = 0x8383.
// Packed byte zero is in bits [7:0]; r is serialized most-significant byte
// first as required by RFC 8554.  SHA-256 response flow control and storage
// are supplied by the bounded lane, making this wrapper purely compositional.
module micro_hbs_lms_tree_parent (
    input  wire         clk,
    input  wire         rst_n,

    input  wire         req_valid,
    output logic        req_ready,
    input  wire [127:0] req_identifier,
    input  wire [31:0]  req_node_number,
    input  wire [255:0] req_left_node,
    input  wire [255:0] req_right_node,

    output logic        rsp_valid,
    input  wire         rsp_ready,
    output logic [255:0] rsp_parent,
    output logic        rsp_error
);
    logic [951:0] hash_message;
    wire hash_req_ready;
    wire hash_rsp_valid;
    wire [255:0] hash_rsp_digest;
    wire hash_rsp_error;

    always @* begin
        hash_message = '0;
        hash_message[0 +: 128] = req_identifier;
        hash_message[8*16 +: 8] = req_node_number[31:24];
        hash_message[8*17 +: 8] = req_node_number[23:16];
        hash_message[8*18 +: 8] = req_node_number[15:8];
        hash_message[8*19 +: 8] = req_node_number[7:0];
        hash_message[8*20 +: 8] = 8'h83;
        hash_message[8*21 +: 8] = 8'h83;
        hash_message[8*22 +: 256] = req_left_node;
        hash_message[8*54 +: 256] = req_right_node;
    end

    assign req_ready = hash_req_ready;
    assign rsp_valid = hash_rsp_valid;
    assign rsp_parent = hash_rsp_error ? 256'b0 : hash_rsp_digest;
    assign rsp_error = hash_rsp_error;

    micro_hbs_sha256_bounded sha256 (
        .clk,
        .rst_n,
        .req_valid,
        .req_ready(hash_req_ready),
        .req_message(hash_message),
        .req_length(7'd86),
        .rsp_valid(hash_rsp_valid),
        .rsp_ready,
        .rsp_digest(hash_rsp_digest),
        .rsp_error(hash_rsp_error)
    );
endmodule

`default_nettype wire
