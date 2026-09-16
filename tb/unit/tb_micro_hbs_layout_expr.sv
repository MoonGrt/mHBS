`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_layout_expr;
    localparam integer VALUE_W = 32;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic cfg_valid;
    wire cfg_ready;
    logic [4:0] cfg_index;
    logic [63:0] cfg_token;
    logic start;
    logic [4:0] start_pc;
    logic [5:0] token_count;
    logic [255:0] registers_flat;
    logic [4*VALUE_W-1:0] operands_flat;
    logic [127:0] contexts_flat;
    wire busy;
    wire done;
    wire error;
    wire [15:0] error_code;
    wire [VALUE_W-1:0] result;
    wire [31:0] retired_tokens;
    wire [31:0] host_writes_busy;
    logic reverse;
    logic [127:0] current_node;
    logic [127:0] auth_node;
    wire [127:0] left_node;
    wire [127:0] right_node;
    integer timeout;

    localparam logic [7:0] PUSH_IMM = 8'h01;
    localparam logic [7:0] PUSH_REG = 8'h02;
    localparam logic [7:0] PUSH_OPERAND = 8'h03;
    localparam logic [7:0] ADD = 8'h10;
    localparam logic [7:0] SUB = 8'h11;
    localparam logic [7:0] XOR_OP = 8'h12;
    localparam logic [7:0] AND_OP = 8'h13;
    localparam logic [7:0] SHL = 8'h15;
    localparam logic [7:0] SHR = 8'h16;

    always #5 clk = ~clk;

    micro_hbs_layout_expr #(.VALUE_W(VALUE_W)) dut (.*);
    micro_hbs_ordered_pair pair_dut (.*);

    function automatic [63:0] token(input [7:0] opcode, input [55:0] immediate);
        token = {opcode, immediate};
    endfunction

    task automatic configure(input [4:0] address, input [63:0] value);
        begin
            @(negedge clk);
            cfg_index = address;
            cfg_token = value;
            cfg_valid = 1'b1;
            @(negedge clk);
            cfg_valid = 1'b0;
        end
    endtask

    task automatic execute(input [4:0] address, input [5:0] count);
        begin
            @(negedge clk);
            start_pc = address;
            token_count = count;
            start = 1'b1;
            @(negedge clk);
            start = 1'b0;
            timeout = 0;
            while (!done && !error && timeout < 80) begin
                @(negedge clk);
                timeout = timeout + 1;
            end
            if (timeout == 80) $fatal(1, "expression timeout");
        end
    endtask

    initial begin
        cfg_valid = 0;
        cfg_index = 0;
        cfg_token = 0;
        start = 0;
        start_pc = 0;
        token_count = 0;
        registers_flat = 0;
        operands_flat = 0;
        contexts_flat = 0;
        reverse = 0;
        current_node = 128'h00112233445566778899aabbccddeeff;
        auth_node = 128'hffeeddccbbaa99887766554433221100;
        repeat (3) @(negedge clk);
        rst_n = 1'b1;

        // tree*64 + (((selected >> height) XOR 1) << height)
        registers_flat[32*0 +: 32] = 10;
        registers_flat[32*1 +: 32] = 1;
        registers_flat[32*6 +: 32] = 2;
        configure(0, token(PUSH_REG, 0));
        configure(1, token(PUSH_IMM, 6));
        configure(2, token(SHL, 0));
        configure(3, token(PUSH_REG, 1));
        configure(4, token(PUSH_REG, 6));
        configure(5, token(SHR, 0));
        configure(6, token(PUSH_IMM, 1));
        configure(7, token(XOR_OP, 0));
        configure(8, token(PUSH_REG, 6));
        configure(9, token(SHL, 0));
        configure(10, token(ADD, 0));
        execute(0, 11);
        if (error || result != 644)
            $fatal(1, "FORS subtree start mismatch %0d error=%h", result, error_code);

        reverse = 1'b0;
        #1;
        if (left_node !== current_node || right_node !== auth_node)
            $fatal(1, "ordered pair zero branch mismatch");
        reverse = 1'b1;
        #1;
        if (left_node !== auth_node || right_node !== current_node)
            $fatal(1, "ordered pair reverse branch mismatch");

        // Configuration during evaluation aborts with an auditable error.
        execute(0, 11);
        // execute waited for completion; start a second run and collide now.
        @(negedge clk);
        start_pc = 0;
        token_count = 11;
        start = 1'b1;
        @(negedge clk);
        start = 1'b0;
        cfg_valid = 1'b1;
        cfg_index = 0;
        cfg_token = 0;
        @(negedge clk);
        cfg_valid = 1'b0;
        if (!error || error_code != 16'h0102 || host_writes_busy != 1)
            $fatal(1, "busy image write did not fail closed");

        configure(12, token(8'hff, 0));
        execute(12, 1);
        if (!error || error_code != 16'h0204 || result != 0)
            $fatal(1, "illegal token did not fail closed");

        execute(13, 1);
        if (!error || error_code != 16'h0208 || result != 0)
            $fatal(1, "unconfigured token did not fail closed");

        configure(14, token(PUSH_IMM, 1));
        configure(15, token(PUSH_IMM, 32));
        configure(16, token(SHL, 0));
        execute(14, 3);
        if (!error || error_code != 16'h0205 || result != 0)
            $fatal(1, "out-of-range shift did not fail closed");

        configure(17, token(PUSH_IMM, 32'hffff_ffff));
        configure(18, token(PUSH_IMM, 1));
        configure(19, token(ADD, 0));
        execute(17, 3);
        if (!error || error_code != 16'h0207 || result != 0)
            $fatal(1, "overflowing add did not fail closed");

        $display("PASS 32-bit layout expression and ordered-pair RTL");
        $finish;
    end
endmodule

`default_nettype wire
