`timescale 1ns/1ps
`default_nettype none
module uhbs_top #(
    parameter integer LANES=2,UNROLL=2,
    parameter bit SWAP_PHYSICAL_LANES=0,
    parameter [255:0] SECRET_SEED=256'h00000000000000000000000000000000d1d06dcbb9181a55aabce64467d6b81d,
    parameter [255:0] SECRET_PRF=256'h00000000000000000000000000000000ca423fc52136322bce5c73a684d95cb7,
    parameter [255:0] PUBLIC_SEED=256'h00000000000000000000000000000000f416dc35e41222ef87445111008541d5,
    parameter [255:0] RANDOMIZER=256'h00000000000000000000000000000000f416dc35e41222ef87445111008541d5,
    parameter [255:0] PUBLIC_ROOT=256'h000000000000000000000000000000003d774653892d5f3695b370c7cdab63ff,
    parameter bit OPERATION=1'b1,
    parameter integer MESSAGE_BYTES=1,
    parameter PROGRAM_INIT_FILE="experiments/v4.2/external_job_message/program_construction.mem",
    parameter TEMPLATE_INIT_FILE="experiments/v4.2/external_job_message/template_construction.mem",
    parameter DESCRIPTOR_INIT_FILE="experiments/v4.2/external_job_message/descriptor_construction.mem"
)(
    input wire clk,rst,
    input wire [63:0] message_data,input wire message_valid,output wire message_ready,
    output wire busy,done,keygen_done,error,output wire [15:0] error_code,
    output wire [31:0] boot_cycles,keygen_cycles,sign_cycles,hash_count,permutation_count,
    output wire out_valid,output wire [63:0] out_data,output wire [7:0] out_keep,
    output wire out_last,result_kind
);
    initial begin
        if(OPERATION && (MESSAGE_BYTES<1 || MESSAGE_BYTES>87)) $error("Sign message length must be 1..87");
        if(!OPERATION && MESSAGE_BYTES!=0) $error("Keygen message length must be zero");
    end
    (* ASYNC_REG="TRUE" *) logic [1:0] reset_sync;
    always_ff @(posedge clk or posedge rst) begin
        if(rst) reset_sync<=2'b11; else reset_sync<={reset_sync[0],1'b0};
    end
    wire rst_n=~reset_sync[1];
    wire [4:0] program_address;
    wire [3:0] template_address;
    wire [63:0] program_data,template_data;
    wire [9:0] descriptor_addresses;
    wire [127:0] descriptor_data;
    // Inferred arrays, no explicit ROM module or vendor memory primitive.
    // Hardware synthesis uses algorithm-independent construction images;
    // real images are applied to INIT only after the common netlist is frozen.
    (* rom_style="distributed", DONT_TOUCH="yes" *) logic [63:0] program_memory[0:31];
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
    (* DONT_TOUCH="yes" *) uhbs_processor processor (
        .job_secret_seed(SECRET_SEED),.job_secret_prf(SECRET_PRF),.job_public_seed(PUBLIC_SEED),
        .job_randomizer(RANDOMIZER),.job_public_root(PUBLIC_ROOT),.job_operation(OPERATION),
        .job_message_length(MESSAGE_BYTES[6:0]),.message_data,.message_valid,.message_ready,
        .clk,.rst_n,.program_address,.program_data,.template_address,.template_data,
        .descriptor_addresses,.descriptor_data,.busy,.done,.keygen_done,.error,.error_code,
        .boot_cycles,.keygen_cycles,.sign_cycles,.hash_count,.permutation_count,
        .out_valid,.out_data,.out_keep,.out_last,.result_kind
    );
endmodule
`default_nettype wire
