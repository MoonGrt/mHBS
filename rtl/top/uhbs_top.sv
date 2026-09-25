`timescale 1ns/1ps
`default_nettype none
module uhbs_top #(
    parameter integer LANES=2,UNROLL=2,
    parameter bit SWAP_PHYSICAL_LANES=0,
    parameter PROGRAM_INIT_FILE="manifests/experiments/unified_hbs_v4.1/slh_only/images/slh_128f/program.mem",
    parameter TEMPLATE_INIT_FILE="manifests/experiments/unified_hbs_v4.1/slh_only/images/slh_128f/template.mem",
    parameter DESCRIPTOR_INIT_FILE="manifests/experiments/unified_hbs_v4.1/slh_only/images/slh_128f/descriptor.mem"
)(
    input wire clk,rst,
    output wire busy,done,keygen_done,error,output wire [15:0] error_code,
    output wire [31:0] boot_cycles,keygen_cycles,sign_cycles,hash_count,permutation_count,
    output wire out_valid,output wire [63:0] out_data,output wire [7:0] out_keep,
    output wire out_last,result_kind
);
    (* ASYNC_REG="TRUE" *) logic [1:0] reset_sync;
    always_ff @(posedge clk or posedge rst) begin
        if(rst) reset_sync<=2'b11; else reset_sync<={reset_sync[0],1'b0};
    end
    wire rst_n=~reset_sync[1];
    wire [5:0] program_address,template_address;
    wire [127:0] program_data,template_data;
    wire [13:0] descriptor_addresses;
    wire [127:0] descriptor_data;
    uhbs_image_rom #(.WIDTH(128),.ADDRESS_BITS(6),.PORTS(1),.INIT_FILE(PROGRAM_INIT_FILE)) program_rom (
        .clk,.addresses(program_address),.data(program_data));
    uhbs_image_rom #(.WIDTH(128),.ADDRESS_BITS(6),.PORTS(1),.PACKING(1),.INIT_FILE(TEMPLATE_INIT_FILE)) template_rom (
        .clk,.addresses(template_address),.data(template_data));
    uhbs_image_rom #(.WIDTH(64),.ADDRESS_BITS(7),.PORTS(2),.INIT_FILE(DESCRIPTOR_INIT_FILE)) descriptor_rom (
        .clk,.addresses(descriptor_addresses),.data(descriptor_data));
    (* DONT_TOUCH="yes" *) uhbs_processor #(.LANES(LANES),.UNROLL(UNROLL),.SWAP_PHYSICAL_LANES(SWAP_PHYSICAL_LANES)) processor (
        .clk,.rst_n,.program_address,.program_data,.template_address,.template_data,
        .descriptor_addresses,.descriptor_data,.busy,.done,.keygen_done,.error,.error_code,
        .boot_cycles,.keygen_cycles,.sign_cycles,.hash_count,.permutation_count,
        .out_valid,.out_data,.out_keep,.out_last,.result_kind
    );
endmodule
`default_nettype wire
