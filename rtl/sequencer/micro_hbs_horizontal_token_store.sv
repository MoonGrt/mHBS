`timescale 1ns/1ps
`default_nettype none

module micro_hbs_horizontal_token_store #(
    parameter integer PROGRAM_TOKENS = 3072,
    parameter integer ADDRESS_WIDTH = $clog2(PROGRAM_TOKENS)
) (
    input  wire                     clk,
    input  wire                     write_enable,
    input  wire [ADDRESS_WIDTH-1:0] write_address,
    input  wire [63:0]              write_data,
    input  wire [ADDRESS_WIDTH-1:0] read_address,
    output logic [63:0]              read_data
);
    (* ram_style = "block" *) logic [63:0] memory [0:PROGRAM_TOKENS-1];

    always_ff @(posedge clk) begin
        if (write_enable)
            memory[write_address] <= write_data;
        read_data <= memory[read_address];
    end
endmodule

`default_nettype wire
