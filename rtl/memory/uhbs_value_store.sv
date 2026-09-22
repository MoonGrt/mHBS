`timescale 1ns/1ps
`default_nettype none
module uhbs_value_store #(parameter integer WIDTH=128, DEPTH=128) (
    input wire clk,
    input wire write0, write1,
    input wire [6:0] address0, address1,
    input wire [WIDTH-1:0] data0, data1,
    input wire [6:0] read0, read1,
    output wire [WIDTH-1:0] value0, value1
);
    (* ram_style="distributed" *) logic [WIDTH-1:0] even_bank [0:DEPTH/2-1];
    (* ram_style="distributed" *) logic [WIDTH-1:0] odd_bank [0:DEPTH/2-1];
    always_ff @(posedge clk) begin
        if (write0 && !address0[0]) even_bank[address0[6:1]] <= data0;
        else if (write1 && !address1[0]) even_bank[address1[6:1]] <= data1;
        if (write0 && address0[0]) odd_bank[address0[6:1]] <= data0;
        else if (write1 && address1[0]) odd_bank[address1[6:1]] <= data1;
    end
    // Readers request adjacent values; one read per parity bank avoids
    // duplicating distributed RAM for two independent read ports.
    localparam integer AW=$clog2(DEPTH/2);
    wire [AW-1:0] even_read = read0[0] ? read1[AW:1] : read0[AW:1];
    wire [AW-1:0] odd_read = read0[0] ? read0[AW:1] : read1[AW:1];
    wire [WIDTH-1:0] even_value=even_bank[even_read], odd_value=odd_bank[odd_read];
    assign value0 = read0[0] ? odd_value : even_value;
    assign value1 = read0[0] ? even_value : odd_value;
endmodule
`default_nettype wire
