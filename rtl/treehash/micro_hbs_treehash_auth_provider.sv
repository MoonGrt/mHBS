`timescale 1ns/1ps
`default_nettype none

// Autonomous cache-first authentication-path provider.  One start command
// supplies only target_leaf.  The provider derives every sibling identity as
//   (height, (((target_leaf >> height) ^ 1) << height))
// and never accepts per-level addresses from software.
module micro_hbs_treehash_auth_provider #(
    parameter integer TREE_HEIGHT = 10
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         start,
    output wire         ready,
    input  wire [15:0]  target_leaf,

    output wire         cache_lookup_valid,
    input  wire         cache_lookup_ready,
    output wire [7:0]   cache_lookup_height,
    output wire [15:0]  cache_lookup_start_leaf,
    input  wire         cache_rsp_valid,
    input  wire         cache_hit,
    input  wire [255:0] cache_value,
    input  wire         cache_bounds_error,

    output wire         recompute_req_valid,
    input  wire         recompute_req_ready,
    output wire [7:0]   recompute_req_height,
    output wire [15:0]  recompute_req_start_leaf,
    input  wire         recompute_rsp_valid,
    input  wire [255:0] recompute_rsp_value,
    input  wire         recompute_rsp_error,

    output logic        auth_valid,
    input  wire         auth_ready,
    output logic [7:0]  auth_level,
    output logic [255:0] auth_node,
    output logic        done,
    output wire         busy,
    output logic        error,
    output logic [15:0] error_code,
    output logic [31:0] cache_hits,
    output logic [31:0] cache_misses,
    output logic [31:0] recompute_requests,
    output logic [31:0] cycles
);
    localparam logic [15:0] ERR_TARGET_RANGE = 16'h0221;
    localparam logic [15:0] ERR_CACHE_RESPONSE = 16'h0222;
    localparam logic [15:0] ERR_RECOMPUTE_RESPONSE = 16'h0223;
    localparam logic [15:0] ERR_INTERNAL_STATE = 16'h0224;
    localparam logic [7:0] LAST_LEVEL = 8'(TREE_HEIGHT-1);

    typedef enum logic [2:0] {
        S_IDLE,
        S_CACHE_REQ,
        S_CACHE_WAIT,
        S_RECOMPUTE_REQ,
        S_RECOMPUTE_WAIT,
        S_EMIT
    } state_t;
    state_t state;
    logic [15:0] target_leaf_latched;
    logic [7:0] current_level;
    logic [15:0] sibling_start_leaf;

    assign ready = (state == S_IDLE);
    assign busy = (state != S_IDLE);
    assign cache_lookup_valid = (state == S_CACHE_REQ);
    assign cache_lookup_height = current_level;
    assign cache_lookup_start_leaf = sibling_start_leaf;
    assign recompute_req_valid = (state == S_RECOMPUTE_REQ);
    assign recompute_req_height = current_level;
    assign recompute_req_start_leaf = sibling_start_leaf;

    always_comb begin
        sibling_start_leaf =
            (((target_leaf_latched >> current_level) ^ 16'd1) << current_level);
    end

    initial begin
        if (TREE_HEIGHT < 1 || TREE_HEIGHT > 15)
            $error("TREE_HEIGHT must be in 1..15");
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            target_leaf_latched <= '0;
            current_level <= '0;
            auth_valid <= 1'b0;
            auth_level <= '0;
            auth_node <= '0;
            done <= 1'b0;
            error <= 1'b0;
            error_code <= '0;
            cache_hits <= '0;
            cache_misses <= '0;
            recompute_requests <= '0;
            cycles <= '0;
        end else begin
            done <= 1'b0;
            if (state != S_IDLE)
                cycles <= cycles + 1'b1;

            case (state)
                S_IDLE: begin
                    auth_valid <= 1'b0;
                    if (start) begin
                        auth_level <= '0;
                        auth_node <= '0;
                        error <= 1'b0;
                        error_code <= '0;
                        cache_hits <= '0;
                        cache_misses <= '0;
                        recompute_requests <= '0;
                        cycles <= '0;
                        current_level <= '0;
                        target_leaf_latched <= target_leaf;
                        if (target_leaf >= (1 << TREE_HEIGHT)) begin
                            // No request or auth output can follow an invalid target.
                            error <= 1'b1;
                            error_code <= ERR_TARGET_RANGE;
                        end else begin
                            state <= S_CACHE_REQ;
                        end
                    end
                end

                S_CACHE_REQ: begin
                    if (cache_lookup_ready)
                        state <= S_CACHE_WAIT;
                end

                S_CACHE_WAIT: begin
                    if (cache_bounds_error) begin
                        auth_valid <= 1'b0;
                        auth_node <= '0;
                        error <= 1'b1;
                        error_code <= ERR_CACHE_RESPONSE;
                        state <= S_IDLE;
                    end else if (cache_rsp_valid) begin
                        if (cache_hit) begin
                            cache_hits <= cache_hits + 1'b1;
                            auth_level <= current_level;
                            auth_node <= cache_value;
                            auth_valid <= 1'b1;
                            state <= S_EMIT;
                        end else begin
                            cache_misses <= cache_misses + 1'b1;
                            state <= S_RECOMPUTE_REQ;
                        end
                    end
                end

                S_RECOMPUTE_REQ: begin
                    if (recompute_req_ready) begin
                        recompute_requests <= recompute_requests + 1'b1;
                        state <= S_RECOMPUTE_WAIT;
                    end
                end

                S_RECOMPUTE_WAIT: begin
                    if (recompute_rsp_error) begin
                        auth_valid <= 1'b0;
                        auth_node <= '0;
                        error <= 1'b1;
                        error_code <= ERR_RECOMPUTE_RESPONSE;
                        state <= S_IDLE;
                    end else if (recompute_rsp_valid) begin
                        auth_level <= current_level;
                        auth_node <= recompute_rsp_value;
                        auth_valid <= 1'b1;
                        state <= S_EMIT;
                    end
                end

                S_EMIT: begin
                    if (auth_valid && auth_ready) begin
                        auth_valid <= 1'b0;
                        if (current_level == LAST_LEVEL) begin
                            done <= 1'b1;
                            state <= S_IDLE;
                        end else begin
                            current_level <= current_level + 1'b1;
                            state <= S_CACHE_REQ;
                        end
                    end
                end

                default: begin
                    auth_valid <= 1'b0;
                    auth_node <= '0;
                    error <= 1'b1;
                    error_code <= ERR_INTERNAL_STATE;
                    state <= S_IDLE;
                end
            endcase
        end
    end
endmodule

`default_nettype wire
