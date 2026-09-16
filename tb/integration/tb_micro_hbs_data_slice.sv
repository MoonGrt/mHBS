`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_data_slice;
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
    logic scratch_init_valid = 1'b0;
    wire scratch_init_ready;
    logic [5:0] scratch_init_address = '0;
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
    wire [31:0] external_task_descriptors, external_hash_descriptors;

    localparam logic [7:0] OP_LOAD  = 8'h08;
    localparam logic [7:0] OP_STORE = 8'h09;
    localparam logic [7:0] OP_XOR   = 8'h0a;
    localparam logic [7:0] OP_EMIT  = 8'h0c;
    localparam logic [7:0] OP_HALT  = 8'h0d;

    logic [63:0] captured [0:1];
    logic [7:0] captured_keep [0:1];
    logic captured_last [0:1];
    integer captured_count = 0;
    integer timeout;

    always #5 clk = ~clk;

    micro_hbs_data_slice #(
        .PROGRAM_WORDS(16), .DESCRIPTOR_COUNT(8),
        .SCRATCH_WORDS(64), .ADDRESS_WIDTH(6)
    ) dut (.*);

    always_ff @(posedge clk) begin
        if (out_valid && out_ready) begin
            if (captured_count >= 2)
                $fatal(1, "duplicate output word");
            captured[captured_count] <= out_data;
            captured_keep[captured_count] <= out_keep;
            captured_last[captured_count] <= out_last;
            captured_count <= captured_count + 1;
        end
    end

    function automatic [63:0] enc(
        input [7:0] opcode, input [7:0] flags,
        input [7:0] rd, input [7:0] rs, input [31:0] imm
    );
        enc = {opcode, flags, rd, rs, imm};
    endfunction

    function automatic [127:0] desc(
        input [15:0] flags, input [15:0] source_a,
        input [15:0] source_b, input [15:0] destination,
        input [15:0] word_count, input [3:0] last_bytes,
        input [3:0] address_mode
    );
        desc = {8'h01, flags, source_a, source_b, destination,
                word_count, last_bytes, address_mode, 32'b0};
    endfunction

    task automatic write_program(input [8:0] address, input [63:0] word);
        begin
            @(negedge clk);
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
                $fatal(1, "descriptor config not ready");
            descriptor_cfg_id = id;
            descriptor_cfg_data = value;
            descriptor_cfg_valid = 1'b1;
            @(negedge clk);
            descriptor_cfg_valid = 1'b0;
            if (descriptor_cfg_error)
                $fatal(1, "descriptor config failed %h",
                       descriptor_cfg_error_code);
        end
    endtask

    task automatic write_scratch(input [5:0] address, input [63:0] value);
        begin
            @(negedge clk);
            if (!scratch_init_ready)
                $fatal(1, "scratch init not ready");
            scratch_init_address = address;
            scratch_init_data = value;
            scratch_init_valid = 1'b1;
            @(negedge clk);
            scratch_init_valid = 1'b0;
        end
    endtask

    task automatic start_job(input [8:0] entry);
        begin
            @(negedge clk);
            if (!job_ready) $fatal(1, "job not ready");
            job_entry = entry;
            job_valid = 1'b1;
            @(negedge clk);
            job_valid = 1'b0;
        end
    endtask

    initial begin
        repeat (3) @(negedge clk);
        rst_n = 1'b1;

        // LOAD R0=1; indexed XOR; indexed STORE; indexed EMIT; HALT.
        write_program(0, enc(OP_LOAD, 0, 0, 0, 0));
        write_program(1, enc(OP_XOR, 0, 0, 0, 1));
        write_program(2, enc(OP_STORE, 0, 0, 0, 2));
        // EMIT descriptor 3 is in imm[31:16].
        write_program(3, enc(OP_EMIT, 1, 0, 0, 32'h0003_0000));
        write_program(4, enc(OP_HALT, 0, 0, 0, 0));
        // A second entry references an uninitialized descriptor 7.
        write_program(8, enc(OP_XOR, 0, 0, 0, 7));
        write_program(9, enc(OP_HALT, 0, 0, 0, 0));

        write_descriptor(0, desc(16'h0001, 5, 0, 0, 1, 0, 0));
        // R0 indexes all three ranges: 10/20/30 become 11/21/31.
        write_descriptor(1, desc(16'h0004, 10, 20, 30, 2, 0, 4'h7));
        // Copy 31..32 to 41..42 using the same R0 index.
        write_descriptor(2, desc(16'h0002, 30, 0, 40, 2, 0, 4'h5));
        // Base 40 plus instruction flags[0] R0 emits 41..42.
        write_descriptor(3, desc(16'h0008, 40, 0, 0, 2, 5, 0));

        write_scratch(5, 64'h0000_0000_0000_0001);
        write_scratch(11, 64'h0123_4567_89ab_cdef);
        write_scratch(12, 64'h1111_2222_3333_4444);
        write_scratch(21, 64'hffff_0000_ffff_0000);
        write_scratch(22, 64'h00ff_00ff_00ff_00ff);

        start_job(0);

        // Configuration is locked while BUSY and cannot perturb the lookup
        // image.  The rejection is observable without supplying any task.
        repeat (2) @(negedge clk);
        descriptor_cfg_id = 1;
        descriptor_cfg_data = '0;
        descriptor_cfg_valid = 1'b1;
        @(negedge clk);
        descriptor_cfg_valid = 1'b0;
        if (!descriptor_cfg_error || descriptor_cfg_error_code != 16'h0601)
            $fatal(1, "BUSY descriptor write was not rejected");

        // Hold the output sink stalled after the first word appears.
        timeout = 0;
        while (!out_valid && timeout < 500) begin
            @(negedge clk);
            timeout = timeout + 1;
        end
        if (!out_valid) $fatal(1, "output timeout");
        repeat (3) begin
            @(negedge clk);
            if (!out_valid || out_data !== 64'hfedc_4567_7654_cdef
                || out_keep !== 8'hff || out_last)
                $fatal(1, "output changed under backpressure");
        end
        out_ready = 1'b1;

        timeout = 0;
        while (!done && !error && timeout < 500) begin
            @(negedge clk);
            timeout = timeout + 1;
        end
        out_ready = 1'b0;
        if (!done || error)
            $fatal(1, "data Job failed error=%h", error_code);
        if (captured_count != 2
            || captured[0] !== 64'hfedc_4567_7654_cdef
            || captured[1] !== 64'h11ee_22dd_33cc_44bb
            || captured_keep[0] !== 8'hff
            || captured_keep[1] !== 8'h1f
            || captured_last[0] || !captured_last[1])
            $fatal(1, "output mismatch count=%0d", captured_count);
        if (accepted_job_commands != 1 || issued_data_requests != 4
            || retired_instructions != 5
            || host_control_writes_during_busy != 0
            || external_task_descriptors != 0
            || external_hash_descriptors != 0)
            $fatal(1, "autonomy/accounting mismatch");

        // A missing static descriptor fails closed before any second output.
        start_job(8);
        timeout = 0;
        while (!error && timeout < 100) begin
            @(negedge clk);
            timeout = timeout + 1;
        end
        if (!error || error_code != 16'h0606 || captured_count != 2)
            $fatal(1, "missing descriptor did not fail closed code=%h",
                   error_code);

        $display("PASS one-Job descriptor->AGU->LOAD/XOR/STORE->arbiter->Scratchpad->EMIT data slice");
        $finish;
    end
endmodule

`default_nettype wire
