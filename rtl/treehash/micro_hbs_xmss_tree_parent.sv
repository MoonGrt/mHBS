`timescale 1ns/1ps
`default_nettype none

// RFC 8391 XMSS randomized tree-parent H for SHAKE256 with n=32.
//
// Packed byte strings use the repository convention: byte zero occupies bits
// [7:0].  The supplied ADRS is passed to the shared randomized-hash composer;
// that composer derives KEY, BM_0, and BM_1 by setting keyAndMask to 0, 1,
// and 2, respectively.  No algorithm-specific sequencer operation is needed.
//
// One request may be outstanding.  A response is buffered until rsp_ready,
// keeping both value and error stable under response backpressure.  On any
// internal hash error, rsp_parent is forced to zero (fail closed).
module micro_hbs_xmss_tree_parent #(
    parameter integer UNROLL = 2
) (
    input  wire         clk,
    input  wire         rst_n,

    input  wire         req_valid,
    output logic        req_ready,
    input  wire [255:0] req_public_seed,
    input  wire [255:0] req_address,
    input  wire [255:0] req_left_node,
    input  wire [255:0] req_right_node,

    output logic        rsp_valid,
    input  wire         rsp_ready,
    output logic [255:0] rsp_parent,
    output logic        rsp_error
);
    typedef enum logic [1:0] {S_IDLE, S_HASH, S_RESPONSE} state_t;
    state_t state;

    wire hash_ready;
    wire [255:0] hash_digest;
    wire hash_done;
    wire hash_error;
    wire [2:0] hash_calls;
    wire hash_start;

    assign req_ready = (state == S_IDLE) && hash_ready;
    assign hash_start = req_valid && req_ready;
    assign rsp_valid = (state == S_RESPONSE);

    micro_hbs_randomized_hash #(
        .NODE_COUNT(2),
        .UNROLL(UNROLL)
    ) randomized_h (
        .clk,
        .rst_n,
        .start(hash_start),
        .ready(hash_ready),
        .pub_seed(req_public_seed),
        .address(req_address),
        .node_data({req_right_node, req_left_node}),
        .digest(hash_digest),
        .done(hash_done),
        .error(hash_error),
        .hash_calls(hash_calls)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            rsp_parent <= '0;
            rsp_error <= 1'b0;
        end else begin
            case (state)
                S_IDLE: begin
                    if (hash_start) begin
                        // Clear stale response information as soon as the
                        // next accepted transaction becomes active.
                        rsp_parent <= '0;
                        rsp_error <= 1'b0;
                        state <= S_HASH;
                    end
                end

                S_HASH: begin
                    if (hash_error) begin
                        rsp_parent <= '0;
                        rsp_error <= 1'b1;
                        state <= S_RESPONSE;
                    end else if (hash_done) begin
                        rsp_parent <= hash_digest;
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
