`timescale 1ns/1ps
`default_nettype none
// Independent immutable ROM, asynchronous read. Fixed physical cells in synthesis;
// initialization is patched after implementation, never a processor specialization.
module uhbs_image_rom #(
    parameter integer WIDTH=128, ADDRESS_BITS=6, PORTS=1,
    parameter INIT_FILE=""
)(input wire clk, input wire [PORTS*ADDRESS_BITS-1:0] addresses,
  output wire [PORTS*WIDTH-1:0] data);
`ifdef SYNTHESIS
    genvar p,b;
    generate for(p=0;p<PORTS;p=p+1) begin: port_bank
        for(b=0;b<WIDTH;b=b+1) begin: bit_cell
            if(ADDRESS_BITS==6) begin: depth64
                (* DONT_TOUCH="yes" *) RAM64X1S #(.INIT(64'h6996966996696996)) rom (
                    .O(data[p*WIDTH+b]),.A0(addresses[p*6]),.A1(addresses[p*6+1]),
                    .A2(addresses[p*6+2]),.A3(addresses[p*6+3]),.A4(addresses[p*6+4]),.A5(addresses[p*6+5]),
                    .D(1'b0),.WE(1'b0),.WCLK(clk));
            end else begin: depth128
                (* DONT_TOUCH="yes" *) RAM128X1S #(.INIT(128'h96696996699696696996966996696996)) rom (
                    .O(data[p*WIDTH+b]),.A0(addresses[p*7]),.A1(addresses[p*7+1]),
                    .A2(addresses[p*7+2]),.A3(addresses[p*7+3]),.A4(addresses[p*7+4]),.A5(addresses[p*7+5]),.A6(addresses[p*7+6]),
                    .D(1'b0),.WE(1'b0),.WCLK(clk));
            end
        end
    end endgenerate
`else
    logic [WIDTH-1:0] memory [0:(1<<ADDRESS_BITS)-1];
    initial if(INIT_FILE!="") $readmemh(INIT_FILE,memory);
    genvar p;
    generate for(p=0;p<PORTS;p=p+1) begin: read_ports
        assign data[p*WIDTH +:WIDTH]=memory[addresses[p*ADDRESS_BITS +:ADDRESS_BITS]];
    end endgenerate
`endif
endmodule
`default_nettype wire
