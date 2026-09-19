`timescale 1ns/1ps
module tb_micro_hbs_byte_output_packer;
    logic clk = 0, rst_n = 0, clear = 0;
    logic in_valid = 0, in_last = 0, out_ready = 1;
    logic [7:0] in_byte = 0;
    wire in_ready, out_valid, out_last, idle;
    wire [63:0] out_data;
    wire [7:0] out_keep;
    integer index, words;

    always #5 clk = ~clk;
    micro_hbs_byte_output_packer dut (.*);

    always @(posedge clk) begin
        if (rst_n && out_valid && out_ready) begin
            if (words == 0 && (out_data !== 64'h0706050403020100
                              || out_keep !== 8'hff || out_last))
                $fatal(1, "full output word mismatch");
            if (words == 1 && (out_data[31:0] !== 32'h0b0a0908
                              || out_keep !== 8'h0f || !out_last))
                $fatal(1, "partial output word mismatch");
            words = words + 1;
        end
    end

    initial begin
        words = 0;
        repeat (3) @(posedge clk);
        rst_n <= 1;
        @(posedge clk);
        for (index = 0; index < 12; index = index + 1) begin
            @(negedge clk);
            while (!in_ready) @(negedge clk);
            in_valid = 1;
            in_byte = index;
            in_last = index == 11;
            @(posedge clk);
            @(negedge clk);
            in_valid = 0;
            in_last = 0;
        end
        while (!idle || words != 2) @(posedge clk);
        $display("BYTE_OUTPUT_PACKER_PASS");
        $finish;
    end
endmodule
