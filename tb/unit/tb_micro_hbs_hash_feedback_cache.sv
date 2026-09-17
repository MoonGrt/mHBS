`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_hash_feedback_cache;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic clear = 1'b0;
    logic fill_valid = 1'b0;
    logic [15:0] fill_base_address = '0;
    logic [1:0] fill_words = '0;
    logic [127:0] fill_data = '0;
    logic invalidate_valid = 1'b0;
    logic [15:0] lookup_base_address = '0;
    logic [1:0] lookup_words = '0;
    wire lookup_hit;
    wire [127:0] lookup_data;

    always #5 clk = ~clk;
    micro_hbs_hash_feedback_cache dut (.*);

    task automatic clock_cycle;
        begin
            @(posedge clk);
            #1;
        end
    endtask

    initial begin
        repeat (2) clock_cycle();
        rst_n = 1'b1;
        clock_cycle();

        fill_valid = 1'b1;
        fill_base_address = 16'd40;
        fill_words = 2'd2;
        fill_data = 128'hfedcba9876543210_0123456789abcdef;
        clock_cycle();
        fill_valid = 1'b0;

        lookup_base_address = 16'd40;
        lookup_words = 2'd2;
        #1;
        if (!lookup_hit
            || lookup_data != 128'hfedcba9876543210_0123456789abcdef)
            $fatal(1, "two-word line lookup failed");
        lookup_words = 2'd3;
        #1;
        if (lookup_hit)
            $fatal(1, "oversize lookup hit");
        lookup_words = 2'd1;
        lookup_base_address = 16'd41;
        #1;
        if (lookup_hit)
            $fatal(1, "non-base lookup hit");

        invalidate_valid = 1'b1;
        clock_cycle();
        invalidate_valid = 1'b0;
        lookup_base_address = 16'd40;
        #1;
        if (lookup_hit)
            $fatal(1, "external-write invalidation failed");

        fill_valid = 1'b1;
        clock_cycle();
        fill_valid = 1'b0;
        clear = 1'b1;
        clock_cycle();
        clear = 1'b0;
        #1;
        if (lookup_hit)
            $fatal(1, "clear failed");

        $display("PASS hash feedback cache");
        $finish;
    end
endmodule

`default_nettype wire
