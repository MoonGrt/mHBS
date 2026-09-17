`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_data_descriptor_store;
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
    wire [15:0] descriptor_flags;
    wire [15:0] descriptor_source_a, descriptor_source_b;
    wire [15:0] descriptor_destination, descriptor_word_count;
    wire [3:0] descriptor_last_bytes, descriptor_address_mode;
    wire [7:0] descriptor_format_version;
    wire [31:0] descriptor_reserved;
    wire image_locked;
    wire [31:0] descriptor_capacity, configured_count, accepted_loads;
    wire [31:0] rejected_loads, host_writes_busy;
    wire [31:0] lookup_requests, lookup_errors;

    logic [127:0] descriptor_a;
    logic [127:0] descriptor_b;
    logic [127:0] descriptor_c;
    logic [127:0] descriptor_c_new;
    integer stalled_cycles = 0;

    always #5 clk = ~clk;

    micro_hbs_data_descriptor_store #(.DESCRIPTOR_COUNT(4)) dut (.*);

    function automatic [127:0] descriptor;
        input [7:0] version_value;
        input [15:0] flags_value;
        input [15:0] source_a_value;
        input [15:0] source_b_value;
        input [15:0] destination_value;
        input [15:0] word_count_value;
        input [3:0] last_bytes_value;
        input [3:0] address_mode_value;
        input [31:0] reserved_value;
        begin
            descriptor = {
                version_value, flags_value, source_a_value, source_b_value,
                destination_value, word_count_value, last_bytes_value,
                address_mode_value, reserved_value
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
                || (expected_error && cfg_error_code !== expected_error_code))
                $fatal(1, "configure status id=%0d ready=%0d error=%0d code=%h",
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
                $fatal(1, "lookup status id=%0d rsp=%0d error=%0d code=%h",
                       descriptor_id_value, lookup_rsp_valid,
                       lookup_rsp_error, lookup_rsp_error_code);
            if (lookup_descriptor !== expected_descriptor)
                $fatal(1, "lookup data id=%0d got=%032x expected=%032x",
                       descriptor_id_value, lookup_descriptor,
                       expected_descriptor);
            if (descriptor_flags !== expected_descriptor[119:104]
                || descriptor_source_a !== expected_descriptor[103:88]
                || descriptor_source_b !== expected_descriptor[87:72]
                || descriptor_destination !== expected_descriptor[71:56]
                || descriptor_word_count !== expected_descriptor[55:40]
                || descriptor_last_bytes !== expected_descriptor[39:36]
                || descriptor_address_mode !== expected_descriptor[35:32]
                || descriptor_format_version !== expected_descriptor[127:120]
                || descriptor_reserved !== expected_descriptor[31:0])
                $fatal(1, "decoded descriptor fields mismatch id=%0d",
                       descriptor_id_value);
            lookup_rsp_ready = 1'b1;
            @(posedge clk);
            #1 lookup_rsp_ready = 1'b0;
            if (lookup_rsp_valid)
                $fatal(1, "lookup response did not retire");
        end
    endtask

    initial begin
        // The store preserves descriptor fields; bit 2 is reserved in v0.2.
        descriptor_a = descriptor(1, 16'b0000_0000_0000_1111,
                                  16'd4, 16'd12, 16'd20, 16'd8,
                                  4'd5, 4'd0, 32'b0);
        descriptor_b = descriptor(1, 16'b0000_0000_0000_1001,
                                  16'd32, 16'd0, 16'd48, 16'd17,
                                  4'd8, 4'd1, 32'h1234_5678);
        descriptor_c = descriptor(1, 16'b0000_0000_0000_0110,
                                  16'd64, 16'd72, 16'd80, 16'd4,
                                  4'd8, 4'd2, 32'b0);
        descriptor_c_new = descriptor(1, 16'h8008,
                                      16'd96, 16'd0, 16'd112, 16'd3,
                                      4'd2, 4'd3, 32'hcafe_f00d);

        repeat (3) @(negedge clk);
        rst_n = 1'b1;
        #1;
        if (descriptor_capacity != 4 || image_locked || !cfg_ready
            || !lookup_ready)
            $fatal(1, "reset/parameter status mismatch");

        configure(0, descriptor_a, 1'b0, 16'b0);
        configure(3, descriptor_b, 1'b0, 16'b0);
        if (configured_count != 2 || accepted_loads != 2
            || rejected_loads != 0)
            $fatal(1, "initial load accounting mismatch");

        lookup(0, 1'b0, 16'b0, descriptor_a);

        // Hold a valid response for four cycles, present a second lookup while
        // it is blocked, and prove the first response tuple never changes.
        @(negedge clk);
        lookup_descriptor_id = 3;
        lookup_valid = 1'b1;
        @(posedge clk);
        #1 lookup_valid = 1'b0;
        if (!lookup_rsp_valid || lookup_rsp_error
            || lookup_descriptor !== descriptor_b)
            $fatal(1, "backpressure lookup did not produce descriptor B");
        lookup_descriptor_id = 0;
        lookup_valid = 1'b1;
        repeat (4) begin
            @(posedge clk);
            #1;
            stalled_cycles = stalled_cycles + 1;
            if (lookup_ready || !lookup_rsp_valid || lookup_rsp_error
                || lookup_descriptor !== descriptor_b)
                $fatal(1, "response changed or request accepted under stall");
        end
        lookup_valid = 1'b0;
        if (lookup_requests != 2)
            $fatal(1, "stalled lookup was counted as accepted");
        lookup_rsp_ready = 1'b1;
        @(posedge clk);
        #1 lookup_rsp_ready = 1'b0;

        // Legal but uninitialized and out-of-range IDs fail closed to zero.
        lookup(2, 1'b1, 16'h0606, 128'b0);
        lookup(4, 1'b1, 16'h0605, 128'b0);
        configure(4, descriptor_c, 1'b1, 16'h0602);
        configure(2, {8'h02, descriptor_c[119:0]}, 1'b1, 16'h0604);

        // BUSY locks configuration but leaves runtime lookup available.
        engine_busy = 1'b1;
        #1;
        if (!image_locked || cfg_ready || !lookup_ready)
            $fatal(1, "BUSY lock status mismatch");
        configure(1, descriptor_c, 1'b1, 16'h0601);
        engine_busy = 1'b0;
        lookup(1, 1'b1, 16'h0606, 128'b0);
        configure(1, descriptor_c, 1'b0, 16'b0);

        // A BUSY host overwrite conflicts with a valid runtime lookup.  BUSY
        // rejection takes precedence and the immutable old descriptor wins.
        @(negedge clk);
        engine_busy = 1'b1;
        cfg_descriptor_id = 1;
        cfg_descriptor = descriptor_c_new;
        cfg_valid = 1'b1;
        lookup_descriptor_id = 1;
        lookup_valid = 1'b1;
        @(posedge clk);
        #1 cfg_valid = 1'b0;
        lookup_valid = 1'b0;
        if (!cfg_error || cfg_error_code != 16'h0601
            || !lookup_rsp_valid || lookup_rsp_error
            || lookup_descriptor !== descriptor_c)
            $fatal(1, "BUSY configuration/lookup conflict mismatch");
        lookup_rsp_ready = 1'b1;
        @(posedge clk);
        #1 lookup_rsp_ready = 1'b0;
        engine_busy = 1'b0;
        lookup(1, 1'b0, 16'b0, descriptor_c);

        // IDLE overwrite is legal and does not grow configured_count.
        configure(1, descriptor_c_new, 1'b0, 16'b0);
        lookup(1, 1'b0, 16'b0, descriptor_c_new);

        // If configuration and lookup arrive together, lookup wins and the
        // rejected write cannot initialize descriptor 2.
        @(negedge clk);
        cfg_descriptor_id = 2;
        cfg_descriptor = descriptor_c;
        cfg_valid = 1'b1;
        lookup_descriptor_id = 0;
        lookup_valid = 1'b1;
        @(posedge clk);
        #1 cfg_valid = 1'b0;
        lookup_valid = 1'b0;
        if (!cfg_error || cfg_error_code != 16'h0603
            || !lookup_rsp_valid || lookup_rsp_error
            || lookup_descriptor !== descriptor_a)
            $fatal(1, "IDLE configuration/lookup arbitration mismatch");
        lookup_rsp_ready = 1'b1;
        @(posedge clk);
        #1 lookup_rsp_ready = 1'b0;
        lookup(2, 1'b1, 16'h0606, 128'b0);

        if (configured_count != 3 || accepted_loads != 4
            || rejected_loads != 5 || host_writes_busy != 2
            || lookup_requests != 10 || lookup_errors != 4
            || stalled_cycles != 4)
            $fatal(1, "counter mismatch cfg=%0d accepted=%0d rejected=%0d busy=%0d lookup=%0d errors=%0d stalls=%0d",
                   configured_count, accepted_loads, rejected_loads,
                   host_writes_busy, lookup_requests, lookup_errors,
                   stalled_cycles);

        // Reset clears visibility metadata; stale physical RAM stays hidden.
        rst_n = 1'b0;
        repeat (2) @(negedge clk);
        rst_n = 1'b1;
        lookup(0, 1'b1, 16'h0606, 128'b0);

        $display("PASS data descriptor store: 128-bit fields, IDLE load, BUSY lock, response backpressure, conflict priority, fail-closed errors, counters");
        $finish;
    end
endmodule

`default_nettype wire
