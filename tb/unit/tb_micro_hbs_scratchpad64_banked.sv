`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_scratchpad64_banked;
    logic clk = 0, rst_n = 0;
    logic request_valid = 0, request_write = 0, request_pair = 0;
    logic [15:0] request_address = 0;
    logic [63:0] request_write_data = 0;
    wire request_ready, response_valid, bounds_error;
    wire [63:0] response_read_data;
    wire [127:0] response_read_pair;
    logic scrub_start = 0;
    wire scrub_busy, scrub_done;

    always #5 clk = ~clk;
    micro_hbs_scratchpad64_banked #(.WORDS(16)) dut (.*);

    task automatic issue(input logic wr, input logic pair,
                         input logic [15:0] addr, input logic [63:0] data);
        begin
            @(negedge clk);
            request_valid = 1;
            request_write = wr;
            request_pair = pair;
            request_address = addr;
            request_write_data = data;
            @(posedge clk); #1 request_valid = 0;
        end
    endtask

    initial begin
        repeat (2) @(posedge clk);
        rst_n = 1;
        issue(1, 0, 4, 64'h0123456789abcdef);
        issue(1, 0, 5, 64'hfedcba9876543210);
        issue(0, 1, 4, 0);
        if (!response_valid
            || response_read_pair
                != 128'hfedcba9876543210_0123456789abcdef)
            $fatal(1, "aligned pair read failed");
        issue(0, 0, 5, 0);
        if (!response_valid || response_read_data != 64'hfedcba9876543210)
            $fatal(1, "odd-bank scalar read failed");
        issue(0, 1, 5, 0);
        if (!bounds_error || response_valid)
            $fatal(1, "unaligned pair did not fail closed");
        issue(1, 1, 4, 0);
        if (!bounds_error)
            $fatal(1, "pair write did not fail closed");
        $display("PASS banked Scratchpad scalar/pair/bounds");
        $finish;
    end
endmodule

`default_nettype wire
