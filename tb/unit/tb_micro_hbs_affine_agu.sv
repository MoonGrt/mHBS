`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_affine_agu;
    logic clk = 1'b0, rst_n = 1'b0, req_valid = 1'b0;
    wire req_ready, rsp_valid;
    logic [31:0] req_base = 0, req_term0_value = 0, req_term1_value = 0;
    logic req_use_term0 = 0, req_use_term1 = 0;
    logic [15:0] req_term0_scale = 0, req_term1_scale = 0;
    logic [15:0] req_span_words = 0;
    logic rsp_ready = 0;
    wire rsp_error;
    wire [15:0] rsp_error_code;
    wire [15:0] rsp_address, rsp_last_address;
    wire [31:0] accepted_requests, completed_responses, error_responses;
    integer timeout;

    always #5 clk = ~clk;
    micro_hbs_affine_agu #(.SCRATCH_WORDS(1024), .ADDRESS_WIDTH(16)) dut (.*);

    task automatic issue(input [31:0] base,
                         input use0, input [31:0] value0, input [15:0] scale0,
                         input use1, input [31:0] value1, input [15:0] scale1,
                         input [15:0] span);
        begin
            while (!req_ready) @(negedge clk);
            req_base=base; req_use_term0=use0; req_term0_value=value0;
            req_term0_scale=scale0; req_use_term1=use1;
            req_term1_value=value1; req_term1_scale=scale1;
            req_span_words=span; req_valid=1;
            @(negedge clk); req_valid=0;
            timeout=0;
            while (!rsp_valid && timeout < 100) begin
                @(negedge clk); timeout=timeout+1;
            end
            if (!rsp_valid) $fatal(1, "affine AGU timeout");
        end
    endtask

    task automatic consume;
        begin
            rsp_ready=1; @(negedge clk); rsp_ready=0; @(negedge clk);
        end
    endtask

    initial begin
        repeat (3) @(negedge clk); rst_n=1;
        // XMSS lowered source: (R5=0 + R7=66) * 4, span four words.
        issue(0, 1, 0, 4, 1, 66, 4, 4);
        if (rsp_error || rsp_address != 264 || rsp_last_address != 267)
            $fatal(1, "XMSS source affine result mismatch");
        repeat (3) begin
            @(negedge clk);
            if (!rsp_valid || rsp_address != 264 || req_ready)
                $fatal(1, "response backpressure instability");
        end
        consume();

        // XMSS lowered destination: (R6=67 + R3=33) * 4.
        issue(0, 1, 67, 4, 1, 33, 4, 4);
        if (rsp_error || rsp_address != 400 || rsp_last_address != 403)
            $fatal(1, "XMSS destination affine result mismatch");
        consume();

        // v1-equivalent single indexed term.
        issue(10, 0, 0, 0, 1, 3, 1, 2);
        if (rsp_error || rsp_address != 13 || rsp_last_address != 14)
            $fatal(1, "single-term affine result mismatch");
        consume();

        issue(1000, 1, 7, 4, 0, 0, 0, 1);
        if (!rsp_error || rsp_error_code != 16'h0312 || rsp_address != 0)
            $fatal(1, "bounds failure not fail-closed");
        consume();
        issue(0, 0, 0, 0, 0, 0, 0, 0);
        if (!rsp_error || rsp_error_code != 16'h0311)
            $fatal(1, "zero span not rejected");
        consume();

        if (accepted_requests != 5 || completed_responses != 5
            || error_responses != 2)
            $fatal(1, "counter mismatch");
        $display("PASS two-term serial affine AGU: XMSS v2 bindings, bounds, backpressure, counters");
        $finish;
    end
endmodule

`default_nettype wire
