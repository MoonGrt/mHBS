`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_autonomous_control;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic program_we = 1'b0;
    logic [8:0] program_addr = '0;
    logic [63:0] program_wdata = '0;
    logic job_valid = 1'b0;
    logic job_ready;
    logic [8:0] job_entry = '0;
    logic [7:0] job_operation = 8'd1;
    logic [15:0] job_parameter_set = 16'h0103;
    logic [31:0] job_message_base = 32'h1000;
    logic [31:0] job_message_length = 32'd0;
    logic [31:0] job_secret_key_base = 32'h2000;
    logic [31:0] job_public_key_base = 32'h3000;
    logic [31:0] job_output_base = 32'h4000;
    logic [31:0] job_state_handle = 32'h5;
    logic [15:0] job_flags = 16'h0;
    logic busy, done, error;
    logic [15:0] error_code;
    logic [31:0] accepted_job_commands;
    logic [31:0] host_control_writes_during_busy;
    logic [31:0] issued_hash_requests;
    logic [31:0] retired_instructions;

    always #5 clk = ~clk;

    micro_hbs_control_slice dut (.*);

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

    initial begin
        repeat (3) @(posedge clk);
        rst_n = 1'b1;

        // LOOP_SETUP R0,3; HASH_LAYOUT layout=7; LOOP_END; HALT
        write_program(0, enc(8'h04, 0, 0, 0, 32'd3));
        write_program(1, enc(8'h03, 1, 8'd12, 0, 32'd7));
        write_program(2, enc(8'h05, 0, 0, 0, 0));
        write_program(3, enc(8'h0d, 0, 0, 0, 0));

        @(negedge clk);
        if (!job_ready) $fatal(1, "job_ready not asserted in IDLE");
        job_valid = 1'b1;
        @(negedge clk);
        job_valid = 1'b0;

        repeat (100) begin
            @(posedge clk);
            if (done) begin
                if (error) $fatal(1, "unexpected error %h", error_code);
                if (accepted_job_commands !== 1) $fatal(1, "job count %0d", accepted_job_commands);
                if (host_control_writes_during_busy !== 0) $fatal(1, "host write count %0d", host_control_writes_during_busy);
                if (issued_hash_requests !== 3) $fatal(1, "hash request count %0d", issued_hash_requests);
                if (retired_instructions !== 8) $fatal(1, "retired count %0d", retired_instructions);
                $display("AUTONOMOUS_CONTROL_PASS jobs=%0d hashes=%0d host_writes_busy=%0d retired=%0d",
                    accepted_job_commands, issued_hash_requests,
                    host_control_writes_during_busy, retired_instructions);
                $finish;
            end
        end
        $fatal(1, "timeout waiting for autonomous completion");
    end
endmodule

`default_nettype wire
