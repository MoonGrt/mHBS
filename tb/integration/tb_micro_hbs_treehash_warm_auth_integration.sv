`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_treehash_warm_auth_integration;
    logic clk = 1'b0;
    logic rst_n = 1'b0;

    logic clear_all = 1'b0;
    logic activate_valid = 1'b0;
    wire activate_ready;
    logic [15:0] activate_target_leaf = '0;
    wire active_window_valid;
    wire [15:0] active_window_base;
    logic store_valid = 1'b0;
    logic [7:0] store_height = '0;
    logic [15:0] store_start_leaf = '0;
    logic [255:0] store_value = '0;

    logic provider_start = 1'b0;
    wire provider_ready, provider_busy, provider_done, provider_error;
    logic [15:0] provider_target_leaf = '0;
    wire [15:0] provider_error_code;
    wire cache_lookup_valid, cache_lookup_ready;
    wire [7:0] cache_lookup_height;
    wire [15:0] cache_lookup_start_leaf;
    wire cache_rsp_valid, cache_hit, cache_bounds_error;
    wire [255:0] cache_value;
    wire recompute_req_valid;
    wire [7:0] recompute_req_height;
    wire [15:0] recompute_req_start_leaf;
    wire auth_valid;
    logic auth_ready = 1'b1;
    wire [7:0] auth_level;
    wire [255:0] auth_node;
    wire [31:0] provider_hits, provider_misses;
    wire [31:0] provider_recompute_requests, provider_cycles;

    wire cache_busy, cache_error;
    wire [15:0] cache_error_code;
    wire [31:0] upper_writes, lower_writes;
    wire [31:0] upper_retained_nodes, lower_retained_nodes;
    wire [31:0] lookup_requests, cache_hits, cache_misses, window_switches;
    wire [31:0] upper_capacity_nodes, lower_capacity_nodes;
    wire [31:0] total_capacity_nodes, logical_capacity_bytes;

    reg [255:0] path_target5 [0:9];
    reg [255:0] path_target21 [0:9];
    reg [9:0] mask_target5 = '0;
    reg [9:0] mask_target21 = '0;
    integer active_job = 0;
    integer job_query_count = 0;
    integer job_auth_count = 0;
    integer total_query_count = 0;
    integer recompute_seen = 0;
    integer stalled_auth_cycles = 0;
    integer level;

    always #5 clk = ~clk;

    function automatic [15:0] sibling_identity;
        input [15:0] target_value;
        input [7:0] height_value;
        begin
            sibling_identity =
                (((target_value >> height_value) ^ 16'd1) << height_value);
        end
    endfunction

    function automatic [255:0] identity_value;
        input [7:0] height_value;
        input [15:0] start_value;
        reg [31:0] identity_word;
        begin
            identity_word = 32'ha5000000
                | ({24'b0, height_value} << 16) | {16'b0, start_value};
            identity_value = {8{identity_word}};
        end
    endfunction

    micro_hbs_treehash_warm_active_cache #(
        .TREE_HEIGHT(10), .WINDOW_HEIGHT(4)
    ) warm_cache (
        .clk, .rst_n, .clear_all, .job_busy(provider_busy),
        .activate_valid, .activate_ready, .activate_target_leaf,
        .active_window_valid, .active_window_base,
        .store_valid, .store_height, .store_start_leaf, .store_value,
        .lookup_valid(cache_lookup_valid), .lookup_ready(cache_lookup_ready),
        .lookup_height(cache_lookup_height),
        .lookup_start_leaf(cache_lookup_start_leaf),
        .lookup_rsp_valid(cache_rsp_valid), .lookup_hit(cache_hit),
        .lookup_value(cache_value), .bounds_error(cache_bounds_error),
        .busy(cache_busy), .error(cache_error), .error_code(cache_error_code),
        .upper_writes, .lower_writes, .upper_retained_nodes,
        .lower_retained_nodes, .lookup_requests, .cache_hits, .cache_misses,
        .window_switches, .upper_capacity_nodes, .lower_capacity_nodes,
        .total_capacity_nodes, .logical_capacity_bytes
    );

    micro_hbs_treehash_auth_provider #(.TREE_HEIGHT(10)) provider (
        .clk, .rst_n, .start(provider_start), .ready(provider_ready),
        .target_leaf(provider_target_leaf),
        .cache_lookup_valid, .cache_lookup_ready, .cache_lookup_height,
        .cache_lookup_start_leaf, .cache_rsp_valid, .cache_hit, .cache_value,
        .cache_bounds_error,
        .recompute_req_valid, .recompute_req_ready(1'b1),
        .recompute_req_height, .recompute_req_start_leaf,
        .recompute_rsp_valid(1'b0), .recompute_rsp_value(256'b0),
        .recompute_rsp_error(1'b0),
        .auth_valid, .auth_ready, .auth_level, .auth_node,
        .done(provider_done), .busy(provider_busy), .error(provider_error),
        .error_code(provider_error_code), .cache_hits(provider_hits),
        .cache_misses(provider_misses),
        .recompute_requests(provider_recompute_requests), .cycles(provider_cycles)
    );

    // Observe only hardware-generated cache requests.  The TB never drives
    // lookup height/start_leaf during either formal provider operation.
    always @(posedge clk) begin
        if (rst_n && cache_lookup_valid && cache_lookup_ready) begin
            if (active_job == 0)
                $fatal(1, "cache lookup outside an active provider job");
            if (cache_lookup_height !== job_query_count[7:0]
                || cache_lookup_start_leaf !== sibling_identity(
                    (active_job == 1) ? 16'd5 : 16'd21,
                    job_query_count[7:0]))
                $fatal(1, "provider identity mismatch job=%0d query=%0d h=%0d start=%0d",
                       active_job, job_query_count, cache_lookup_height,
                       cache_lookup_start_leaf);
            job_query_count = job_query_count + 1;
            total_query_count = total_query_count + 1;
        end

        if (rst_n && auth_valid && auth_ready) begin
            if (auth_level !== job_auth_count[7:0])
                $fatal(1, "auth ordering mismatch job=%0d count=%0d level=%0d",
                       active_job, job_auth_count, auth_level);
            if (auth_node !== identity_value(
                    auth_level,
                    sibling_identity((active_job == 1) ? 16'd5 : 16'd21,
                                     auth_level)))
                $fatal(1, "auth value mismatch job=%0d level=%0d",
                       active_job, auth_level);
            if (active_job == 1) begin
                path_target5[auth_level] <= auth_node;
                mask_target5[auth_level] <= 1'b1;
            end else if (active_job == 2) begin
                path_target21[auth_level] <= auth_node;
                mask_target21[auth_level] <= 1'b1;
            end else begin
                $fatal(1, "auth output outside an active job");
            end
            job_auth_count = job_auth_count + 1;
        end

        if (rst_n && auth_valid && !auth_ready)
            stalled_auth_cycles = stalled_auth_cycles + 1;
        if (rst_n && recompute_req_valid) begin
            recompute_seen = recompute_seen + 1;
            $fatal(1, "unexpected recompute request h=%0d start=%0d",
                   recompute_req_height, recompute_req_start_leaf);
        end
    end

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

    task automatic retire_node;
        input [7:0] height_value;
        input [15:0] start_value;
        begin
            @(negedge clk);
            store_height = height_value;
            store_start_leaf = start_value;
            store_value = identity_value(height_value, start_value);
            store_valid = 1'b1;
            @(posedge clk);
            #1 store_valid = 1'b0;
        end
    endtask

    task automatic start_provider_job;
        input [15:0] target_value;
        begin
            @(negedge clk);
            if (!provider_ready)
                $fatal(1, "provider not ready before target=%0d", target_value);
            provider_target_leaf = target_value;
            provider_start = 1'b1;
            @(posedge clk);
            #1 provider_start = 1'b0;
        end
    endtask

    initial begin : test_sequence
        reg [255:0] held_auth_node;
        reg [7:0] held_auth_level;

        repeat (3) @(posedge clk);
        rst_n = 1'b1;
        if (upper_capacity_nodes != 127 || lower_capacity_nodes != 30
            || total_capacity_nodes != 157 || logical_capacity_bytes != 5024)
            $fatal(1, "warm-cache capacity mismatch");

        // Internal TreeHash retirement prefill for target 5.  A complete tree
        // also retires the adjacent h4/start0 root; retain it now so target 21
        // can later reuse all six upper levels without any upper refill.
        activate_for_target(5);
        if (!active_window_valid || active_window_base != 0)
            $fatal(1, "target 5 did not derive active base 0");
        for (level = 0; level < 10; level = level + 1)
            retire_node(level[7:0], sibling_identity(5, level[7:0]));
        retire_node(4, sibling_identity(21, 4));
        if (lower_writes != 4 || lower_retained_nodes != 4
            || upper_writes != 7 || upper_retained_nodes != 7)
            $fatal(1, "target-5 prefill accounting mismatch");

        // Provider operation 1: one start command only.  Stall the first auth
        // node for exactly two cycles and prove valid/level/data remain stable.
        active_job = 1;
        job_query_count = 0;
        job_auth_count = 0;
        auth_ready = 1'b0;
        start_provider_job(5);
        wait (auth_valid);
        held_auth_node = auth_node;
        held_auth_level = auth_level;
        repeat (2) begin
            @(posedge clk);
            #1;
            if (!auth_valid || auth_node !== held_auth_node
                || auth_level !== held_auth_level)
                $fatal(1, "auth output changed under backpressure");
        end
        @(negedge clk);
        auth_ready = 1'b1;
        while (!provider_done) begin
            @(posedge clk);
            #1;
        end
        if (provider_error || job_query_count != 10 || job_auth_count != 10
            || mask_target5 != 10'h3ff || provider_hits != 10
            || provider_misses != 0 || provider_recompute_requests != 0
            || provider_cycles != 32 || stalled_auth_cycles != 2)
            $fatal(1, "target-5 provider result q=%0d auth=%0d hit=%0d miss=%0d rec=%0d cycles=%0d stalls=%0d",
                   job_query_count, job_auth_count, provider_hits,
                   provider_misses, provider_recompute_requests,
                   provider_cycles, stalled_auth_cycles);
        for (level = 0; level < 10; level = level + 1)
            if (path_target5[level] !== identity_value(
                    level[7:0], sibling_identity(5, level[7:0])))
                $fatal(1, "target-5 path mismatch level=%0d", level);

        // target 21 derives base 16.  Only h0..h3 are refilled; the upper
        // write count must remain seven, proving all h4..h9 nodes are reused.
        active_job = 0;
        activate_for_target(21);
        if (active_window_base != 16 || lower_retained_nodes != 0
            || upper_retained_nodes != 7 || window_switches != 2)
            $fatal(1, "target 21 did not derive base 16/preserve upper cache");
        for (level = 0; level < 4; level = level + 1)
            retire_node(level[7:0], sibling_identity(21, level[7:0]));
        if (lower_writes != 8 || lower_retained_nodes != 4
            || upper_writes != 7 || upper_retained_nodes != 7)
            $fatal(1, "target-21 lower-only refill changed upper cache");

        // Provider operation 2: again only one start command, no lookup drive.
        active_job = 2;
        job_query_count = 0;
        job_auth_count = 0;
        start_provider_job(21);
        while (!provider_done) begin
            @(posedge clk);
            #1;
        end
        if (provider_error || job_query_count != 10 || job_auth_count != 10
            || mask_target21 != 10'h3ff || provider_hits != 10
            || provider_misses != 0 || provider_recompute_requests != 0
            || provider_cycles != 30 || total_query_count != 20
            || recompute_seen != 0 || lookup_requests != 20
            || cache_hits != 20 || cache_misses != 0)
            $fatal(1, "target-21/provider aggregate mismatch q=%0d auth=%0d hit=%0d miss=%0d rec=%0d cycles=%0d totalq=%0d",
                   job_query_count, job_auth_count, provider_hits,
                   provider_misses, provider_recompute_requests,
                   provider_cycles, total_query_count);
        for (level = 0; level < 10; level = level + 1)
            if (path_target21[level] !== identity_value(
                    level[7:0], sibling_identity(21, level[7:0])))
                $fatal(1, "target-21 path mismatch level=%0d", level);
        if (cache_error || cache_error_code != 0 || cache_busy)
            $fatal(1, "cache ended in error/busy code=%h", cache_error_code);

        $display("PASS combined warm-cache/auth-provider target5=10/10 hits target21=10/10 hits upper-reused=7 nodes recompute=0 backpressure=2 cycles paths exact");
        $finish;
    end
endmodule

`default_nettype wire
