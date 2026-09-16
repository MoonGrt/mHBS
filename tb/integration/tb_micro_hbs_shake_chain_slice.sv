`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_shake_chain_slice;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic program_we = 1'b0;
    logic [8:0] program_addr = '0;
    logic [63:0] program_wdata = '0;
    logic job_valid = 1'b0;
    wire job_ready;
    logic [8:0] job_entry = '0;
    logic [255:0] job_initial_value = '0;
    wire busy, done, error;
    wire [15:0] error_code;
    wire [255:0] result;
    wire [31:0] accepted_job_commands;
    wire [31:0] host_control_writes_during_busy;
    wire [31:0] issued_hash_requests;
    wire [31:0] retired_instructions;
    integer i;
    integer watchdog;

    always #5 clk = ~clk;

    micro_hbs_shake_chain_slice #(.UNROLL(2)) dut (.*);

    function automatic [63:0] enc;
        input [7:0] opcode;
        input [7:0] flags;
        input [7:0] rd;
        input [7:0] rs;
        input [31:0] imm;
        enc = {opcode, flags, rd, rs, imm};
    endfunction

    task automatic write_program;
        input [8:0] address;
        input [63:0] word;
        begin
            @(negedge clk);
            program_addr = address;
            program_wdata = word;
            program_we = 1'b1;
            @(negedge clk);
            program_we = 1'b0;
        end
    endtask

    initial begin
        repeat (3) @(posedge clk);
        rst_n = 1'b1;

        // Three autonomous SHAKE256 feedback steps using capability layout 0.
        write_program(0, enc(8'h04, 0, 0, 0, 32'd3));
        write_program(1, enc(8'h03, 1, 0, 0, 32'd0));
        write_program(2, enc(8'h05, 0, 0, 0, 0));
        write_program(3, enc(8'h0d, 0, 0, 0, 0));

        for (i = 0; i < 32; i = i + 1)
            job_initial_value[8*i +: 8] = i[7:0];
        @(negedge clk);
        if (!job_ready) $fatal(1, "slice not ready");
        job_valid = 1'b1;
        @(negedge clk);
        job_valid = 1'b0;

        // Mutating the external bus after acceptance must not affect the Job.
        job_initial_value = '1;
        watchdog = 0;
        while (!done && !error) begin
            @(posedge clk);
            #1;
            watchdog = watchdog + 1;
            if (watchdog > 100) $fatal(1, "SHAKE chain slice timeout");
        end
        if (error) $fatal(1, "unexpected slice error %h", error_code);
        if (result !== 256'h93d3d66a466e0bc6ecd6665ef1eb993c51722c6fbce605692491c01fc87c773d)
            $fatal(1, "three-step chain mismatch got=%064x", result);
        if (accepted_job_commands != 1 || issued_hash_requests != 3)
            $fatal(1, "autonomy counters jobs=%0d hashes=%0d",
                   accepted_job_commands, issued_hash_requests);
        if (host_control_writes_during_busy != 0)
            $fatal(1, "unexpected host control writes %0d", host_control_writes_during_busy);
        if (retired_instructions != 8)
            $fatal(1, "retired instruction mismatch %0d", retired_instructions);
        // Runtime defense: an image that bypasses the offline verifier must
        // still terminate on an unsupported layout instead of hanging.
        write_program(1, enc(8'h03, 1, 0, 0, 32'd99));
        @(negedge clk);
        job_valid = 1'b1;
        @(negedge clk);
        job_valid = 1'b0;
        watchdog = 0;
        while (!error && !done) begin
            @(posedge clk);
            #1;
            watchdog = watchdog + 1;
            if (watchdog > 30) $fatal(1, "invalid-layout job timeout");
        end
        if (!error || done || error_code != 16'h0101)
            $fatal(1, "invalid layout fail-closed mismatch done=%0d error=%0d code=%h",
                   done, error, error_code);

        $display("PASS autonomous SHAKE chain and invalid-layout fail-closed");
        $finish;
    end
endmodule

`default_nettype wire
