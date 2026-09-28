`timescale 1ns/1ps
`default_nettype none
module mhbs_top #(
    parameter integer LANES=2,UNROLL=2,
    parameter bit SWAP_PHYSICAL_LANES=0,
    // Statistics are observable in simulation, absent from production hardware.
`ifdef SYNTHESIS
    parameter bit PROFILE_ENABLE=0,
`else
    parameter bit PROFILE_ENABLE=1,
`endif
    parameter [255:0] SECRET_SEED=256'h0b4aa1346ff6f7f48301823c2594d44555f9a25b176721a082227130abd55d79,
    parameter [255:0] SECRET_PRF=256'ha327db7afb31277f93a9c7eb2f31358cc3f0ec984b8f1aa32901b14c85c748ad,
    parameter [255:0] PUBLIC_SEED=256'ha30998feb9594a23d122c76ea0367151ede46dbbe9c52d130c3751f97fdbf9cc,
    parameter [255:0] RANDOMIZER=256'ha30998feb9594a23d122c76ea0367151ede46dbbe9c52d130c3751f97fdbf9cc,
    parameter [255:0] PUBLIC_ROOT=256'h9e992c407e2903019dda36ac6bbbf4cd474ae00833cfe77ff9677ee403440ee3,
    parameter bit OPERATION=1'b1,
    parameter PROGRAM_INIT_FILE="experiments/v4.2/external_job_message/program_construction.mem",
    parameter TEMPLATE_INIT_FILE="experiments/v4.2/external_job_message/template_construction.mem",
    parameter DESCRIPTOR_INIT_FILE="experiments/v4.2/external_job_message/descriptor_construction.mem"
)(
    input wire clk,rst,
    input wire message_valid,output wire message_ready,
    input wire [6:0] message_length,input wire [63:0] message_data,
    output logic busy,done,keygen_done,error,output logic [15:0] error_code,
    output logic [31:0] boot_cycles,keygen_cycles,sign_cycles,
    output wire [31:0] hash_count,permutation_count,
    output wire out_valid,output wire [63:0] out_data,output wire [7:0] out_keep,
    output wire out_last,result_kind
);
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
    (* DONT_TOUCH="yes" *) mhbs_common common (
.job_secret_seed(SECRET_SEED),.job_secret_prf(SECRET_PRF),.job_public_seed(PUBLIC_SEED),.job_randomizer(RANDOMIZER),.job_public_root(PUBLIC_ROOT),.job_operation(OPERATION),
 .clk,.rst,.message_length,.message_data,.message_valid,.message_ready,
 .program_address,.program_data,.template_address,.template_data,.descriptor_addresses,.descriptor_data,
 .busy,.done,.keygen_done,.error,.error_code,.boot_cycles,.keygen_cycles,.sign_cycles,
 .hash_count,.permutation_count,.out_valid,.out_data,.out_keep,.out_last,.result_kind
    );
endmodule
`default_nettype wire
