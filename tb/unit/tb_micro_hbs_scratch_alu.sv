`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_scratch_alu;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic cmd_valid = 1'b0;
    wire cmd_ready;
    logic [5:0] cmd_source_a = '0;
    logic [5:0] cmd_destination = '0;
    logic [15:0] cmd_word_count = '0;
    wire rsp_valid;
    logic rsp_ready = 1'b0;
    wire rsp_error;
    wire [15:0] rsp_error_code;

    wire alu_request_valid, alu_request_write;
    wire alu_request_ready;
    wire [5:0] alu_request_address;
    wire [63:0] alu_request_write_data;
    wire scratch_response_valid;
    wire [63:0] scratch_response_read_data;
    wire scratch_bounds_error;
    wire [31:0] accepted_commands, completed_responses, error_responses;
    wire [31:0] scratch_reads, scratch_writes;

    logic host_mode = 1'b1;
    logic host_valid = 1'b0;
    logic host_write = 1'b0;
    logic [5:0] host_address = '0;
    logic [63:0] host_write_data = '0;
    wire scratch_request_ready;
    wire scratch_request_valid = host_mode ? host_valid : alu_request_valid;
    wire scratch_request_write = host_mode ? host_write : alu_request_write;
    wire [5:0] scratch_request_address = host_mode ? host_address : alu_request_address;
    wire [63:0] scratch_request_write_data = host_mode
        ? host_write_data : alu_request_write_data;
    assign alu_request_ready = !host_mode && scratch_request_ready;

    wire scrub_busy, scrub_done;
    integer timeout;
    logic held_error;
    logic [15:0] held_code;

    always #5 clk = ~clk;

    micro_hbs_scratch_alu #(.WORDS(64), .ADDRESS_WIDTH(6)) dut (
        .clk, .rst_n, .cmd_valid, .cmd_ready,
        .cmd_source_a, .cmd_destination, .cmd_word_count,
        .rsp_valid, .rsp_ready, .rsp_error, .rsp_error_code,
        .scratch_request_valid(alu_request_valid),
        .scratch_request_ready(alu_request_ready),
        .scratch_request_write(alu_request_write),
        .scratch_request_address(alu_request_address),
        .scratch_request_write_data(alu_request_write_data),
        .scratch_response_valid, .scratch_response_read_data,
        .scratch_bounds_error, .accepted_commands, .completed_responses,
        .error_responses, .scratch_reads, .scratch_writes
    );

    micro_hbs_scratchpad64 #(.WORDS(64), .ADDRESS_WIDTH(6)) scratchpad (
        .clk, .rst_n,
        .request_valid(scratch_request_valid),
        .request_ready(scratch_request_ready),
        .request_write(scratch_request_write),
        .request_address(scratch_request_address),
        .request_write_data(scratch_request_write_data),
        .response_valid(scratch_response_valid),
        .response_read_data(scratch_response_read_data),
        .bounds_error(scratch_bounds_error),
        .scrub_start(1'b0), .scrub_busy, .scrub_done
    );

    task automatic host_store;
        input [5:0] address;
        input [63:0] value;
        begin
            @(negedge clk);
            host_address = address;
            host_write_data = value;
            host_write = 1'b1;
            host_valid = 1'b1;
            @(negedge clk);
            host_valid = 1'b0;
        end
    endtask

    task automatic host_load_check;
        input [5:0] address;
        input [63:0] expected;
        begin
            @(negedge clk);
            host_address = address;
            host_write = 1'b0;
            host_valid = 1'b1;
            @(negedge clk);
            host_valid = 1'b0;
            timeout = 0;
            while (!scratch_response_valid && timeout < 5) begin
                @(negedge clk);
                timeout = timeout + 1;
            end
            if (!scratch_response_valid || scratch_response_read_data !== expected)
                $fatal(1, "scratch[%0d]=%h expected=%h",
                       address, scratch_response_read_data, expected);
        end
    endtask

    task automatic issue;
        input [5:0] source_a;
        input [5:0] destination;
        input [15:0] words;
        begin
            host_mode = 1'b0;
            @(negedge clk);
            if (!cmd_ready) $fatal(1, "command not ready");
            cmd_source_a = source_a;
            cmd_destination = destination;
            cmd_word_count = words;
            cmd_valid = 1'b1;
            @(negedge clk);
            cmd_valid = 1'b0;
        end
    endtask

    task automatic finish_response;
        input expected_error;
        input [15:0] expected_code;
        begin
            timeout = 0;
            while (!rsp_valid && timeout < 100) begin
                @(negedge clk);
                timeout = timeout + 1;
            end
            if (!rsp_valid || rsp_error !== expected_error
                || rsp_error_code !== expected_code)
                $fatal(1, "response error=%0d code=%h", rsp_error, rsp_error_code);
            held_error = rsp_error;
            held_code = rsp_error_code;
            repeat (2) begin
                @(negedge clk);
                if (!rsp_valid || rsp_error !== held_error
                    || rsp_error_code !== held_code || cmd_ready)
                    $fatal(1, "response changed under backpressure");
            end
            rsp_ready = 1'b1;
            @(negedge clk);
            rsp_ready = 1'b0;
            if (!cmd_ready || rsp_valid) $fatal(1, "response did not retire");
            host_mode = 1'b1;
        end
    endtask

    initial begin
        repeat (3) @(negedge clk);
        rst_n = 1'b1;

        host_store(10, 64'h0123_4567_89ab_cdef);
        host_store(11, 64'h1111_2222_3333_4444);
        host_store(12, 64'hfeed_face_cafe_beef);
        issue(10, 20, 3);
        finish_response(1'b0, 16'h0000);
        host_load_check(20, 64'h0123_4567_89ab_cdef);
        host_load_check(21, 64'h1111_2222_3333_4444);
        host_load_check(22, 64'hfeed_face_cafe_beef);

        // All bounds are checked before the first read/write.
        issue(63, 50, 2);
        finish_response(1'b1, 16'h0403);
        issue(10, 63, 2);
        finish_response(1'b1, 16'h0403);
        issue(10, 20, 0);
        finish_response(1'b1, 16'h0402);
        // Large counts must not wrap in the command-time end calculation.
        issue(0, 0, 16'hffff);
        finish_response(1'b1, 16'h0403);

        if (accepted_commands != 5 || completed_responses != 5
            || error_responses != 4 || scratch_reads != 3
            || scratch_writes != 3)
            $fatal(1, "counter mismatch cmd=%0d done=%0d err=%0d rd=%0d wr=%0d",
                   accepted_commands, completed_responses, error_responses,
                   scratch_reads, scratch_writes);

        $display("PASS Scratchpad DATA_MOVE word engine range precheck/backpressure/counters");
        $finish;
    end
endmodule

`default_nettype wire
