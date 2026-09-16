`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_layout_descriptor_store;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic engine_busy = 1'b0;
    logic cfg_valid = 1'b0;
    wire cfg_ready;
    logic [15:0] cfg_layout_id = '0;
    logic [127:0] cfg_descriptor = '0;
    wire cfg_error;
    wire [15:0] cfg_error_code;
    logic lookup_valid = 1'b0;
    wire lookup_ready;
    logic [15:0] lookup_layout_id = '0;
    wire lookup_rsp_valid, lookup_rsp_error;
    wire [15:0] lookup_rsp_error_code;
    wire [127:0] lookup_descriptor;
    wire image_locked;
    wire [31:0] layout_capacity, configured_count, accepted_loads;
    wire [31:0] rejected_loads, host_writes_busy;
    wire [31:0] lookup_requests, lookup_errors;

    logic [127:0] descriptor_a;
    logic [127:0] descriptor_b;
    logic [127:0] descriptor_c;
    logic [127:0] descriptor_c_new;

    always #5 clk = ~clk;

    micro_hbs_layout_descriptor_store #(.LAYOUT_COUNT(4)) dut (.*);

    function automatic [127:0] descriptor;
        input [7:0] version_value;
        input [7:0] capability_value;
        input [7:0] input_mode_value;
        input [7:0] output_mode_value;
        input [15:0] flags_value;
        input [15:0] message_bytes_value;
        input [15:0] expression_pc_value;
        input [7:0] expression_tokens_value;
        input [7:0] source_count_value;
        input [15:0] scratch_base_value;
        input [15:0] scratch_span_value;
        begin
            descriptor = {
                version_value, capability_value, input_mode_value,
                output_mode_value, flags_value, message_bytes_value,
                expression_pc_value, expression_tokens_value,
                source_count_value, scratch_base_value, scratch_span_value
            };
        end
    endfunction

    task automatic configure;
        input [15:0] layout_id_value;
        input [127:0] descriptor_value;
        input expected_error;
        input [15:0] expected_error_code;
        begin
            @(negedge clk);
            cfg_layout_id = layout_id_value;
            cfg_descriptor = descriptor_value;
            cfg_valid = 1'b1;
            @(posedge clk);
            #1 cfg_valid = 1'b0;
            if (cfg_error !== expected_error
                || (expected_error && cfg_error_code !== expected_error_code))
                $fatal(1, "configure status id=%0d ready=%0d error=%0d code=%h",
                       layout_id_value, cfg_ready, cfg_error, cfg_error_code);
        end
    endtask

    task automatic lookup;
        input [15:0] layout_id_value;
        input expected_error;
        input [15:0] expected_error_code;
        input [127:0] expected_descriptor;
        begin
            @(negedge clk);
            lookup_layout_id = layout_id_value;
            lookup_valid = 1'b1;
            @(posedge clk);
            #1 lookup_valid = 1'b0;
            if (!lookup_rsp_valid || lookup_rsp_error !== expected_error
                || (expected_error
                    && lookup_rsp_error_code !== expected_error_code))
                $fatal(1, "lookup status id=%0d rsp=%0d error=%0d code=%h",
                       layout_id_value, lookup_rsp_valid, lookup_rsp_error,
                       lookup_rsp_error_code);
            if (lookup_descriptor !== expected_descriptor)
                $fatal(1, "lookup data id=%0d got=%032x expected=%032x",
                       layout_id_value, lookup_descriptor, expected_descriptor);
        end
    endtask

    initial begin
        descriptor_a = descriptor(1, 8'h11, 8'h01, 8'h02, 16'h0003,
                                  16'd64, 16'd0, 8'd7, 8'd3, 16'd16, 16'd12);
        descriptor_b = descriptor(1, 8'h22, 8'h03, 8'h01, 16'h0010,
                                  16'd136, 16'd12, 8'd5, 8'd4, 16'd40, 16'd20);
        descriptor_c = descriptor(1, 8'h31, 8'h02, 8'h03, 16'h0100,
                                  16'd96, 16'd20, 8'd9, 8'd2, 16'd80, 16'd16);
        descriptor_c_new = descriptor(1, 8'h32, 8'h04, 8'h02, 16'h0200,
                                      16'd32, 16'd29, 8'd3, 8'd1, 16'd96, 16'd4);

        repeat (3) @(negedge clk);
        rst_n = 1'b1;
        #1;
        if (layout_capacity != 4 || image_locked || !cfg_ready || !lookup_ready)
            $fatal(1, "reset/parameter status mismatch");

        configure(0, descriptor_a, 1'b0, 16'b0);
        configure(3, descriptor_b, 1'b0, 16'b0);
        if (configured_count != 2 || accepted_loads != 2 || rejected_loads != 0)
            $fatal(1, "initial load accounting mismatch");
        lookup(0, 1'b0, 16'b0, descriptor_a);
        lookup(3, 1'b0, 16'b0, descriptor_b);

        // A legal but uninitialized layout and an out-of-range ID both return
        // zero, never the most recently read descriptor.
        lookup(2, 1'b1, 16'h020c, 128'b0);
        lookup(4, 1'b1, 16'h020b, 128'b0);

        configure(4, descriptor_c, 1'b1, 16'h0209);
        configure(2, {8'h02, descriptor_c[119:0]}, 1'b1, 16'h020d);
        if (configured_count != 2 || accepted_loads != 2 || rejected_loads != 2)
            $fatal(1, "invalid configuration changed image/accounting");

        // Busy-time load is rejected and cannot initialize ID 1.
        engine_busy = 1'b1;
        #1;
        if (!image_locked || cfg_ready)
            $fatal(1, "BUSY did not lock descriptor image");
        configure(1, descriptor_c, 1'b1, 16'h0102);
        engine_busy = 1'b0;
        lookup(1, 1'b1, 16'h020c, 128'b0);
        if (host_writes_busy != 1 || rejected_loads != 3)
            $fatal(1, "busy rejection accounting mismatch");

        configure(1, descriptor_c, 1'b0, 16'b0);
        if (configured_count != 3 || accepted_loads != 3)
            $fatal(1, "ID 1 initialization accounting mismatch");

        // During BUSY, a HASH_LAYOUT lookup still works while a simultaneous
        // host overwrite attempt is rejected.  The old immutable word wins.
        @(negedge clk);
        engine_busy = 1'b1;
        cfg_layout_id = 1;
        cfg_descriptor = descriptor_c_new;
        cfg_valid = 1'b1;
        lookup_layout_id = 1;
        lookup_valid = 1'b1;
        @(posedge clk);
        #1 cfg_valid = 1'b0;
        lookup_valid = 1'b0;
        if (!cfg_error || cfg_error_code != 16'h0102
            || !lookup_rsp_valid || lookup_rsp_error
            || lookup_descriptor !== descriptor_c)
            $fatal(1, "BUSY lock/read concurrency mismatch");
        engine_busy = 1'b0;
        lookup(1, 1'b0, 16'b0, descriptor_c);

        // An idle overwrite is legal but does not increase configured_count.
        configure(1, descriptor_c_new, 1'b0, 16'b0);
        lookup(1, 1'b0, 16'b0, descriptor_c_new);

        // Idle lookup has priority over configuration to avoid same-address
        // RAM ambiguity; the losing configuration is an explicit error.
        @(negedge clk);
        cfg_layout_id = 2;
        cfg_descriptor = descriptor_c;
        cfg_valid = 1'b1;
        lookup_layout_id = 0;
        lookup_valid = 1'b1;
        @(posedge clk);
        #1 cfg_valid = 1'b0;
        lookup_valid = 1'b0;
        if (!cfg_error || cfg_error_code != 16'h020a
            || !lookup_rsp_valid || lookup_rsp_error
            || lookup_descriptor !== descriptor_a)
            $fatal(1, "idle config/lookup conflict was not deterministic");
        lookup(2, 1'b1, 16'h020c, 128'b0);

        if (configured_count != 3 || accepted_loads != 4
            || rejected_loads != 5 || host_writes_busy != 2
            || lookup_requests != 10 || lookup_errors != 4)
            $fatal(1, "final counters cfg=%0d accepted=%0d rejected=%0d busy=%0d lookups=%0d errors=%0d",
                   configured_count, accepted_loads, rejected_loads,
                   host_writes_busy, lookup_requests, lookup_errors);

        // Reset clears only validity metadata; stale physical RAM remains masked.
        rst_n = 1'b0;
        repeat (2) @(negedge clk);
        rst_n = 1'b1;
        lookup(0, 1'b1, 16'h020c, 128'b0);

        $display("PASS layout descriptor store 128-bit idle-load BUSY-lock bounds/uninitialized/version fail-closed no-runtime");
        $finish;
    end
endmodule

`default_nettype wire
