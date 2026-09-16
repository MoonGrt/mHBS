`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_data_v2_faults;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic program_we = 1'b0;
    logic [8:0] program_addr = '0;
    logic [63:0] program_wdata = '0;
    logic descriptor_cfg_valid = 1'b0;
    wire descriptor_cfg_ready;
    logic [15:0] descriptor_cfg_id = '0;
    logic [127:0] descriptor_cfg_data = '0;
    wire descriptor_cfg_error;
    wire [15:0] descriptor_cfg_error_code;
    logic binding_cfg_valid = 1'b0;
    wire binding_cfg_ready;
    logic [15:0] binding_cfg_id = '0;
    logic [7:0] binding_cfg_format_version = 8'h01;
    logic [63:0] binding_cfg_data = '0;
    wire binding_cfg_error;
    wire [15:0] binding_cfg_error_code;
    logic scratch_init_valid = 1'b0;
    wire scratch_init_ready;
    logic [8:0] scratch_init_address = '0;
    logic [63:0] scratch_init_data = '0;
    logic job_valid = 1'b0;
    wire job_ready;
    logic [8:0] job_entry = '0;
    wire out_valid;
    logic out_ready = 1'b0;
    wire [63:0] out_data;
    wire [7:0] out_keep;
    wire out_last;
    wire busy, done, error;
    wire [15:0] error_code;
    wire [31:0] accepted_job_commands;
    wire [31:0] host_control_writes_during_busy;
    wire [31:0] issued_data_requests, retired_instructions;
    wire [31:0] descriptor_host_writes_busy, binding_host_writes_busy;
    wire [31:0] descriptor_lookup_requests, binding_lookup_requests;
    wire [31:0] scratch_transactions;
    wire [31:0] external_task_descriptors, external_hash_descriptors;

    localparam logic [7:0] OP_MOVI  = 8'h01;
    localparam logic [7:0] OP_STORE = 8'h09;
    localparam logic [7:0] OP_EMIT  = 8'h0c;
    localparam logic [7:0] OP_HALT  = 8'h0d;

    localparam logic [15:0] ERR_AGU_BOUNDS = 16'h0312;
    localparam logic [15:0] ERR_BINDING_UNINITIALIZED = 16'h080a;

    // Exact descriptor and binding words emitted by model/data_lowering.py.
    localparam logic [127:0] XMSS_STORE_DESC =
        128'h02000200000000000000048500002000;
    localparam logic [63:0] XMSS_SOURCE_BIND = 64'h37c0010001000000;
    localparam logic [63:0] XMSS_DEST_BIND   = 64'hbac0010001000000;
    localparam logic [127:0] STATIC_EMIT_DESC =
        128'h02000801900000000000048000000000;

    localparam integer PHASE_MISSING_BINDING = 0;
    localparam integer PHASE_ADDRESS_BOUNDS  = 1;
    localparam integer PHASE_RECOVERY        = 2;

    logic [63:0] expected [0:3];
    integer phase = PHASE_MISSING_BINDING;
    integer observed_out_valid = 0;
    integer captured_words = 0;
    integer observed_done = 0;
    integer timeout;
    integer index;

    always #5 clk = ~clk;

    micro_hbs_data_v2_slice dut (.*);

    function automatic [63:0] enc(
        input [7:0] opcode, input [7:0] flags,
        input [7:0] rd, input [7:0] rs, input [31:0] imm
    );
        enc = {opcode, flags, rd, rs, imm};
    endfunction

    always @(posedge clk) begin
        if (!rst_n) begin
            observed_out_valid <= 0;
            captured_words <= 0;
            observed_done <= 0;
        end else begin
            if (out_valid) begin
                observed_out_valid <= observed_out_valid + 1;
                if (phase != PHASE_RECOVERY)
                    $fatal(1, "faulting Job exposed out_valid in phase %0d",
                           phase);
            end
            if (out_valid && out_ready) begin
                if (captured_words >= 4
                    || out_data !== expected[captured_words])
                    $fatal(1, "recovery output %0d mismatch: %h",
                           captured_words, out_data);
                if (out_keep !== 8'hff
                    || out_last !== (captured_words == 3))
                    $fatal(1, "recovery framing %0d keep=%h last=%0d",
                           captured_words, out_keep, out_last);
                captured_words <= captured_words + 1;
            end
            if (done) begin
                observed_done <= observed_done + 1;
                if (phase != PHASE_RECOVERY)
                    $fatal(1, "faulting Job exposed done in phase %0d",
                           phase);
            end
        end
    end

    task automatic reset_dut;
        begin
            @(negedge clk);
            rst_n = 1'b0;
            program_we = 1'b0;
            descriptor_cfg_valid = 1'b0;
            binding_cfg_valid = 1'b0;
            scratch_init_valid = 1'b0;
            job_valid = 1'b0;
            out_ready = 1'b0;
            repeat (3) @(negedge clk);
            rst_n = 1'b1;
            @(negedge clk);
            if (busy || done || error || error_code != 0 || !job_ready)
                $fatal(1, "reset did not restore clean IDLE state");
            if (observed_out_valid != 0 || captured_words != 0
                || observed_done != 0)
                $fatal(1, "test observation counters did not reset");
        end
    endtask

    task automatic write_program(input [8:0] address,
                                 input [63:0] word);
        begin
            @(negedge clk);
            if (busy || error)
                $fatal(1, "program configuration attempted outside IDLE");
            program_addr = address;
            program_wdata = word;
            program_we = 1'b1;
            @(negedge clk);
            program_we = 1'b0;
        end
    endtask

    task automatic write_descriptor(input [15:0] id,
                                    input [127:0] value);
        begin
            @(negedge clk);
            if (!descriptor_cfg_ready)
                $fatal(1, "descriptor configuration not ready");
            descriptor_cfg_id = id;
            descriptor_cfg_data = value;
            descriptor_cfg_valid = 1'b1;
            @(negedge clk);
            descriptor_cfg_valid = 1'b0;
            if (descriptor_cfg_error)
                $fatal(1, "descriptor configuration error %h",
                       descriptor_cfg_error_code);
        end
    endtask

    task automatic write_binding(input [15:0] id,
                                 input [63:0] value);
        begin
            @(negedge clk);
            if (!binding_cfg_ready)
                $fatal(1, "binding configuration not ready");
            binding_cfg_id = id;
            binding_cfg_data = value;
            binding_cfg_valid = 1'b1;
            @(negedge clk);
            binding_cfg_valid = 1'b0;
            if (binding_cfg_error)
                $fatal(1, "binding configuration error %h",
                       binding_cfg_error_code);
        end
    endtask

    task automatic write_scratch(input [8:0] address,
                                 input [63:0] value);
        begin
            @(negedge clk);
            if (!scratch_init_ready)
                $fatal(1, "Scratchpad initialization not ready");
            scratch_init_address = address;
            scratch_init_data = value;
            scratch_init_valid = 1'b1;
            @(negedge clk);
            scratch_init_valid = 1'b0;
        end
    endtask

    task automatic start_job;
        begin
            @(negedge clk);
            if (!job_ready)
                $fatal(1, "Job interface not ready");
            job_entry = 0;
            job_valid = 1'b1;
            @(posedge clk);
            #1;
            if (!busy || job_ready)
                $fatal(1, "Job was not accepted atomically");
            @(negedge clk);
            job_valid = 1'b0;
        end
    endtask

    task automatic expect_fault(input [15:0] expected_code);
        begin
            timeout = 0;
            while (!error && timeout < 800) begin
                @(negedge clk);
                if (out_valid || done)
                    $fatal(1, "faulting Job produced output/completion token");
                timeout = timeout + 1;
            end
            if (!error)
                $fatal(1, "faulting Job timed out");
            if (error_code !== expected_code || busy || job_ready)
                $fatal(1, "fault contract mismatch error=%0d code=%h busy=%0d ready=%0d",
                       error, error_code, busy, job_ready);
            if (observed_out_valid != 0 || observed_done != 0)
                $fatal(1, "faulting Job leaked output/done observation");

            // Sequencer faults are sticky and reject another Job until reset.
            repeat (5) begin
                @(posedge clk);
                #1;
                if (!error || error_code !== expected_code || busy
                    || job_ready || out_valid || done)
                    $fatal(1, "fault code/state was not stable: %h",
                           error_code);
            end
        end
    endtask

    initial begin
        expected[0] = 64'h0123_4567_89ab_cdef;
        expected[1] = 64'h1111_2222_3333_4444;
        expected[2] = 64'hfedc_ba98_7654_3210;
        expected[3] = 64'h55aa_00ff_a55a_5aa5;

        // Fault 1: descriptor advertises source/destination bindings, but the
        // destination binding at ID 1 was never configured.
        phase = PHASE_MISSING_BINDING;
        reset_dut();
        write_program(0, enc(OP_STORE, 0, 0, 0, 0));
        write_program(1, enc(OP_HALT, 0, 0, 0, 0));
        write_descriptor(0, XMSS_STORE_DESC);
        write_binding(0, XMSS_SOURCE_BIND);
        start_job();
        expect_fault(ERR_BINDING_UNINITIALIZED);
        if (issued_data_requests != 1 || descriptor_lookup_requests != 1
            || binding_lookup_requests != 3 || scratch_transactions != 0)
            $fatal(1, "missing-binding accounting mismatch data=%0d desc=%0d bind=%0d scratch=%0d",
                   issued_data_requests, descriptor_lookup_requests,
                   binding_lookup_requests, scratch_transactions);

        // Fault 2 is isolated by reset. R5 drives the exact XMSS source
        // binding to word 512, outside the 0..511 Scratchpad contract.
        phase = PHASE_ADDRESS_BOUNDS;
        reset_dut();
        write_program(0, enc(OP_MOVI, 0, 5, 0, 32'd512));
        write_program(1, enc(OP_STORE, 0, 0, 0, 0));
        write_program(2, enc(OP_HALT, 0, 0, 0, 0));
        write_descriptor(0, XMSS_STORE_DESC);
        write_binding(0, XMSS_SOURCE_BIND);
        write_binding(1, XMSS_DEST_BIND);
        start_job();
        expect_fault(ERR_AGU_BOUNDS);
        if (issued_data_requests != 1 || retired_instructions != 1
            || descriptor_lookup_requests != 1
            || binding_lookup_requests != 1 || scratch_transactions != 0)
            $fatal(1, "bounds accounting mismatch data=%0d retired=%0d desc=%0d bind=%0d scratch=%0d",
                   issued_data_requests, retired_instructions,
                   descriptor_lookup_requests, binding_lookup_requests,
                   scratch_transactions);

        // Reset clears the sticky fault and configuration validity maps. A
        // fresh image then completes a normal autonomous EMIT Job.
        phase = PHASE_RECOVERY;
        reset_dut();
        write_program(0, enc(OP_EMIT, 0, 0, 0, 32'h0001_0000));
        write_program(1, enc(OP_HALT, 0, 0, 0, 0));
        write_descriptor(1, STATIC_EMIT_DESC);
        for (index = 0; index < 4; index = index + 1)
            write_scratch(400 + index, expected[index]);
        out_ready = 1'b1;
        start_job();

        timeout = 0;
        while (!done && !error && timeout < 800) begin
            @(negedge clk);
            timeout = timeout + 1;
        end
        out_ready = 1'b0;
        if (error || error_code != 0 || !done || captured_words != 4)
            $fatal(1, "post-reset recovery failed done=%0d error=%0d code=%h words=%0d pulses=%0d",
                   done, error, error_code, captured_words, observed_done);
        // The monitor samples the registered done pulse on the next edge.
        @(posedge clk);
        #1;
        if (observed_done != 1)
            $fatal(1, "post-reset recovery completion pulse was not observed");
        if (accepted_job_commands != 1 || issued_data_requests != 1
            || retired_instructions != 2 || descriptor_lookup_requests != 1
            || binding_lookup_requests != 0 || scratch_transactions != 4
            || host_control_writes_during_busy != 0
            || descriptor_host_writes_busy != 0
            || binding_host_writes_busy != 0
            || external_task_descriptors != 0
            || external_hash_descriptors != 0)
            $fatal(1, "recovery accounting/interface-isolation mismatch");

        $display("PASS v2 fail-closed missing binding (080a), affine bounds (0312), no output/done leakage, sticky codes, and reset recovery");
        $finish;
    end
endmodule

`default_nettype wire
