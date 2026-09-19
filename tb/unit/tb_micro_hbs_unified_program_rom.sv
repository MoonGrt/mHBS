`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_unified_program_rom;
    logic clk = 0;
    logic rst_n = 0;
    logic [7:0] address = 0;
    logic request_valid = 0;
    wire request_ready, data_valid;
    wire [127:0] data;
    always #5 clk = ~clk;

    micro_hbs_unified_program_rom dut (.*);

    task read_and_check(input [7:0] addr, input [1:0] algorithm,
                        input [5:0] n_bytes, input stateful);
        begin
            while (!request_ready) @(posedge clk);
            address = addr;
            request_valid = 1; @(posedge clk); #1; request_valid = 0;
            while (!data_valid) begin @(posedge clk); #1; end
            if (data[1:0] !== algorithm || data[2] !== stateful
                || data[8:3] !== n_bytes)
                $fatal(1, "directory mismatch addr=%0d data=%h", addr, data);
        end
    endtask

    initial begin
        repeat (2) @(posedge clk);
        rst_n <= 1;
        @(posedge clk);
        while (!request_ready) @(posedge clk);
        address = 0; request_valid = 1;
        @(posedge clk); #1; request_valid = 0;
        while (!data_valid) begin @(posedge clk); #1; end
        if (data[127:96] !== 32'h4d484253 || data[95:88] !== 8'd1
            || data[87:80] !== 8'd3 || data[15:0] == 0
            || data[15:0] > 16'd256)
            $fatal(1, "unified image header mismatch data=%h", data);
        read_and_check(1, 0, 16, 0);
        read_and_check(2, 1, 32, 1);
        read_and_check(3, 2, 32, 1);
        $display("UNIFIED_PROGRAM_ROM_PASS");
        $finish;
    end
endmodule

`default_nettype wire
