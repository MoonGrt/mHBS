`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_horizontal_token_image;
    localparam integer EXPANDED_WORDS = 5817;
    logic clk = 0, rst_n = 0, job_valid = 0;
    logic lane0_done_valid = 0, lane1_done_valid = 0;
    logic [2:0] lane0_done_event = 0, lane1_done_event = 0;
    wire job_ready, done, busy, error, lane0_valid, lane1_valid;
    wire [7:0] error_code, pending_events, completed_events;
    wire [47:0] lane0_command, lane1_command;
    wire [2:0] lane0_event, lane1_event;
    wire [7:0] program_counter;
    wire [31:0] retired_words, retired_tokens, issued_lane0,
                issued_lane1, wait_cycles;
    logic [127:0] expected [0:EXPANDED_WORDS-1];
    integer expanded_pc = 0;
    integer expected_lane0 = 0;
    integer expected_lane1 = 0;
    integer index;

    always #5 clk = ~clk;

    micro_hbs_horizontal_token_sequencer #(
        .PROGRAM_TOKENS(256), .ADDRESS_WIDTH(8)
    ) dut (
        .clk, .rst_n,
        .token_we(1'b0), .token_addr(8'b0), .token_wdata(64'b0),
        .template_we(1'b0), .template_addr(6'b0),
        .template_wdata(128'b0),
        .job_valid, .job_ready, .job_entry(8'b0),
        .done, .busy, .error, .error_code,
        .lane0_valid, .lane0_ready(1'b1), .lane0_command, .lane0_event,
        .lane1_valid, .lane1_ready(1'b1), .lane1_command, .lane1_event,
        .lane0_done_valid, .lane0_done_event,
        .lane1_done_valid, .lane1_done_event,
        .program_counter, .pending_events, .completed_events,
        .retired_words, .retired_tokens, .issued_lane0, .issued_lane1,
        .wait_cycles
    );

    initial begin
        $readmemh("build/slh_dsa_horizontal_tokens_v0.mem",
                  dut.token_store.memory, 0, 188);
        $readmemh("build/slh_dsa_horizontal_templates_v0.mem",
                  dut.template_store.memory, 0, 32);
        $readmemh("build/slh_dsa_horizontal_expanded_v0.mem",
                  expected, 0, EXPANDED_WORDS - 1);
        for (index = 0; index < EXPANDED_WORDS - 1; index = index + 1) begin
            expected_lane0 = expected_lane0 + expected[index][107];
            expected_lane1 = expected_lane1 + expected[index][106];
        end
    end

    always @(posedge clk) begin
        lane0_done_valid <= lane0_valid;
        lane0_done_event <= lane0_event;
        lane1_done_valid <= lane1_valid;
        lane1_done_event <= lane1_event;
        if (lane0_valid || lane1_valid) begin
            if (expanded_pc >= EXPANDED_WORDS - 1)
                $fatal(1, "RTL emitted past expanded image");
            if (expected[expanded_pc][127:124] != 4'h1
                    || lane0_valid != expected[expanded_pc][107]
                    || lane1_valid != expected[expanded_pc][106]
                    || (lane0_valid
                        && lane0_command != expected[expanded_pc][99:52])
                    || (lane1_valid
                        && lane1_command != expected[expanded_pc][51:4])
                    || (lane0_valid
                        && lane0_event != expected[expanded_pc][105:103])
                    || (lane1_valid
                        && lane1_event != expected[expanded_pc][102:100]))
                $fatal(1, "expanded image mismatch word=%0d", expanded_pc);
            expanded_pc <= expanded_pc + 1;
        end
    end

    initial begin
        repeat (3) @(posedge clk);
        rst_n = 1;
        @(negedge clk); job_valid = 1;
        @(posedge clk); #1 job_valid = 0;
        wait (done || error);
        if (error)
            $fatal(1, "image replay error=%h pc=%0d", error_code,
                   program_counter);
        if (expanded_pc != EXPANDED_WORDS - 1
                || retired_words != EXPANDED_WORDS
                || issued_lane0 != expected_lane0
                || issued_lane1 != expected_lane1)
            $fatal(1, "image counters expanded=%0d retired=%0d lanes=%0d/%0d",
                   expanded_pc, retired_words, issued_lane0, issued_lane1);
        $display("PASS 189-token image expands to all 5817 horizontal words");
        $finish;
    end

    initial begin
        #2000000;
        $fatal(1, "token image timeout expanded=%0d token_pc=%0d",
               expanded_pc, program_counter);
    end
endmodule

`default_nettype wire
