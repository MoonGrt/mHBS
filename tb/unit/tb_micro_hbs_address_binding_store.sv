`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_address_binding_store;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic engine_busy = 1'b0;
    logic cfg_valid = 1'b0;
    wire cfg_ready;
    logic [15:0] cfg_binding_id = '0;
    logic [7:0] cfg_format_version = 8'h01;
    logic [63:0] cfg_binding = '0;
    wire cfg_error;
    wire [15:0] cfg_error_code;
    logic lookup_valid = 1'b0;
    wire lookup_ready;
    logic [15:0] lookup_binding_id = '0;
    wire lookup_rsp_valid;
    logic lookup_rsp_ready = 1'b0;
    wire lookup_rsp_error;
    wire [15:0] lookup_rsp_error_code;
    wire [63:0] lookup_binding;
    wire [1:0] binding_operand;
    wire binding_use_base_reg;
    wire [2:0] binding_base_reg;
    wire binding_use_index_reg;
    wire [2:0] binding_index_reg;
    wire [15:0] binding_base_scale_words;
    wire [15:0] binding_index_stride_words;
    wire image_locked;
    wire [31:0] binding_capacity, configured_count, accepted_loads;
    wire [31:0] rejected_loads, host_writes_busy;
    wire [31:0] lookup_requests, lookup_errors;

    localparam logic [63:0] XMSS_SOURCE = 64'h37c0010001000000;
    localparam logic [63:0] XMSS_DEST   = 64'hbac0010001000000;
    integer stalled_cycles = 0;

    always #5 clk = ~clk;

    micro_hbs_address_binding_store #(.BINDING_COUNT(4)) dut (.*);

    task automatic configure;
        input [15:0] binding_id_value;
        input [7:0] version_value;
        input [63:0] binding_value;
        input expected_error;
        input [15:0] expected_error_code;
        begin
            @(negedge clk);
            cfg_binding_id = binding_id_value;
            cfg_format_version = version_value;
            cfg_binding = binding_value;
            cfg_valid = 1'b1;
            @(posedge clk);
            #1 cfg_valid = 1'b0;
            if (cfg_error !== expected_error
                || (expected_error && cfg_error_code !== expected_error_code))
                $fatal(1, "configure mismatch id=%0d ready=%0d error=%0d code=%h expected=%h",
                       binding_id_value, cfg_ready, cfg_error,
                       cfg_error_code, expected_error_code);
        end
    endtask

    task automatic lookup;
        input [15:0] binding_id_value;
        input expected_error;
        input [15:0] expected_error_code;
        input [63:0] expected_binding;
        begin
            @(negedge clk);
            while (!lookup_ready) @(negedge clk);
            lookup_binding_id = binding_id_value;
            lookup_valid = 1'b1;
            @(posedge clk);
            #1 lookup_valid = 1'b0;
            if (!lookup_rsp_valid || lookup_rsp_error !== expected_error
                || (expected_error
                    && lookup_rsp_error_code !== expected_error_code)
                || lookup_binding !== expected_binding)
                $fatal(1, "lookup mismatch id=%0d valid=%0d error=%0d code=%h data=%h",
                       binding_id_value, lookup_rsp_valid, lookup_rsp_error,
                       lookup_rsp_error_code, lookup_binding);
            if (binding_operand !== expected_binding[63:62]
                || binding_use_base_reg !== expected_binding[61]
                || binding_base_reg !== expected_binding[60:58]
                || binding_use_index_reg !== expected_binding[57]
                || binding_index_reg !== expected_binding[56:54]
                || binding_base_scale_words !== expected_binding[53:38]
                || binding_index_stride_words !== expected_binding[37:22])
                $fatal(1, "decoded binding mismatch id=%0d", binding_id_value);
            lookup_rsp_ready = 1'b1;
            @(posedge clk);
            #1 lookup_rsp_ready = 1'b0;
            if (lookup_rsp_valid)
                $fatal(1, "lookup response did not retire");
        end
    endtask

    initial begin
        repeat (3) @(negedge clk);
        rst_n = 1'b1;
        #1;
        if (binding_capacity != 4 || image_locked || !cfg_ready
            || !lookup_ready)
            $fatal(1, "reset/capacity status mismatch");

        // Exact words emitted by the Python XMSS keygen move-0 lowering.
        configure(0, 1, XMSS_SOURCE, 1'b0, 16'b0);
        configure(1, 1, XMSS_DEST, 1'b0, 16'b0);
        if (configured_count != 2 || accepted_loads != 2
            || rejected_loads != 0)
            $fatal(1, "initial load counters mismatch");

        lookup(0, 1'b0, 16'b0, XMSS_SOURCE);

        // Hold destination response and try to inject another lookup.  The
        // complete payload and decoded tuple must remain stable.
        @(negedge clk);
        lookup_binding_id = 1;
        lookup_valid = 1'b1;
        @(posedge clk);
        #1 lookup_valid = 1'b0;
        if (!lookup_rsp_valid || lookup_rsp_error
            || lookup_binding !== XMSS_DEST)
            $fatal(1, "XMSS destination response missing");
        lookup_binding_id = 0;
        lookup_valid = 1'b1;
        repeat (4) begin
            @(posedge clk);
            #1 stalled_cycles = stalled_cycles + 1;
            if (lookup_ready || !lookup_rsp_valid || lookup_rsp_error
                || lookup_binding !== XMSS_DEST
                || binding_operand != 2 || !binding_use_base_reg
                || binding_base_reg != 6 || !binding_use_index_reg
                || binding_index_reg != 3
                || binding_base_scale_words != 4
                || binding_index_stride_words != 4)
                $fatal(1, "binding response changed under backpressure");
        end
        lookup_valid = 1'b0;
        if (lookup_requests != 2)
            $fatal(1, "stalled lookup was accepted or counted");
        lookup_rsp_ready = 1'b1;
        @(posedge clk);
        #1 lookup_rsp_ready = 1'b0;

        // Every configuration validation category is fail-closed and cannot
        // initialize ID 2 or mutate the two valid XMSS entries.
        configure(4, 1, XMSS_SOURCE, 1'b1, 16'h0802);
        configure(2, 2, XMSS_SOURCE, 1'b1, 16'h0804);
        configure(2, 1, XMSS_SOURCE | 64'hc000000000000000,
                  1'b1, 16'h0805);
        configure(2, 1, XMSS_SOURCE | 64'h1, 1'b1, 16'h0806);
        // Disable base use while retaining R5: a disabled register field must
        // use the canonical R0 encoding.
        configure(2, 1, XMSS_SOURCE & ~(64'h1 << 61),
                  1'b1, 16'h0807);
        // Retain use_base_reg/R5 but clear its required nonzero scale.
        configure(2, 1, XMSS_SOURCE & ~(64'hffff << 38),
                  1'b1, 16'h0808);
        if (configured_count != 2 || accepted_loads != 2
            || rejected_loads != 6)
            $fatal(1, "invalid config affected image/counters");

        engine_busy = 1'b1;
        #1;
        if (!image_locked || cfg_ready || !lookup_ready)
            $fatal(1, "BUSY lock status mismatch");
        configure(2, 1, XMSS_SOURCE, 1'b1, 16'h0801);

        // Runtime lookup remains legal while BUSY and wins over the rejected
        // host overwrite attempt; the stored word cannot be perturbed.
        @(negedge clk);
        cfg_binding_id = 0;
        cfg_format_version = 1;
        cfg_binding = XMSS_DEST;
        cfg_valid = 1'b1;
        lookup_binding_id = 0;
        lookup_valid = 1'b1;
        @(posedge clk);
        #1 cfg_valid = 1'b0;
        lookup_valid = 1'b0;
        if (!cfg_error || cfg_error_code != 16'h0801
            || !lookup_rsp_valid || lookup_rsp_error
            || lookup_binding !== XMSS_SOURCE)
            $fatal(1, "BUSY write/lookup behavior mismatch");
        lookup_rsp_ready = 1'b1;
        @(posedge clk);
        #1 lookup_rsp_ready = 1'b0;
        engine_busy = 1'b0;

        // Legal overwrite does not increase configured_count.
        configure(0, 1, XMSS_SOURCE, 1'b0, 16'b0);

        // IDLE lookup priority converts a simultaneous configuration request
        // into a deterministic conflict error.
        @(negedge clk);
        cfg_binding_id = 2;
        cfg_binding = XMSS_SOURCE;
        cfg_valid = 1'b1;
        lookup_binding_id = 1;
        lookup_valid = 1'b1;
        @(posedge clk);
        #1 cfg_valid = 1'b0;
        lookup_valid = 1'b0;
        if (!cfg_error || cfg_error_code != 16'h0803
            || !lookup_rsp_valid || lookup_rsp_error
            || lookup_binding !== XMSS_DEST)
            $fatal(1, "IDLE config/lookup conflict mismatch");
        lookup_rsp_ready = 1'b1;
        @(posedge clk);
        #1 lookup_rsp_ready = 1'b0;

        lookup(2, 1'b1, 16'h080a, 64'b0);
        lookup(4, 1'b1, 16'h0809, 64'b0);
        if (configured_count != 2 || accepted_loads != 3
            || rejected_loads != 9 || host_writes_busy != 2
            || lookup_requests != 6 || lookup_errors != 2
            || stalled_cycles != 4)
            $fatal(1, "final counters cfg=%0d accept=%0d reject=%0d busy=%0d lookup=%0d errors=%0d stalls=%0d",
                   configured_count, accepted_loads, rejected_loads,
                   host_writes_busy, lookup_requests, lookup_errors,
                   stalled_cycles);

        // Reset clears only validity metadata; stale physical RAM is masked.
        rst_n = 1'b0;
        repeat (2) @(negedge clk);
        rst_n = 1'b1;
        lookup(0, 1'b1, 16'h080a, 64'b0);

        $display("PASS address binding store: exact XMSS words, decode, IDLE/BUSY lock, validation, backpressure, fail-closed lookup, counters");
        $finish;
    end
endmodule

`default_nettype wire
