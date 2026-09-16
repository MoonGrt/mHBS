`timescale 1ns/1ps
`default_nettype none

// Stateful-signature index protocol. Atomic durable storage is external; this
// block never releases an index until that storage acknowledges next_index.
module micro_hbs_state_manager (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         configure,
    input  wire [31:0]  recovered_next_index,
    input  wire [31:0]  recovery_floor,
    input  wire [31:0]  maximum_index_exclusive,
    output logic        configured,
    input  wire         reserve,
    output logic        reserve_ready,
    output logic        persist_req_valid,
    output logic [31:0] persist_next_index,
    input  wire         persist_ack,
    output logic        release_valid,
    output logic [31:0] release_index,
    input  wire         consume,
    input  wire         cancel,
    input  wire         soft_reset,
    output logic [31:0] next_index,
    output logic [31:0] burned_count,
    output logic [31:0] consumed_count,
    output logic        error,
    output logic [15:0] error_code
);
    localparam logic [15:0] ERR_ROLLBACK = 16'h0301;
    localparam logic [15:0] ERR_EXHAUSTED = 16'h0302;
    localparam logic [15:0] ERR_PROTOCOL = 16'h0303;

    typedef enum logic [1:0] {S_IDLE, S_WAIT_PERSIST, S_RELEASED} state_t;
    state_t state;
    logic [31:0] reserved_index;
    logic cancel_pending;

    assign reserve_ready = configured && !error && state == S_IDLE;
    assign persist_req_valid = state == S_WAIT_PERSIST;
    assign release_valid = state == S_RELEASED;
    assign release_index = reserved_index;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            configured <= 1'b0;
            next_index <= '0;
            reserved_index <= '0;
            persist_next_index <= '0;
            cancel_pending <= 1'b0;
            burned_count <= '0;
            consumed_count <= '0;
            error <= 1'b0;
            error_code <= '0;
        end else begin
            if (configure) begin
                if (state != S_IDLE) begin
                    error <= 1'b1;
                    error_code <= ERR_PROTOCOL;
                end else if (recovered_next_index < recovery_floor) begin
                    configured <= 1'b0;
                    error <= 1'b1;
                    error_code <= ERR_ROLLBACK;
                end else begin
                    configured <= 1'b1;
                    next_index <= recovered_next_index;
                    error <= 1'b0;
                    error_code <= '0;
                    burned_count <= '0;
                    consumed_count <= '0;
                end
            end else begin
                case (state)
                    S_IDLE: begin
                        cancel_pending <= 1'b0;
                        if (reserve && configured && !error) begin
                            if (next_index >= maximum_index_exclusive) begin
                                error <= 1'b1;
                                error_code <= ERR_EXHAUSTED;
                            end else begin
                                reserved_index <= next_index;
                                persist_next_index <= next_index + 1'b1;
                                state <= S_WAIT_PERSIST;
                            end
                        end else if (consume || persist_ack) begin
                            error <= 1'b1;
                            error_code <= ERR_PROTOCOL;
                        end
                    end
                    S_WAIT_PERSIST: begin
                        if (cancel || soft_reset)
                            cancel_pending <= 1'b1;
                        if (persist_ack) begin
                            next_index <= persist_next_index;
                            if (cancel_pending || cancel || soft_reset) begin
                                burned_count <= burned_count + 1'b1;
                                state <= S_IDLE;
                            end else begin
                                state <= S_RELEASED;
                            end
                        end
                        if (consume) begin
                            error <= 1'b1;
                            error_code <= ERR_PROTOCOL;
                        end
                    end
                    S_RELEASED: begin
                        if (consume) begin
                            consumed_count <= consumed_count + 1'b1;
                            state <= S_IDLE;
                        end else if (cancel || soft_reset) begin
                            burned_count <= burned_count + 1'b1;
                            state <= S_IDLE;
                        end else if (persist_ack || reserve) begin
                            error <= 1'b1;
                            error_code <= ERR_PROTOCOL;
                        end
                    end
                    default: begin
                        error <= 1'b1;
                        error_code <= ERR_PROTOCOL;
                        state <= S_IDLE;
                    end
                endcase
            end
        end
    end
endmodule

`default_nettype wire
