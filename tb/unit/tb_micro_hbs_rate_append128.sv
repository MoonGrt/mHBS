`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_rate_append128;
    logic [7:0] component_kind;
    logic [7:0] component_remaining;
    logic [31:0] component_immediate;
    logic [127:0] source_a_data, source_b_data;
    logic [4:0] source_window_bytes;
    logic [3:0] source_byte_index;
    logic [7:0] rate_fill;
    wire [127:0] append_data;
    wire [4:0] append_bytes;

    micro_hbs_rate_append128 dut (.*);

    initial begin
        component_kind = 8'h04;
        component_remaining = 8'd16;
        component_immediate = '0;
        source_a_data = 128'hffeeddccbbaa9988_7766554433221100;
        source_b_data = '0;
        source_window_bytes = 5'd16;
        source_byte_index = '0;
        rate_fill = '0;
        #1;
        if (append_bytes != 16 || append_data != source_a_data)
            $fatal(1, "16-byte Scratch append failed");

        rate_fill = 8'd130;
        #1;
        if (append_bytes != 6
            || append_data[47:0] != 48'h554433221100)
            $fatal(1, "rate-boundary clamp failed");

        component_kind = 8'h05;
        component_remaining = 8'd8;
        source_window_bytes = 5'd8;
        source_a_data = {64'b0, 64'h0123456789abcdef};
        source_b_data = {64'b0, 64'hffff0000ffff0000};
        rate_fill = 0;
        #1;
        if (append_bytes != 8
            || append_data[63:0] != 64'hfedc45677654cdef)
            $fatal(1, "XOR append failed");

        component_kind = 8'h03;
        component_remaining = 8'd4;
        component_immediate = 32'h01020304;
        #1;
        if (append_bytes != 4 || append_data[31:0] != 32'h04030201)
            $fatal(1, "immediate byte order failed");

        $display("PASS 128-bit rate append");
        $finish;
    end
endmodule

`default_nettype wire
