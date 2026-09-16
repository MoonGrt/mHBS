`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_randomized_hash;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic start_f = 1'b0, start_h = 1'b0;
    logic [255:0] pub_seed = '0;
    logic [255:0] address_f = '0, address_h = '0;
    logic [511:0] node_data = '0;
    wire ready_f, ready_h, done_f, done_h, error_f, error_h;
    wire [255:0] digest_f, digest_h;
    wire [2:0] calls_f, calls_h;
    integer i;

    always #5 clk = ~clk;

    micro_hbs_randomized_hash #(.NODE_COUNT(1), .UNROLL(2)) f_dut (
        .clk, .rst_n, .start(start_f), .ready(ready_f), .pub_seed,
        .address(address_f), .node_data, .digest(digest_f), .done(done_f),
        .error(error_f), .hash_calls(calls_f)
    );
    micro_hbs_randomized_hash #(.NODE_COUNT(2), .UNROLL(2)) h_dut (
        .clk, .rst_n, .start(start_h), .ready(ready_h), .pub_seed,
        .address(address_h), .node_data, .digest(digest_h), .done(done_h),
        .error(error_h), .hash_calls(calls_h)
    );

    initial begin
        for (i = 0; i < 32; i = i + 1) begin
            pub_seed[8*i +: 8] = 8'h40 + i;
            node_data[8*i +: 8] = 8'ha0 + i;
            node_data[8*(32+i) +: 8] = 8'hc0 + i;
        end
        // Big-endian words [0,0,0,type,5,2,3,0], byte zero at low bits.
        address_f[8*19 +: 8] = 8'h05;
        address_f[8*23 +: 8] = 8'h02;
        address_f[8*27 +: 8] = 8'h03;
        address_h = address_f;
        address_h[8*15 +: 8] = 8'h01;

        repeat (3) @(posedge clk);
        rst_n = 1'b1;
        @(posedge clk);
        start_f = 1'b1;
        @(posedge clk); #1 start_f = 1'b0;
        while (!done_f && !error_f) begin @(posedge clk); #1; end
        if (error_f || digest_f !== 256'h70e61cfbd8af7cff5c641c10a9643892e84270df2b8b80d7414ec454c68902b6 || calls_f != 3)
            $fatal(1, "randomized F mismatch digest=%h calls=%0d", digest_f, calls_f);

        while (!ready_h) @(posedge clk);
        start_h = 1'b1;
        @(posedge clk); #1 start_h = 1'b0;
        while (!done_h && !error_h) begin @(posedge clk); #1; end
        if (error_h || digest_h !== 256'h131f4ebe7c3f2e7dfc359e0153352572e613acb46772250f26664a94979c091d || calls_h != 4)
            $fatal(1, "randomized H mismatch digest=%h calls=%0d", digest_h, calls_h);

        $display("PASS randomized F/H composer with 3/4 SHAKE calls");
        $finish;
    end
endmodule

`default_nettype wire
