`timescale 1ns/1ps
`default_nettype none

// HASH_LAYOUT capability adapter for a complete RFC 8391 WOTS+ leaf.
// Layout 0x0200 writes the generated 32-byte leaf to the fixed 32-byte logical
// node slot `destination`. `index_value` selects the XMSS leaf identity, not a
// storage offset. Sequential leaves therefore reuse one four-word buffer,
// preserving TREEHASH_MIN's O(tree height) storage boundary.
module micro_hbs_xmss_wots_leaf_scratch_adapter #(
    parameter integer SCRATCH_WORDS = 64,
    parameter integer UNROLL = 2
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         req_valid,
    output wire         req_ready,
    input  wire [15:0]  layout_id,
    input  wire [1:0]   lane_mask,
    input  wire [7:0]   destination,
    input  wire [31:0]  index_value,
    input  wire [255:0] sk_seed,
    input  wire [255:0] pub_seed,
    input  wire [255:0] address_template,
    output logic        rsp_valid,
    output logic        rsp_error,
    output logic [15:0] rsp_error_code,
    output logic        sp_req_valid,
    input  wire         sp_req_ready,
    output wire         sp_req_write,
    output logic [15:0] sp_req_address,
    output logic [63:0] sp_req_write_data,
    input  wire         sp_rsp_valid,
    input  wire         sp_rsp_error,
    output wire [31:0]  prf_keygen_calls,
    output wire [31:0]  chain_steps,
    output wire [31:0]  ltree_parents,
    output wire [31:0]  shake_calls,
    output logic [31:0] scratch_writes
);
    localparam logic [15:0] LAYOUT_XMSS_WOTS_LEAF = 16'h0200;
    localparam logic [15:0] ERR_UNSUPPORTED_LAYOUT = 16'h0101;
    localparam logic [15:0] ERR_BAD_LANE_MASK      = 16'h0103;
    localparam logic [15:0] ERR_SCRATCH_BOUNDS     = 16'h0201;
    localparam logic [15:0] ERR_LEAF_ENGINE        = 16'h0302;

    typedef enum logic [2:0] {
        S_IDLE, S_LEAF_REQ, S_LEAF_WAIT, S_WRITE_REQ, S_WRITE_WAIT
    } state_t;
    state_t state;
    logic [31:0] saved_index;
    logic [15:0] saved_base_word;
    logic [1:0] word_index;
    logic [255:0] saved_leaf;
    wire leaf_req_ready, leaf_rsp_valid, leaf_rsp_error;
    wire [255:0] generated_leaf;
    wire [17:0] requested_base_word;
    wire request_in_bounds;

    assign requested_base_word = {10'b0, destination} * 4;
    assign request_in_bounds = (requested_base_word + 4 <= SCRATCH_WORDS);
    assign req_ready = (state == S_IDLE);
    assign sp_req_write = 1'b1;

    micro_hbs_xmss_wots_leaf #(.UNROLL(UNROLL)) leaf_engine (
        .clk, .rst_n, .req_valid(state == S_LEAF_REQ),
        .req_ready(leaf_req_ready), .sk_seed, .pub_seed, .address_template,
        .leaf_index(saved_index), .rsp_valid(leaf_rsp_valid),
        .rsp_ready(state == S_LEAF_WAIT), .leaf(generated_leaf),
        .rsp_error(leaf_rsp_error), .prf_keygen_calls, .chain_steps,
        .ltree_parents, .shake_calls
    );

    always_comb begin
        sp_req_valid = (state == S_WRITE_REQ);
        sp_req_address = saved_base_word + word_index;
        sp_req_write_data = saved_leaf[64*word_index +: 64];
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            saved_index <= '0;
            saved_base_word <= '0;
            word_index <= '0;
            saved_leaf <= '0;
            rsp_valid <= 1'b0;
            rsp_error <= 1'b0;
            rsp_error_code <= '0;
            scratch_writes <= '0;
        end else begin
            rsp_valid <= 1'b0;
            rsp_error <= 1'b0;
            rsp_error_code <= '0;
            case (state)
                S_IDLE: if (req_valid) begin
                    if (layout_id != LAYOUT_XMSS_WOTS_LEAF) begin
                        rsp_valid <= 1'b1;
                        rsp_error <= 1'b1;
                        rsp_error_code <= ERR_UNSUPPORTED_LAYOUT;
                    end else if (lane_mask != 2'b01) begin
                        rsp_valid <= 1'b1;
                        rsp_error <= 1'b1;
                        rsp_error_code <= ERR_BAD_LANE_MASK;
                    end else if (!request_in_bounds) begin
                        rsp_valid <= 1'b1;
                        rsp_error <= 1'b1;
                        rsp_error_code <= ERR_SCRATCH_BOUNDS;
                    end else begin
                        saved_index <= index_value;
                        saved_base_word <= requested_base_word[15:0];
                        state <= S_LEAF_REQ;
                    end
                end

                S_LEAF_REQ: if (leaf_req_ready) state <= S_LEAF_WAIT;
                S_LEAF_WAIT: if (leaf_rsp_valid) begin
                    if (leaf_rsp_error) begin
                        rsp_valid <= 1'b1;
                        rsp_error <= 1'b1;
                        rsp_error_code <= ERR_LEAF_ENGINE;
                        state <= S_IDLE;
                    end else begin
                        saved_leaf <= generated_leaf;
                        word_index <= '0;
                        state <= S_WRITE_REQ;
                    end
                end

                S_WRITE_REQ: if (sp_req_ready) state <= S_WRITE_WAIT;
                S_WRITE_WAIT: if (sp_rsp_valid) begin
                    if (sp_rsp_error) begin
                        rsp_valid <= 1'b1;
                        rsp_error <= 1'b1;
                        rsp_error_code <= ERR_SCRATCH_BOUNDS;
                        state <= S_IDLE;
                    end else begin
                        scratch_writes <= scratch_writes + 1'b1;
                        if (word_index == 3) begin
                            rsp_valid <= 1'b1;
                            state <= S_IDLE;
                        end else begin
                            word_index <= word_index + 1'b1;
                            state <= S_WRITE_REQ;
                        end
                    end
                end

                default: begin
                    rsp_valid <= 1'b1;
                    rsp_error <= 1'b1;
                    rsp_error_code <= ERR_LEAF_ENGINE;
                    state <= S_IDLE;
                end
            endcase
        end
    end
endmodule

`default_nettype wire
