`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_scratchpad64;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic request_valid = 1'b0;
    wire request_ready;
    logic request_write = 1'b0;
    logic [15:0] request_address = '0;
    logic [63:0] request_write_data = '0;
    wire response_valid;
    wire [63:0] response_read_data;
    wire bounds_error;
    logic scrub_start = 1'b0;
    wire scrub_busy;
    wire scrub_done;
    integer i;
    integer scrub_cycles;

    always #5 clk = ~clk;
    micro_hbs_scratchpad64 #(.WORDS(16)) dut (.*);

    task automatic request;
        input write_enable;
        input [15:0] address;
        input [63:0] data;
        begin
            while (!request_ready) @(negedge clk);
            @(negedge clk);
            request_write = write_enable;
            request_address = address;
            request_write_data = data;
            request_valid = 1'b1;
            @(posedge clk);
            #1 request_valid = 1'b0;
        end
    endtask

    task automatic read_expect;
        input [15:0] address;
        input [63:0] expected;
        begin
            request(1'b0, address, '0);
            while (!response_valid) begin
                @(posedge clk);
                #1;
            end
            if (response_read_data !== expected)
                $fatal(1, "scratch read mismatch addr=%0d got=%016x expected=%016x",
                       address, response_read_data, expected);
        end
    endtask

    initial begin
        repeat (3) @(posedge clk);
        rst_n = 1'b1;
        for (i = 0; i < 16; i = i + 1)
            request(1'b1, i[15:0], 64'h0123456789abcdef ^ i);
        for (i = 0; i < 16; i = i + 1)
            read_expect(i[15:0], 64'h0123456789abcdef ^ i);

        request(1'b0, 16'd16, '0);
        if (!bounds_error || response_valid)
            $fatal(1, "out-of-bounds request did not fail closed");

        @(negedge clk);
        scrub_start = 1'b1;
        @(posedge clk);
        #1 scrub_start = 1'b0;
        if (!scrub_busy || request_ready)
            $fatal(1, "scrub did not lock external port");

        // A request held during scrub must neither access RAM nor raise a
        // stale response/error.  The producer observes request_ready low.
        request_valid = 1'b1;
        request_write = 1'b1;
        request_address = 16'd3;
        request_write_data = 64'hdeaddeaddeaddead;
        scrub_cycles = 0;
        while (!scrub_done) begin
            @(posedge clk);
            #1;
            scrub_cycles = scrub_cycles + 1;
            if (!scrub_done && (response_valid || bounds_error || request_ready))
                $fatal(1, "external request leaked through active scrub");
        end
        request_valid = 1'b0;
        if (scrub_cycles != 16)
            $fatal(1, "scrub latency mismatch got=%0d expected=16", scrub_cycles);
        for (i = 0; i < 16; i = i + 1)
            read_expect(i[15:0], 64'b0);
        $display("PASS scratchpad read/write/bounds, locked scrub and all 16 words zeroized in %0d cycles",
                 scrub_cycles);
        $finish;
    end
endmodule

`default_nettype wire
