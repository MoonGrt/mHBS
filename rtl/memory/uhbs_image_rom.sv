`timescale 1ns/1ps
`default_nettype none
// Independent immutable ROM, asynchronous read. Fixed physical cells in synthesis;
// initialization is patched after implementation, never a processor specialization.
module uhbs_image_rom #(
    parameter integer WIDTH=128, ADDRESS_BITS=6, PORTS=1, PACKING=0,
    parameter INIT_FILE=""
)(
    input wire clk, input wire [PORTS*ADDRESS_BITS-1:0] addresses,
    output wire [PORTS*WIDTH-1:0] data
);
`ifdef SYNTHESIS
    localparam integer PHYSICAL_WIDTH=PACKING==1 ? 64 : WIDTH;
    localparam integer PHYSICAL_ADDRESS_BITS=PACKING==2 ? 6 : ADDRESS_BITS;
    function automatic [6:0] descriptor_location(input [6:0] address);
        begin
            descriptor_location=0;
            if(address<=52 && address!=39) descriptor_location={1'b1,address[5:0]};
            else case(address)
                64:descriptor_location={1'b1,6'd39};
                65:descriptor_location={1'b1,6'd53};
                66:descriptor_location={1'b1,6'd54};
                67:descriptor_location={1'b1,6'd55};
                68:descriptor_location={1'b1,6'd56};
                69:descriptor_location={1'b1,6'd57};
                70:descriptor_location={1'b1,6'd58};
                71:descriptor_location={1'b1,6'd59};
                80:descriptor_location={1'b1,6'd60};
                81:descriptor_location={1'b1,6'd61};
                82:descriptor_location={1'b1,6'd62};
                84:descriptor_location={1'b1,6'd63};
                default:begin end
            endcase
        end
    endfunction
    genvar p,b;
    generate for(p=0;p<PORTS;p=p+1) begin: port_bank
        wire [PHYSICAL_WIDTH-1:0] physical_data;
        wire [PHYSICAL_ADDRESS_BITS-1:0] physical_address;
        wire [6:0] location=descriptor_location(addresses[p*ADDRESS_BITS +:ADDRESS_BITS]);
        if(PACKING==2) assign physical_address=location[5:0];
        else assign physical_address=addresses[p*ADDRESS_BITS +:ADDRESS_BITS];
        if(PACKING==1) begin: expand_template
            wire [127:0] expanded={physical_data[63:60],physical_data[59:52],physical_data[51:44],
                physical_data[43],1'b0,physical_data[42:40],3'b0,physical_data[39:16],
                24'd0,48'd0,physical_data[15],3'b0};
            // Corrupt reserved physical bits remain visible to Boot validation.
            assign data[p*WIDTH +:WIDTH]=expanded | {(|physical_data[14:0]),127'd0};
        end else if(PACKING==2) assign data[p*WIDTH +:WIDTH]=location[6] ? physical_data : 64'd0;
        else assign data[p*WIDTH +:WIDTH]=physical_data;
        for(b=0;b<PHYSICAL_WIDTH;b=b+1) begin: bit_cell
            if(PHYSICAL_ADDRESS_BITS==6) begin: depth64
                (* DONT_TOUCH="yes" *) RAM64X1S #(.INIT(64'h6996966996696996)) rom (
                    .O(physical_data[b]),.A0(physical_address[0]),.A1(physical_address[1]),
                    .A2(physical_address[2]),.A3(physical_address[3]),.A4(physical_address[4]),.A5(physical_address[5]),
                    .D(1'b0),.WE(1'b0),.WCLK(clk));
            end else begin: depth128
                (* DONT_TOUCH="yes" *) RAM128X1S #(.INIT(128'h96696996699696696996966996696996)) rom (
                    .O(physical_data[b]),.A0(physical_address[0]),.A1(physical_address[1]),
                    .A2(physical_address[2]),.A3(physical_address[3]),.A4(physical_address[4]),.A5(physical_address[5]),.A6(physical_address[6]),
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
