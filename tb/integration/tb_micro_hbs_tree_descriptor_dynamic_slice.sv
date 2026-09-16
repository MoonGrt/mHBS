`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_tree_descriptor_dynamic_slice;
    localparam integer MAX_TREE_HEIGHT = 3;
    localparam integer DESCRIPTOR_COUNT = 7;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic cfg_valid = 1'b0;
    wire cfg_ready;
    logic [15:0] cfg_descriptor_id = '0;
    logic [127:0] cfg_descriptor = '0;
    wire cfg_error;
    wire [15:0] cfg_error_code;
    logic start_valid = 1'b0;
    wire start_ready;
    logic [15:0] start_descriptor_id = '0;
    logic [15:0] start_target_leaf = '0;
    logic leaf_valid = 1'b0;
    wire leaf_ready;
    logic [15:0] leaf_index = '0;
    logic [255:0] leaf_value = '0;

    wire parent_req_valid;
    logic parent_req_ready = 1'b0;
    wire [7:0] parent_req_height;
    wire [15:0] parent_req_start_leaf;
    wire [255:0] parent_req_left;
    wire [255:0] parent_req_right;
    wire [15:0] parent_req_layout_id;
    logic parent_rsp_valid = 1'b0;
    logic [255:0] parent_rsp_value = '0;
    logic parent_rsp_error = 1'b0;

    wire auth_valid;
    wire [7:0] auth_level;
    wire [255:0] auth_node;
    wire root_valid;
    wire [255:0] root;
    wire busy;
    wire done;
    wire error;
    wire [15:0] error_code;
    wire [15:0] accepted_leaves;
    wire [15:0] parent_hashes;
    wire [7:0] peak_stack_nodes;
    wire [31:0] accepted_starts;
    wire [31:0] rejected_starts;
    wire [31:0] descriptor_host_writes_busy;
    wire [31:0] descriptor_lookup_requests;

    logic [255:0] leaves [0:7];
    logic [255:0] oracle_work [0:7];
    logic [255:0] oracle_next [0:7];
    logic [255:0] expected_auth [0:MAX_TREE_HEIGHT-1];
    logic [255:0] expected_root;
    logic [255:0] captured_auth [0:MAX_TREE_HEIGHT-1];
    logic [MAX_TREE_HEIGHT-1:0] captured_mask = '0;
    logic [255:0] captured_root = '0;
    integer auth_events = 0;
    integer root_events = 0;

    logic parent_pending = 1'b0;
    logic [2:0] parent_delay = '0;
    logic [255:0] pending_parent_value = '0;
    integer parent_stall_count = 0;
    logic [15:0] expected_parent_layout = '0;
    integer i;
    integer j;
    integer level;
    integer nodes_at_level;
    integer target_at_level;
    integer timeout;

    logic [127:0] descriptor_h2_min;
    logic [127:0] descriptor_h3_min;
    logic [127:0] descriptor_h3_subtree;
    logic [127:0] descriptor_h3_full;
    logic [127:0] descriptor_h2_n24;

    always #5 clk = ~clk;

    function automatic [255:0] hash_parent;
        input [255:0] left;
        input [255:0] right;
        input [7:0] height;
        input [15:0] start_leaf_value;
        begin
            hash_parent = left ^ right
                ^ {216'b0, height, start_leaf_value, 16'h7bc2};
        end
    endfunction

    function automatic [127:0] descriptor;
        input [7:0] height_value;
        input [15:0] node_bytes_value;
        input [15:0] layout_value;
        input [7:0] mode_value;
        input [7:0] subtree_value;
        input [7:0] window_value;
        begin
            descriptor = {8'h01, height_value, node_bytes_value,
                layout_value, mode_value, subtree_value, window_value,
                56'b0};
        end
    endfunction

    micro_hbs_tree_descriptor_dynamic_slice #(
        .MAX_TREE_HEIGHT(MAX_TREE_HEIGHT),
        .DESCRIPTOR_COUNT(DESCRIPTOR_COUNT)
    ) dut (.*);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            parent_req_ready <= 1'b0;
            parent_rsp_valid <= 1'b0;
            parent_rsp_value <= '0;
            parent_rsp_error <= 1'b0;
            parent_pending <= 1'b0;
            parent_delay <= '0;
            pending_parent_value <= '0;
            parent_stall_count <= 0;
        end else begin
            parent_rsp_valid <= 1'b0;
            parent_rsp_error <= 1'b0;
            if (!parent_pending && parent_req_valid
                && !parent_req_ready) begin
                if (parent_stall_count == 1) begin
                    parent_req_ready <= 1'b1;
                    parent_stall_count <= 0;
                end else begin
                    parent_stall_count <= parent_stall_count + 1;
                end
            end
            if (parent_req_valid && parent_req_ready) begin
                if (parent_req_layout_id != expected_parent_layout)
                    $fatal(1, "parent layout got=%h expected=%h",
                           parent_req_layout_id, expected_parent_layout);
                parent_req_ready <= 1'b0;
                parent_pending <= 1'b1;
                parent_delay <= 2;
                pending_parent_value <= hash_parent(parent_req_left,
                    parent_req_right, parent_req_height,
                    parent_req_start_leaf);
            end
            if (parent_pending) begin
                if (parent_delay == 0) begin
                    parent_pending <= 1'b0;
                    parent_rsp_valid <= 1'b1;
                    parent_rsp_value <= pending_parent_value;
                end else begin
                    parent_delay <= parent_delay - 1'b1;
                end
            end
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            captured_mask <= '0;
            captured_root <= '0;
            auth_events <= 0;
            root_events <= 0;
            for (i = 0; i < MAX_TREE_HEIGHT; i = i + 1)
                captured_auth[i] <= '0;
        end else begin
            if (auth_valid) begin
                captured_mask[auth_level] <= 1'b1;
                captured_auth[auth_level] <= auth_node;
                auth_events <= auth_events + 1;
            end
            if (root_valid) begin
                captured_root <= root;
                root_events <= root_events + 1;
            end
        end
    end

    task automatic configure;
        input [15:0] id_value;
        input [127:0] descriptor_value;
        input expected_error;
        input [15:0] expected_code;
        begin
            @(negedge clk);
            cfg_descriptor_id = id_value;
            cfg_descriptor = descriptor_value;
            cfg_valid = 1'b1;
            @(posedge clk);
            #1 cfg_valid = 1'b0;
            if (cfg_error !== expected_error
                || (expected_error && cfg_error_code != expected_code))
                $fatal(1, "cfg id=%0d error=%0d code=%h ready=%0d",
                       id_value, cfg_error, cfg_error_code, cfg_ready);
        end
    endtask

    task automatic clear_capture;
        begin
            @(negedge clk);
            captured_mask = '0;
            captured_root = '0;
            auth_events = 0;
            root_events = 0;
            for (i = 0; i < MAX_TREE_HEIGHT; i = i + 1)
                captured_auth[i] = '0;
        end
    endtask

    task automatic make_oracle;
        input integer height_value;
        input integer target_value;
        begin
            nodes_at_level = 1 << height_value;
            target_at_level = target_value;
            for (i = 0; i < nodes_at_level; i = i + 1)
                oracle_work[i] = leaves[i];
            for (level = 0; level < height_value; level = level + 1) begin
                expected_auth[level]
                    = oracle_work[target_at_level ^ 1];
                for (j = 0; j < nodes_at_level/2; j = j + 1)
                    oracle_next[j] = hash_parent(oracle_work[2*j],
                        oracle_work[2*j+1], level+1,
                        j << (level+1));
                nodes_at_level = nodes_at_level / 2;
                target_at_level = target_at_level >> 1;
                for (j = 0; j < nodes_at_level; j = j + 1)
                    oracle_work[j] = oracle_next[j];
            end
            expected_root = oracle_work[0];
        end
    endtask

    task automatic start_job;
        input [15:0] descriptor_id_value;
        input [15:0] target_value;
        begin
            while (!start_ready) @(negedge clk);
            @(negedge clk);
            start_descriptor_id = descriptor_id_value;
            start_target_leaf = target_value;
            start_valid = 1'b1;
            @(posedge clk);
            #1 start_valid = 1'b0;
        end
    endtask

    task automatic send_leaf;
        input [15:0] index_value;
        begin
            while (!leaf_ready) @(negedge clk);
            leaf_index = index_value;
            leaf_value = leaves[index_value];
            leaf_valid = 1'b1;
            @(posedge clk);
            #1 leaf_valid = 1'b0;
        end
    endtask

    task automatic run_job;
        input [15:0] descriptor_id_value;
        input integer height_value;
        input integer target_value;
        input [15:0] layout_value;
        input busy_overwrite;
        integer leaf_count;
        integer expected_mask_value;
        begin
            make_oracle(height_value, target_value);
            clear_capture();
            expected_parent_layout = layout_value;
            start_job(descriptor_id_value, target_value[15:0]);
            if (!busy)
                $fatal(1, "coarse start did not lock slice");
            if (busy_overwrite)
                configure(descriptor_id_value, descriptor_h2_min,
                          1'b1, 16'h0901);
            leaf_count = 1 << height_value;
            for (i = 0; i < leaf_count; i = i + 1)
                send_leaf(i[15:0]);
            timeout = 0;
            while (!done && !error && timeout < 1000) begin
                @(posedge clk);
                #1 timeout = timeout + 1;
            end
            if (!done || error)
                $fatal(1, "job id=%0d failed code=%h", descriptor_id_value,
                       error_code);
            expected_mask_value = (1 << height_value) - 1;
            if (captured_root !== expected_root || root_events != 1
                || captured_mask !== expected_mask_value[MAX_TREE_HEIGHT-1:0]
                || auth_events != height_value)
                $fatal(1, "job id=%0d output mask=%b auth=%0d roots=%0d",
                       descriptor_id_value, captured_mask, auth_events,
                       root_events);
            for (level = 0; level < height_value; level = level + 1)
                if (captured_auth[level] !== expected_auth[level])
                    $fatal(1, "job id=%0d auth level=%0d mismatch",
                           descriptor_id_value, level);
            if (accepted_leaves != leaf_count
                || parent_hashes != leaf_count-1
                || peak_stack_nodes != height_value)
                $fatal(1, "job id=%0d metrics leaves=%0d parents=%0d peak=%0d",
                       descriptor_id_value, accepted_leaves,
                       parent_hashes, peak_stack_nodes);
        end
    endtask

    task automatic expect_start_error;
        input [15:0] descriptor_id_value;
        input [15:0] expected_code;
        begin
            clear_capture();
            start_job(descriptor_id_value, 0);
            timeout = 0;
            while (busy && timeout < 50) begin
                @(posedge clk);
                #1 timeout = timeout + 1;
            end
            if (busy || !error || error_code != expected_code
                || root_valid || auth_valid || root != 0 || auth_node != 0
                || root_events != 0 || auth_events != 0)
                $fatal(1, "rejected start id=%0d error=%0d code=%h",
                       descriptor_id_value, error, error_code);
        end
    endtask

    initial begin
        for (i = 0; i < 8; i = i + 1)
            leaves[i] = {8{32'h4050_6000 + i}};
        descriptor_h2_min = descriptor(2, 32, 16'h0022, 0, 0, 0);
        descriptor_h3_min = descriptor(3, 32, 16'h0033, 0, 0, 0);
        descriptor_h3_subtree = descriptor(3, 32, 16'h0044, 1, 2, 0);
        descriptor_h3_full = descriptor(3, 32, 16'h0055, 2, 0, 0);
        descriptor_h2_n24 = descriptor(2, 24, 16'h0066, 0, 0, 0);

        repeat (3) @(posedge clk);
        rst_n = 1'b1;
        configure(0, descriptor_h2_min, 1'b0, 0);
        configure(1, descriptor_h3_min, 1'b0, 0);
        configure(2, descriptor_h3_subtree, 1'b0, 0);
        configure(3, descriptor_h3_full, 1'b0, 0);
        configure(5, descriptor_h2_n24, 1'b0, 0);

        run_job(0, 2, 2, 16'h0022, 1'b0);
        run_job(1, 3, 5, 16'h0033, 1'b1);
        if (descriptor_host_writes_busy != 1)
            $fatal(1, "BUSY overwrite was not counted");

        expect_start_error(4, 16'h090b);
        expect_start_error(7, 16'h090a);
        expect_start_error(2, 16'h0a01);
        expect_start_error(3, 16'h0a01);
        expect_start_error(5, 16'h0a02);

        // A descriptor rejection does not poison the next coarse transaction.
        run_job(0, 2, 1, 16'h0022, 1'b0);
        if (accepted_starts != 8 || rejected_starts != 5
            || descriptor_lookup_requests != 8)
            $fatal(1, "accounting starts=%0d rejected=%0d lookups=%0d",
                   accepted_starts, rejected_starts,
                   descriptor_lookup_requests);

        $display("PASS descriptor-dynamic TreeHash slice: coarse h2/h3 MIN exact, layout forwarding, BUSY lock, uninitialized/bounds/SUBTREE/FULL/node-width fail-closed and recovery");
        $finish;
    end
endmodule

`default_nettype wire
