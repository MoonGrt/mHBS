`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_treehash_auth_provider;
    localparam integer SUBTREE_CACHE = 1;
    localparam integer FULL_CACHE = 2;
    localparam logic [255:0] AUTH0 = {32{8'h04}};
    localparam logic [255:0] AUTH1 =
        256'h37625def1a14451301f6c7427d36d89fb377086b3364fc1c80f9c9a30f0bf83b;
    localparam logic [255:0] AUTH2 =
        256'h9c76244d9eae66584ddaf7df47f84479f3005c6f450e1bdc01ce7b3c54ce3d31;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic cache_clear = 1'b0;
    logic store_valid = 1'b0;
    logic [7:0] store_height = '0;
    logic [15:0] store_start = '0;
    logic [255:0] store_value = '0;

    logic full_start = 1'b0;
    logic [15:0] full_target = 16'd5;
    wire full_ready, full_busy, full_done, full_error;
    wire [15:0] full_error_code;
    wire full_cache_lookup_valid, full_cache_lookup_ready;
    wire [7:0] full_cache_lookup_height;
    wire [15:0] full_cache_lookup_start;
    wire full_cache_rsp_valid, full_cache_hit, full_cache_bounds;
    wire [255:0] full_cache_value;
    wire full_auth_valid;
    wire [7:0] full_auth_level;
    wire [255:0] full_auth_node;
    wire full_recompute_req_valid;
    wire [7:0] full_recompute_req_height;
    wire [15:0] full_recompute_req_start;
    wire [31:0] full_hits, full_misses, full_recompute_requests, full_cycles;

    logic sub_start = 1'b0;
    logic [15:0] sub_target = 16'd5;
    wire sub_ready, sub_busy, sub_done, sub_error;
    wire [15:0] sub_error_code;
    wire sub_cache_lookup_valid, sub_cache_lookup_ready;
    wire [7:0] sub_cache_lookup_height;
    wire [15:0] sub_cache_lookup_start;
    wire sub_cache_rsp_valid, sub_cache_hit, sub_cache_bounds;
    wire [255:0] sub_cache_value;
    wire sub_auth_valid;
    wire [7:0] sub_auth_level;
    wire [255:0] sub_auth_node;
    wire sub_recompute_req_valid;
    wire [7:0] sub_recompute_req_height;
    wire [15:0] sub_recompute_req_start;
    logic sub_recompute_rsp_valid = 1'b0;
    logic [255:0] sub_recompute_rsp_value = '0;
    logic sub_recompute_rsp_error = 1'b0;
    logic sub_recompute_error_mode = 1'b0;
    wire [31:0] sub_hits, sub_misses, sub_recompute_requests, sub_cycles;

    wire full_cache_error, sub_cache_error;
    wire [15:0] full_cache_error_code, sub_cache_error_code;
    wire [31:0] full_cache_writes, full_cache_retained, full_cache_capacity;
    wire [31:0] sub_cache_writes, sub_cache_retained, sub_cache_capacity;

    reg [255:0] full_path [0:2];
    reg [255:0] sub_path [0:2];
    reg [2:0] full_mask = '0;
    reg [2:0] sub_mask = '0;
    reg full_done_seen = 1'b0;
    reg sub_done_seen = 1'b0;
    integer full_auth_events = 0;
    integer sub_auth_events = 0;
    integer sub_recompute_events = 0;
    integer watchdog = 0;

    always #5 clk = ~clk;

    micro_hbs_treehash_cache_store #(
        .TREE_HEIGHT(3), .CACHE_MODE(FULL_CACHE), .SUBTREE_HEIGHT(2)
    ) full_cache (
        .clk, .rst_n, .clear(cache_clear),
        .store_valid, .store_height, .store_start_leaf(store_start), .store_value,
        .lookup_valid(full_cache_lookup_valid),
        .lookup_ready(full_cache_lookup_ready),
        .lookup_height(full_cache_lookup_height),
        .lookup_start_leaf(full_cache_lookup_start),
        .lookup_rsp_valid(full_cache_rsp_valid), .lookup_hit(full_cache_hit),
        .lookup_value(full_cache_value), .bounds_error(full_cache_bounds),
        .error(full_cache_error), .error_code(full_cache_error_code),
        .cache_writes(full_cache_writes), .retained_nodes(full_cache_retained),
        .capacity_nodes(full_cache_capacity)
    );

    micro_hbs_treehash_cache_store #(
        .TREE_HEIGHT(3), .CACHE_MODE(SUBTREE_CACHE), .SUBTREE_HEIGHT(2)
    ) sub_cache (
        .clk, .rst_n, .clear(cache_clear),
        .store_valid, .store_height, .store_start_leaf(store_start), .store_value,
        .lookup_valid(sub_cache_lookup_valid),
        .lookup_ready(sub_cache_lookup_ready),
        .lookup_height(sub_cache_lookup_height),
        .lookup_start_leaf(sub_cache_lookup_start),
        .lookup_rsp_valid(sub_cache_rsp_valid), .lookup_hit(sub_cache_hit),
        .lookup_value(sub_cache_value), .bounds_error(sub_cache_bounds),
        .error(sub_cache_error), .error_code(sub_cache_error_code),
        .cache_writes(sub_cache_writes), .retained_nodes(sub_cache_retained),
        .capacity_nodes(sub_cache_capacity)
    );

    micro_hbs_treehash_auth_provider #(.TREE_HEIGHT(3)) full_provider (
        .clk, .rst_n, .start(full_start), .ready(full_ready),
        .target_leaf(full_target),
        .cache_lookup_valid(full_cache_lookup_valid),
        .cache_lookup_ready(full_cache_lookup_ready),
        .cache_lookup_height(full_cache_lookup_height),
        .cache_lookup_start_leaf(full_cache_lookup_start),
        .cache_rsp_valid(full_cache_rsp_valid), .cache_hit(full_cache_hit),
        .cache_value(full_cache_value), .cache_bounds_error(full_cache_bounds),
        .recompute_req_valid(full_recompute_req_valid),
        .recompute_req_ready(1'b1),
        .recompute_req_height(full_recompute_req_height),
        .recompute_req_start_leaf(full_recompute_req_start),
        .recompute_rsp_valid(1'b0), .recompute_rsp_value(256'b0),
        .recompute_rsp_error(1'b0),
        .auth_valid(full_auth_valid), .auth_ready(1'b1),
        .auth_level(full_auth_level), .auth_node(full_auth_node),
        .done(full_done), .busy(full_busy), .error(full_error),
        .error_code(full_error_code), .cache_hits(full_hits),
        .cache_misses(full_misses), .recompute_requests(full_recompute_requests),
        .cycles(full_cycles)
    );

    micro_hbs_treehash_auth_provider #(.TREE_HEIGHT(3)) sub_provider (
        .clk, .rst_n, .start(sub_start), .ready(sub_ready),
        .target_leaf(sub_target),
        .cache_lookup_valid(sub_cache_lookup_valid),
        .cache_lookup_ready(sub_cache_lookup_ready),
        .cache_lookup_height(sub_cache_lookup_height),
        .cache_lookup_start_leaf(sub_cache_lookup_start),
        .cache_rsp_valid(sub_cache_rsp_valid), .cache_hit(sub_cache_hit),
        .cache_value(sub_cache_value), .cache_bounds_error(sub_cache_bounds),
        .recompute_req_valid(sub_recompute_req_valid),
        .recompute_req_ready(1'b1),
        .recompute_req_height(sub_recompute_req_height),
        .recompute_req_start_leaf(sub_recompute_req_start),
        .recompute_rsp_valid(sub_recompute_rsp_valid),
        .recompute_rsp_value(sub_recompute_rsp_value),
        .recompute_rsp_error(sub_recompute_rsp_error),
        .auth_valid(sub_auth_valid), .auth_ready(1'b1),
        .auth_level(sub_auth_level), .auth_node(sub_auth_node),
        .done(sub_done), .busy(sub_busy), .error(sub_error),
        .error_code(sub_error_code), .cache_hits(sub_hits),
        .cache_misses(sub_misses), .recompute_requests(sub_recompute_requests),
        .cycles(sub_cycles)
    );

    // One-cycle recompute model.  It checks the provider-derived identity and
    // returns the independently fixed h=3 oracle node; no address is supplied
    // by the test after the single start command.
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sub_recompute_rsp_valid <= 1'b0;
            sub_recompute_rsp_value <= '0;
            sub_recompute_rsp_error <= 1'b0;
            sub_recompute_events <= 0;
        end else begin
            sub_recompute_rsp_valid <= 1'b0;
            sub_recompute_rsp_error <= 1'b0;
            if (sub_recompute_req_valid) begin
                sub_recompute_events <= sub_recompute_events + 1;
                if (sub_recompute_error_mode) begin
                    sub_recompute_rsp_value <= '0;
                    sub_recompute_rsp_error <= 1'b1;
                end else if (sub_recompute_req_height == 0
                             && sub_recompute_req_start == 4) begin
                    sub_recompute_rsp_value <= AUTH0;
                    sub_recompute_rsp_valid <= 1'b1;
                end else if (sub_recompute_req_height == 1
                             && sub_recompute_req_start == 6) begin
                    sub_recompute_rsp_value <= AUTH1;
                    sub_recompute_rsp_valid <= 1'b1;
                end else begin
                    sub_recompute_rsp_value <= '0;
                    sub_recompute_rsp_error <= 1'b1;
                end
            end
        end
    end

    always @(posedge clk) begin
        if (rst_n && full_auth_valid) begin
            full_path[full_auth_level] <= full_auth_node;
            full_mask[full_auth_level] <= 1'b1;
            full_auth_events <= full_auth_events + 1;
        end
        if (rst_n && sub_auth_valid) begin
            sub_path[sub_auth_level] <= sub_auth_node;
            sub_mask[sub_auth_level] <= 1'b1;
            sub_auth_events <= sub_auth_events + 1;
        end
        if (rst_n && full_done)
            full_done_seen <= 1'b1;
        if (rst_n && sub_done)
            sub_done_seen <= 1'b1;
        if (rst_n && (full_busy || sub_busy)) begin
            watchdog <= watchdog + 1;
            if (watchdog > 200)
                $fatal(1, "auth-provider timeout");
        end
    end

    task automatic preload_node;
        input [7:0] height_value;
        input [15:0] start_value;
        input [255:0] value;
        begin
            @(negedge clk);
            store_height = height_value;
            store_start = start_value;
            store_value = value;
            store_valid = 1'b1;
            @(posedge clk);
            #1 store_valid = 1'b0;
        end
    endtask

    initial begin
        repeat (3) @(posedge clk);
        rst_n = 1'b1;

        // Populate the three target-5 siblings.  The SUBTREE policy silently
        // ignores h0/h1 and retains only h2; FULL retains all three.
        preload_node(0, 4, AUTH0);
        preload_node(1, 6, AUTH1);
        preload_node(2, 0, AUTH2);
        if (full_cache_capacity != 15 || full_cache_retained != 3
            || full_cache_writes != 3)
            $fatal(1, "FULL preload accounting mismatch");
        if (sub_cache_capacity != 3 || sub_cache_retained != 1
            || sub_cache_writes != 1)
            $fatal(1, "SUBTREE preload accounting mismatch");
        if (full_cache_error || sub_cache_error)
            $fatal(1, "valid preload caused cache error");

        // A single autonomous start is the only per-job control input.
        @(negedge clk);
        full_start = 1'b1;
        sub_start = 1'b1;
        @(posedge clk);
        #1 full_start = 1'b0;
        sub_start = 1'b0;

        while (!(full_done_seen && sub_done_seen)) begin
            @(posedge clk);
            #1;
        end
        if (full_error || sub_error)
            $fatal(1, "auth provider error full=%h sub=%h",
                   full_error_code, sub_error_code);
        if (full_mask != 3'b111 || sub_mask != 3'b111)
            $fatal(1, "auth path masks full=%b sub=%b", full_mask, sub_mask);
        if (full_path[0] !== AUTH0 || full_path[1] !== AUTH1
            || full_path[2] !== AUTH2 || sub_path[0] !== AUTH0
            || sub_path[1] !== AUTH1 || sub_path[2] !== AUTH2)
            $fatal(1, "provider auth path differs from h3 SHAKE oracle");
        if (full_hits != 3 || full_misses != 0 || full_recompute_requests != 0
            || full_recompute_req_valid)
            $fatal(1, "FULL stats hits=%0d misses=%0d recompute=%0d",
                   full_hits, full_misses, full_recompute_requests);
        if (sub_hits != 1 || sub_misses != 2 || sub_recompute_requests != 2
            || sub_recompute_events != 2)
            $fatal(1, "SUBTREE stats hits=%0d misses=%0d recompute=%0d ext=%0d",
                   sub_hits, sub_misses, sub_recompute_requests,
                   sub_recompute_events);
        if (full_cycles != 9 || sub_cycles != 13)
            $fatal(1, "cycle accounting full=%0d sub=%0d", full_cycles, sub_cycles);

        // Invalid target fails before any cache/recompute request or auth emit.
        @(negedge clk);
        full_target = 16'd8;
        full_done_seen = 1'b0;
        full_start = 1'b1;
        @(posedge clk);
        #1 full_start = 1'b0;
        @(posedge clk);
        #1;
        if (!full_error || full_error_code != 16'h0221 || full_busy
            || full_cache_lookup_valid || full_recompute_req_valid
            || full_auth_valid || full_auth_node != 0 || full_done || full_hits != 0
            || full_misses != 0 || full_recompute_requests != 0
            || full_cycles != 0)
            $fatal(1, "invalid target did not fail closed");

        // Empty SUBTREE cache forces recompute; an error response must abort
        // before emitting any additional authentication node.
        @(negedge clk);
        cache_clear = 1'b1;
        @(posedge clk);
        #1 cache_clear = 1'b0;
        sub_recompute_error_mode = 1'b1;
        sub_target = 16'd5;
        sub_start = 1'b1;
        @(posedge clk);
        #1 sub_start = 1'b0;
        while (!sub_error) begin
            @(posedge clk);
            #1;
        end
        if (sub_error_code != 16'h0223 || sub_busy || sub_auth_valid
            || sub_auth_node != 0 || sub_done
            || sub_hits != 0 || sub_misses != 1 || sub_recompute_requests != 1
            || sub_auth_events != 3)
            $fatal(1, "recompute error did not fail closed code=%h events=%0d",
                   sub_error_code, sub_auth_events);

        $display("PASS auth provider FULL hits=3 misses=0 recompute=0 cycles=9; SUBTREE hits=1 misses=2 recompute=2 cycles=13; errors fail-closed");
        $finish;
    end
endmodule

`default_nettype wire
