`timescale 1ns/1ps
module tb_uhbs_program_bounds;
    logic clk=0,rst_n=0,job_valid=0;
    wire job_ready,done,busy,error;wire [7:0]error_code;
    logic [8:0]job_entry=0;
    wire [5:0]program_address,template_address;
    logic [127:0]program_data=0,template_data=128'h10000800000000000000000000000008;
    wire [5:0]program_count=1;wire [6:0]template_count=1;
    wire lane0_valid,lane1_valid;
    wire lane0_ready=1,lane1_ready=1,lane0_done_valid=0,lane1_done_valid=0;
    wire [2:0]lane0_done_event=0,lane1_done_event=0;wire [2:0]lane0_event,lane1_event;
    wire [47:0]lane0_command,lane1_command;
    wire [8:0]program_counter;wire [7:0]pending_events;
    wire [31:0]retired_words,retired_tokens;
    uhbs_program_sequencer dut(.*);
    always #5 clk=~clk;
    task tick;begin @(posedge clk);#1;end endtask
    task reject_template(input [127:0] malformed);
        begin
            rst_n=0;tick();rst_n=1;job_entry=0;program_data=0;
            template_data=malformed;job_valid=1;tick();job_valid=0;
            repeat(8)tick();
            if(!error || retired_words!=0) $fatal(1,"unsupported template accepted");
        end
    endtask
    initial begin
        repeat(2)tick();rst_n=1;tick();job_valid=1;tick();job_valid=0;
        repeat(12)tick();
        if(!error || error_code!=8'h31 || program_counter!=1 || retired_words!=1) $fatal(1,"fallthrough must not fetch outside program");
        rst_n=0;tick();rst_n=1;job_entry=32;job_valid=1;tick();job_valid=0;
        repeat(5)tick();if(!error || retired_words!=0) $fatal(1,"data entry accepted");
        job_entry=256;rst_n=0;tick();rst_n=1;job_valid=1;tick();job_valid=0;
        repeat(5)tick();if(!error || retired_words!=0) $fatal(1,"wide entry truncated");
        reject_template(128'h10000800000000000000000000000008 | (128'd1<<103));
        reject_template(128'h10000800000000000000000000000008 | (128'd1<<117));
        reject_template(128'h10000800000000000000000000000008 | (128'd1<<106));
        rst_n=0;tick();rst_n=1;job_entry=0;
        template_data=128'h10000800000000000000000000000008;
        program_data=128'd1<<72;job_valid=1;tick();job_valid=0;
        repeat(8)tick();if(!error || retired_words!=0) $fatal(1,"second coordinate accepted");
        rst_n=0;tick();rst_n=1;
        program_data=(128'd2<<126)|(128'd4095<<114)|(128'd1<<108);
        job_valid=1;tick();job_valid=0;
        repeat(8)tick();if(!error || retired_words!=0) $fatal(1,"LOOP back count wrapped");
        $display("PROGRAM_BOUNDS_PASS");$finish;
    end
endmodule
