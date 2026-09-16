`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_data_v2_slice;
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
    logic [7:0] binding_cfg_format_version = 1;
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
    localparam logic [127:0] XMSS_STORE_DESC =
        128'h02000200000000000000048500002000;
    localparam logic [63:0] XMSS_SOURCE_BIND = 64'h37c0010001000000;
    localparam logic [63:0] XMSS_DEST_BIND   = 64'hbac0010001000000;
    localparam logic [127:0] STATIC_EMIT_DESC =
        128'h02000801900000000000048000000000;

    logic [63:0] expected [0:3];
    integer captured_count = 0;
    integer timeout;
    integer i;

    always #5 clk = ~clk;

    micro_hbs_data_v2_slice dut (.*);

    function automatic [63:0] enc(
        input [7:0] opcode, input [7:0] flags,
        input [7:0] rd, input [7:0] rs, input [31:0] imm
    );
        enc = {opcode, flags, rd, rs, imm};
    endfunction

    always @(posedge clk) begin
        if (out_valid && out_ready) begin
            if (captured_count >= 4 || out_data !== expected[captured_count])
                $fatal(1, "output word %0d mismatch data=%h",
                       captured_count, out_data);
            if (out_keep !== 8'hff || out_last !== (captured_count == 3))
                $fatal(1, "output framing %0d keep=%h last=%0d",
                       captured_count, out_keep, out_last);
            captured_count = captured_count + 1;
        end
    end

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
                $fatal(1, "descriptor config error %h",
                       descriptor_cfg_error_code);
        end
    endtask

    task automatic write_binding(input [15:0] id, input [63:0] value);
        begin
            @(negedge clk);
            if (!binding_cfg_ready)
                $fatal(1, "binding config not ready");
            binding_cfg_id = id;
            binding_cfg_data = value;
            binding_cfg_valid = 1'b1;
            @(negedge clk);
            binding_cfg_valid = 1'b0;
            if (binding_cfg_error)
                $fatal(1, "binding config error %h", binding_cfg_error_code);
        end
    endtask

    task automatic write_scratch(input [8:0] address, input [63:0] value);
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

    initial begin
        expected[0] = 64'h0123_4567_89ab_cdef;
        expected[1] = 64'h1111_2222_3333_4444;
        expected[2] = 64'hfedc_ba98_7654_3210;
        expected[3] = 64'h55aa_00ff_a55a_5aa5;

        repeat (3) @(negedge clk);
        rst_n = 1'b1;

        // Same Job owns all four register values used by the XMSS bindings.
        write_program(0, enc(OP_MOVI, 0, 5, 0, 0));
        write_program(1, enc(OP_MOVI, 0, 7, 0, 66));
        write_program(2, enc(OP_MOVI, 0, 6, 0, 67));
        write_program(3, enc(OP_MOVI, 0, 3, 0, 33));
        write_program(4, enc(OP_STORE, 0, 0, 0, 0));
        // EMIT descriptor ID is imm[31:16]; its static base is physical 400.
        write_program(5, enc(OP_EMIT, 0, 0, 0, 32'h0001_0000));
        write_program(6, enc(OP_HALT, 0, 0, 0, 0));

        write_descriptor(0, XMSS_STORE_DESC);
        write_descriptor(1, STATIC_EMIT_DESC);
        write_binding(0, XMSS_SOURCE_BIND);
        write_binding(1, XMSS_DEST_BIND);
        for (i = 0; i < 4; i = i + 1)
            write_scratch(264 + i, expected[i]);

        @(negedge clk);
        if (!job_ready) $fatal(1, "Job interface not ready");
        job_entry = 0;
        job_valid = 1'b1;
        @(negedge clk);
        job_valid = 1'b0;
        if (!busy || scratch_init_ready)
            $fatal(1, "Job did not lock IDLE-only interfaces");

        // Busy-time image mutations are rejected locally and cannot alter the
        // autonomous STORE/EMIT sequence.
        repeat (3) @(negedge clk);
        descriptor_cfg_id = 0;
        descriptor_cfg_data = '0;
        descriptor_cfg_valid = 1'b1;
        binding_cfg_id = 0;
        binding_cfg_data = XMSS_DEST_BIND;
        binding_cfg_valid = 1'b1;
        @(negedge clk);
        descriptor_cfg_valid = 1'b0;
        binding_cfg_valid = 1'b0;
        if (!descriptor_cfg_error || descriptor_cfg_error_code != 16'h0601
            || !binding_cfg_error || binding_cfg_error_code != 16'h0801)
            $fatal(1, "BUSY image write was not rejected");

        timeout = 0;
        while (!out_valid && !error && timeout < 2000) begin
            @(negedge clk);
            timeout = timeout + 1;
        end
        if (error || !out_valid)
            $fatal(1, "v2 path failed/timeout error=%h", error_code);

        // Exercise output backpressure before accepting all four words.
        repeat (3) begin
            @(negedge clk);
            if (!out_valid || out_data !== expected[0]
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

        if (!done || error || captured_count != 4)
            $fatal(1, "v2 Job result done=%0d error=%0d code=%h count=%0d",
                   done, error, error_code, captured_count);
        if (accepted_job_commands != 1 || issued_data_requests != 2
            || retired_instructions != 7
            || host_control_writes_during_busy != 0
            || descriptor_host_writes_busy != 1
            || binding_host_writes_busy != 1
            || descriptor_lookup_requests != 2
            || binding_lookup_requests != 3
            || scratch_transactions != 12
            || external_task_descriptors != 0
            || external_hash_descriptors != 0)
            $fatal(1, "v2 accounting jobs=%0d data=%0d retired=%0d host=%0d desc_busy=%0d bind_busy=%0d desc_lookup=%0d bind_lookup=%0d scratch=%0d",
                   accepted_job_commands, issued_data_requests,
                   retired_instructions, host_control_writes_during_busy,
                   descriptor_host_writes_busy, binding_host_writes_busy,
                   descriptor_lookup_requests, binding_lookup_requests,
                   scratch_transactions);

        $display("PASS v2 one-Job XMSS affine STORE->EMIT: R5+R7 source 264, R6+R3 destination 400, exact descriptor/bindings, no host task/hash ingress");
        $finish;
    end
endmodule

`default_nettype wire
