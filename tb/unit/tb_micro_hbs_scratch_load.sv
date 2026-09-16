`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_scratch_load;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic cmd_valid = 1'b0;
    wire cmd_ready;
    logic [5:0] cmd_source_address = '0;
    logic [7:0] cmd_destination_reg = '0;
    logic cmd_high_word = 1'b0;
    wire rsp_valid;
    logic rsp_ready = 1'b0;
    wire rsp_error;
    wire [15:0] rsp_error_code;
    wire rsp_reg_write;
    wire [7:0] rsp_reg_index;
    wire [31:0] rsp_reg_value;

    wire load_req_valid, load_req_ready;
    wire [5:0] load_req_address;
    wire sp_rsp_valid;
    wire [63:0] sp_rsp_data;
    wire sp_error;
    wire [31:0] accepted_commands, completed_responses, error_responses;

    logic host_mode = 1'b1;
    logic host_valid = 1'b0;
    logic [5:0] host_address = '0;
    logic [63:0] host_data = '0;
    wire sp_req_valid = host_mode ? host_valid : load_req_valid;
    wire sp_req_write = host_mode;
    wire [5:0] sp_req_address = host_mode ? host_address : load_req_address;
    wire [63:0] sp_req_data = host_data;
    wire sp_req_ready;
    assign load_req_ready = !host_mode && sp_req_ready;

    integer timeout;

    always #5 clk = ~clk;

    micro_hbs_scratch_load #(.SCRATCH_WORDS(64), .ADDRESS_WIDTH(6)) dut (
        .clk, .rst_n, .cmd_valid, .cmd_ready, .cmd_source_address,
        .cmd_destination_reg, .cmd_high_word, .rsp_valid, .rsp_ready,
        .rsp_error, .rsp_error_code, .rsp_reg_write, .rsp_reg_index,
        .rsp_reg_value, .scratch_request_valid(load_req_valid),
        .scratch_request_ready(load_req_ready),
        .scratch_request_address(load_req_address),
        .scratch_response_valid(sp_rsp_valid),
        .scratch_response_data(sp_rsp_data),
        .scratch_response_error(sp_error), .accepted_commands,
        .completed_responses, .error_responses
    );

    micro_hbs_scratchpad64 #(.WORDS(64), .ADDRESS_WIDTH(6)) scratch (
        .clk, .rst_n, .request_valid(sp_req_valid),
        .request_ready(sp_req_ready), .request_write(sp_req_write),
        .request_address(sp_req_address), .request_write_data(sp_req_data),
        .response_valid(sp_rsp_valid), .response_read_data(sp_rsp_data),
        .bounds_error(sp_error), .scrub_start(1'b0), .scrub_busy(),
        .scrub_done()
    );

    task automatic host_store(input [5:0] address, input [63:0] value);
        begin
            @(negedge clk);
            host_address = address;
            host_data = value;
            host_valid = 1'b1;
            @(negedge clk);
            host_valid = 1'b0;
        end
    endtask

    task automatic issue(input [5:0] address, input [7:0] destination,
                         input high_word);
        begin
            host_mode = 1'b0;
            @(negedge clk);
            if (!cmd_ready) $fatal(1, "LOAD not ready");
            cmd_source_address = address;
            cmd_destination_reg = destination;
            cmd_high_word = high_word;
            cmd_valid = 1'b1;
            @(negedge clk);
            cmd_valid = 1'b0;
        end
    endtask

    task automatic finish(input expected_error, input [15:0] expected_code,
                          input expected_write, input [7:0] expected_reg,
                          input [31:0] expected_value);
        begin
            timeout = 0;
            while (!rsp_valid && timeout < 20) begin
                @(negedge clk);
                timeout = timeout + 1;
            end
            if (!rsp_valid || rsp_error !== expected_error
                || rsp_error_code !== expected_code
                || rsp_reg_write !== expected_write
                || (expected_write && (rsp_reg_index !== expected_reg
                    || rsp_reg_value !== expected_value)))
                $fatal(1, "LOAD response err=%b code=%h wr=%b idx=%0d value=%h",
                       rsp_error, rsp_error_code, rsp_reg_write,
                       rsp_reg_index, rsp_reg_value);
            repeat (2) begin
                @(negedge clk);
                if (!rsp_valid || cmd_ready)
                    $fatal(1, "LOAD response unstable under backpressure");
            end
            rsp_ready = 1'b1;
            @(negedge clk);
            rsp_ready = 1'b0;
            if (!cmd_ready || rsp_valid)
                $fatal(1, "LOAD response did not retire");
            host_mode = 1'b1;
        end
    endtask

    initial begin
        repeat (3) @(negedge clk);
        rst_n = 1'b1;
        host_store(5, 64'h89ab_cdef_0123_4567);

        issue(5, 2, 1'b0);
        finish(1'b0, 16'h0000, 1'b1, 2, 32'h0123_4567);
        issue(5, 7, 1'b1);
        finish(1'b0, 16'h0000, 1'b1, 7, 32'h89ab_cdef);
        issue(5, 8, 1'b0);
        finish(1'b1, 16'h0602, 1'b0, 0, 0);

        // ADDRESS_WIDTH can encode 0..63, so inject a downstream error to
        // exercise response propagation independently of the static precheck.
        host_mode = 1'b0;
        force sp_error = 1'b1;
        issue(6, 1, 1'b0);
        finish(1'b1, 16'h0603, 1'b0, 0, 0);
        release sp_error;

        if (accepted_commands != 4 || completed_responses != 4
            || error_responses != 2)
            $fatal(1, "LOAD counters cmd=%0d done=%0d err=%0d",
                   accepted_commands, completed_responses, error_responses);

        $display("PASS Scratchpad LOAD low/high register writeback, backpressure and errors");
        $finish;
    end
endmodule

`default_nettype wire
