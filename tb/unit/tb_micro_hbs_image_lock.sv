`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_image_lock;
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
    logic [31:0] job_message_base = '0;
    logic [31:0] job_message_length = '0;
    logic [31:0] job_secret_key_base = '0;
    logic [31:0] job_public_key_base = '0;
    logic [31:0] job_output_base = '0;
    logic [31:0] job_state_handle = '0;
    logic [15:0] job_flags = '0;
    logic busy, done, error;
    logic [15:0] error_code;
    logic [31:0] accepted_job_commands;
    logic [31:0] host_control_writes_during_busy;
    logic [31:0] issued_hash_requests;
    logic [31:0] retired_instructions;

    always #5 clk = ~clk;
    micro_hbs_control_slice dut (.*);

    initial begin
        repeat (3) @(posedge clk);
        rst_n = 1'b1;
        @(negedge clk);
        program_we = 1'b1;
        program_wdata = {8'h03, 8'h01, 8'h00, 8'h00, 32'h0};
        @(negedge clk);
        program_we = 1'b0;
        job_valid = 1'b1;
        @(negedge clk);
        job_valid = 1'b0;
        wait (busy);
        @(negedge clk);
        program_we = 1'b1;
        @(negedge clk);
        program_we = 1'b0;
        @(posedge clk);
        if (!error || error_code != 16'h0001) $fatal(1, "image lock did not fail closed");
        if (host_control_writes_during_busy != 1) $fatal(1, "busy write not counted");
        if (done) $fatal(1, "done and error both asserted");
        $display("IMAGE_LOCK_PASS error=%h host_writes_busy=%0d", error_code, host_control_writes_during_busy);
        $finish;
    end
endmodule

`default_nettype wire
