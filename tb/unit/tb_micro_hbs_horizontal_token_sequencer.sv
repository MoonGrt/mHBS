`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_horizontal_token_sequencer;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic token_we = 1'b0;
    logic [3:0] token_addr = '0;
    logic [63:0] token_wdata = '0;
    logic template_we = 1'b0;
    logic [5:0] template_addr = '0;
    logic [127:0] template_wdata = '0;
    logic job_valid = 1'b0;
    logic [3:0] job_entry = '0;
    logic lane0_ready = 1'b1;
    logic lane1_ready = 1'b1;
    wire job_ready, done, busy, error;
    wire [7:0] error_code;
    wire lane0_valid, lane1_valid;
    wire [47:0] lane0_command, lane1_command;
    wire [2:0] lane0_event, lane1_event;
    wire [3:0] program_counter;
    wire [7:0] pending_events, completed_events;
    wire [31:0] retired_words, retired_tokens;
    wire [31:0] issued_lane0, issued_lane1, wait_cycles;
    integer issue_count = 0;

    always #5 clk = ~clk;

    micro_hbs_horizontal_token_sequencer #(
        .PROGRAM_TOKENS(16), .ADDRESS_WIDTH(4)
    ) dut (
        .clk, .rst_n, .token_we, .token_addr, .token_wdata,
        .template_we, .template_addr, .template_wdata,
        .job_valid, .job_ready, .job_entry, .done, .busy, .error,
        .error_code, .lane0_valid, .lane0_ready, .lane0_command,
        .lane0_event, .lane1_valid, .lane1_ready, .lane1_command,
        .lane1_event, .lane0_done_valid(1'b0), .lane0_done_event(3'b0),
        .lane1_done_valid(1'b0), .lane1_done_event(3'b0),
        .program_counter, .pending_events, .completed_events,
        .retired_words, .retired_tokens, .issued_lane0, .issued_lane1,
        .wait_cycles
    );

    function automatic [127:0] issue_template;
        input [7:0] recipe0;
        input [7:0] recipe1;
        begin
            issue_template = {4'h1, 8'b0, 8'b0, 1'b1, 1'b1,
                3'b0, 3'b0,
                recipe0, 12'b0, 4'b0, 24'b0,
                recipe1, 12'b0, 4'b1, 24'b0,
                1'b0, 1'b0, 2'b0};
        end
    endfunction

    function automatic [63:0] run_token;
        input [5:0] template_id;
        input [12:0] base0;
        input [12:0] base1;
        input [4:0] repeat_minus_one;
        input [4:0] step0;
        input [4:0] step1;
        begin
            run_token = {2'b01, template_id, base0, base1,
                         repeat_minus_one, step0, step1, 15'b0};
        end
    endfunction

    task automatic load_template(input [5:0] address,
                                 input [127:0] word);
        begin
            @(negedge clk);
            template_addr = address;
            template_wdata = word;
            template_we = 1'b1;
            @(posedge clk);
            #1 template_we = 1'b0;
        end
    endtask

    task automatic load_token(input [3:0] address, input [63:0] word);
        begin
            @(negedge clk);
            token_addr = address;
            token_wdata = word;
            token_we = 1'b1;
            @(posedge clk);
            #1 token_we = 1'b0;
        end
    endtask

    always @(posedge clk) begin
        if (lane0_valid && lane1_valid) begin
            if (lane0_command[23:0] != 24'(5 + issue_count)
                    || lane1_command[23:0] != 24'(100 + 2 * issue_count))
                $fatal(1, "expanded command mismatch at issue %0d: %h/%h",
                       issue_count, lane0_command, lane1_command);
            issue_count <= issue_count + 1;
        end
    end

    initial begin
        repeat (3) @(posedge clk);
        rst_n = 1'b1;
        load_template(0, issue_template(8'h04, 8'h05));
        load_token(0, run_token(0, 13'd5, 13'd100, 5'd2, 5'd1, 5'd2));
        load_token(1, {2'b11, 62'b0});

        @(negedge clk);
        job_valid = 1'b1;
        @(posedge clk);
        #1 job_valid = 1'b0;

        wait (done || error);
        if (error)
            $fatal(1, "token sequencer error=%0h", error_code);
        if (issue_count != 3 || retired_words != 4 || retired_tokens != 2)
            $fatal(1, "counter mismatch issues=%0d words=%0d tokens=%0d",
                   issue_count, retired_words, retired_tokens);
        if (issued_lane0 != 3 || issued_lane1 != 3)
            $fatal(1, "lane count mismatch %0d/%0d",
                   issued_lane0, issued_lane1);
        $display("PASS horizontal token sequencer affine expansion");
        $finish;
    end

    initial begin
        #5000;
        $fatal(1, "horizontal token sequencer timeout pc=%0d", program_counter);
    end
endmodule

`default_nettype wire
