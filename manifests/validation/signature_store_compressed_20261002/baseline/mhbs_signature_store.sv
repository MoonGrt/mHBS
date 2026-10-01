`timescale 1ns/1ps
`default_nettype none
// One output node per word: no packing or backpressure on the execution core.
// 1558 nodes covers the largest supported signature (SHAKE-256f).
module mhbs_signature_store (
    input wire clk,rst,finish,abort,
    input wire write_valid,input wire [255:0] write_data,input wire [5:0] write_bytes,
    input wire read_enable,input wire [10:0] read_address,
    output logic read_valid,output logic [255:0] read_data,
    output logic [5:0] node_bytes,
    output wire complete,output logic error,
    output logic [10:0] nodes,output logic [15:0] length
);
    (* ram_style="block" *) logic [255:0] memory[0:1557];
    wire size_ok=(write_bytes==16 || write_bytes==24 || write_bytes==32) &&
                 (nodes==0 || write_bytes==node_bytes);
    wire writing=write_valid && !rst && !finish && !abort && !error;
    wire reading=read_enable && complete && read_address<nodes;
    assign complete=finish && !rst && !abort && !error && nodes!=0;
    // Do not reset the array or data register: infer synchronous block RAM.
    always_ff @(posedge clk) begin
        if(writing && nodes<1558 && size_ok) memory[nodes]<=write_data;
        if(reading) read_data<=memory[read_address];
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
