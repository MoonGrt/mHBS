`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_randomized_chain_slice;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic program_we = 1'b0;
    logic [8:0] program_addr = '0;
    logic [63:0] program_wdata = '0;
    logic host_sp_valid = 1'b0;
    wire host_sp_ready;
    logic host_sp_write = 1'b0;
    logic [15:0] host_sp_address = '0;
    logic [63:0] host_sp_write_data = '0;
    wire host_sp_response_valid;
    wire [63:0] host_sp_read_data;
    wire host_sp_bounds_error;
    logic job_valid = 1'b0;
    wire job_ready;
    logic [8:0] job_entry = '0;
    wire busy, done, error;
    wire [15:0] error_code;
    wire [255:0] result;
    wire [31:0] accepted_job_commands;
    wire [31:0] host_control_writes_during_busy;
    wire [31:0] issued_hash_requests;
    wire [31:0] retired_instructions;
    wire [31:0] scratch_reads;
    wire [31:0] scratch_writes;
    wire [31:0] internal_hash_calls;
    integer i;
    integer watchdog;
    integer job_cycles;

    always #5 clk = ~clk;

    micro_hbs_randomized_chain_slice #(.SCRATCH_WORDS(32), .UNROLL(2)) dut (.*);

    function automatic [63:0] enc(
        input [7:0] opcode,
        input [7:0] flags,
        input [7:0] rd,
        input [7:0] rs,
        input [31:0] imm
    );
        enc = {opcode, flags, rd, rs, imm};
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

    task automatic write_scratch(input [15:0] address, input [63:0] data);
        begin
            @(negedge clk);
            while (!host_sp_ready) @(negedge clk);
            host_sp_address = address;
            host_sp_write_data = data;
            host_sp_write = 1'b1;
            host_sp_valid = 1'b1;
            @(posedge clk);
            #1 host_sp_valid = 1'b0;
            host_sp_write = 1'b0;
        end
    endtask

    initial begin
        repeat (3) @(posedge clk);
        rst_n = 1'b1;

        // R1 points to the public 8-bit chain bound in Scratchpad word 12.
        // One HASH_LAYOUT instruction iterates autonomously with R0=0,1,2.
        write_program(0, enc(8'h01, 0, 1, 0, 32'd12));
        write_program(1, enc(8'h04, 1, 1, 0, 32'd4));
        write_program(2, enc(8'h03, 1, 8, 0, 32'h00000100));
        write_program(3, enc(8'h05, 0, 0, 0, 0));
        write_program(4, enc(8'h0d, 0, 0, 0, 0));

        // public seed = bytes 20..3f
        write_scratch(0, 64'h2726252423222120);
        write_scratch(1, 64'h2f2e2d2c2b2a2928);
        write_scratch(2, 64'h3736353433323130);
        write_scratch(3, 64'h3f3e3d3c3b3a3938);
        // Address words [0,0,0,0,5,2,step,0], serialized big endian.
        write_scratch(4, 64'h0000000000000000);
        write_scratch(5, 64'h0000000000000000);
        write_scratch(6, 64'h0200000005000000);
        write_scratch(7, 64'h0000000000000000);
        // Initial node = bytes 00..1f.
        write_scratch(8, 64'h0706050403020100);
        write_scratch(9, 64'h0f0e0d0c0b0a0908);
        write_scratch(10, 64'h1716151413121110);
        write_scratch(11, 64'h1f1e1d1c1b1a1918);
        write_scratch(12, 64'h0000000000000003);

        @(negedge clk);
        if (!job_ready) $fatal(1, "slice not ready");
        job_valid = 1'b1;
        @(negedge clk);
        job_valid = 1'b0;

        watchdog = 0;
        while (!done && !error) begin
            @(posedge clk);
            #1;
            watchdog = watchdog + 1;
            if (!done && !error && host_sp_ready)
                $fatal(1, "host Scratchpad port exposed while BUSY");
            if (watchdog > 800)
                $fatal(1, "randomized chain timeout");
        end
        if (error) $fatal(1, "unexpected error %h", error_code);
        if (result !== 256'h3d8f3507289a0eef556841c6b7ffc6567b41c9b7cc1a1ac8deddc08808bf51aa)
            $fatal(1, "randomized F chain mismatch got=%064x", result);
        if (accepted_job_commands != 1 || issued_hash_requests != 3)
            $fatal(1, "autonomy mismatch jobs=%0d requests=%0d",
                   accepted_job_commands, issued_hash_requests);
        if (host_control_writes_during_busy != 0)
            $fatal(1, "host wrote control while BUSY");
        if (scratch_reads != 36 || scratch_writes != 12 || internal_hash_calls != 9)
            $fatal(1, "accounting mismatch reads=%0d writes=%0d hash_calls=%0d",
                   scratch_reads, scratch_writes, internal_hash_calls);
        if (retired_instructions != 9)
            $fatal(1, "retired mismatch %0d", retired_instructions);
        job_cycles = watchdog;

        // A dynamic bound outside the physical Scratchpad must terminate
        // instead of waiting forever or wrapping the address.
        write_program(0, enc(8'h01, 0, 1, 0, 32'd32));
        @(negedge clk);
        job_valid = 1'b1;
        @(negedge clk);
        job_valid = 1'b0;
        watchdog = 0;
        while (!done && !error) begin
            @(posedge clk);
            #1;
            watchdog = watchdog + 1;
            if (watchdog > 30)
                $fatal(1, "out-of-bounds dynamic bound did not terminate");
        end
        if (!error || done || error_code != 16'h0201)
            $fatal(1, "dynamic bound error mismatch done=%0d error=%0d code=%h",
                   done, error, error_code);

        $display("PASS one-Job dynamic randomized-F chain cycles=%0d and fail-closed bound",
                 job_cycles);
        $finish;
    end
endmodule

`default_nettype wire
