`timescale 1ns / 1ps
`default_nettype none
// One producer per cycle; adjacent reads use one asynchronous port per parity
// bank. XMSS L-tree and unaligned LMS list absorption need both read values.
// verilog_format: off
module value #(
    parameter integer WIDTH=256, DEPTH=136, ADDRESS_BITS=8
) (
    input wire clk,write_enable,
    input wire [ADDRESS_BITS-1:0] write_address,
    input wire [WIDTH-1:0] write_data,
    input wire [ADDRESS_BITS-1:0] read0, read1,
    output wire [WIDTH-1:0] value0, value1
);
// verilog_format: on
    wire [WIDTH-1:0] bank_value[0:1];
    for (genvar bank = 0; bank < 2; bank = bank + 1) begin : banks
        wire we = write_enable && write_address[0] == bank;
        wire [ADDRESS_BITS-1:0] ra = read0[0] == bank ? read0 : read1;
        if (DEPTH == 136) begin : compact
            (* ram_style="distributed" *)logic [WIDTH-1:0] main[0:63];
            (* ram_style="distributed" *)logic [WIDTH-1:0] tail[ 0:3];
            always_ff @(posedge clk)
                if (we) begin
                    if (!write_address[7]) main[write_address[6:1]] <= write_data;
                    else if (write_address < 136) tail[write_address[2:1]] <= write_data;
                end
            assign bank_value[bank] = ra[7] ? tail[ra[2:1]] : main[ra[6:1]];
        end else begin : regular
            (* ram_style="distributed" *) logic [WIDTH-1:0] words[0:DEPTH/2-1];
            always_ff @(posedge clk) if (we) words[write_address[ADDRESS_BITS-1:1]] <= write_data;
            assign bank_value[bank] = words[ra[ADDRESS_BITS-1:1]];
        end
    end
    assign value0 = read0[0] ? bank_value[1] : bank_value[0];
    assign value1 = read0[0] ? bank_value[0] : bank_value[1];
endmodule
`default_nettype wire
