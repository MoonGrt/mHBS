`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_agu;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic req_valid = 1'b0;
    wire req_ready;
    logic [31:0] req_base = '0;
    logic req_use_base_reg = 1'b0;
    logic [31:0] req_base_reg_value = '0;
    logic req_use_index = 1'b0;
    logic [31:0] req_index_value = '0;
    logic [15:0] req_stride = '0;
    logic [15:0] req_span_words = '0;
    wire rsp_valid;
    logic rsp_ready = 1'b0;
    wire rsp_error;
    wire [15:0] rsp_error_code;
    wire [15:0] rsp_address;
    wire [15:0] rsp_last_address;
    wire [31:0] accepted_requests, completed_responses, error_responses;

    integer timeout;
    logic [15:0] held_address, held_last;
    logic held_error;
    logic [15:0] held_code;

    always #5 clk = ~clk;

    micro_hbs_agu #(
        .SCRATCH_WORDS(512),
        .ADDRESS_WIDTH(16)
    ) dut (.*);

    task automatic issue;
        input [31:0] base_value;
        input use_base_reg_value;
        input [31:0] base_reg_value;
        input use_index_value;
        input [31:0] index_value;
        input [15:0] stride_value;
        input [15:0] span_value;
        begin
            @(negedge clk);
            if (!req_ready) $fatal(1, "request unexpectedly backpressured");
            req_base = base_value;
            req_use_base_reg = use_base_reg_value;
            req_base_reg_value = base_reg_value;
            req_use_index = use_index_value;
            req_index_value = index_value;
            req_stride = stride_value;
            req_span_words = span_value;
            req_valid = 1'b1;
            @(negedge clk);
            req_valid = 1'b0;
        end
    endtask

    task automatic await_response;
        input expected_error;
        input [15:0] expected_code;
        input [15:0] expected_address;
        input [15:0] expected_last;
        begin
            timeout = 0;
            while (!rsp_valid && timeout < 40) begin
                @(negedge clk);
                timeout = timeout + 1;
            end
            if (!rsp_valid) $fatal(1, "response timeout");
            if (rsp_error !== expected_error || rsp_error_code !== expected_code)
                $fatal(1, "response status error=%0d code=%h", rsp_error, rsp_error_code);
            if (!expected_error
                && (rsp_address !== expected_address
                    || rsp_last_address !== expected_last))
                $fatal(1, "address got=%0d..%0d expected=%0d..%0d",
                       rsp_address, rsp_last_address, expected_address, expected_last);
            held_address = rsp_address;
            held_last = rsp_last_address;
            held_error = rsp_error;
            held_code = rsp_error_code;
            // Hold response back for three cycles.  Payload and status must be stable.
            repeat (3) begin
                @(negedge clk);
                if (!rsp_valid || rsp_address !== held_address
                    || rsp_last_address !== held_last || rsp_error !== held_error
                    || rsp_error_code !== held_code)
                    $fatal(1, "response changed under backpressure");
                if (req_ready) $fatal(1, "accepted another request with pending response");
            end
            rsp_ready = 1'b1;
            @(negedge clk);
            rsp_ready = 1'b0;
            if (!req_ready || rsp_valid)
                $fatal(1, "response handshake did not return to idle");
        end
    endtask

    initial begin
        repeat (3) @(negedge clk);
        rst_n = 1'b1;

        issue(32'd10, 1'b0, 0, 1'b0, 0, 0, 16'd4);
        await_response(1'b0, 16'h0000, 16'd10, 16'd13);

        // Existing descriptor form: base + base_reg + index * stride.
        issue(32'd1, 1'b1, 32'd6, 1'b1, 32'd9, 16'd7, 16'd4);
        // 1 + 6 + 9*7 = 70; four words occupy 70..73.
        await_response(1'b0, 16'h0000, 16'd70, 16'd73);

        issue(32'd511, 1'b0, 0, 1'b0, 0, 0, 16'd1);
        await_response(1'b0, 16'h0000, 16'd511, 16'd511);

        issue(32'd511, 1'b0, 0, 1'b0, 0, 0, 16'd2);
        await_response(1'b1, 16'h0302, 0, 0);

        issue(32'd0, 1'b0, 0, 1'b0, 0, 0, 16'd0);
        await_response(1'b1, 16'h0301, 0, 0);

        // A wide product cannot wrap into the legal Scratchpad window.
        issue(32'd0, 1'b0, 0, 1'b1, 32'hffff_ffff, 16'hffff, 16'd1);
        await_response(1'b1, 16'h0302, 0, 0);

        if (accepted_requests != 6 || completed_responses != 6
            || error_responses != 3)
            $fatal(1, "counter mismatch accepted=%0d completed=%0d errors=%0d",
                   accepted_requests, completed_responses, error_responses);

        $display("PASS bounded serial AGU base/base-reg/index-stride/span/backpressure/errors");
        $finish;
    end
endmodule

`default_nettype wire
