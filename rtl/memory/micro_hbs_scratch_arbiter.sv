`timescale 1ns/1ps
`default_nettype none

// Fixed-priority arbiter for three internal clients sharing one synchronous,
// single-port Scratchpad.  Priority is DATA ALU > EMIT > TreeHash.
//
// There is no request queue and no run-time scheduling policy.  When the
// Scratchpad applies backpressure, only the selected owner is locked; that
// client must retain valid and payload according to the usual valid/ready
// contract.  After the Scratchpad accepts a request, exactly one transaction is
// outstanding until its registered response is consumed by that owner.
//
// micro_hbs_scratchpad64 produces response_valid only for reads and reports a
// write bounds error in the cycle after request acceptance.  Accordingly, a
// write generates a registered success response after that check cycle.
module micro_hbs_scratch_arbiter #(
    parameter integer ADDRESS_WIDTH = 16
) (
    input  wire                     clk,
    input  wire                     rst_n,

    input  wire                     alu_request_valid,
    output logic                    alu_request_ready,
    input  wire                     alu_request_write,
    input  wire [ADDRESS_WIDTH-1:0] alu_request_address,
    input  wire [63:0]              alu_request_write_data,
    output logic                    alu_response_valid,
    input  wire                     alu_response_ready,
    output logic [63:0]             alu_response_read_data,
    output logic                    alu_response_error,

    input  wire                     emit_request_valid,
    output logic                    emit_request_ready,
    input  wire                     emit_request_write,
    input  wire [ADDRESS_WIDTH-1:0] emit_request_address,
    input  wire [63:0]              emit_request_write_data,
    output logic                    emit_response_valid,
    input  wire                     emit_response_ready,
    output logic [63:0]             emit_response_read_data,
    output logic                    emit_response_error,

    input  wire                     tree_request_valid,
    output logic                    tree_request_ready,
    input  wire                     tree_request_write,
    input  wire [ADDRESS_WIDTH-1:0] tree_request_address,
    input  wire [63:0]              tree_request_write_data,
    output logic                    tree_response_valid,
    input  wire                     tree_response_ready,
    output logic [63:0]             tree_response_read_data,
    output logic                    tree_response_error,

    output logic                    scratch_request_valid,
    input  wire                     scratch_request_ready,
    output logic                    scratch_request_write,
    output logic [ADDRESS_WIDTH-1:0] scratch_request_address,
    output logic [63:0]             scratch_request_write_data,
    input  wire                     scratch_response_valid,
    input  wire [63:0]              scratch_response_read_data,
    input  wire                     scratch_bounds_error,

    output logic                    busy,
    output logic                    outstanding,
    output logic [1:0]              active_owner,
    output logic [31:0]             alu_grants,
    output logic [31:0]             emit_grants,
    output logic [31:0]             tree_grants,
    output logic [31:0]             accepted_transactions,
    output logic [31:0]             completed_transactions,
    output logic [31:0]             error_transactions
);
    localparam logic [1:0] OWNER_ALU  = 2'd0;
    localparam logic [1:0] OWNER_EMIT = 2'd1;
    localparam logic [1:0] OWNER_TREE = 2'd2;
    localparam logic [1:0] OWNER_NONE = 2'd3;

    typedef enum logic [1:0] {S_IDLE, S_REQUEST, S_WAIT, S_RESPONSE} state_t;
    state_t state;
    logic [1:0] owner;
    logic owner_write;
    logic [63:0] response_data;
    logic response_error;
    logic [1:0] selected_owner;
    logic selected_valid;
    logic selected_write;
    logic [ADDRESS_WIDTH-1:0] selected_address;
    logic [63:0] selected_write_data;
    logic owner_response_ready;

    initial begin
        if (ADDRESS_WIDTH < 1 || ADDRESS_WIDTH > 16)
            $error("ADDRESS_WIDTH must be in 1..16");
    end

    // This priority encoder is the entire arbitration policy.
    always_comb begin
        selected_owner = OWNER_NONE;
        selected_valid = 1'b0;
        selected_write = 1'b0;
        selected_address = '0;
        selected_write_data = '0;
        if (alu_request_valid) begin
            selected_owner = OWNER_ALU;
            selected_valid = 1'b1;
            selected_write = alu_request_write;
            selected_address = alu_request_address;
            selected_write_data = alu_request_write_data;
        end else if (emit_request_valid) begin
            selected_owner = OWNER_EMIT;
            selected_valid = 1'b1;
            selected_write = emit_request_write;
            selected_address = emit_request_address;
            selected_write_data = emit_request_write_data;
        end else if (tree_request_valid) begin
            selected_owner = OWNER_TREE;
            selected_valid = 1'b1;
            selected_write = tree_request_write;
            selected_address = tree_request_address;
            selected_write_data = tree_request_write_data;
        end
    end

    always_comb begin
        alu_request_ready = 1'b0;
        emit_request_ready = 1'b0;
        tree_request_ready = 1'b0;
        scratch_request_valid = 1'b0;
        scratch_request_write = 1'b0;
        scratch_request_address = '0;
        scratch_request_write_data = '0;

        if (state == S_IDLE && selected_valid) begin
            scratch_request_valid = 1'b1;
            scratch_request_write = selected_write;
            scratch_request_address = selected_address;
            scratch_request_write_data = selected_write_data;
            case (selected_owner)
                OWNER_ALU: alu_request_ready = scratch_request_ready;
                OWNER_EMIT: emit_request_ready = scratch_request_ready;
                OWNER_TREE: tree_request_ready = scratch_request_ready;
                default: begin end
            endcase
        end else if (state == S_REQUEST) begin
            case (owner)
                OWNER_ALU: begin
                    scratch_request_valid = alu_request_valid;
                    scratch_request_write = alu_request_write;
                    scratch_request_address = alu_request_address;
                    scratch_request_write_data = alu_request_write_data;
                    alu_request_ready = scratch_request_ready;
                end
                OWNER_EMIT: begin
                    scratch_request_valid = emit_request_valid;
                    scratch_request_write = emit_request_write;
                    scratch_request_address = emit_request_address;
                    scratch_request_write_data = emit_request_write_data;
                    emit_request_ready = scratch_request_ready;
                end
                OWNER_TREE: begin
                    scratch_request_valid = tree_request_valid;
                    scratch_request_write = tree_request_write;
                    scratch_request_address = tree_request_address;
                    scratch_request_write_data = tree_request_write_data;
                    tree_request_ready = scratch_request_ready;
                end
                default: begin end
            endcase
        end
    end

    always_comb begin
        alu_response_valid = 1'b0;
        alu_response_read_data = '0;
        alu_response_error = 1'b0;
        emit_response_valid = 1'b0;
        emit_response_read_data = '0;
        emit_response_error = 1'b0;
        tree_response_valid = 1'b0;
        tree_response_read_data = '0;
        tree_response_error = 1'b0;
        owner_response_ready = 1'b0;

        if (state == S_RESPONSE) begin
            case (owner)
                OWNER_ALU: begin
                    alu_response_valid = 1'b1;
                    alu_response_read_data = response_data;
                    alu_response_error = response_error;
                    owner_response_ready = alu_response_ready;
                end
                OWNER_EMIT: begin
                    emit_response_valid = 1'b1;
                    emit_response_read_data = response_data;
                    emit_response_error = response_error;
                    owner_response_ready = emit_response_ready;
                end
                OWNER_TREE: begin
                    tree_response_valid = 1'b1;
                    tree_response_read_data = response_data;
                    tree_response_error = response_error;
                    owner_response_ready = tree_response_ready;
                end
                default: begin end
            endcase
        end
    end

    assign busy = (state != S_IDLE);
    assign outstanding = (state == S_WAIT) || (state == S_RESPONSE);
    assign active_owner = (state == S_IDLE) ? selected_owner
        : ((state == S_REQUEST || state == S_WAIT || state == S_RESPONSE)
            ? owner : OWNER_NONE);

    task automatic accept_transaction(input logic [1:0] grant_owner,
                                      input logic grant_write);
        begin
            owner <= grant_owner;
            owner_write <= grant_write;
            accepted_transactions <= accepted_transactions + 1'b1;
            case (grant_owner)
                OWNER_ALU: alu_grants <= alu_grants + 1'b1;
                OWNER_EMIT: emit_grants <= emit_grants + 1'b1;
                OWNER_TREE: tree_grants <= tree_grants + 1'b1;
                default: begin end
            endcase
            state <= S_WAIT;
        end
    endtask

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            owner <= OWNER_NONE;
            owner_write <= 1'b0;
            response_data <= '0;
            response_error <= 1'b0;
            alu_grants <= '0;
            emit_grants <= '0;
            tree_grants <= '0;
            accepted_transactions <= '0;
            completed_transactions <= '0;
            error_transactions <= '0;
        end else begin
            case (state)
                S_IDLE: begin
                    if (selected_valid) begin
                        owner <= selected_owner;
                        if (scratch_request_ready) begin
                            accept_transaction(selected_owner, selected_write);
                        end else begin
                            state <= S_REQUEST;
                        end
                    end
                end

                S_REQUEST: begin
                    if (scratch_request_valid && scratch_request_ready)
                        accept_transaction(owner, scratch_request_write);
                end

                S_WAIT: begin
                    if (scratch_bounds_error) begin
                        response_data <= '0;
                        response_error <= 1'b1;
                        error_transactions <= error_transactions + 1'b1;
                        state <= S_RESPONSE;
                    end else if (scratch_response_valid) begin
                        response_data <= scratch_response_read_data;
                        response_error <= 1'b0;
                        state <= S_RESPONSE;
                    end else if (owner_write) begin
                        response_data <= '0;
                        response_error <= 1'b0;
                        state <= S_RESPONSE;
                    end
                end

                S_RESPONSE: begin
                    if (owner_response_ready) begin
                        completed_transactions <= completed_transactions + 1'b1;
                        owner <= OWNER_NONE;
                        owner_write <= 1'b0;
                        response_data <= '0;
                        response_error <= 1'b0;
                        state <= S_IDLE;
                    end
                end

                default: begin
                    owner <= OWNER_NONE;
                    owner_write <= 1'b0;
                    response_data <= '0;
                    response_error <= 1'b0;
                    state <= S_IDLE;
                end
            endcase
        end
    end
endmodule

`default_nettype wire
