`timescale 1ns/1ps
`default_nettype none
// One output node per word: no packing or backpressure on the execution core.
// 1558 nodes covers the largest supported signature (SHAKE-256f).
module signature (
    input wire clk,rst,finish,abort,
    input wire write_valid,input wire [255:0] write_data,input wire [5:0] write_bytes,
    input wire read_enable,input wire [10:0] read_address,
    output logic read_valid,output logic [255:0] read_data,
    output logic [5:0] node_bytes,
    output wire complete,output logic error,
    output logic [10:0] nodes,output logic [15:0] length
);
    // Split the address space to avoid rounding all 1558 words up to 2048.
    (* ram_style="block" *) logic [255:0] main_memory[0:1023];
    (* ram_style="block" *) logic [255:0] middle_memory[0:511];
    (* ram_style="distributed" *) logic [255:0] tail_memory[0:21];
    logic [255:0] main_data,middle_data,tail_data;
    logic [1:0] read_bank;
    wire size_ok=(write_bytes==16 || write_bytes==24 || write_bytes==32) &&
                 (nodes==0 || write_bytes==node_bytes);
    wire writing=write_valid && !rst && !finish && !abort && !error;
    wire reading=read_enable && complete && read_address<nodes;
    assign complete=finish && !rst && !abort && !error && nodes!=0;
    // Do not reset the array or data register: infer synchronous block RAM.
    always_ff @(posedge clk) begin
        if(writing && nodes<1558 && size_ok) begin
            if(!nodes[10]) main_memory[nodes[9:0]]<=write_data;
            else if(!nodes[9]) middle_memory[nodes[8:0]]<=write_data;
            else tail_memory[nodes[4:0]]<=write_data;
        end
        if(reading) begin
            if(!read_address[10]) begin
                main_data<=main_memory[read_address[9:0]];read_bank<=0;
            end else if(!read_address[9]) begin
                middle_data<=middle_memory[read_address[8:0]];read_bank<=1;
            end else begin
                tail_data<=tail_memory[read_address[4:0]];read_bank<=2;
            end
        end
    end
    always_comb begin
        case(read_bank)
            0:read_data=main_data;
            1:read_data=middle_data;
            default:read_data=tail_data;
        endcase
    end
    always_ff @(posedge clk) begin
        if(rst) begin
            nodes<=0;length<=0;node_bytes<=0;error<=0;read_valid<=0;
        end else begin
            read_valid<=reading;
            if(abort) error<=1;
            if(writing) begin
                if(nodes>=1558 || !size_ok) error<=1;
                else begin
                    nodes<=nodes+1'b1;
                    length<=length+{10'd0,write_bytes};
                    node_bytes<=write_bytes;
                end
            end
        end
    end
endmodule
`default_nettype wire
