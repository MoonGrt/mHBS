`timescale 1ns/1ps
module tb_uhbs_full_tree_cache256;
    logic clk = 0;
    logic rst_n = 0;
    logic build_start = 0, build_abort = 0, build_commit = 0;
    logic store0_valid = 0, store0_tree_node = 0;
    logic [10:0] store0_address = 0;
    logic [255:0] store0_data = 0;
    logic store1_valid = 0, store1_tree_node = 0;
    logic [10:0] store1_address = 0;
    logic [255:0] store1_data = 0;
    logic lookup_valid = 0, lookup_allow_uncommitted = 0;
    logic [10:0] lookup_address = 0;
    wire build_ready, cache_valid, build_active, store_ready;
    wire lookup_ready, lookup_rsp_valid, lookup_hit, error;
    wire [255:0] lookup_data;
    wire [15:0] error_code;
    wire [11:0] tree_writes;
    wire [2:0] queued_writes;
    always #5 clk = ~clk;

    uhbs_full_tree_cache256 dut (.*);
    task tick; begin @(posedge clk); #1; end endtask

    initial begin
        repeat (2) tick(); rst_n = 1; tick();
        build_start = 1; tick(); build_start = 0;
        if (!build_active || cache_valid) $fatal(1, "build start");
        store0_valid = 1; store0_tree_node = 1;
        store0_address = 11'd3; store0_data = 256'h33;
        store1_valid = 1; store1_tree_node = 1;
        store1_address = 11'd4; store1_data = 256'h44;
        tick(); store0_valid = 0; store1_valid = 0;
        repeat (3) tick();
        if (tree_writes != 2 || queued_writes != 0) $fatal(1, "dual write drain");
        lookup_allow_uncommitted = 1; lookup_address = 3;
        lookup_valid = 1; tick(); lookup_valid = 0;
        tick();
        if (!lookup_rsp_valid || !lookup_hit || lookup_data != 256'h33)
            $fatal(1, "build lookup");
        build_abort = 1; tick(); build_abort = 0;
        if (cache_valid || build_active) $fatal(1, "abort invalidation");
        $display("FULL_TREE_CACHE256_PASS");
        $finish;
    end
endmodule
