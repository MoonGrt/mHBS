`timescale 1ns/1ps
`default_nettype none

// Converts generic TreeHash merge context into an RFC 8391 hash-tree ADRS and
// invokes the shared XMSS randomized-H parent capability.  parent_height is
// the produced node height, so ADRS treeHeight is parent_height-1 and ADRS
// treeIndex is start_leaf >> parent_height.
module micro_hbs_xmss_tree_parent_context #(
    parameter integer UNROLL = 2
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire [255:0] public_seed,
    input  wire [255:0] address_template,
    input  wire         req_valid,
    output wire         req_ready,
    input  wire [7:0]   req_parent_height,
    input  wire [15:0]  req_start_leaf,
    input  wire [255:0] req_left_node,
    input  wire [255:0] req_right_node,
    output wire         rsp_valid,
    output wire [255:0] rsp_parent,
    output wire         rsp_error
);
    typedef enum logic [1:0] {S_IDLE, S_PARENT, S_ERROR} state_t;
    state_t state;

    logic [255:0] xmss_address;
    logic [16:0] alignment_mask;
    logic [15:0] parent_index;
    logic context_valid;
    wire parent_req_ready;
    wire parent_rsp_valid, parent_rsp_error;
    wire [255:0] parent_rsp_value;

    always_comb begin
        alignment_mask = 17'b0;
        if (req_parent_height >= 1 && req_parent_height <= 15)
            alignment_mask = (17'h1 << req_parent_height) - 1'b1;
        parent_index = req_start_leaf >> req_parent_height;
        context_valid = req_parent_height >= 1
            && req_parent_height <= 15
            && (({1'b0, req_start_leaf} & alignment_mask) == 0);

        xmss_address = address_template;
        // Clear words 3..7, then encode big-endian 32-bit ADRS words:
        // type=2, OTS address=0, treeHeight, treeIndex, keyAndMask=0.
        xmss_address[8*12 +: 8*20] = 160'b0;
        xmss_address[8*15 +: 8] = 8'h02;
        xmss_address[8*23 +: 8] = req_parent_height - 1'b1;
        xmss_address[8*26 +: 8] = parent_index[15:8];
        xmss_address[8*27 +: 8] = parent_index[7:0];
    end

    assign req_ready = (state == S_IDLE)
        && (context_valid ? parent_req_ready : 1'b1);
    assign rsp_valid = (state == S_ERROR) ||
        (state == S_PARENT && parent_rsp_valid);
    assign rsp_parent = (state == S_PARENT && parent_rsp_valid
                         && !parent_rsp_error)
        ? parent_rsp_value : 256'b0;
    assign rsp_error = (state == S_ERROR)
        || (state == S_PARENT && parent_rsp_valid && parent_rsp_error);

    micro_hbs_xmss_tree_parent #(.UNROLL(UNROLL)) parent (
        .clk, .rst_n,
        .req_valid(state == S_IDLE && req_valid && context_valid),
        .req_ready(parent_req_ready), .req_public_seed(public_seed),
        .req_address(xmss_address), .req_left_node, .req_right_node,
        .rsp_valid(parent_rsp_valid), .rsp_ready(state == S_PARENT),
        .rsp_parent(parent_rsp_value), .rsp_error(parent_rsp_error)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            state <= S_IDLE;
        else case (state)
            S_IDLE: begin
                if (req_valid && req_ready)
                    state <= context_valid ? S_PARENT : S_ERROR;
            end
            S_PARENT: begin
                if (parent_rsp_valid)
                    state <= S_IDLE;
            end
            S_ERROR: state <= S_IDLE;
            default: state <= S_ERROR;
        endcase
    end
endmodule

`default_nettype wire
