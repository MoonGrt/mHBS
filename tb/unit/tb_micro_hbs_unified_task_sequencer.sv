`timescale 1ns/1ps
module tb_micro_hbs_unified_task_sequencer;
    logic clk = 0, rst_n = 0, job_valid = 0;
    logic [1:0] job_algorithm = 0, job_operation = 0;
    wire job_ready, done, busy, error;
    wire [7:0] error_code;
    wire lane0_valid, lane1_valid;
    logic lane0_ready = 1, lane1_ready = 1;
    wire [47:0] lane0_command, lane1_command;
    wire [63:0] lane0_descriptor;
    wire [2:0] lane0_event, lane1_event;
    logic lane0_done_valid = 0, lane1_done_valid = 0;
    logic [2:0] lane0_done_event = 0, lane1_done_event = 0;
    wire [7:0] descriptor_base, descriptor_count, pending_events;
    logic descriptor_request_valid = 0;
    wire descriptor_request_ready, descriptor_response_valid;
    logic [7:0] descriptor_request_index = 0;
    wire [63:0] descriptor_response_data;
    wire [5:0] profile_n_bytes;
    wire [4:0] profile_height;
    wire profile_stateful;
    wire [31:0] retired_words, retired_tokens;
    integer cycles = 0;
    logic completion_pending = 0, pending_lane1 = 0;
    logic [2:0] pending_event0 = 0, pending_event1 = 0;

    always #5 clk = ~clk;
    always @(posedge clk) begin
        cycles <= cycles + 1;
        lane0_done_valid <= 0;
        lane1_done_valid <= 0;
        descriptor_request_valid <= 0;
        if (completion_pending) begin
            lane0_done_valid <= 1;
            lane0_done_event <= pending_event0;
            lane1_done_valid <= pending_lane1;
            lane1_done_event <= pending_event1;
            completion_pending <= 0;
        end
        if (lane0_valid) begin
            if (profile_stateful && lane0_descriptor[63:60] == 0)
                $fatal(1, "empty prefetched descriptor returned");
            completion_pending <= 1;
            pending_lane1 <= lane1_valid;
            pending_event0 <= lane0_event;
            pending_event1 <= lane1_event;
        end
        if (cycles > 1000000) begin
            $display("state=%0d pc=%0d pending=%h dreq=%0d/%0d dpending=%0d wait=%0d words=%0d",
                     dut.state, dut.pc, pending_events,
                     descriptor_request_valid, descriptor_request_ready,
                     dut.descriptor_pending, 0,
                     retired_words);
            $fatal(1, "sequencer timeout");
        end
    end

    micro_hbs_unified_task_sequencer dut (.*);

    task tick; begin @(posedge clk); #1; end endtask
    task run(input [1:0] alg, input [1:0] op,
             input integer words, input integer nbytes,
             input integer height, input integer stateful);
        begin
            while (!job_ready) tick();
            job_algorithm = alg; job_operation = op; job_valid = 1;
            tick(); job_valid = 0;
            while (!done && !error) tick();
            if (error) $fatal(1, "sequencer error %h alg=%0d op=%0d",
                              error_code, alg, op);
            if (retired_words != words || profile_n_bytes != nbytes
                    || profile_height != height
                    || profile_stateful != stateful)
                $fatal(1, "metadata/word mismatch got %0d n=%0d h=%0d s=%0d",
                       retired_words, profile_n_bytes, profile_height,
                       profile_stateful);
            tick();
        end
    endtask

    initial begin
        repeat (3) tick(); rst_n = 1; tick();
        run(0, 1, 101, 16, 6, 0);
        run(0, 0, 2, 16, 6, 0);
        run(1, 0, 70658, 32, 10, 1);
        run(1, 1, 5, 32, 10, 1);
        run(2, 0, 4098, 32, 10, 1);
        run(2, 1, 5, 32, 10, 1);
        $display("UNIFIED_TASK_SEQUENCER_PASS");
        $finish;
    end
endmodule
