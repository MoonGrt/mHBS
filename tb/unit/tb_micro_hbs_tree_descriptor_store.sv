`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_tree_descriptor_store;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic engine_busy = 1'b0;

    logic cfg_valid = 1'b0;
    wire cfg_ready;
    logic [15:0] cfg_descriptor_id = '0;
    logic [127:0] cfg_descriptor = '0;
    wire cfg_error;
    wire [15:0] cfg_error_code;

    logic lookup_valid = 1'b0;
    wire lookup_ready;
    logic [15:0] lookup_descriptor_id = '0;
    wire lookup_rsp_valid;
    logic lookup_rsp_ready = 1'b0;
    wire lookup_rsp_error;
    wire [15:0] lookup_rsp_error_code;
    wire [127:0] lookup_descriptor;

    wire [7:0] descriptor_format_version;
    wire [7:0] descriptor_tree_height;
    wire [15:0] descriptor_node_bytes;
    wire [15:0] descriptor_parent_layout_id;
    wire [7:0] descriptor_storage_mode;
    wire [7:0] descriptor_subtree_height;
    wire [7:0] descriptor_window_height;
    wire [55:0] descriptor_reserved;
    wire image_locked;
    wire [31:0] descriptor_capacity;
    wire [31:0] configured_count;
    wire [31:0] accepted_loads;
    wire [31:0] rejected_loads;
    wire [31:0] host_writes_busy;
    wire [31:0] lookup_requests;
    wire [31:0] lookup_errors;

    logic [127:0] descriptor_min;
    logic [127:0] descriptor_subtree;
    logic [127:0] descriptor_full;
    logic [127:0] descriptor_overwrite;
    integer stalled_cycles = 0;

    always #5 clk = ~clk;

    micro_hbs_tree_descriptor_store #(.DESCRIPTOR_COUNT(4)) dut (.*);

    function automatic [127:0] descriptor;
        input [7:0] version_value;
        input [7:0] tree_height_value;
        input [15:0] node_bytes_value;
        input [15:0] parent_layout_id_value;
        input [7:0] storage_mode_value;
        input [7:0] subtree_height_value;
        input [7:0] window_height_value;
        input [55:0] reserved_value;
        begin
            descriptor = {
                version_value, tree_height_value, node_bytes_value,
                parent_layout_id_value, storage_mode_value,
                subtree_height_value, window_height_value, reserved_value
            };
        end
    endfunction

    task automatic configure;
        input [15:0] descriptor_id_value;
        input [127:0] descriptor_value;
        input expected_error;
        input [15:0] expected_error_code;
        begin
            @(negedge clk);
            cfg_descriptor_id = descriptor_id_value;
            cfg_descriptor = descriptor_value;
            cfg_valid = 1'b1;
            @(posedge clk);
            #1 cfg_valid = 1'b0;
            if (cfg_error !== expected_error
                || (expected_error
                    && cfg_error_code !== expected_error_code))
                $fatal(1, "configure id=%0d ready=%0d error=%0d code=%h",
                       descriptor_id_value, cfg_ready, cfg_error,
                       cfg_error_code);
        end
    endtask

    task automatic lookup;
        input [15:0] descriptor_id_value;
        input expected_error;
        input [15:0] expected_error_code;
        input [127:0] expected_descriptor;
        begin
            @(negedge clk);
            while (!lookup_ready) @(negedge clk);
            lookup_descriptor_id = descriptor_id_value;
            lookup_valid = 1'b1;
            @(posedge clk);
            #1 lookup_valid = 1'b0;
            if (!lookup_rsp_valid || lookup_rsp_error !== expected_error
                || (expected_error
                    && lookup_rsp_error_code !== expected_error_code))
                $fatal(1, "lookup id=%0d rsp=%0d error=%0d code=%h",
                       descriptor_id_value, lookup_rsp_valid,
                       lookup_rsp_error, lookup_rsp_error_code);
            if (lookup_descriptor !== expected_descriptor)
                $fatal(1, "lookup data id=%0d got=%032x expected=%032x",
                       descriptor_id_value, lookup_descriptor,
                       expected_descriptor);
            if (descriptor_format_version !== expected_descriptor[127:120]
                || descriptor_tree_height !== expected_descriptor[119:112]
                || descriptor_node_bytes !== expected_descriptor[111:96]
                || descriptor_parent_layout_id
                    !== expected_descriptor[95:80]
                || descriptor_storage_mode !== expected_descriptor[79:72]
                || descriptor_subtree_height
                    !== expected_descriptor[71:64]
                || descriptor_window_height !== expected_descriptor[63:56]
                || descriptor_reserved !== expected_descriptor[55:0])
                $fatal(1, "decoded fields mismatch id=%0d",
                       descriptor_id_value);
            lookup_rsp_ready = 1'b1;
            @(posedge clk);
            #1 lookup_rsp_ready = 1'b0;
            if (lookup_rsp_valid)
                $fatal(1, "lookup response did not retire");
        end
    endtask

    initial begin
        descriptor_min = descriptor(1, 8'd10, 16'd32, 16'h0011,
                                    8'd0, 8'd0, 8'd0, 56'b0);
        // SUBTREE with a four-level active window is a legal generic policy.
        descriptor_subtree = descriptor(1, 8'd10, 16'd24, 16'h0022,
                                        8'd1, 8'd4, 8'd4, 56'b0);
        descriptor_full = descriptor(1, 8'd5, 16'd16, 16'h0033,
                                     8'd2, 8'd0, 8'd0, 56'b0);
        descriptor_overwrite = descriptor(1, 8'd8, 16'd8, 16'h0044,
                                          8'd1, 8'd3, 8'd0, 56'b0);

        repeat (3) @(negedge clk);
        rst_n = 1'b1;
        #1;
        if (descriptor_capacity != 4 || image_locked || !cfg_ready
            || !lookup_ready)
            $fatal(1, "reset/parameter status mismatch");

        // All three generic storage policies are accepted and immutable while
        // the engine is BUSY.
        configure(0, descriptor_min, 1'b0, 16'b0);
        configure(1, descriptor_subtree, 1'b0, 16'b0);
        configure(2, descriptor_full, 1'b0, 16'b0);
        if (configured_count != 3 || accepted_loads != 3)
            $fatal(1, "legal mode load accounting mismatch");
        lookup(0, 1'b0, 16'b0, descriptor_min);
        lookup(1, 1'b0, 16'b0, descriptor_subtree);
        lookup(2, 1'b0, 16'b0, descriptor_full);

        // Hold one successful response while presenting another request.  The
        // first tuple must remain stable and the second must not be accepted.
        @(negedge clk);
        lookup_descriptor_id = 1;
        lookup_valid = 1'b1;
        @(posedge clk);
        #1 lookup_valid = 1'b0;
        if (!lookup_rsp_valid || lookup_rsp_error
            || lookup_descriptor !== descriptor_subtree)
            $fatal(1, "backpressure setup response mismatch");
        lookup_descriptor_id = 0;
        lookup_valid = 1'b1;
        repeat (3) begin
            @(posedge clk);
            #1;
            stalled_cycles = stalled_cycles + 1;
            if (lookup_ready || !lookup_rsp_valid || lookup_rsp_error
                || lookup_descriptor !== descriptor_subtree)
                $fatal(1, "response changed under backpressure");
        end
        lookup_valid = 1'b0;
        if (lookup_requests != 4)
            $fatal(1, "blocked request was accepted or counted");
        lookup_rsp_ready = 1'b1;
        @(posedge clk);
        #1 lookup_rsp_ready = 1'b0;

        // BUSY rejects an overwrite; runtime lookup remains legal and returns
        // the original static descriptor.
        engine_busy = 1'b1;
        #1;
        if (!image_locked || cfg_ready || !lookup_ready)
            $fatal(1, "BUSY lock status mismatch");
        configure(1, descriptor_overwrite, 1'b1, 16'h0901);
        lookup(1, 1'b0, 16'b0, descriptor_subtree);
        engine_busy = 1'b0;

        // Descriptor-ID bounds and initialization validity are independent of
        // stale physical RAM contents and always return an all-zero tuple.
        lookup(3, 1'b1, 16'h090b, 128'b0);
        lookup(4, 1'b1, 16'h090a, 128'b0);
        configure(4, descriptor_min, 1'b1, 16'h0902);

        // Version, dimensions, mode, cross-field combinations, and reserved
        // bits each fail closed without initializing descriptor 3.
        configure(3, descriptor(2, 10, 32, 0, 0, 0, 0, 0),
                  1'b1, 16'h0904);
        configure(3, descriptor(1, 0, 32, 0, 0, 0, 0, 0),
                  1'b1, 16'h0905);
        configure(3, descriptor(1, 10, 20, 0, 0, 0, 0, 0),
                  1'b1, 16'h0906);
        configure(3, descriptor(1, 10, 32, 0, 3, 0, 0, 0),
                  1'b1, 16'h0907);
        configure(3, descriptor(1, 10, 32, 0, 0, 4, 0, 0),
                  1'b1, 16'h0908);
        configure(3, descriptor(1, 10, 32, 0, 1, 4, 5, 0),
                  1'b1, 16'h0908);
        configure(3, descriptor(1, 10, 32, 0, 2, 0, 1, 0),
                  1'b1, 16'h0908);
        configure(3, descriptor(1, 10, 32, 0, 1, 4, 0, 1),
                  1'b1, 16'h0909);
        lookup(3, 1'b1, 16'h090b, 128'b0);

        // Simultaneous IDLE lookup/config gives lookup priority; the losing
        // host write is an explicit conflict and cannot initialize ID 3.
        @(negedge clk);
        cfg_descriptor_id = 3;
        cfg_descriptor = descriptor_overwrite;
        cfg_valid = 1'b1;
        lookup_descriptor_id = 0;
        lookup_valid = 1'b1;
        @(posedge clk);
        #1 cfg_valid = 1'b0;
        lookup_valid = 1'b0;
        if (!cfg_error || cfg_error_code != 16'h0903
            || !lookup_rsp_valid || lookup_rsp_error
            || lookup_descriptor !== descriptor_min)
            $fatal(1, "IDLE lookup/config arbitration mismatch");
        lookup_rsp_ready = 1'b1;
        @(posedge clk);
        #1 lookup_rsp_ready = 1'b0;
        lookup(3, 1'b1, 16'h090b, 128'b0);

        if (configured_count != 3 || accepted_loads != 3
            || rejected_loads != 11 || host_writes_busy != 1
            || lookup_requests != 10 || lookup_errors != 4
            || stalled_cycles != 3)
            $fatal(1, "counter mismatch cfg=%0d accepted=%0d rejected=%0d busy=%0d lookup=%0d errors=%0d stalls=%0d",
                   configured_count, accepted_loads, rejected_loads,
                   host_writes_busy, lookup_requests, lookup_errors,
                   stalled_cycles);

        // Reset invalidates visibility without clearing the inferred RAM.
        rst_n = 1'b0;
        repeat (2) @(negedge clk);
        rst_n = 1'b1;
        lookup(0, 1'b1, 16'h090b, 128'b0);

        $display("PASS tree descriptor store: versioned MIN/SUBTREE/FULL, IDLE load, BUSY lock, validation, backpressure, fail-closed lookup");
        $finish;
    end
endmodule

`default_nettype wire
