`timescale 1ns/1ps
`default_nettype none
// FORS roots: one writer and two adjacent asynchronous readers.
module mhbs_root_store (
    input wire clk,write,
    input wire [5:0] address,read0,read1,
    input wire [255:0] data,
    output wire [255:0] value0,value1
);
    (* ram_style="distributed" *) logic [255:0] even_bank[0:31];
    (* ram_style="distributed" *) logic [255:0] odd_bank[0:31];
    always_ff @(posedge clk) begin
        if(write && !address[0]) even_bank[address[5:1]]<=data;
        if(write && address[0]) odd_bank[address[5:1]]<=data;
    end
    wire [255:0] even_value=even_bank[read0[0] ? read1[5:1] : read0[5:1]];
    wire [255:0] odd_value=odd_bank[read0[0] ? read0[5:1] : read1[5:1]];
    assign value0=read0[0] ? odd_value : even_value;
    assign value1=read0[0] ? even_value : odd_value;
endmodule
`default_nettype wire
