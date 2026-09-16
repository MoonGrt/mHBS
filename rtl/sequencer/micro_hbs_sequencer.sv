`timescale 1ns/1ps
`default_nettype none

module micro_hbs_sequencer #(
    parameter int PROGRAM_WORDS = 512,
    parameter int LOOP_DEPTH = 6,
    parameter int CALL_DEPTH = 4,
    parameter PROGRAM_INIT_FILE = "",
    parameter int PROGRAM_INIT_WORDS = PROGRAM_WORDS
) (
    input  wire         clk,
    input  wire         rst_n,

    input  wire         program_we,
    input  wire  [8:0]  program_addr,
    input  wire  [63:0] program_wdata,

    input  wire         job_valid,
    output logic        job_ready,
    input  wire  [8:0]  job_entry,

    output logic        busy,
    output logic        done,
    output logic        error,
    output logic [15:0] error_code,

    output logic        hash_req_valid,
    input  wire         hash_req_ready,
    output logic [15:0] hash_layout_id,
    output logic [1:0]  hash_lane_mask,
    output logic [7:0]  hash_dest,
    output logic [7:0]  hash_index_reg,
    output logic [31:0] hash_index_value,
    input  wire         hash_rsp_valid,
    input  wire         hash_rsp_error,
    input  wire  [15:0] hash_rsp_error_code,

    output logic        dynamic_bound_req,
    output logic [15:0] dynamic_bound_addr,
    input  wire         dynamic_bound_valid,
    input  wire  [7:0]  dynamic_bound_value,
    input  wire         dynamic_bound_error,
    input  wire  [15:0] dynamic_bound_error_code,

    // Internal command channel to the static load/move/XOR/output data path.
    // This is not an external task ingress: one request is derived solely
    // from the currently executing instruction and its latched register.
    output logic        data_req_valid,
    input  wire         data_req_ready,
    output logic [7:0]  data_req_opcode,
    output logic [7:0]  data_req_flags,
    output logic [7:0]  data_req_rd,
    output logic [7:0]  data_req_rs,
    output logic [31:0] data_req_imm,
    output logic [31:0] data_req_rs_value,
    input  wire         data_rsp_valid,
    input  wire         data_rsp_error,
    input  wire  [15:0] data_rsp_error_code,
    input  wire         data_rsp_reg_write,
    input  wire  [7:0]  data_rsp_reg_index,
    input  wire  [31:0] data_rsp_reg_value,

    // Internal command channel to a generic tree-stack data path.  As with
    // the data channel, every request field is latched from one instruction.
    output logic        tree_req_valid,
    input  wire         tree_req_ready,
    output logic [7:0]  tree_req_flags,
    output logic [7:0]  tree_req_rd,
    output logic [7:0]  tree_req_rs,
    output logic [31:0] tree_req_imm,
    output logic [31:0] tree_req_rs_value,
    input  wire         tree_rsp_valid,
    input  wire         tree_rsp_error,
    input  wire  [15:0] tree_rsp_error_code,

    output logic [31:0] accepted_job_commands,
    output logic [31:0] host_control_writes_during_busy,
    output logic [31:0] issued_hash_requests,
    output logic [31:0] issued_data_requests,
    output logic [31:0] issued_tree_requests,
    output logic [31:0] retired_instructions,

    // Read-only snapshot for internal descriptor/address consumers. This is
    // not an external register-write interface; values remain owned by the
    // sequencer and are captured by a command consumer at request acceptance.
    output wire [255:0] register_snapshot
);
    localparam logic [7:0] OP_NOP         = 8'h00;
    localparam logic [7:0] OP_MOVI        = 8'h01;
    localparam logic [7:0] OP_ADDI        = 8'h02;
    localparam logic [7:0] OP_HASH_LAYOUT = 8'h03;
    localparam logic [7:0] OP_LOOP_SETUP  = 8'h04;
    localparam logic [7:0] OP_LOOP_END    = 8'h05;
    localparam logic [7:0] OP_CALL        = 8'h06;
    localparam logic [7:0] OP_RET         = 8'h07;
    localparam logic [7:0] OP_LOAD        = 8'h08;
    localparam logic [7:0] OP_STORE       = 8'h09;
    localparam logic [7:0] OP_XOR         = 8'h0a;
    localparam logic [7:0] OP_TREE_PUSH   = 8'h0b;
    localparam logic [7:0] OP_EMIT        = 8'h0c;
    localparam logic [7:0] OP_HALT        = 8'h0d;
    localparam logic [7:0] OP_FAIL        = 8'h0e;
    localparam logic [7:0] OP_WAIT        = 8'h0f;
    localparam logic [7:0] OP_BARRIER     = 8'h10;
    localparam logic [7:0] OP_JUMP        = 8'h11;

    localparam logic [15:0] ERR_NONE          = 16'h0000;
    localparam logic [15:0] ERR_IMAGE_LOCKED  = 16'h0001;
    localparam logic [15:0] ERR_PC_BOUNDS     = 16'h0002;
    localparam logic [15:0] ERR_OPCODE        = 16'h0003;
    localparam logic [15:0] ERR_RESERVED      = 16'h0004;
    localparam logic [15:0] ERR_LOOP_OVERFLOW = 16'h0005;
    localparam logic [15:0] ERR_LOOP_UNDERFLOW= 16'h0006;
    localparam logic [15:0] ERR_CALL_OVERFLOW = 16'h0007;
    localparam logic [15:0] ERR_CALL_UNDERFLOW= 16'h0008;
    localparam logic [15:0] ERR_BRANCH_BOUNDS = 16'h0009;
    localparam logic [15:0] ERR_BAD_LOOP_BOUND= 16'h000a;
    localparam logic [15:0] ERR_DYNAMIC_BOUND = 16'h000b;
    localparam logic [15:0] ERR_PROGRAM_FAIL  = 16'h8000;

    typedef enum logic [3:0] {S_IDLE, S_FETCH, S_RUN, S_HASH_REQ, S_HASH_WAIT,
                              S_BOUND_WAIT, S_DATA_REQ, S_DATA_WAIT,
                              S_TREE_REQ, S_TREE_WAIT} state_t;
    state_t state;

    logic [31:0] regs [0:7];
    logic [8:0] pc;
    logic [8:0] loop_body_pc [0:LOOP_DEPTH-1];
    logic [7:0] loop_counter_reg [0:LOOP_DEPTH-1];
    logic [31:0] loop_bound [0:LOOP_DEPTH-1];
    logic [$clog2(LOOP_DEPTH+1)-1:0] loop_sp;
    logic [8:0] call_return_pc [0:CALL_DEPTH-1];
    logic [$clog2(CALL_DEPTH+1)-1:0] call_sp;

    logic [63:0] instruction;
    logic [7:0] opcode, flags, rd, rs;
    logic [31:0] imm;
    logic [32:0] add_result;
    integer index;
    genvar register_index;

    generate
        for (register_index = 0; register_index < 8;
             register_index = register_index + 1) begin : register_snapshot_gen
            assign register_snapshot[32*register_index +: 32] =
                regs[register_index];
        end
    endgenerate

    micro_hbs_program_store #(
        .PROGRAM_WORDS(PROGRAM_WORDS),
        .PROGRAM_INIT_FILE(PROGRAM_INIT_FILE),
        .PROGRAM_INIT_WORDS(PROGRAM_INIT_WORDS)
    ) program_store (
        .clk,
        .write_enable(program_we && state == S_IDLE && !job_valid && !error),
        .write_address(program_addr),
        .write_data(program_wdata),
        .read_address(pc),
        .read_data(instruction)
    );
    assign opcode = instruction[63:56];
    assign flags = instruction[55:48];
    assign rd = instruction[47:40];
    assign rs = instruction[39:32];
    assign imm = instruction[31:0];
    assign add_result = {1'b0, regs[rs[2:0]]} + {{1{imm[31]}}, imm};

    assign job_ready = (state == S_IDLE) && !error;
    assign busy = (state != S_IDLE);
    assign hash_req_valid = (state == S_HASH_REQ);
    assign data_req_valid = (state == S_DATA_REQ);
    assign tree_req_valid = (state == S_TREE_REQ);
    assign dynamic_bound_req = (state == S_BOUND_WAIT);
    assign dynamic_bound_addr = regs[rd[2:0]][15:0];

    task automatic fault(input logic [15:0] code);
        begin
            error <= 1'b1;
            error_code <= code;
            state <= S_IDLE;
        end
    endtask

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            pc <= '0;
            loop_sp <= '0;
            call_sp <= '0;
            done <= 1'b0;
            error <= 1'b0;
            error_code <= ERR_NONE;
            hash_layout_id <= '0;
            hash_lane_mask <= '0;
            hash_dest <= '0;
            hash_index_reg <= '0;
            hash_index_value <= '0;
            data_req_opcode <= '0;
            data_req_flags <= '0;
            data_req_rd <= '0;
            data_req_rs <= '0;
            data_req_imm <= '0;
            data_req_rs_value <= '0;
            tree_req_flags <= '0;
            tree_req_rd <= '0;
            tree_req_rs <= '0;
            tree_req_imm <= '0;
            tree_req_rs_value <= '0;
            accepted_job_commands <= '0;
            host_control_writes_during_busy <= '0;
            issued_hash_requests <= '0;
            issued_data_requests <= '0;
            issued_tree_requests <= '0;
            retired_instructions <= '0;
            for (index = 0; index < 8; index = index + 1)
                regs[index] <= '0;
        end else begin
            done <= 1'b0;

            if (program_we && !(state == S_IDLE && !job_valid && !error)) begin
                // Image writes have priority over every in-flight response so
                // a write attempt during BUSY cannot be hidden by retirement.
                host_control_writes_during_busy <= host_control_writes_during_busy + 1'b1;
                fault(ERR_IMAGE_LOCKED);
            end else case (state)
                S_IDLE: begin
                    if (job_valid && !program_we && !error) begin
                        if (job_entry >= PROGRAM_WORDS)
                            fault(ERR_PC_BOUNDS);
                        else begin
                            pc <= job_entry;
                            loop_sp <= '0;
                            call_sp <= '0;
                            accepted_job_commands <= accepted_job_commands + 1'b1;
                            state <= S_FETCH;
                            for (index = 0; index < 8; index = index + 1)
                                regs[index] <= '0;
                        end
                    end
                end

                S_FETCH: begin
                    if (pc >= PROGRAM_WORDS)
                        fault(ERR_PC_BOUNDS);
                    else
                        state <= S_RUN;
                end

                S_RUN: begin
                    if (pc >= PROGRAM_WORDS)
                        fault(ERR_PC_BOUNDS);
                    else if (flags[7:2] != 0)
                        fault(ERR_RESERVED);
                    else begin
                        case (opcode)
                            OP_NOP: begin
                                pc <= pc + 1'b1;
                                state <= S_FETCH;
                                retired_instructions <= retired_instructions + 1'b1;
                            end
                            OP_MOVI: begin
                                if (rd >= 8)
                                    fault(ERR_RESERVED);
                                else begin
                                    regs[rd[2:0]] <= imm;
                                    pc <= pc + 1'b1;
                                    state <= S_FETCH;
                                    retired_instructions <= retired_instructions + 1'b1;
                                end
                            end
                            OP_ADDI: begin
                                if (rd >= 8 || rs >= 8 || add_result[32])
                                    fault(ERR_RESERVED);
                                else begin
                                    regs[rd[2:0]] <= add_result[31:0];
                                    pc <= pc + 1'b1;
                                    state <= S_FETCH;
                                    retired_instructions <= retired_instructions + 1'b1;
                                end
                            end
                            OP_HASH_LAYOUT: begin
                                if (rs >= 8 || flags[1:0] == 0)
                                    fault(ERR_RESERVED);
                                else begin
                                    hash_layout_id <= imm[15:0];
                                    hash_lane_mask <= flags[1:0];
                                    hash_dest <= rd;
                                    hash_index_reg <= rs;
                                    hash_index_value <= regs[rs[2:0]];
                                    state <= S_HASH_REQ;
                                end
                            end
                            OP_LOOP_SETUP: begin
                                if (rs >= 8 || rd >= 8 || flags[1])
                                    fault(ERR_BAD_LOOP_BOUND);
                                else if (flags[0]) begin
                                    if (imm >= PROGRAM_WORDS || regs[rd[2:0]][31:16] != 0)
                                        fault(ERR_DYNAMIC_BOUND);
                                    else
                                        state <= S_BOUND_WAIT;
                                end
                                else if (imm == 0)
                                    fault(ERR_BAD_LOOP_BOUND);
                                else if (loop_sp == LOOP_DEPTH)
                                    fault(ERR_LOOP_OVERFLOW);
                                else begin
                                    regs[rs[2:0]] <= '0;
                                    loop_body_pc[loop_sp] <= pc + 1'b1;
                                    loop_counter_reg[loop_sp] <= rs;
                                    loop_bound[loop_sp] <= imm;
                                    loop_sp <= loop_sp + 1'b1;
                                    pc <= pc + 1'b1;
                                    state <= S_FETCH;
                                    retired_instructions <= retired_instructions + 1'b1;
                                end
                            end
                            OP_LOOP_END: begin
                                if (loop_sp == 0)
                                    fault(ERR_LOOP_UNDERFLOW);
                                else if (regs[loop_counter_reg[loop_sp-1][2:0]] + 1 < loop_bound[loop_sp-1]) begin
                                    regs[loop_counter_reg[loop_sp-1][2:0]] <= regs[loop_counter_reg[loop_sp-1][2:0]] + 1'b1;
                                    pc <= loop_body_pc[loop_sp-1];
                                    state <= S_FETCH;
                                    retired_instructions <= retired_instructions + 1'b1;
                                end else begin
                                    regs[loop_counter_reg[loop_sp-1][2:0]] <= regs[loop_counter_reg[loop_sp-1][2:0]] + 1'b1;
                                    loop_sp <= loop_sp - 1'b1;
                                    pc <= pc + 1'b1;
                                    state <= S_FETCH;
                                    retired_instructions <= retired_instructions + 1'b1;
                                end
                            end
                            OP_CALL: begin
                                if (imm >= PROGRAM_WORDS)
                                    fault(ERR_BRANCH_BOUNDS);
                                else if (call_sp == CALL_DEPTH)
                                    fault(ERR_CALL_OVERFLOW);
                                else begin
                                    call_return_pc[call_sp] <= pc + 1'b1;
                                    call_sp <= call_sp + 1'b1;
                                    pc <= imm[8:0];
                                    state <= S_FETCH;
                                    retired_instructions <= retired_instructions + 1'b1;
                                end
                            end
                            OP_RET: begin
                                if (call_sp == 0)
                                    fault(ERR_CALL_UNDERFLOW);
                                else begin
                                    pc <= call_return_pc[call_sp-1];
                                    call_sp <= call_sp - 1'b1;
                                    state <= S_FETCH;
                                    retired_instructions <= retired_instructions + 1'b1;
                                end
                            end
                            OP_LOAD, OP_STORE, OP_XOR: begin
                                if (flags != 0 || rd >= 8 || rs >= 8)
                                    fault(ERR_RESERVED);
                                else begin
                                    data_req_opcode <= opcode;
                                    data_req_flags <= flags;
                                    data_req_rd <= rd;
                                    data_req_rs <= rs;
                                    data_req_imm <= imm;
                                    data_req_rs_value <= regs[rs[2:0]];
                                    state <= S_DATA_REQ;
                                end
                            end
                            OP_TREE_PUSH: begin
                                if (flags != 0 || rs >= 8)
                                    fault(ERR_RESERVED);
                                else begin
                                    tree_req_flags <= flags;
                                    tree_req_rd <= rd;
                                    tree_req_rs <= rs;
                                    tree_req_imm <= imm;
                                    tree_req_rs_value <= regs[rs[2:0]];
                                    state <= S_TREE_REQ;
                                end
                            end
                            OP_EMIT: begin
                                if (flags[1] || rs >= 8)
                                    fault(ERR_RESERVED);
                                else begin
                                    data_req_opcode <= opcode;
                                    data_req_flags <= flags;
                                    data_req_rd <= rd;
                                    data_req_rs <= rs;
                                    data_req_imm <= imm;
                                    data_req_rs_value <= regs[rs[2:0]];
                                    state <= S_DATA_REQ;
                                end
                            end
                            OP_JUMP: begin
                                if (imm >= PROGRAM_WORDS)
                                    fault(ERR_BRANCH_BOUNDS);
                                else begin
                                    pc <= imm[8:0];
                                    state <= S_FETCH;
                                    retired_instructions <= retired_instructions + 1'b1;
                                end
                            end
                            OP_WAIT, OP_BARRIER: begin
                                pc <= pc + 1'b1;
                                state <= S_FETCH;
                                retired_instructions <= retired_instructions + 1'b1;
                            end
                            OP_HALT: begin
                                if (loop_sp != 0 || call_sp != 0)
                                    fault(ERR_RESERVED);
                                else begin
                                    done <= 1'b1;
                                    state <= S_IDLE;
                                    retired_instructions <= retired_instructions + 1'b1;
                                end
                            end
                            OP_FAIL: fault(ERR_PROGRAM_FAIL | imm[14:0]);
                            default: fault(ERR_OPCODE);
                        endcase
                    end
                end

                S_HASH_REQ: begin
                    if (hash_req_ready) begin
                        issued_hash_requests <= issued_hash_requests + 1'b1;
                        state <= S_HASH_WAIT;
                    end
                end

                S_HASH_WAIT: begin
                    if (hash_rsp_error) begin
                        fault(hash_rsp_error_code);
                    end else if (hash_rsp_valid) begin
                        pc <= pc + 1'b1;
                        retired_instructions <= retired_instructions + 1'b1;
                        state <= S_FETCH;
                    end
                end

                S_BOUND_WAIT: begin
                    if (dynamic_bound_error) begin
                        fault(dynamic_bound_error_code);
                    end else if (dynamic_bound_valid) begin
                        regs[rs[2:0]] <= '0;
                        if (dynamic_bound_value == 0) begin
                            pc <= imm[8:0];
                        end else if (loop_sp == LOOP_DEPTH) begin
                            fault(ERR_LOOP_OVERFLOW);
                        end else begin
                            loop_body_pc[loop_sp] <= pc + 1'b1;
                            loop_counter_reg[loop_sp] <= rs;
                            loop_bound[loop_sp] <= {24'b0, dynamic_bound_value};
                            loop_sp <= loop_sp + 1'b1;
                            pc <= pc + 1'b1;
                        end
                        if (loop_sp != LOOP_DEPTH || dynamic_bound_value == 0) begin
                            state <= S_FETCH;
                            retired_instructions <= retired_instructions + 1'b1;
                        end
                    end
                end

                S_DATA_REQ: begin
                    if (data_req_ready) begin
                        issued_data_requests <= issued_data_requests + 1'b1;
                        state <= S_DATA_WAIT;
                    end
                end

                S_DATA_WAIT: begin
                    if (data_rsp_error) begin
                        fault(data_rsp_error_code);
                    end else if (data_rsp_valid) begin
                        if (data_rsp_reg_write && data_rsp_reg_index >= 8) begin
                            fault(ERR_RESERVED);
                        end else begin
                            if (data_rsp_reg_write)
                                regs[data_rsp_reg_index[2:0]] <= data_rsp_reg_value;
                            pc <= pc + 1'b1;
                            retired_instructions <= retired_instructions + 1'b1;
                            state <= S_FETCH;
                        end
                    end
                end

                S_TREE_REQ: begin
                    if (tree_req_ready) begin
                        issued_tree_requests <= issued_tree_requests + 1'b1;
                        state <= S_TREE_WAIT;
                    end
                end

                S_TREE_WAIT: begin
                    if (tree_rsp_error) begin
                        fault(tree_rsp_error_code);
                    end else if (tree_rsp_valid) begin
                        pc <= pc + 1'b1;
                        retired_instructions <= retired_instructions + 1'b1;
                        state <= S_FETCH;
                    end
                end

                default: fault(ERR_OPCODE);
            endcase
        end
    end
endmodule

`default_nettype wire
