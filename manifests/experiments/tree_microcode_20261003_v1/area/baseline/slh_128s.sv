`timescale 1ns/1ps
`default_nettype none
module mhbs_top #(
    parameter integer LANES=2,UNROLL=2,
    parameter bit SWAP_PHYSICAL_LANES=0,
    parameter bit SIGNATURE_STORE_ENABLE=1,
    // Statistics are observable in simulation, absent from production hardware.
`ifdef SYNTHESIS
    parameter bit PROFILE_ENABLE=0,
`else
    parameter bit PROFILE_ENABLE=1,
`endif
    parameter [255:0] SECRET_SEED=256'h00000000000000000000000000000000d1d06dcbb9181a55aabce64467d6b81d,
    parameter [255:0] SECRET_PRF=256'h00000000000000000000000000000000ca423fc52136322bce5c73a684d95cb7,
    parameter [255:0] PUBLIC_SEED=256'h00000000000000000000000000000000f416dc35e41222ef87445111008541d5,
    parameter [255:0] RANDOMIZER=256'h00000000000000000000000000000000f416dc35e41222ef87445111008541d5,
    parameter [255:0] PUBLIC_ROOT=256'h00000000000000000000000000000000d7f500005b3c1e4c03cb5c28f7f75ad0,
    parameter [1:0] OPERATION=2'd1,
    parameter PROGRAM_INIT_FILE="manifests/experiments/unified_hbs_v4.2/external_job_message/images/slh_128s/program.mem",
    parameter TEMPLATE_INIT_FILE="manifests/experiments/unified_hbs_v4.2/external_job_message/images/slh_128s/template.mem",
    parameter DESCRIPTOR_INIT_FILE="manifests/experiments/unified_hbs_v4.2/external_job_message/images/slh_128s/descriptor.mem"
)(
    input wire clk,rst,
    input wire message_valid,output wire message_ready,
    input wire [6:0] message_length,input wire [63:0] message_data,
    input wire verify_valid,output wire verify_ready,
    input wire [255:0] verify_data,output wire verify_pass,
    output logic busy,done,keygen_done,error,output logic [15:0] error_code,
    output logic [31:0] boot_cycles,keygen_cycles,sign_cycles,
    output wire [31:0] hash_count,permutation_count,
    output wire out_valid,output wire [255:0] out_data,output wire [5:0] out_bytes,
    output wire [1:0] result_kind,
    input wire signature_read_enable,input wire [10:0] signature_read_address,
    output wire signature_read_valid,output wire [255:0] signature_read_data,
    output wire [5:0] signature_node_bytes,
    output wire signature_valid,signature_error,
    output wire [10:0] signature_nodes,output wire [15:0] signature_length
);
    wire [3:0] program_address;
    wire [3:0] template_address;
    wire [63:0] program_data,template_data;
    wire [9:0] descriptor_addresses;
    wire [127:0] descriptor_data;
    // Inferred arrays, no explicit ROM module or vendor memory primitive.
    // Hardware synthesis uses algorithm-independent construction images;
    // real images are applied to INIT only after the common netlist is frozen.
    (* rom_style="distributed", DONT_TOUCH="yes" *) logic [63:0] program_memory[0:15];
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
 .verify_valid,.verify_ready,.verify_data,.verify_pass,
 .program_address,.program_data,.template_address,.template_data,.descriptor_addresses,.descriptor_data,
 .busy,.done,.keygen_done,.error,.error_code,.boot_cycles,.keygen_cycles,.sign_cycles,
 .hash_count,.permutation_count,.out_valid,.out_data,.out_bytes,.result_kind
    );
    generate if(SIGNATURE_STORE_ENABLE && OPERATION==1) begin: stored_signature
        mhbs_signature_store storage (
            .clk,.rst,.finish(done),.abort(error),
            .write_valid(out_valid),.write_data(out_data),.write_bytes(out_bytes),
            .read_enable(signature_read_enable),.read_address(signature_read_address),
            .read_valid(signature_read_valid),.read_data(signature_read_data),
            .node_bytes(signature_node_bytes),.complete(signature_valid),
            .error(signature_error),.nodes(signature_nodes),.length(signature_length)
        );
    end else begin: no_signature_store
        assign signature_read_valid=0;
        assign signature_read_data=0;
        assign signature_node_bytes=0;
        assign signature_valid=0;
        assign signature_error=0;
        assign signature_nodes=0;
        assign signature_length=0;
    end endgenerate
endmodule
`default_nettype wire
