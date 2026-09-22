`timescale 1ns/1ps
`default_nettype none

// Volatile leaf-index guard.  A signing request is released only after the
// caller acknowledges durable persistence of q+1.  Once acknowledged, an
// aborted or failed signature burns the index instead of rolling it back.
module uhbs_stateful_index_guard #(
    parameter integer TREE_HEIGHT = 10
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        initialize_valid,
    output wire        initialize_ready,
    input  wire [10:0] initial_q,
    input  wire        invalidate,

    input  wire        sign_valid,
    output wire        sign_ready,
    output logic       sign_grant,
    output logic [9:0] sign_q,

    output logic        state_commit_valid,
    input  wire         state_commit_ready,
    output logic [10:0] state_next_q,

    output logic        initialized,
    output logic [10:0] current_q,
    output logic        error,
    output logic [15:0] error_code
);
    localparam integer LEAF_COUNT = 1 << TREE_HEIGHT;
    localparam logic [15:0] ERR_NOT_INITIALIZED = 16'h2501;
    localparam logic [15:0] ERR_EXHAUSTED       = 16'h2502;
    localparam logic [15:0] ERR_INITIAL_Q       = 16'h2503;

    typedef enum logic {S_IDLE, S_COMMIT} state_t;
    state_t state;
    logic [9:0] reserved_q;

    assign initialize_ready = state == S_IDLE;
    assign sign_ready = state == S_IDLE;

    initial begin
        if (TREE_HEIGHT != 10)
            $error("stateful index guard currently fixes h=10");
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            reserved_q <= '0;
            sign_grant <= 1'b0;
            sign_q <= '0;
            state_commit_valid <= 1'b0;
            state_next_q <= '0;
            initialized <= 1'b0;
            current_q <= '0;
            error <= 1'b0;
            error_code <= '0;
        end else begin
            sign_grant <= 1'b0;

            if (invalidate) begin
                state <= S_IDLE;
                state_commit_valid <= 1'b0;
                initialized <= 1'b0;
            end else if (initialize_valid && initialize_ready) begin
                if (initial_q > LEAF_COUNT) begin
                    initialized <= 1'b0;
                    error <= 1'b1;
                    error_code <= ERR_INITIAL_Q;
                end else begin
                    current_q <= initial_q;
                    initialized <= 1'b1;
                    error <= 1'b0;
                    error_code <= '0;
                end
            end else case (state)
                S_IDLE: begin
                    state_commit_valid <= 1'b0;
                    if (sign_valid) begin
                        if (!initialized) begin
                            error <= 1'b1;
                            error_code <= ERR_NOT_INITIALIZED;
                        end else if (current_q >= LEAF_COUNT) begin
                            error <= 1'b1;
                            error_code <= ERR_EXHAUSTED;
                        end else begin
                            reserved_q <= current_q[9:0];
                            state_next_q <= current_q + 1'b1;
                            state_commit_valid <= 1'b1;
                            state <= S_COMMIT;
                            error <= 1'b0;
                            error_code <= '0;
                        end
                    end
                end
                S_COMMIT: begin
                    if (state_commit_valid && state_commit_ready) begin
                        current_q <= state_next_q;
                        sign_q <= reserved_q;
                        sign_grant <= 1'b1;
                        state_commit_valid <= 1'b0;
                        state <= S_IDLE;
                    end
                end
                default: state <= S_IDLE;
            endcase
        end
    end
endmodule

`default_nettype wire
