`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_treehash_min_dynamic;
    localparam integer MAX_TREE_HEIGHT = 3;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic start = 1'b0;
    wire ready;
    logic [7:0] tree_height = '0;
    logic [15:0] target_leaf = '0;
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
    logic parent_rsp_valid = 1'b0;
    logic [255:0] parent_rsp_value = '0;
    logic parent_rsp_error = 1'b0;

    wire auth_valid;
    wire [7:0] auth_level;
    wire [255:0] auth_node;
    wire root_valid;
    wire [255:0] root;
    wire busy;
    wire error;
    wire [15:0] error_code;
    wire [15:0] accepted_leaves;
    wire [15:0] parent_hashes;
    wire [7:0] peak_stack_nodes;

    logic [255:0] leaves [0:7];
    logic [255:0] oracle_work [0:7];
    logic [255:0] oracle_next [0:7];
    logic [255:0] expected_auth [0:MAX_TREE_HEIGHT-1];
    logic [255:0] expected_root;
    logic [255:0] captured_auth [0:MAX_TREE_HEIGHT-1];
    logic [MAX_TREE_HEIGHT-1:0] captured_mask = '0;
    logic [255:0] captured_root = '0;

    logic parent_pending = 1'b0;
    logic [3:0] parent_delay = '0;
    logic [255:0] pending_parent_value = '0;
    logic pending_parent_error = 1'b0;
    logic inject_parent_error = 1'b0;
    integer configured_parent_delay = 2;
    integer parent_stall_count = 0;
    integer parent_handshakes = 0;
    integer auth_events = 0;
    integer root_events = 0;
    integer i;
    integer j;
    integer level;
    integer nodes_at_level;
    integer target_at_level;
    integer timeout;

    always #5 clk = ~clk;

    function automatic [255:0] hash_parent;
        input [255:0] left;
        input [255:0] right;
        input [7:0] height;
        input [15:0] start_leaf_value;
        begin
            hash_parent = left ^ right
                ^ {216'b0, height, start_leaf_value, 16'h5a3c};
        end
    endfunction

    micro_hbs_treehash_min_dynamic #(
        .MAX_TREE_HEIGHT(MAX_TREE_HEIGHT)
    ) dut (.*);

    // Independent deterministic parent service with request backpressure and
    // a configurable delayed response/error.
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            parent_req_ready <= 1'b0;
            parent_rsp_valid <= 1'b0;
            parent_rsp_value <= '0;
            parent_rsp_error <= 1'b0;
            parent_pending <= 1'b0;
            parent_delay <= '0;
            pending_parent_value <= '0;
            pending_parent_error <= 1'b0;
            inject_parent_error <= 1'b0;
            configured_parent_delay <= 2;
            parent_stall_count <= 0;
            parent_handshakes <= 0;
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
                parent_req_ready <= 1'b0;
                parent_pending <= 1'b1;
                parent_delay <= configured_parent_delay;
                pending_parent_value <= hash_parent(parent_req_left,
                    parent_req_right, parent_req_height,
                    parent_req_start_leaf);
                pending_parent_error <= inject_parent_error;
                inject_parent_error <= 1'b0;
                parent_handshakes <= parent_handshakes + 1;
            end

            if (parent_pending) begin
                if (parent_delay == 0) begin
                    parent_pending <= 1'b0;
                    if (pending_parent_error)
                        parent_rsp_error <= 1'b1;
                    else begin
                        parent_rsp_valid <= 1'b1;
                        parent_rsp_value <= pending_parent_value;
                    end
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
                if (auth_level >= MAX_TREE_HEIGHT)
                    $fatal(1, "auth level out of elaborated range %0d",
                           auth_level);
                captured_auth[auth_level] <= auth_node;
                captured_mask[auth_level] <= 1'b1;
                auth_events <= auth_events + 1;
            end
            if (root_valid) begin
                captured_root <= root;
                root_events <= root_events + 1;
            end
        end
    end

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

    task automatic pulse_start;
        input [7:0] height_value;
        input [15:0] target_value;
        begin
            while (!ready) @(negedge clk);
            @(negedge clk);
            tree_height = height_value;
            target_leaf = target_value;
            start = 1'b1;
            @(posedge clk);
            #1 start = 1'b0;
        end
    endtask

    task automatic pulse_cancel;
        begin
            @(negedge clk);
            start = 1'b1;
            @(posedge clk);
            #1 start = 1'b0;
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

    task automatic wait_ready;
        begin
            timeout = 0;
            while (!ready && timeout < 1000) begin
                @(posedge clk);
                #1 timeout = timeout + 1;
            end
            if (!ready)
                $fatal(1, "ready timeout state=%0d", dut.state);
        end
    endtask

    task automatic run_tree;
        input integer height_value;
        input integer target_value;
        integer leaf_count;
        integer expected_mask_value;
        begin
            make_oracle(height_value, target_value);
            clear_capture();
            pulse_start(height_value[7:0], target_value[15:0]);
            leaf_count = 1 << height_value;
            for (i = 0; i < leaf_count; i = i + 1)
                send_leaf(i[15:0]);

            timeout = 0;
            while (!root_valid && !error && timeout < 1000) begin
                @(posedge clk);
                #1 timeout = timeout + 1;
            end
            if (error || !root_valid || root !== expected_root)
                $fatal(1, "h%0d root error=%0d code=%h got=%064x expected=%064x",
                       height_value, error, error_code, root,
                       expected_root);
            wait_ready();
            // auth_valid is registered.  The final level makes ready rise on
            // the same edge, so allow the monitor one edge to sample it.
            @(posedge clk);
            #1;
            expected_mask_value = (1 << height_value) - 1;
            if (captured_root !== expected_root || root_events != 1
                || captured_mask !== expected_mask_value[MAX_TREE_HEIGHT-1:0]
                || auth_events != height_value)
                $fatal(1, "h%0d committed output mismatch mask=%b auth=%0d roots=%0d",
                       height_value, captured_mask, auth_events,
                       root_events);
            for (level = 0; level < height_value; level = level + 1)
                if (captured_auth[level] !== expected_auth[level])
                    $fatal(1, "h%0d auth level %0d got=%064x expected=%064x",
                           height_value, level, captured_auth[level],
                           expected_auth[level]);
            if (accepted_leaves != leaf_count
                || parent_hashes != leaf_count-1
                || peak_stack_nodes != height_value)
                $fatal(1, "h%0d metrics leaves=%0d parents=%0d peak=%0d",
                       height_value, accepted_leaves, parent_hashes,
                       peak_stack_nodes);
        end
    endtask

    task automatic expect_start_error;
        input [7:0] height_value;
        input [15:0] target_value;
        input [15:0] expected_code;
        begin
            clear_capture();
            pulse_start(height_value, target_value);
            if (!ready || !error || error_code != expected_code
                || root_valid || auth_valid || root != 0 || auth_node != 0
                || accepted_leaves != 0 || parent_hashes != 0
                || peak_stack_nodes != 0)
                $fatal(1, "invalid start h=%0d target=%0d status ready=%0d error=%0d code=%h",
                       height_value, target_value, ready, error,
                       error_code);
        end
    endtask

    initial begin
        for (i = 0; i < 8; i = i + 1)
            leaves[i] = {8{32'h1020_3000 + i}};

        repeat (3) @(posedge clk);
        rst_n = 1'b1;

        // Consecutive heights share one elaborated MAX=3 instance.
        run_tree(2, 2);
        run_tree(3, 5);

        expect_start_error(0, 0, 16'h0205);
        expect_start_error(4, 0, 16'h0205);
        expect_start_error(2, 4, 16'h0201);

        // A leaf-order fault clears all partial outputs and the following job
        // succeeds without reset.
        clear_capture();
        pulse_start(2, 1);
        send_leaf(0);
        send_leaf(2);
        #1;
        if (!ready || !error || error_code != 16'h0202
            || root_valid || auth_valid || root != 0 || auth_node != 0)
            $fatal(1, "leaf-order fail-closed mismatch");
        run_tree(2, 1);

        // A parent error after an accepted request cannot release the buffered
        // partial auth path; a complete h=3 job then proves clean recovery.
        clear_capture();
        pulse_start(2, 1);
        @(negedge clk);
        inject_parent_error = 1'b1;
        send_leaf(0);
        send_leaf(1);
        timeout = 0;
        while (!error && timeout < 100) begin
            @(posedge clk);
            #1 timeout = timeout + 1;
        end
        if (!ready || error_code != 16'h0204 || captured_mask != 0
            || root_events != 0 || auth_events != 0 || root != 0
            || auth_node != 0)
            $fatal(1, "parent error was not fail-closed");
        run_tree(3, 6);

        // Cancel with an accepted, delayed parent operation.  ready must stay
        // low until the untagged old response is drained, after which a new
        // start completes with an exact independent oracle.
        clear_capture();
        configured_parent_delay = 8;
        pulse_start(2, 0);
        send_leaf(0);
        send_leaf(1);
        while (!parent_pending) @(negedge clk);
        pulse_cancel();
        if (ready || !busy || root_valid || auth_valid || root != 0
            || auth_node != 0)
            $fatal(1, "cancel exposed ready/output before old response drain");
        wait_ready();
        if (parent_pending || error || captured_mask != 0
            || root_events != 0 || auth_events != 0)
            $fatal(1, "cancel drain/cleanup mismatch");
        configured_parent_delay = 2;
        run_tree(3, 3);

        if (parent_handshakes < 1)
            $fatal(1, "parent service was not exercised");
        $display("PASS dynamic TREEHASH_MIN: one MAX=3 engine h2/h3 root/auth exact, runtime peak, invalid height/target/order, parent error, cancel drain and restart fail-closed");
        $finish;
    end
endmodule

`default_nettype wire
