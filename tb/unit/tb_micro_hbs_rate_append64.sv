`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_rate_append64;
    logic [7:0] component_kind;
    logic [7:0] component_remaining;
    logic [31:0] component_immediate;
    logic [63:0] source_a_word;
    logic [63:0] source_b_word;
    logic [2:0] source_byte_index;
    logic [7:0] rate_fill;
    wire [63:0] append_data;
    wire [3:0] append_bytes;

    micro_hbs_rate_append64 dut (.*);

    task automatic expect_append(
        input [3:0] expected_bytes,
        input [63:0] expected_data
    );
        begin
            #1;
            if (append_bytes !== expected_bytes
                || append_data !== expected_data)
                $fatal(1,
                    "append mismatch bytes=%0d/%0d data=%016h/%016h",
                    append_bytes, expected_bytes,
                    append_data, expected_data);
        end
    endtask

    initial begin
        component_kind = 8'h01;
        component_remaining = 8'd4;
        component_immediate = 32'h11223344;
        source_a_word = 64'h0706050403020100;
        source_b_word = 64'hf0f0f0f0f0f0f0f0;
        source_byte_index = 3'd0;
        rate_fill = 8'd0;
        expect_append(4, 64'h0000000044332211);

        component_kind = 8'h04;
        component_remaining = 8'd12;
        expect_append(8, 64'h0706050403020100);

        source_byte_index = 3'd3;
        component_remaining = 8'd7;
        expect_append(5, 64'h0000000706050403);

        component_kind = 8'h05;
        source_byte_index = 3'd0;
        component_remaining = 8'd8;
        expect_append(8, 64'hf7f6f5f4f3f2f1f0);

        component_kind = 8'h02;
        component_remaining = 8'd10;
        rate_fill = 8'd132;
        expect_append(4, 64'h0000000000000000);

        component_kind = 8'h01;
        component_remaining = 8'd4;
        rate_fill = 8'd134;
        expect_append(2, 64'h0000000000002211);

        component_remaining = 8'd2;
        component_immediate = 32'h11223344;
        rate_fill = 8'd0;
        expect_append(2, 64'h0000000000004433);

        $display("PASS rate-wide 64-bit append selection");
        $finish;
    end
endmodule

`default_nettype wire
