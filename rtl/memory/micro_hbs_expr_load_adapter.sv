`timescale 1ns/1ps
`default_nettype none

// Static descriptor adapter for generic 32-bit postfix-expression LOADs.
// Descriptor format:
// [63:56] version=1, [55:48] token start, [47:40] token count,
// [39] destination is register, [38:36] destination register,
// [35:20] destination Scratchpad word, [19:15] output bytes,
// [14:0] reserved.
module micro_hbs_expr_load_adapter #(
    parameter integer DESCRIPTOR_COUNT = 16,
    parameter integer TOKEN_WORDS = 64,
    parameter integer SCRATCH_WORDS = 1024,
    parameter integer ADDRESS_WIDTH = 16
) (
    input  wire                         clk,
    input  wire                         rst_n,
    input  wire                         engine_busy,
    input  wire                         descriptor_cfg_valid,
    output wire                         descriptor_cfg_ready,
    input  wire [15:0]                  descriptor_cfg_id,
    input  wire [63:0]                  descriptor_cfg_data,
    output logic                        descriptor_cfg_error,
    output logic [15:0]                 descriptor_cfg_error_code,
    input  wire                         token_cfg_valid,
    output wire                         token_cfg_ready,
    input  wire [$clog2(TOKEN_WORDS)-1:0] token_cfg_index,
    input  wire [63:0]                  token_cfg_data,

    input  wire                         cmd_valid,
    output wire                         cmd_ready,
    input  wire [7:0]                   cmd_opcode,
    input  wire [31:0]                  cmd_imm,
    input  wire [255:0]                 cmd_registers,
    output wire                         cmd_match,
    output wire                         rsp_valid,
    input  wire                         rsp_ready,
    output logic                        rsp_error,
    output logic [15:0]                 rsp_error_code,
    output logic                        rsp_reg_write,
    output logic [7:0]                  rsp_reg_index,
    output logic [31:0]                 rsp_reg_value,

    output wire                         scratch_request_valid,
    input  wire                         scratch_request_ready,
    output wire                         scratch_request_write,
    output wire [ADDRESS_WIDTH-1:0]     scratch_request_address,
    output logic [63:0]                 scratch_request_write_data,
    output wire                         busy,
    output logic [31:0]                 accepted_commands
);
    localparam logic [7:0] OP_LOAD = 8'h08;
    localparam logic [15:0] ERR_CFG_BUSY = 16'h0f01;
    localparam logic [15:0] ERR_CFG_ID   = 16'h0f02;
    localparam logic [15:0] ERR_CFG_FMT  = 16'h0f03;
    localparam logic [15:0] ERR_CFG_DUP  = 16'h0f04;
    localparam logic [15:0] ERR_COMMAND  = 16'h0f05;
    localparam logic [15:0] ERR_RESULT   = 16'h0f06;
    localparam integer INDEX_WIDTH = DESCRIPTOR_COUNT <= 2
        ? 1 : $clog2(DESCRIPTOR_COUNT);

    typedef enum logic [2:0] {
        S_IDLE, S_LAUNCH, S_WAIT, S_WRITE, S_RESPONSE
    } state_t;
    state_t state;
    logic [63:0] descriptors [0:DESCRIPTOR_COUNT-1];
    logic [DESCRIPTOR_COUNT-1:0] configured;
    logic [63:0] active;
    logic [255:0] saved_registers;
    logic [31:0] result_latched;
    integer byte_index;
    integer result_byte_index;

    wire [7:0] d_start_pc = active[55:48];
    wire [7:0] d_token_count = active[47:40];
    wire d_dest_is_reg = active[39];
    wire [2:0] d_dest_reg = active[38:36];
    wire [15:0] d_destination = active[35:20];
    wire [4:0] d_output_bytes = active[19:15];
    wire expr_cfg_ready;
    wire expr_busy, expr_done, expr_error;
    wire [15:0] expr_error_code;
    wire [31:0] expr_result;

    assign descriptor_cfg_ready = !engine_busy && state == S_IDLE;
    assign token_cfg_ready = !engine_busy && state == S_IDLE && expr_cfg_ready;
    assign cmd_ready = state == S_IDLE;
    assign cmd_match = cmd_opcode == OP_LOAD && cmd_imm < DESCRIPTOR_COUNT
        && configured[cmd_imm[INDEX_WIDTH-1:0]];
    assign busy = state != S_IDLE;
    assign rsp_valid = state == S_RESPONSE;
    assign scratch_request_valid = state == S_WRITE;
    assign scratch_request_write = 1'b1;
    assign scratch_request_address = d_destination[ADDRESS_WIDTH-1:0];

    always_comb begin
        scratch_request_write_data = '0;
        for (byte_index = 0; byte_index < 8; byte_index = byte_index + 1) begin
            result_byte_index = d_output_bytes - 1 - byte_index;
            if (byte_index < d_output_bytes && result_byte_index >= 0
                && result_byte_index < 4)
                scratch_request_write_data[8*byte_index +: 8]
                    = result_latched >> (8*result_byte_index);
        end
    end

    micro_hbs_layout_expr #(
        .VALUE_W(32), .TOKEN_WORDS(TOKEN_WORDS), .STACK_DEPTH(8)
    ) expression (
        .clk, .rst_n,
        .cfg_valid(token_cfg_valid && token_cfg_ready),
        .cfg_ready(expr_cfg_ready), .cfg_index(token_cfg_index),
        .cfg_token(token_cfg_data), .start(state == S_LAUNCH),
        .start_pc(d_start_pc[$clog2(TOKEN_WORDS)-1:0]),
        .token_count(d_token_count[$clog2(TOKEN_WORDS+1)-1:0]),
        .registers_flat(saved_registers), .operands_flat('0),
        .contexts_flat('0), .busy(expr_busy), .done(expr_done),
        .error(expr_error), .error_code(expr_error_code),
        .result(expr_result), .retired_tokens(), .host_writes_busy()
    );

    always_ff @(posedge clk) begin
        if (descriptor_cfg_valid && descriptor_cfg_ready
            && descriptor_cfg_id < DESCRIPTOR_COUNT
            && descriptor_cfg_data[63:56] == 8'h01
            && descriptor_cfg_data[14:0] == 0)
            descriptors[descriptor_cfg_id[INDEX_WIDTH-1:0]]
                <= descriptor_cfg_data;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            configured <= '0;
            active <= '0;
            saved_registers <= '0;
            result_latched <= '0;
            descriptor_cfg_error <= 1'b0;
            descriptor_cfg_error_code <= '0;
            rsp_error <= 1'b0;
            rsp_error_code <= '0;
            rsp_reg_write <= 1'b0;
            rsp_reg_index <= '0;
            rsp_reg_value <= '0;
            accepted_commands <= '0;
        end else begin
            descriptor_cfg_error <= 1'b0;
            descriptor_cfg_error_code <= '0;
            if (descriptor_cfg_valid) begin
                if (!descriptor_cfg_ready) begin
                    descriptor_cfg_error <= 1'b1;
                    descriptor_cfg_error_code <= ERR_CFG_BUSY;
                end else if (descriptor_cfg_id >= DESCRIPTOR_COUNT) begin
                    descriptor_cfg_error <= 1'b1;
                    descriptor_cfg_error_code <= ERR_CFG_ID;
                end else if (descriptor_cfg_data[63:56] != 8'h01
                             || descriptor_cfg_data[14:0] != 0
                             || descriptor_cfg_data[47:40] == 0) begin
                    descriptor_cfg_error <= 1'b1;
                    descriptor_cfg_error_code <= ERR_CFG_FMT;
                end else if (configured[descriptor_cfg_id[INDEX_WIDTH-1:0]]) begin
                    descriptor_cfg_error <= 1'b1;
                    descriptor_cfg_error_code <= ERR_CFG_DUP;
                end else
                    configured[descriptor_cfg_id[INDEX_WIDTH-1:0]] <= 1'b1;
            end

            case (state)
                S_IDLE: if (cmd_valid) begin
                    accepted_commands <= accepted_commands + 1'b1;
                    rsp_error <= 1'b0;
                    rsp_error_code <= '0;
                    rsp_reg_write <= 1'b0;
                    if (cmd_opcode != OP_LOAD || !cmd_match) begin
                        rsp_error <= 1'b1;
                        rsp_error_code <= ERR_COMMAND;
                        state <= S_RESPONSE;
                    end else begin
                        active <= descriptors[cmd_imm[INDEX_WIDTH-1:0]];
                        saved_registers <= cmd_registers;
                        state <= S_LAUNCH;
                    end
                end
                S_LAUNCH: state <= S_WAIT;
                S_WAIT: begin
                    if (expr_error) begin
                        rsp_error <= 1'b1;
                        rsp_error_code <= expr_error_code;
                        state <= S_RESPONSE;
                    end else if (expr_done) begin
                        result_latched <= expr_result;
                        if (d_dest_is_reg) begin
                            rsp_reg_write <= 1'b1;
                            rsp_reg_index <= {5'b0, d_dest_reg};
                            rsp_reg_value <= expr_result;
                            state <= S_RESPONSE;
                        end else if (d_output_bytes == 0
                                     || d_output_bytes > 4
                                     || d_destination >= SCRATCH_WORDS) begin
                            rsp_error <= 1'b1;
                            rsp_error_code <= ERR_RESULT;
                            state <= S_RESPONSE;
                        end else
                            state <= S_WRITE;
                    end
                end
                S_WRITE: if (scratch_request_ready)
                    state <= S_RESPONSE;
                S_RESPONSE: if (rsp_ready) begin
                    rsp_error <= 1'b0;
                    rsp_error_code <= '0;
                    rsp_reg_write <= 1'b0;
                    state <= S_IDLE;
                end
                default: begin
                    rsp_error <= 1'b1;
                    rsp_error_code <= ERR_COMMAND;
                    state <= S_RESPONSE;
                end
            endcase
        end
    end
endmodule

`default_nettype wire
