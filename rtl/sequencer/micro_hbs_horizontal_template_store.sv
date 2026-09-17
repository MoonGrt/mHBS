`timescale 1ns/1ps
`default_nettype none

// 64 x 128 is deliberately distributed: consuming a RAMB36 for this small,
// wide table is less efficient than one LUTRAM bit per template output bit.
module micro_hbs_horizontal_template_store (
    input  wire         clk,
    input  wire         write_enable,
    input  wire [5:0]   write_address,
    input  wire [127:0] write_data,
    input  wire [5:0]   read_address,
    output wire [127:0] read_data
);
    (* ram_style = "distributed" *) logic [127:0] memory [0:63];

    always_ff @(posedge clk)
        if (write_enable)
            memory[write_address] <= write_data;

    assign read_data = memory[read_address];
endmodule

`default_nettype wire
