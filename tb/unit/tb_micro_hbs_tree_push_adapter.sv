`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_tree_push_adapter;
    localparam integer TREE_HEIGHT = 2;
    localparam integer NODE_BYTES = 32;
    localparam integer SCRATCH_WORDS = 32;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic cancel = 1'b0;
    logic cmd_valid = 1'b0;
    wire cmd_ready;
    logic [15:0] cmd_descriptor_id = '0;
    logic [15:0] cmd_layout_id = '0;
    logic [7:0] cmd_node_source = '0;
    logic [15:0] cmd_node_base_word = '0;
    logic [15:0] cmd_node_index = '0;
    logic [15:0] cmd_leaf_index = '0;
    logic cmd_tree_start = 1'b0;
    logic [15:0] cmd_target_leaf = '0;
    wire rsp_valid;
    wire rsp_error;
    wire [15:0] rsp_error_code;
    wire [15:0] rsp_descriptor_id;
    wire [15:0] rsp_layout_id;

    wire sp_req_valid;
    logic sp_req_ready = 1'b0;
    wire sp_req_write;
    wire [15:0] sp_req_address;
    wire [63:0] sp_req_write_data;
    logic sp_rsp_valid = 1'b0;
    logic [63:0] sp_rsp_read_data = '0;
    logic sp_rsp_error = 1'b0;
    logic [15:0] sp_rsp_error_code = '0;

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
    wire poisoned;
    wire [15:0] accepted_leaves;
    wire [15:0] parent_hashes;
    wire [7:0] peak_stack_nodes;

    logic [63:0] scratch [0:SCRATCH_WORDS-1];
    logic [255:0] leaf [0:3];
    logic scratch_pending = 1'b0;
    logic [3:0] scratch_delay = '0;
    logic [63:0] scratch_pending_data = '0;
    logic scratch_pending_error = 1'b0;
    logic [15:0] scratch_pending_error_code = '0;
    logic inject_next_sp_error = 1'b0;
    logic scratch_enable = 1'b0;
    integer configured_scratch_delay = 1;

    logic parent_pending = 1'b0;
    logic [3:0] parent_delay = '0;
    logic [255:0] parent_pending_value = '0;
    logic parent_pending_error = 1'b0;
    logic inject_next_parent_error = 1'b0;
    integer configured_parent_delay = 2;
    integer parent_stall_count = 0;
    integer scratch_handshakes = 0;
    integer scratch_stall_cycles = 0;
    integer parent_handshakes = 0;
    integer parent_stall_cycles = 0;
    integer auth_count = 0;
    integer root_count = 0;
    integer i;
    logic [255:0] expected_root;
    logic [255:0] recovery_leaf [0:3];
    logic [255:0] expected_recovery_root;
    logic [255:0] captured_auth [0:TREE_HEIGHT-1];

    always #5 clk = ~clk;

    function automatic [255:0] hash_parent;
        input [255:0] left;
        input [255:0] right;
        input [7:0] height;
        input [15:0] start_leaf;
        begin
            hash_parent = left ^ right ^ {232'b0, height, start_leaf};
        end
    endfunction

    micro_hbs_tree_push_adapter #(
        .TREE_HEIGHT(TREE_HEIGHT),
        .NODE_BYTES(NODE_BYTES),
        .SCRATCH_WORDS(SCRATCH_WORDS)
    ) dut (.*);

    // One-cycle delayed scratch responses.  scratch_enable is deliberately
    // held low at first to prove that a request is stable under backpressure.
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sp_req_ready <= 1'b0;
            sp_rsp_valid <= 1'b0;
            sp_rsp_error <= 1'b0;
            sp_rsp_error_code <= '0;
            scratch_pending <= 1'b0;
            scratch_delay <= '0;
            scratch_handshakes <= 0;
            scratch_stall_cycles <= 0;
            inject_next_sp_error <= 1'b0;
            configured_scratch_delay <= 1;
        end else begin
            sp_rsp_valid <= 1'b0;
            sp_rsp_error <= 1'b0;
            sp_rsp_error_code <= '0;
            sp_req_ready <= scratch_enable && !scratch_pending;

            if (sp_req_valid && !sp_req_ready)
                scratch_stall_cycles <= scratch_stall_cycles + 1;

            if (sp_req_valid && sp_req_ready) begin
                if (sp_req_write || sp_req_write_data != 0)
                    $fatal(1, "TREE_PUSH attempted a scratch write");
                scratch_handshakes <= scratch_handshakes + 1;
                scratch_pending <= 1'b1;
                scratch_delay <= configured_scratch_delay;
                if (sp_req_address >= SCRATCH_WORDS)
                    $fatal(1, "adapter emitted out-of-range scratch address %0d",
                           sp_req_address);
                scratch_pending_data <= scratch[sp_req_address[4:0]];
                scratch_pending_error <= inject_next_sp_error;
                scratch_pending_error_code <= 16'h55aa;
                inject_next_sp_error <= 1'b0;
                sp_req_ready <= 1'b0;
            end

            if (scratch_pending) begin
                if (scratch_delay == 0) begin
                    scratch_pending <= 1'b0;
                    if (scratch_pending_error) begin
                        sp_rsp_error <= 1'b1;
                        sp_rsp_error_code <= scratch_pending_error_code;
                    end else begin
                        sp_rsp_valid <= 1'b1;
                        sp_rsp_read_data <= scratch_pending_data;
                    end
                end else begin
                    scratch_delay <= scratch_delay - 1'b1;
                end
            end
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            auth_count <= 0;
            root_count <= 0;
        end else begin
            if (auth_valid) begin
                auth_count <= auth_count + 1;
                captured_auth[auth_level] <= auth_node;
                if (auth_level >= TREE_HEIGHT || auth_node === 256'bx)
                    $fatal(1, "invalid authentication output");
            end
            if (root_valid)
                root_count <= root_count + 1;
        end
    end

    // Parent requests see two or more cycles of backpressure, then receive a
    // deterministic two-cycle-latency response.
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            parent_req_ready <= 1'b0;
            parent_rsp_valid <= 1'b0;
            parent_rsp_error <= 1'b0;
            parent_pending <= 1'b0;
            parent_delay <= '0;
            parent_stall_count <= 0;
            parent_handshakes <= 0;
            parent_stall_cycles <= 0;
            inject_next_parent_error <= 1'b0;
            configured_parent_delay <= 2;
        end else begin
            parent_rsp_valid <= 1'b0;
            parent_rsp_error <= 1'b0;

            if (parent_req_valid && !parent_req_ready) begin
                parent_stall_cycles <= parent_stall_cycles + 1;
                if (parent_stall_count == 2) begin
                    parent_req_ready <= 1'b1;
                end else begin
                    parent_stall_count <= parent_stall_count + 1;
                end
            end

            if (parent_req_valid && parent_req_ready) begin
                parent_handshakes <= parent_handshakes + 1;
                parent_req_ready <= 1'b0;
                parent_stall_count <= 0;
                parent_pending <= 1'b1;
                parent_delay <= configured_parent_delay;
                parent_pending_value <= hash_parent(parent_req_left,
                    parent_req_right, parent_req_height,
                    parent_req_start_leaf);
                parent_pending_error <= inject_next_parent_error;
                inject_next_parent_error <= 1'b0;
            end

            if (parent_pending) begin
                if (parent_delay == 0) begin
                    parent_pending <= 1'b0;
                    if (parent_pending_error)
                        parent_rsp_error <= 1'b1;
                    else begin
                        parent_rsp_valid <= 1'b1;
                        parent_rsp_value <= parent_pending_value;
                    end
                end else begin
                    parent_delay <= parent_delay - 1'b1;
                end
            end
        end
    end

    task automatic reset_dut;
        begin
            @(negedge clk);
            rst_n = 1'b0;
            scratch_enable = 1'b0;
            cancel = 1'b0;
            repeat (3) @(posedge clk);
            @(negedge clk);
            rst_n = 1'b1;
        end
    endtask

    task automatic send_command;
        input start_tree;
        input [7:0] source;
        input [15:0] base_word;
        input [15:0] node_index;
        input [15:0] leaf_index_value;
        input [15:0] target_leaf_value;
        input [15:0] descriptor_value;
        input [15:0] layout_value;
        begin
            while (!cmd_ready) @(negedge clk);
            cmd_tree_start = start_tree;
            cmd_node_source = source;
            cmd_node_base_word = base_word;
            cmd_node_index = node_index;
            cmd_leaf_index = leaf_index_value;
            cmd_target_leaf = target_leaf_value;
            cmd_descriptor_id = descriptor_value;
            cmd_layout_id = layout_value;
            cmd_valid = 1'b1;
            @(negedge clk);
            cmd_valid = 1'b0;
        end
    endtask

    task automatic expect_response;
        input expected_error;
        input [15:0] expected_code;
        input [15:0] expected_descriptor;
        input [15:0] expected_layout;
        begin
            i = 0;
            while (!rsp_valid && i < 1000) begin
                @(negedge clk);
                i = i + 1;
            end
            if (!rsp_valid)
                $fatal(1, "response timeout busy=%b tree_busy=%b scratch_pending=%b",
                       busy, dut.tree_busy, scratch_pending);
            if (rsp_error !== expected_error
                || (expected_error && rsp_error_code !== expected_code)
                || rsp_descriptor_id !== expected_descriptor
                || rsp_layout_id !== expected_layout)
                $fatal(1, "response mismatch err=%b code=%04x desc=%04x layout=%04x",
                       rsp_error, rsp_error_code, rsp_descriptor_id,
                       rsp_layout_id);
        end
    endtask

    task automatic pulse_cancel;
        begin
            @(negedge clk);
            cancel = 1'b1;
            @(negedge clk);
            cancel = 1'b0;
        end
    endtask

    task automatic run_recovery_tree;
        input [15:0] descriptor_base;
        begin
            send_command(1'b1, 8'h00, 16'd16, 16'd0, 16'd0,
                         16'd2, descriptor_base, 16'hcafe);
            expect_response(1'b0, 16'h0000, descriptor_base, 16'hcafe);
            send_command(1'b0, 8'h00, 16'd16, 16'd1, 16'd1,
                         16'd0, descriptor_base+1, 16'hcafe);
            expect_response(1'b0, 16'h0000, descriptor_base+1, 16'hcafe);
            send_command(1'b0, 8'h00, 16'd16, 16'd2, 16'd2,
                         16'd0, descriptor_base+2, 16'hcafe);
            expect_response(1'b0, 16'h0000, descriptor_base+2, 16'hcafe);
            send_command(1'b0, 8'h00, 16'd16, 16'd3, 16'd3,
                         16'd0, descriptor_base+3, 16'hcafe);
            expect_response(1'b0, 16'h0000, descriptor_base+3, 16'hcafe);
            if (root !== expected_recovery_root || accepted_leaves != 4
                || captured_auth[0] !== recovery_leaf[3]
                || captured_auth[1] !== hash_parent(recovery_leaf[0],
                    recovery_leaf[1], 8'd1, 16'd0))
                $fatal(1, "post-abort recovery root/auth mismatch root=%064x",
                       root);
        end
    endtask

    initial begin
        for (i = 0; i < 4; i = i + 1) begin
            leaf[i] = {8{32'h10203040 + i}};
            scratch[4*i+0] = leaf[i][63:0];
            scratch[4*i+1] = leaf[i][127:64];
            scratch[4*i+2] = leaf[i][191:128];
            scratch[4*i+3] = leaf[i][255:192];
            recovery_leaf[i] = {8{32'ha0b0c000 + i}};
            scratch[16+4*i+0] = recovery_leaf[i][63:0];
            scratch[16+4*i+1] = recovery_leaf[i][127:64];
            scratch[16+4*i+2] = recovery_leaf[i][191:128];
            scratch[16+4*i+3] = recovery_leaf[i][255:192];
        end

        expected_root = hash_parent(
            hash_parent(leaf[0], leaf[1], 8'd1, 16'd0),
            hash_parent(leaf[2], leaf[3], 8'd1, 16'd2),
            8'd2, 16'd0);
        expected_recovery_root = hash_parent(
            hash_parent(recovery_leaf[0], recovery_leaf[1], 8'd1, 16'd0),
            hash_parent(recovery_leaf[2], recovery_leaf[3], 8'd1, 16'd2),
            8'd2, 16'd0);

        reset_dut();
        // Hold the first scratch request for at least three clocks.
        fork
            begin
                repeat (4) @(posedge clk);
                scratch_enable = 1'b1;
            end
            begin
                send_command(1'b1, 8'h00, 16'd0, 16'd0, 16'd0,
                             16'd1, 16'h1234, 16'habcd);
                expect_response(1'b0, 16'h0000, 16'h1234, 16'habcd);
            end
        join

        send_command(1'b0, 8'h00, 16'd0, 16'd1, 16'd1,
                     16'd0, 16'h1235, 16'habcd);
        expect_response(1'b0, 16'h0000, 16'h1235, 16'habcd);
        send_command(1'b0, 8'h00, 16'd0, 16'd2, 16'd2,
                     16'd0, 16'h1236, 16'habcd);
        expect_response(1'b0, 16'h0000, 16'h1236, 16'habcd);
        send_command(1'b0, 8'h00, 16'd0, 16'd3, 16'd3,
                     16'd0, 16'h1237, 16'habcd);
        expect_response(1'b0, 16'h0000, 16'h1237, 16'habcd);

        if (root !== expected_root || accepted_leaves != 4
            || parent_hashes != 3 || scratch_handshakes != 16
            || parent_handshakes != 3 || root_count != 1
            || auth_count != TREE_HEIGHT || peak_stack_nodes == 0)
            $fatal(1, "full tree mismatch root=%064x leaves=%0d parents=%0d reads=%0d reqs=%0d",
                   root, accepted_leaves, parent_hashes,
                   scratch_handshakes, parent_handshakes);
        if (scratch_stall_cycles < 2 || parent_stall_cycles < 6)
            $fatal(1, "backpressure was not exercised scratch=%0d parent=%0d",
                   scratch_stall_cycles, parent_stall_cycles);

        // Entire node range is checked before starting TreeHash or reading RAM.
        reset_dut();
        scratch_enable = 1'b1;
        send_command(1'b1, 8'h00, 16'd30, 16'd0, 16'd0,
                     16'd0, 16'h2000, 16'h3000);
        expect_response(1'b1, 16'h0402, 16'h2000, 16'h3000);
        if (scratch_handshakes != 0 || accepted_leaves != 0 || poisoned)
            $fatal(1, "bounds failure caused a side effect");

        send_command(1'b1, 8'h7f, 16'd0, 16'd0, 16'd0,
                     16'd0, 16'h2004, 16'h3004);
        expect_response(1'b1, 16'h0401, 16'h2004, 16'h3004);
        if (scratch_handshakes != 0 || accepted_leaves != 0 || busy)
            $fatal(1, "unsupported node source caused a side effect");

        // A scratch response fault after one accepted leaf must abort and clean
        // the partial tree.  The next complete tree runs without global reset.
        reset_dut();
        scratch_enable = 1'b1;
        send_command(1'b1, 8'h00, 16'd0, 16'd0, 16'd0,
                     16'd0, 16'h2001, 16'h3001);
        expect_response(1'b0, 16'h0000, 16'h2001, 16'h3001);
        inject_next_sp_error = 1'b1;
        send_command(1'b0, 8'h00, 16'd0, 16'd1, 16'd1,
                     16'd0, 16'h2002, 16'h3001);
        expect_response(1'b1, 16'h55aa, 16'h2002, 16'h3001);
        if (poisoned || !cmd_ready || accepted_leaves != 1
            || scratch_handshakes != 5 || !dut.tree_ready)
            $fatal(1, "scratch response error did not abort cleanly");
        run_recovery_tree(16'h2100);
        if (scratch_handshakes != 21 || parent_handshakes != 3
            || root_count != 1 || auth_count != TREE_HEIGHT)
            $fatal(1, "scratch-fault recovery counters mismatch");

        // Parent response errors clean the stack and return TreeHash's error
        // code.  Again, immediately run a distinct tree without reset.
        reset_dut();
        scratch_enable = 1'b1;
        send_command(1'b1, 8'h00, 16'd0, 16'd0, 16'd0,
                     16'd0, 16'h2200, 16'h3002);
        expect_response(1'b0, 16'h0000, 16'h2200, 16'h3002);
        inject_next_parent_error = 1'b1;
        send_command(1'b0, 8'h00, 16'd0, 16'd1, 16'd1,
                     16'd0, 16'h2201, 16'h3002);
        expect_response(1'b1, 16'h0204, 16'h2201, 16'h3002);
        if (poisoned || !cmd_ready || accepted_leaves != 2
            || parent_handshakes != 1 || !dut.tree_ready)
            $fatal(1, "parent response error handling mismatch");
        run_recovery_tree(16'h2300);
        if (scratch_handshakes != 24 || parent_handshakes != 4
            || root_count != 1 || auth_count != TREE_HEIGHT+1)
            $fatal(1, "parent-fault recovery counters mismatch");

        // Cancellation may race an already accepted scratch read.  Do not
        // expose ready until its deliberately delayed old response is drained.
        reset_dut();
        scratch_enable = 1'b1;
        configured_scratch_delay = 8;
        send_command(1'b1, 8'h00, 16'd0, 16'd0, 16'd0,
                     16'd0, 16'h2380, 16'h3003);
        while (!scratch_pending) @(negedge clk);
        pulse_cancel();
        if (cmd_ready || !busy)
            $fatal(1, "cancel exposed ready before old scratch response drain");
        expect_response(1'b1, 16'h0406, 16'h2380, 16'h3003);
        if (scratch_pending || poisoned || !cmd_ready || !dut.tree_ready)
            $fatal(1, "cancel did not drain old scratch transaction");
        configured_scratch_delay = 1;
        run_recovery_tree(16'h2390);
        if (scratch_handshakes != 17 || parent_handshakes != 3
            || root_count != 1 || auth_count != TREE_HEIGHT)
            $fatal(1, "scratch-cancel recovery counters mismatch");

        // Cancel while an accepted parent hash is still outstanding. TreeHash
        // must drain that old response before cmd_ready can rise; otherwise it
        // could be mistaken for a response belonging to the recovery tree.
        reset_dut();
        scratch_enable = 1'b1;
        send_command(1'b1, 8'h00, 16'd0, 16'd0, 16'd0,
                     16'd0, 16'h2400, 16'h3003);
        expect_response(1'b0, 16'h0000, 16'h2400, 16'h3003);
        configured_parent_delay = 8;
        send_command(1'b0, 8'h00, 16'd0, 16'd1, 16'd1,
                     16'd0, 16'h2401, 16'h3003);
        while (!parent_pending) @(negedge clk);
        pulse_cancel();
        if (cmd_ready || !busy)
            $fatal(1, "cancel exposed ready before old parent response drain");
        expect_response(1'b1, 16'h0406, 16'h2401, 16'h3003);
        if (parent_pending || poisoned || !cmd_ready || !dut.tree_ready)
            $fatal(1, "cancel did not drain/clean old parent transaction");
        configured_parent_delay = 2;
        run_recovery_tree(16'h2500);
        if (scratch_handshakes != 24 || parent_handshakes != 4
            || root_count != 1 || auth_count != TREE_HEIGHT+1)
            $fatal(1, "explicit-abort recovery counters mismatch");

        $display("PASS TREE_PUSH abort recovery: scratch/parent fault cleanup, explicit cancel drain, old-response isolation, next-job root/auth exact, backpressure live");
        $finish;
    end
endmodule

`default_nettype wire
