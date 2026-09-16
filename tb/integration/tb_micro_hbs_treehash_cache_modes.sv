`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_treehash_cache_modes;
    localparam integer SUBTREE_CACHE = 1;
    localparam integer FULL_CACHE = 2;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic start = 1'b0;
    logic [15:0] target_leaf = 16'd5;
    logic leaf_valid = 1'b0;
    logic [15:0] leaf_index = '0;
    logic [255:0] leaf_value = '0;
    logic cache_clear = 1'b0;

    wire full_ready, full_leaf_ready;
    wire full_parent_req_valid, full_parent_req_ready;
    wire [7:0] full_parent_req_height;
    wire [15:0] full_parent_req_start_leaf;
    wire [255:0] full_parent_req_left, full_parent_req_right;
    wire full_parent_rsp_valid, full_parent_rsp_error;
    wire [255:0] full_parent_rsp_value;
    wire full_auth_valid, full_root_valid, full_busy, full_error;
    wire [7:0] full_auth_level;
    wire [255:0] full_auth_node, full_root;
    wire [15:0] full_error_code, full_accepted_leaves, full_parent_hashes;
    wire [7:0] full_peak_stack_nodes;
    logic full_lookup_valid = 1'b0;
    wire full_lookup_ready, full_cache_rsp_valid, full_cache_hit;
    logic [7:0] full_lookup_height = '0;
    logic [15:0] full_lookup_start = '0;
    wire [255:0] full_cache_value;
    wire full_cache_bounds_error, full_cache_error;
    wire [15:0] full_cache_error_code;
    wire [31:0] full_cache_writes, full_cache_retained, full_cache_capacity;

    wire sub_ready, sub_leaf_ready;
    wire sub_parent_req_valid, sub_parent_req_ready;
    wire [7:0] sub_parent_req_height;
    wire [15:0] sub_parent_req_start_leaf;
    wire [255:0] sub_parent_req_left, sub_parent_req_right;
    wire sub_parent_rsp_valid, sub_parent_rsp_error;
    wire [255:0] sub_parent_rsp_value;
    wire sub_auth_valid, sub_root_valid, sub_busy, sub_error;
    wire [7:0] sub_auth_level;
    wire [255:0] sub_auth_node, sub_root;
    wire [15:0] sub_error_code, sub_accepted_leaves, sub_parent_hashes;
    wire [7:0] sub_peak_stack_nodes;
    logic sub_lookup_valid = 1'b0;
    wire sub_lookup_ready, sub_cache_rsp_valid, sub_cache_hit;
    logic [7:0] sub_lookup_height = '0;
    logic [15:0] sub_lookup_start = '0;
    wire [255:0] sub_cache_value;
    wire sub_cache_bounds_error, sub_cache_error;
    wire [15:0] sub_cache_error_code;
    wire [31:0] sub_cache_writes, sub_cache_retained, sub_cache_capacity;

    reg [255:0] full_auth [0:2];
    reg [255:0] sub_auth [0:2];
    reg [2:0] full_auth_mask = '0;
    reg [2:0] sub_auth_mask = '0;
    reg [255:0] full_root_saved = '0;
    reg [255:0] sub_root_saved = '0;
    reg full_root_seen = 1'b0;
    reg sub_root_seen = 1'b0;
    integer i;
    integer watchdog = 0;

    localparam logic [255:0] EXPECTED_ROOT =
        256'h8b6d34f4de669ae6d99c1d69d9ea4677461e47f99f659752bdfe48fe0e630cd8;
    localparam logic [255:0] EXPECTED_AUTH1 =
        256'h37625def1a14451301f6c7427d36d89fb377086b3364fc1c80f9c9a30f0bf83b;
    localparam logic [255:0] EXPECTED_AUTH2 =
        256'h9c76244d9eae66584ddaf7df47f84479f3005c6f450e1bdc01ce7b3c54ce3d31;

    always #5 clk = ~clk;

    always @(posedge clk) begin
        if (rst_n && full_auth_valid) begin
            full_auth[full_auth_level] <= full_auth_node;
            full_auth_mask[full_auth_level] <= 1'b1;
        end
        if (rst_n && sub_auth_valid) begin
            sub_auth[sub_auth_level] <= sub_auth_node;
            sub_auth_mask[sub_auth_level] <= 1'b1;
        end
        if (rst_n && full_root_valid) begin
            full_root_saved <= full_root;
            full_root_seen <= 1'b1;
        end
        if (rst_n && sub_root_valid) begin
            sub_root_saved <= sub_root;
            sub_root_seen <= 1'b1;
        end
        if (rst_n && (full_busy || sub_busy)) begin
            watchdog <= watchdog + 1;
            if (watchdog > 500)
                $fatal(1, "cached TreeHash timeout");
        end
    end

    micro_hbs_treehash_cached #(
        .TREE_HEIGHT(3), .CACHE_MODE(FULL_CACHE), .SUBTREE_HEIGHT(2)
    ) full_tree (
        .clk, .rst_n, .start, .ready(full_ready), .target_leaf,
        .leaf_valid, .leaf_ready(full_leaf_ready), .leaf_index, .leaf_value,
        .parent_req_valid(full_parent_req_valid),
        .parent_req_ready(full_parent_req_ready),
        .parent_req_height(full_parent_req_height),
        .parent_req_start_leaf(full_parent_req_start_leaf),
        .parent_req_left(full_parent_req_left),
        .parent_req_right(full_parent_req_right),
        .parent_rsp_valid(full_parent_rsp_valid),
        .parent_rsp_value(full_parent_rsp_value),
        .parent_rsp_error(full_parent_rsp_error),
        .auth_valid(full_auth_valid), .auth_level(full_auth_level),
        .auth_node(full_auth_node), .root_valid(full_root_valid), .root(full_root),
        .busy(full_busy), .error(full_error), .error_code(full_error_code),
        .accepted_leaves(full_accepted_leaves), .parent_hashes(full_parent_hashes),
        .peak_stack_nodes(full_peak_stack_nodes), .cache_clear,
        .cache_lookup_valid(full_lookup_valid),
        .cache_lookup_ready(full_lookup_ready),
        .cache_lookup_height(full_lookup_height),
        .cache_lookup_start_leaf(full_lookup_start),
        .cache_rsp_valid(full_cache_rsp_valid), .cache_hit(full_cache_hit),
        .cache_value(full_cache_value),
        .cache_bounds_error(full_cache_bounds_error),
        .cache_error(full_cache_error), .cache_error_code(full_cache_error_code),
        .cache_writes(full_cache_writes),
        .cache_retained_nodes(full_cache_retained),
        .cache_capacity_nodes(full_cache_capacity)
    );

    micro_hbs_tree_parent_shake #(.UNROLL(2)) full_parent_hash (
        .clk, .rst_n, .req_valid(full_parent_req_valid),
        .req_ready(full_parent_req_ready), .left_node(full_parent_req_left),
        .right_node(full_parent_req_right), .rsp_valid(full_parent_rsp_valid),
        .rsp_value(full_parent_rsp_value), .rsp_error(full_parent_rsp_error)
    );

    micro_hbs_treehash_cached #(
        .TREE_HEIGHT(3), .CACHE_MODE(SUBTREE_CACHE), .SUBTREE_HEIGHT(2)
    ) sub_tree (
        .clk, .rst_n, .start, .ready(sub_ready), .target_leaf,
        .leaf_valid, .leaf_ready(sub_leaf_ready), .leaf_index, .leaf_value,
        .parent_req_valid(sub_parent_req_valid),
        .parent_req_ready(sub_parent_req_ready),
        .parent_req_height(sub_parent_req_height),
        .parent_req_start_leaf(sub_parent_req_start_leaf),
        .parent_req_left(sub_parent_req_left),
        .parent_req_right(sub_parent_req_right),
        .parent_rsp_valid(sub_parent_rsp_valid),
        .parent_rsp_value(sub_parent_rsp_value),
        .parent_rsp_error(sub_parent_rsp_error),
        .auth_valid(sub_auth_valid), .auth_level(sub_auth_level),
        .auth_node(sub_auth_node), .root_valid(sub_root_valid), .root(sub_root),
        .busy(sub_busy), .error(sub_error), .error_code(sub_error_code),
        .accepted_leaves(sub_accepted_leaves), .parent_hashes(sub_parent_hashes),
        .peak_stack_nodes(sub_peak_stack_nodes), .cache_clear,
        .cache_lookup_valid(sub_lookup_valid),
        .cache_lookup_ready(sub_lookup_ready),
        .cache_lookup_height(sub_lookup_height),
        .cache_lookup_start_leaf(sub_lookup_start),
        .cache_rsp_valid(sub_cache_rsp_valid), .cache_hit(sub_cache_hit),
        .cache_value(sub_cache_value),
        .cache_bounds_error(sub_cache_bounds_error),
        .cache_error(sub_cache_error), .cache_error_code(sub_cache_error_code),
        .cache_writes(sub_cache_writes),
        .cache_retained_nodes(sub_cache_retained),
        .cache_capacity_nodes(sub_cache_capacity)
    );

    micro_hbs_tree_parent_shake #(.UNROLL(2)) sub_parent_hash (
        .clk, .rst_n, .req_valid(sub_parent_req_valid),
        .req_ready(sub_parent_req_ready), .left_node(sub_parent_req_left),
        .right_node(sub_parent_req_right), .rsp_valid(sub_parent_rsp_valid),
        .rsp_value(sub_parent_rsp_value), .rsp_error(sub_parent_rsp_error)
    );

    task automatic send_leaf;
        input [15:0] index_value;
        input [7:0] fill_byte;
        integer byte_index;
        begin
            while (!(full_leaf_ready && sub_leaf_ready)) @(negedge clk);
            leaf_index = index_value;
            for (byte_index = 0; byte_index < 32; byte_index = byte_index + 1)
                leaf_value[8*byte_index +: 8] = fill_byte;
            leaf_valid = 1'b1;
            @(posedge clk);
            #1 leaf_valid = 1'b0;
        end
    endtask

    task automatic check_full_lookup;
        input [7:0] height_value;
        input [15:0] start_value;
        input expected_hit;
        input [255:0] expected_value;
        input expected_bounds;
        begin
            @(negedge clk);
            full_lookup_height = height_value;
            full_lookup_start = start_value;
            full_lookup_valid = 1'b1;
            @(posedge clk);
            #1 full_lookup_valid = 1'b0;
            if (!full_cache_rsp_valid || full_cache_hit !== expected_hit
                || full_cache_bounds_error !== expected_bounds)
                $fatal(1, "FULL lookup status h=%0d start=%0d rsp=%0d hit=%0d bounds=%0d",
                       height_value, start_value, full_cache_rsp_valid,
                       full_cache_hit, full_cache_bounds_error);
            if (full_cache_value !== expected_value)
                $fatal(1, "FULL lookup value h=%0d start=%0d got=%064x",
                       height_value, start_value, full_cache_value);
        end
    endtask

    task automatic check_sub_lookup;
        input [7:0] height_value;
        input [15:0] start_value;
        input expected_hit;
        input [255:0] expected_value;
        input expected_bounds;
        begin
            @(negedge clk);
            sub_lookup_height = height_value;
            sub_lookup_start = start_value;
            sub_lookup_valid = 1'b1;
            @(posedge clk);
            #1 sub_lookup_valid = 1'b0;
            if (!sub_cache_rsp_valid || sub_cache_hit !== expected_hit
                || sub_cache_bounds_error !== expected_bounds)
                $fatal(1, "SUB lookup status h=%0d start=%0d rsp=%0d hit=%0d bounds=%0d",
                       height_value, start_value, sub_cache_rsp_valid,
                       sub_cache_hit, sub_cache_bounds_error);
            if (sub_cache_value !== expected_value)
                $fatal(1, "SUB lookup value h=%0d start=%0d got=%064x",
                       height_value, start_value, sub_cache_value);
        end
    endtask

    initial begin
        repeat (3) @(posedge clk);
        rst_n = 1'b1;
        @(negedge clk);
        if (!full_ready || !sub_ready) $fatal(1, "wrappers not ready after reset");
        start = 1'b1;
        @(posedge clk);
        #1 start = 1'b0;

        for (i = 0; i < 8; i = i + 1)
            send_leaf(i[15:0], i[7:0]);

        while (!(full_root_seen && sub_root_seen)) begin
            @(posedge clk);
            #1;
        end
        if (full_error || sub_error)
            $fatal(1, "TreeHash/cache build error full=%h sub=%h",
                   full_error_code, sub_error_code);
        if (full_root_saved !== EXPECTED_ROOT || sub_root_saved !== EXPECTED_ROOT)
            $fatal(1, "cached roots differ from TreeHash oracle");
        if (full_auth_mask != 3'b111 || sub_auth_mask != 3'b111)
            $fatal(1, "incomplete auth paths full=%b sub=%b", full_auth_mask, sub_auth_mask);
        if (full_auth[0] !== {32{8'h04}} || sub_auth[0] !== {32{8'h04}}
            || full_auth[1] !== EXPECTED_AUTH1 || sub_auth[1] !== EXPECTED_AUTH1
            || full_auth[2] !== EXPECTED_AUTH2 || sub_auth[2] !== EXPECTED_AUTH2)
            $fatal(1, "authentication path mismatch");
        if (full_cache_capacity != 15 || full_cache_retained != 15
            || full_cache_writes != 15)
            $fatal(1, "FULL retention mismatch cap=%0d retained=%0d writes=%0d",
                   full_cache_capacity, full_cache_retained, full_cache_writes);
        if (sub_cache_capacity != 3 || sub_cache_retained != 3
            || sub_cache_writes != 3)
            $fatal(1, "SUBTREE retention mismatch cap=%0d retained=%0d writes=%0d",
                   sub_cache_capacity, sub_cache_retained, sub_cache_writes);

        // FULL_CACHE serves the complete authentication path and root.
        check_full_lookup(0, 4, 1'b1, {32{8'h04}}, 1'b0);
        check_full_lookup(1, 6, 1'b1, EXPECTED_AUTH1, 1'b0);
        check_full_lookup(2, 0, 1'b1, EXPECTED_AUTH2, 1'b0);
        check_full_lookup(3, 0, 1'b1, EXPECTED_ROOT, 1'b0);

        // SUBTREE_CACHE(h>=2) cleanly misses lower nodes but retains upper ones.
        check_sub_lookup(0, 4, 1'b0, 256'b0, 1'b0);
        check_sub_lookup(1, 6, 1'b0, 256'b0, 1'b0);
        check_sub_lookup(2, 0, 1'b1, EXPECTED_AUTH2, 1'b0);
        check_sub_lookup(3, 0, 1'b1, EXPECTED_ROOT, 1'b0);

        // Out-of-tree and unaligned identities fail closed with no data exposure.
        check_full_lookup(0, 8, 1'b0, 256'b0, 1'b1);
        check_sub_lookup(2, 1, 1'b0, 256'b0, 1'b1);
        if (!full_cache_error || full_cache_error_code != 16'h0212
            || !sub_cache_error || sub_cache_error_code != 16'h0212)
            $fatal(1, "cache identity errors were not latched");

        // Explicit cleanup invalidates retained nodes without reading RAM data.
        @(negedge clk);
        cache_clear = 1'b1;
        @(posedge clk);
        #1 cache_clear = 1'b0;
        if (full_cache_retained != 0 || sub_cache_retained != 0
            || full_cache_error || sub_cache_error)
            $fatal(1, "cache clear did not reset metadata/error state");
        check_full_lookup(3, 0, 1'b0, 256'b0, 1'b0);
        check_sub_lookup(3, 0, 1'b0, 256'b0, 1'b0);

        $display("PASS TreeHash cache modes root/auth exact FULL=15 SUBTREE(h>=2)=3 OOB fail-closed clear-safe");
        $finish;
    end
endmodule

`default_nettype wire
