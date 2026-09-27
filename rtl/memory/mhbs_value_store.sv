`timescale 1ns/1ps
`default_nettype none
module mhbs_value_store #(parameter integer WIDTH=128, DEPTH=128, ADDRESS_BITS=7) (
    input wire clk,
    input wire write0, write1,
    input wire [ADDRESS_BITS-1:0] address0, address1,
    input wire [WIDTH-1:0] data0, data1,
    input wire [ADDRESS_BITS-1:0] read0, read1,
    output wire [WIDTH-1:0] value0, value1
);
    generate if(DEPTH==136) begin: compact
        // 128 main entries plus eight tail entries. Each parity bank retains
        // one write and one asynchronous read; no clock or latency change.
        genvar bank;
        wire [WIDTH-1:0] read_value[0:1];
        for(bank=0;bank<2;bank=bank+1) begin: banks
            (* ram_style="distributed" *) logic [WIDTH-1:0] main [0:63];
            (* ram_style="distributed" *) logic [WIDTH-1:0] tail [0:3];
            wire select0=write0 && address0[0]==bank;
            wire select1=write1 && address1[0]==bank;
            wire [7:0] wa=select0 ? address0 : address1;
            wire [WIDTH-1:0] wd=select0 ? data0 : data1;
            wire [7:0] ra=read0[0]==bank ? read0 : read1;
            always_ff @(posedge clk) begin
                if(select0 || select1) begin
                    if(!wa[7]) main[wa[6:1]]<=wd;
                    else if(wa<136) tail[wa[2:1]]<=wd;
                end
            end
            assign read_value[bank]=ra[7] ? tail[ra[2:1]] : main[ra[6:1]];
        end
        assign value0=read0[0] ? read_value[1] : read_value[0];
        assign value1=read0[0] ? read_value[0] : read_value[1];
    end else begin: regular
    localparam integer AW=$clog2(DEPTH/2);
    (* ram_style="distributed" *) logic [WIDTH-1:0] even_bank [0:DEPTH/2-1];
    (* ram_style="distributed" *) logic [WIDTH-1:0] odd_bank [0:DEPTH/2-1];
    wire even_select0=write0 && !address0[0];
    wire even_select1=write1 && !address1[0];
    wire odd_select0=write0 && address0[0];
    wire odd_select1=write1 && address1[0];
    wire [AW-1:0] even_write_address=even_select0 ? address0[AW:1] : address1[AW:1];
    wire [AW-1:0] odd_write_address=odd_select0 ? address0[AW:1] : address1[AW:1];
    wire [WIDTH-1:0] even_write_data=even_select0 ? data0 : data1;
    wire [WIDTH-1:0] odd_write_data=odd_select0 ? data0 : data1;
    always_ff @(posedge clk) begin
        if (even_select0 || even_select1) even_bank[even_write_address] <= even_write_data;
        if (odd_select0 || odd_select1) odd_bank[odd_write_address] <= odd_write_data;
    end
    // Readers request adjacent values; one read per parity bank avoids
    // duplicating distributed RAM for two independent read ports.
    wire [AW-1:0] even_read = read0[0] ? read1[AW:1] : read0[AW:1];
    wire [AW-1:0] odd_read = read0[0] ? read0[AW:1] : read1[AW:1];
    wire [WIDTH-1:0] even_value=even_bank[even_read], odd_value=odd_bank[odd_read];
    assign value0 = read0[0] ? odd_value : even_value;
    assign value1 = read0[0] ? even_value : odd_value;
    end endgenerate
endmodule
`default_nettype wire
