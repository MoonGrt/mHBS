`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_treehash_warm_active_cache;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic clear_all = 1'b0;
    logic job_busy = 1'b0;
    logic activate_valid = 1'b0;
    wire activate_ready;
    logic [15:0] activate_target_leaf = '0;
    wire active_window_valid;
    wire [15:0] active_window_base;
    logic store_valid = 1'b0;
    logic [7:0] store_height = '0;
    logic [15:0] store_start_leaf = '0;
    logic [255:0] store_value = '0;
    logic lookup_valid = 1'b0;
    wire lookup_ready;
    logic [7:0] lookup_height = '0;
    logic [15:0] lookup_start_leaf = '0;
    wire lookup_rsp_valid, lookup_hit, bounds_error;
    wire [255:0] lookup_value;
    wire busy, error;
    wire [15:0] error_code;
    wire [31:0] upper_writes, lower_writes;
    wire [31:0] upper_retained_nodes, lower_retained_nodes;
    wire [31:0] lookup_requests, cache_hits, cache_misses, window_switches;
    wire [31:0] upper_capacity_nodes, lower_capacity_nodes;
    wire [31:0] total_capacity_nodes, logical_capacity_bytes;
    integer level;

    always #5 clk = ~clk;

    micro_hbs_treehash_warm_active_cache #(
        .TREE_HEIGHT(10), .WINDOW_HEIGHT(4)
    ) dut (.*);

    function automatic [15:0] sibling_identity;
        input [15:0] target_value;
        input [7:0] height_value;
        begin
            sibling_identity =
                (((target_value >> height_value) ^ 16'd1) << height_value);
        end
    endfunction

    function automatic [255:0] node_for_level;
        input [7:0] height_value;
        reg [7:0] fill_byte;
        begin
            fill_byte = 8'h40 + height_value;
            node_for_level = {32{fill_byte}};
        end
    endfunction

    task automatic activate_for_target;
        input [15:0] target_value;
        begin
            @(negedge clk);
            while (!activate_ready) @(negedge clk);
            activate_target_leaf = target_value;
            activate_valid = 1'b1;
            @(posedge clk);
            #1 activate_valid = 1'b0;
        end
    endtask

    task automatic store_node;
        input [7:0] height_value;
        input [15:0] start_value;
        input [255:0] value;
        begin
            @(negedge clk);
            store_height = height_value;
            store_start_leaf = start_value;
            store_value = value;
            store_valid = 1'b1;
            @(posedge clk);
            #1 store_valid = 1'b0;
        end
    endtask

    task automatic check_lookup;
        input [7:0] height_value;
        input [15:0] start_value;
        input expected_hit;
        input [255:0] expected_value;
        input expected_bounds;
        begin
            while (!lookup_ready) @(negedge clk);
            @(negedge clk);
            lookup_height = height_value;
            lookup_start_leaf = start_value;
            lookup_valid = 1'b1;
            @(posedge clk);
            #1 lookup_valid = 1'b0;
            if (!lookup_rsp_valid || lookup_hit !== expected_hit
                || bounds_error !== expected_bounds)
                $fatal(1, "lookup status h=%0d start=%0d rsp=%0d hit=%0d bounds=%0d",
                       height_value, start_value, lookup_rsp_valid,
                       lookup_hit, bounds_error);
            if (lookup_value !== expected_value)
                $fatal(1, "lookup data h=%0d start=%0d got=%064x expected=%064x",
                       height_value, start_value, lookup_value, expected_value);
        end
    endtask

    initial begin
        repeat (3) @(posedge clk);
        rst_n = 1'b1;
        if (upper_capacity_nodes != 127 || lower_capacity_nodes != 30
            || total_capacity_nodes != 157 || logical_capacity_bytes != 5024)
            $fatal(1, "capacity mismatch upper=%0d lower=%0d total=%0d bytes=%0d",
                   upper_capacity_nodes, lower_capacity_nodes,
                   total_capacity_nodes, logical_capacity_bytes);

        // Known target-5 sibling identities across an h10 tree.
        if (sibling_identity(5, 0) != 4 || sibling_identity(5, 1) != 6
            || sibling_identity(5, 2) != 0 || sibling_identity(5, 3) != 8
            || sibling_identity(5, 4) != 16 || sibling_identity(5, 5) != 32
            || sibling_identity(5, 6) != 64 || sibling_identity(5, 7) != 128
            || sibling_identity(5, 8) != 256 || sibling_identity(5, 9) != 512)
            $fatal(1, "target-5 sibling identity formula mismatch");

        // The host supplies only target=5; RTL derives aligned base 0.
        activate_for_target(5);
        if (error || !active_window_valid || active_window_base != 0
            || window_switches != 1)
            $fatal(1, "initial activation failed err=%0d code=%h valid=%0d base=%0d switches=%0d ready=%0d",
                   error, error_code, active_window_valid, active_window_base,
                   window_switches, activate_ready);

        // Emulate internal TreeHash node-retirement events.  h0..h3 enter the
        // active 16-leaf region; h4..h9 enter the permanent global region.
        for (level = 0; level < 10; level = level + 1)
            store_node(level[7:0], sibling_identity(5, level[7:0]),
                       node_for_level(level[7:0]));
        if (lower_writes != 4 || lower_retained_nodes != 4
            || upper_writes != 6 || upper_retained_nodes != 6)
            $fatal(1, "initial retention lower=%0d/%0d upper=%0d/%0d",
                   lower_retained_nodes, lower_writes,
                   upper_retained_nodes, upper_writes);

        // All ten target-5 authentication siblings are warm.
        for (level = 0; level < 10; level = level + 1)
            check_lookup(level[7:0], sibling_identity(5, level[7:0]),
                         1'b1, node_for_level(level[7:0]), 1'b0);
        if (lookup_requests != 10 || cache_hits != 10 || cache_misses != 0)
            $fatal(1, "warm lookup accounting req=%0d hits=%0d misses=%0d",
                   lookup_requests, cache_hits, cache_misses);

        // One target=21 activation makes RTL derive base 16.  It invalidates
        // every lower node but preserves all six populated permanent nodes.
        activate_for_target(21);
        if (error || active_window_base != 16 || lower_retained_nodes != 0
            || upper_retained_nodes != 6 || window_switches != 2)
            $fatal(1, "window switch did not preserve upper/clear lower");
        for (level = 0; level < 4; level = level + 1)
            check_lookup(level[7:0], sibling_identity(5, level[7:0]),
                         1'b0, 256'b0, 1'b0);
        for (level = 4; level < 10; level = level + 1)
            check_lookup(level[7:0], sibling_identity(5, level[7:0]),
                         1'b1, node_for_level(level[7:0]), 1'b0);
        if (lookup_requests != 20 || cache_hits != 16 || cache_misses != 4)
            $fatal(1, "post-switch accounting req=%0d hits=%0d misses=%0d",
                   lookup_requests, cache_hits, cache_misses);

        // Populate one node in the new window, then prove job_busy rejects a
        // target=37 activation (which would otherwise derive base 32).
        store_node(0, 20, {32{8'hb4}});
        if (lower_writes != 5 || lower_retained_nodes != 1)
            $fatal(1, "new-window lower node not retained");
        @(negedge clk);
        job_busy = 1'b1;
        activate_target_leaf = 16'd37;
        activate_valid = 1'b1;
        @(posedge clk);
        #1 activate_valid = 1'b0;
        job_busy = 1'b0;
        if (!error || error_code != 16'h0232 || active_window_base != 16
            || lower_retained_nodes != 1 || window_switches != 2)
            $fatal(1, "busy activation was not fail-closed");
        check_lookup(0, 20, 1'b1, {32{8'hb4}}, 1'b0);

        // Recover, refill, and attempt activation while the lookup response is
        // still in flight.  The active window and its node must remain intact.
        activate_for_target(21);
        if (error || window_switches != 3 || lower_retained_nodes != 0)
            $fatal(1, "recovery before in-flight lookup test failed");
        store_node(0, 20, {32{8'hb5}});
        check_lookup(0, 20, 1'b1, {32{8'hb5}}, 1'b0);
        @(negedge clk);
        activate_target_leaf = 16'd37;
        activate_valid = 1'b1;
        @(posedge clk);
        #1 activate_valid = 1'b0;
        if (!error || error_code != 16'h0232 || active_window_base != 16
            || lower_retained_nodes != 1 || window_switches != 3)
            $fatal(1, "lookup-active activation was not fail-closed");

        // Invalid internal store and lookup identities cannot alias a physical
        // entry or alter write/retention counts.
        activate_for_target(21);
        if (error || window_switches != 4 || lower_retained_nodes != 0)
            $fatal(1, "recovery before identity tests failed");
        store_node(11, 0, {32{8'hee}});
        if (!error || error_code != 16'h0233 || upper_writes != 6
            || lower_writes != 6 || upper_retained_nodes != 6
            || lower_retained_nodes != 0)
            $fatal(1, "invalid store was not fail-closed");

        activate_for_target(21);
        if (error || window_switches != 5)
            $fatal(1, "recovery before invalid lookup failed");
        check_lookup(11, 0, 1'b0, 256'b0, 1'b1);
        if (!error || error_code != 16'h0234 || lookup_requests != 23
            || cache_hits != 18 || cache_misses != 4)
            $fatal(1, "invalid lookup accounting/fail-close mismatch");

        // Target 1024 is out of the h10 tree.  It is rejected without changing
        // the currently derived base or invalidating permanent upper entries.
        activate_for_target(21);
        if (error || window_switches != 6)
            $fatal(1, "final recovery activation failed");
        activate_for_target(1024);
        if (!error || error_code != 16'h0231 || active_window_base != 16
            || window_switches != 6 || upper_retained_nodes != 6
            || lower_retained_nodes != 0 || upper_writes != 6
            || lower_writes != 6)
            $fatal(1, "out-of-tree target activation was not fail-closed");

        $display("PASS warm active cache h10/w4 activate target5->base0 target21->base16 capacity=127+30=157 nodes/5024B auth-hits=10 switch-low-misses=4 upper-retained=6 writes=6+6 busy/lookup/errors fail-closed");
        $finish;
    end
endmodule

`default_nettype wire
