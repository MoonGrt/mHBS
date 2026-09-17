`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_horizontal_token_loop;
    logic clk = 0, rst_n = 0;
    logic token_we = 0, template_we = 0, job_valid = 0;
    logic [3:0] token_addr = 0, job_entry = 0;
    logic [63:0] token_wdata = 0;
    logic [5:0] template_addr = 0;
    logic [127:0] template_wdata = 0;
    wire job_ready, done, busy, error, lane0_valid, lane1_valid;
    wire [7:0] error_code, pending_events, completed_events;
    wire [47:0] lane0_command, lane1_command;
    wire [2:0] lane0_event, lane1_event;
    wire [3:0] program_counter;
    wire [31:0] retired_words, retired_tokens, issued_lane0,
                issued_lane1, wait_cycles;
    integer issues = 0;

    always #5 clk = ~clk;

    micro_hbs_horizontal_token_sequencer #(
        .PROGRAM_TOKENS(16), .ADDRESS_WIDTH(4)
    ) dut (
        .clk, .rst_n, .token_we, .token_addr, .token_wdata,
        .template_we, .template_addr, .template_wdata,
        .job_valid, .job_ready, .job_entry, .done, .busy, .error,
        .error_code, .lane0_valid, .lane0_ready(1'b1), .lane0_command,
        .lane0_event, .lane1_valid, .lane1_ready(1'b1), .lane1_command,
        .lane1_event, .lane0_done_valid(1'b0), .lane0_done_event(3'b0),
        .lane1_done_valid(1'b0), .lane1_done_event(3'b0),
        .program_counter, .pending_events, .completed_events,
        .retired_words, .retired_tokens, .issued_lane0, .issued_lane1,
        .wait_cycles
    );

    task automatic write_template(input [127:0] value);
        begin
            @(negedge clk); template_wdata = value; template_we = 1;
            @(posedge clk); #1 template_we = 0;
        end
    endtask

    task automatic write_token(input [3:0] address, input [63:0] value);
        begin
            @(negedge clk); token_addr = address;
            token_wdata = value; token_we = 1;
            @(posedge clk); #1 token_we = 0;
        end
    endtask

    always @(posedge clk)
        if (lane0_valid && lane1_valid) begin
            if (lane0_command[23:0] != 10 + issues
                    || lane1_command[23:0] != 20 + issues)
                $fatal(1, "loop context mismatch issue=%0d cmd=%h/%h",
                       issues, lane0_command, lane1_command);
            issues <= issues + 1;
        end

    initial begin
        repeat (3) @(posedge clk);
        rst_n = 1;
        // ISSUE template, both untracked lanes, context index fields zero.
        write_template({4'h1, 8'b0, 8'b0, 1'b1, 1'b1, 6'b0,
                        8'h04, 12'b0, 4'b0, 24'b0,
                        8'h05, 12'b0, 4'b1, 24'b0, 4'b0});
        // Two-token body, repeated twice more with context delta +2.
        write_token(0, {2'b00, 6'd0, 13'd10, 13'd20,
                        5'd0, 5'd0, 5'd0, 15'd0});
        write_token(1, {2'b00, 6'd0, 13'd11, 13'd21,
                        5'd0, 5'd0, 5'd0, 15'd0});
        write_token(2, {2'b10, 12'd1, 5'd2, 13'd2, 32'd0});
        write_token(3, {2'b11, 62'd0});

        @(negedge clk); job_valid = 1;
        @(posedge clk); #1 job_valid = 0;
        wait (done || error);
        if (error)
            $fatal(1, "loop sequencer error=%h", error_code);
        if (issues != 6 || retired_words != 7 || retired_tokens != 10)
            $fatal(1, "loop counters issues=%0d words=%0d tokens=%0d",
                   issues, retired_words, retired_tokens);
        $display("PASS horizontal token outer loop expansion");
        $finish;
    end

    initial begin
        #5000; $fatal(1, "token loop timeout pc=%0d", program_counter);
    end
endmodule

`default_nettype wire
