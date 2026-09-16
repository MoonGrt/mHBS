`timescale 1ns/1ps
`default_nettype none

// Bounded postfix-expression engine for versioned layout descriptors.
// Configuration is allowed only while idle; evaluation is fully autonomous.
module micro_hbs_layout_expr #(
    parameter integer VALUE_W = 288,
    parameter integer TOKEN_WORDS = 32,
    parameter integer STACK_DEPTH = 8
) (
    input  wire                         clk,
    input  wire                         rst_n,

    input  wire                         cfg_valid,
    output wire                         cfg_ready,
    input  wire [$clog2(TOKEN_WORDS)-1:0] cfg_index,
    input  wire [63:0]                  cfg_token,

    input  wire                         start,
    input  wire [$clog2(TOKEN_WORDS)-1:0] start_pc,
    input  wire [$clog2(TOKEN_WORDS+1)-1:0] token_count,
    input  wire [8*32-1:0]              registers_flat,
    input  wire [4*VALUE_W-1:0]         operands_flat,
    input  wire [4*32-1:0]              contexts_flat,

    output logic                        busy,
    output logic                        done,
    output logic                        error,
    output logic [15:0]                 error_code,
    output logic [VALUE_W-1:0]          result,
    output logic [31:0]                 retired_tokens,
    output logic [31:0]                 host_writes_busy
);
    localparam integer PC_W = $clog2(TOKEN_WORDS);
    localparam integer COUNT_W = $clog2(TOKEN_WORDS+1);
    localparam integer DEPTH_W = $clog2(STACK_DEPTH+1);

    localparam logic [7:0] OP_PUSH_IMM     = 8'h01;
    localparam logic [7:0] OP_PUSH_REG     = 8'h02;
    localparam logic [7:0] OP_PUSH_OPERAND = 8'h03;
    localparam logic [7:0] OP_PUSH_CONTEXT = 8'h04;
    localparam logic [7:0] OP_ADD          = 8'h10;
    localparam logic [7:0] OP_SUB          = 8'h11;
    localparam logic [7:0] OP_XOR          = 8'h12;
    localparam logic [7:0] OP_AND          = 8'h13;
    localparam logic [7:0] OP_OR           = 8'h14;
    localparam logic [7:0] OP_SHL          = 8'h15;
    localparam logic [7:0] OP_SHR          = 8'h16;

    localparam logic [15:0] ERR_IMAGE_WRITE_BUSY = 16'h0102;
    localparam logic [15:0] ERR_PROGRAM_BOUNDS   = 16'h0201;
    localparam logic [15:0] ERR_STACK_OVERFLOW   = 16'h0202;
    localparam logic [15:0] ERR_STACK_UNDERFLOW  = 16'h0203;
    localparam logic [15:0] ERR_ILLEGAL_TOKEN    = 16'h0204;
    localparam logic [15:0] ERR_SHIFT_RANGE      = 16'h0205;
    localparam logic [15:0] ERR_RESULT_DEPTH     = 16'h0206;
    localparam logic [15:0] ERR_ARITH_RANGE      = 16'h0207;

    typedef enum logic [1:0] {S_IDLE, S_RUN, S_FINAL} state_t;
    state_t state;
    logic [63:0] token_memory [0:TOKEN_WORDS-1];
    logic [VALUE_W-1:0] value_stack [0:STACK_DEPTH-1];
    logic [8*32-1:0] saved_registers;
    logic [4*VALUE_W-1:0] saved_operands;
    logic [4*32-1:0] saved_contexts;
    logic [PC_W-1:0] pc;
    logic [COUNT_W-1:0] remaining;
    logic [DEPTH_W-1:0] depth;
    logic [63:0] token;
    logic [7:0] token_opcode;
    logic [55:0] token_immediate;
    logic [VALUE_W-1:0] push_value;
    logic token_fault;
    logic [15:0] token_fault_code;
    integer index;

    assign cfg_ready = (state == S_IDLE);

    always @* begin
        token = token_memory[pc];
        token_opcode = token[63:56];
        token_immediate = token[55:0];
        push_value = '0;
        case (token_opcode)
            OP_PUSH_IMM: push_value[55:0] = token_immediate;
            OP_PUSH_REG: push_value[31:0] = saved_registers[32*token_immediate[2:0] +: 32];
            OP_PUSH_OPERAND: push_value = saved_operands[VALUE_W*token_immediate[1:0] +: VALUE_W];
            OP_PUSH_CONTEXT: push_value[31:0] = saved_contexts[32*token_immediate[1:0] +: 32];
            default: push_value = '0;
        endcase
    end

    always @* begin
        token_fault = 1'b0;
        token_fault_code = '0;
        if (token_opcode == OP_PUSH_IMM ||
            token_opcode == OP_PUSH_REG ||
            token_opcode == OP_PUSH_OPERAND ||
            token_opcode == OP_PUSH_CONTEXT) begin
            if (depth >= STACK_DEPTH) begin
                token_fault = 1'b1;
                token_fault_code = ERR_STACK_OVERFLOW;
            end
        end else if (token_opcode >= OP_ADD && token_opcode <= OP_SHR) begin
            if (depth < 2) begin
                token_fault = 1'b1;
                token_fault_code = ERR_STACK_UNDERFLOW;
            end else if ((token_opcode == OP_SHL || token_opcode == OP_SHR) &&
                         value_stack[depth-1] >= VALUE_W) begin
                token_fault = 1'b1;
                token_fault_code = ERR_SHIFT_RANGE;
            end else if (token_opcode == OP_ADD &&
                         value_stack[depth-2] > {VALUE_W{1'b1}} - value_stack[depth-1]) begin
                token_fault = 1'b1;
                token_fault_code = ERR_ARITH_RANGE;
            end else if (token_opcode == OP_SUB &&
                         value_stack[depth-2] < value_stack[depth-1]) begin
                token_fault = 1'b1;
                token_fault_code = ERR_ARITH_RANGE;
            end else if (token_opcode == OP_SHL && value_stack[depth-1] != 0 &&
                         (value_stack[depth-2] >> (VALUE_W-value_stack[depth-1])) != 0) begin
                token_fault = 1'b1;
                token_fault_code = ERR_ARITH_RANGE;
            end
        end else begin
            token_fault = 1'b1;
            token_fault_code = ERR_ILLEGAL_TOKEN;
        end
    end

    task automatic fail(input logic [15:0] code);
        begin
            busy <= 1'b0;
            error <= 1'b1;
            error_code <= code;
            result <= '0;
            depth <= '0;
            state <= S_IDLE;
        end
    endtask

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            busy <= 1'b0;
            done <= 1'b0;
            error <= 1'b0;
            error_code <= '0;
            result <= '0;
            retired_tokens <= '0;
            host_writes_busy <= '0;
            saved_registers <= '0;
            saved_operands <= '0;
            saved_contexts <= '0;
            pc <= '0;
            remaining <= '0;
            depth <= '0;
            for (index = 0; index < TOKEN_WORDS; index = index + 1)
                token_memory[index] <= '0;
            for (index = 0; index < STACK_DEPTH; index = index + 1)
                value_stack[index] <= '0;
        end else begin
            done <= 1'b0;
            error <= 1'b0;
            error_code <= '0;

            if (cfg_valid && state != S_IDLE) begin
                host_writes_busy <= host_writes_busy + 1'b1;
                fail(ERR_IMAGE_WRITE_BUSY);
            end else begin
                if (cfg_valid && cfg_ready)
                    token_memory[cfg_index] <= cfg_token;

                case (state)
                    S_IDLE: if (start) begin
                        if (token_count == 0 ||
                            {1'b0, start_pc} + token_count > TOKEN_WORDS) begin
                            fail(ERR_PROGRAM_BOUNDS);
                        end else begin
                            saved_registers <= registers_flat;
                            saved_operands <= operands_flat;
                            saved_contexts <= contexts_flat;
                            pc <= start_pc;
                            remaining <= token_count;
                            depth <= '0;
                            result <= '0;
                            retired_tokens <= '0;
                            busy <= 1'b1;
                            state <= S_RUN;
                        end
                    end

                    S_RUN: begin
                        if (token_fault) begin
                            fail(token_fault_code);
                        end else begin
                            if (token_opcode == OP_PUSH_IMM ||
                                token_opcode == OP_PUSH_REG ||
                                token_opcode == OP_PUSH_OPERAND ||
                                token_opcode == OP_PUSH_CONTEXT) begin
                                value_stack[depth] <= push_value;
                                depth <= depth + 1'b1;
                            end else begin
                                case (token_opcode)
                                    OP_ADD: value_stack[depth-2] <= value_stack[depth-2] + value_stack[depth-1];
                                    OP_SUB: value_stack[depth-2] <= value_stack[depth-2] - value_stack[depth-1];
                                    OP_XOR: value_stack[depth-2] <= value_stack[depth-2] ^ value_stack[depth-1];
                                    OP_AND: value_stack[depth-2] <= value_stack[depth-2] & value_stack[depth-1];
                                    OP_OR:  value_stack[depth-2] <= value_stack[depth-2] | value_stack[depth-1];
                                    OP_SHL: value_stack[depth-2] <= value_stack[depth-2] << value_stack[depth-1];
                                    OP_SHR: value_stack[depth-2] <= value_stack[depth-2] >> value_stack[depth-1];
                                    default: value_stack[depth-2] <= '0;
                                endcase
                                depth <= depth - 1'b1;
                            end

                            retired_tokens <= retired_tokens + 1'b1;
                            if (remaining == 1) begin
                                remaining <= '0;
                                state <= S_FINAL;
                            end else begin
                                remaining <= remaining - 1'b1;
                                pc <= pc + 1'b1;
                            end
                        end
                    end

                    S_FINAL: begin
                        busy <= 1'b0;
                        if (depth != 1)
                            fail(ERR_RESULT_DEPTH);
                        else begin
                            result <= value_stack[0];
                            done <= 1'b1;
                            state <= S_IDLE;
                        end
                    end

                    default: fail(ERR_ILLEGAL_TOKEN);
                endcase
            end
        end
    end

    initial begin
        if (TOKEN_WORDS < 1 || STACK_DEPTH < 2)
            $error("layout expression bounds are invalid");
    end
endmodule

`default_nettype wire
