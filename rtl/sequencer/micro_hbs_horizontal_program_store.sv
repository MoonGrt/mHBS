`timescale 1ns/1ps
`default_nettype none

module micro_hbs_horizontal_program_store #(
    parameter integer PROGRAM_WORDS = 1024,
    parameter integer ADDRESS_WIDTH = $clog2(PROGRAM_WORDS)
) (
    input  wire                     clk,
    input  wire                     write_enable,
    input  wire [ADDRESS_WIDTH-1:0] write_address,
    input  wire [127:0]             write_data,
    input  wire [ADDRESS_WIDTH-1:0] read_address,
    output logic [127:0]            read_data
);
    (* ram_style = "block" *) logic [127:0] memory [0:PROGRAM_WORDS-1];

    always_ff @(posedge clk) begin
        if (write_enable)
            memory[write_address] <= write_data;
        read_data <= memory[read_address];
    end
endmodule

`default_nettype wire
