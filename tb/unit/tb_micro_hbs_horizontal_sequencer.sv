`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_horizontal_sequencer;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic program_we = 1'b0;
    logic [3:0] program_addr = '0;
    logic [127:0] program_wdata = '0;
    logic job_valid = 1'b0;
    logic [3:0] job_entry = '0;
    logic lane0_ready = 1'b1;
    logic lane1_ready = 1'b1;
    logic lane0_done_valid = 1'b0;
    logic [2:0] lane0_done_event = '0;
    logic lane1_done_valid = 1'b0;
    logic [2:0] lane1_done_event = '0;
    wire job_ready, done, busy, error;
    wire [7:0] error_code;
    wire lane0_valid, lane1_valid;
    wire [47:0] lane0_command, lane1_command;
    wire [2:0] lane0_event, lane1_event;
    wire [3:0] program_counter;
    wire [7:0] pending_events, completed_events;
    wire [31:0] retired_words, issued_lane0, issued_lane1, wait_cycles;

    always #5 clk = ~clk;

    micro_hbs_horizontal_sequencer #(
        .PROGRAM_WORDS(16), .ADDRESS_WIDTH(4)
    ) dut (
        .clk, .rst_n, .program_we, .program_addr, .program_wdata,
        .job_valid, .job_ready, .job_entry, .done, .busy, .error,
        .error_code, .lane0_valid, .lane0_ready, .lane0_command,
        .lane0_event, .lane1_valid, .lane1_ready, .lane1_command,
        .lane1_event, .lane0_done_valid, .lane0_done_event,
        .lane1_done_valid, .lane1_done_event, .program_counter,
        .pending_events, .completed_events, .retired_words,
        .issued_lane0, .issued_lane1, .wait_cycles
    );

    function automatic [127:0] issue_word(
        input [7:0] waits,
        input [7:0] consumes,
        input valid0,
        input [2:0] event0,
        input [47:0] command0,
        input valid1,
        input [2:0] event1,
        input [47:0] command1,
        input track0,
        input track1
    );
        begin
            issue_word = {4'h1, waits, consumes, valid0, valid1,
                          event0, event1, command0, command1,
                          track0, track1, 2'b0};
        end
    endfunction

    function automatic [127:0] wait_word(
        input [7:0] waits,
        input [7:0] consumes
    );
        wait_word = {4'h2, waits, consumes, 108'b0};
    endfunction

    task automatic load_word(input [3:0] address, input [127:0] word);
        begin
            @(negedge clk);
            program_addr = address;
            program_wdata = word;
            program_we = 1'b1;
            @(posedge clk);
            #1 program_we = 1'b0;
        end
    endtask

    task automatic complete0(input [2:0] event_id);
        begin
            @(negedge clk);
            lane0_done_event = event_id;
            lane0_done_valid = 1'b1;
            @(posedge clk);
            #1 lane0_done_valid = 1'b0;
        end
    endtask

    task automatic complete1(input [2:0] event_id);
        begin
            @(negedge clk);
            lane1_done_event = event_id;
            lane1_done_valid = 1'b1;
            @(posedge clk);
            #1 lane1_done_valid = 1'b0;
        end
    endtask

    initial begin
        repeat (3) @(posedge clk);
        rst_n = 1'b1;
        load_word(0, issue_word(0, 0, 1, 0, 48'h100,
                                      1, 1, 48'h101, 1, 1));
        load_word(1, issue_word(8'h01, 8'h01, 1, 2, 48'h202,
                                      0, 0, 48'h0, 1, 0));
        load_word(2, wait_word(8'h06, 8'h06));
        load_word(3, issue_word(0, 0, 0, 0, 48'h0,
                                      1, 0, 48'h300, 0, 1));
        load_word(4, {4'hf, 124'b0});

        @(negedge clk);
        job_valid = 1'b1;
        @(posedge clk);
        #1 job_valid = 1'b0;

        wait (lane0_valid && lane1_valid);
        if (lane0_command != 48'h100 || lane1_command != 48'h101
            || lane0_event != 0 || lane1_event != 1)
            $fatal(1, "first horizontal issue mismatch");
        @(posedge clk);
        #1;

        complete1(1);
        repeat (4) @(posedge clk);
        if (program_counter != 1 || lane0_valid)
            $fatal(1, "dependency wait did not stall word 1");
        complete0(0);
        // Completion bypass accepts word 1 on the same edge as event 0.
        if (issued_lane0 != 2 || pending_events != 8'h04)
            $fatal(1, "dependent issue/bypass mismatch issued=%0d pending=%h",
                   issued_lane0, pending_events);
        complete0(2);

        wait (lane1_valid);
        if (lane1_command != 48'h300 || lane1_event != 0)
            $fatal(1, "event reuse issue mismatch");
        @(posedge clk);
        #1;
        complete1(0);
        wait (done || error);
        if (error)
            $fatal(1, "horizontal sequencer error=%0h", error_code);
        if (retired_words != 5 || issued_lane0 != 2 || issued_lane1 != 2)
            $fatal(1, "counter mismatch retired=%0d lane=%0d/%0d",
                   retired_words, issued_lane0, issued_lane1);
        $display("PASS horizontal sequencer dual issue and 8-event scoreboard");
        $finish;
    end

    initial begin
        #10000;
        $fatal(1, "horizontal sequencer timeout pc=%0d pending=%h completed=%h",
               program_counter, pending_events, completed_events);
    end
endmodule

`default_nettype wire
