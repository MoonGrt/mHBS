`timescale 1ns/1ps
`default_nettype none
module uhbs_top #(
    parameter integer LANES=2,UNROLL=2,
    parameter bit SWAP_PHYSICAL_LANES=0,
    parameter PROGRAM_INIT_FILE="manifests/experiments/unified_hbs_v4.2/images/slh_128f/sign/program.mem",
    parameter TEMPLATE_INIT_FILE="manifests/experiments/unified_hbs_v4.2/images/slh_128f/sign/template.mem",
    parameter DESCRIPTOR_INIT_FILE="manifests/experiments/unified_hbs_v4.2/images/slh_128f/sign/descriptor.mem"
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
    wire [5:0] program_address;
    wire [3:0] template_address;
    wire [63:0] program_data,template_data;
    wire [9:0] descriptor_addresses;
    wire [127:0] descriptor_data;
    // Inferred arrays, no explicit ROM module or vendor memory primitive.
    // Hardware synthesis uses algorithm-independent construction images;
    // real images are applied to INIT only after the common netlist is frozen.
    (* rom_style="distributed", DONT_TOUCH="yes" *) logic [63:0] program_memory[0:63];
    (* rom_style="distributed", DONT_TOUCH="yes" *) logic [63:0] template_memory[0:15];
    (* rom_style="distributed", DONT_TOUCH="yes" *) logic [63:0] descriptor_memory[0:31];
    initial begin
        if(PROGRAM_INIT_FILE!="") $readmemh(PROGRAM_INIT_FILE,program_memory);
        if(TEMPLATE_INIT_FILE!="") $readmemh(TEMPLATE_INIT_FILE,template_memory);
        if(DESCRIPTOR_INIT_FILE!="") $readmemh(DESCRIPTOR_INIT_FILE,descriptor_memory);
    end
    assign program_data=program_memory[program_address];
    assign template_data=template_memory[template_address];
    assign descriptor_data={descriptor_memory[descriptor_addresses[9:5]],descriptor_memory[descriptor_addresses[4:0]]};
    (* DONT_TOUCH="yes" *) uhbs_processor #(.LANES(LANES),.UNROLL(UNROLL),.SWAP_PHYSICAL_LANES(SWAP_PHYSICAL_LANES)) processor (
        .clk,.rst_n,.program_address,.program_data,.template_address,.template_data,
        .descriptor_addresses,.descriptor_data,.busy,.done,.keygen_done,.error,.error_code,
        .boot_cycles,.keygen_cycles,.sign_cycles,.hash_count,.permutation_count,
        .out_valid,.out_data,.out_keep,.out_last,.result_kind
    );
endmodule
`default_nettype wire
