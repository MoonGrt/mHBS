`timescale 1ns/1ps
`default_nettype none
// v4.1 processor compiled independently of all three ROM contents.
module uhbs_processor #(
    parameter integer LANES=2, UNROLL=2,
    parameter bit SWAP_PHYSICAL_LANES=0
)(
    input wire clk,rst_n,
    output wire [5:0] program_address,template_address,
    input wire [127:0] program_data,template_data,
    output wire [55:0] descriptor_addresses,
    input wire [511:0] descriptor_data,
    output wire out_valid,output wire [63:0] out_data,output wire [7:0] out_keep,
    output wire out_last,result_kind,
    output logic busy,done,keygen_done,error,output logic [15:0] error_code,
    output logic [31:0] boot_cycles,keygen_cycles,sign_cycles,
    output wire [31:0] hash_count,permutation_count,
    output wire [10:0] state_next_q,output wire tree_cache_valid
);
    typedef enum logic [3:0] {HEADER,PROFILE,CONTROL,CHECK_PROGRAM,CHECK_TEMPLATE,CHECK_DESCRIPTOR,
        RELEASE_CORE,KEYGEN_REQUEST,KEYGEN_WAIT,SIGN_REQUEST,SIGN_WAIT,HALTED} phase_t;
    phase_t phase;
    logic [6:0] scan;
    logic [63:0] image_header,profile_descriptor;
    logic [5:0] program_count;
    logic [6:0] template_count,message_length;
    logic [10:0] initial_q;
    logic [255:0] secret_seed,secret_prf,public_seed,randomizer;
    logic [127:0] identifier;
    logic core_released,operation;
    wire [5:0] core_program_address,core_template_address;
    wire [55:0] core_descriptor_addresses;
    wire booting=!core_released;
    wire [6:0] boot_program_address=phase==CONTROL ? 7'd41 : scan;
    logic [6:0] message_offset;
    wire [63:0] message_data=message_offset[3] ? program_data[127:64] : program_data[63:0];
    wire message_ready;
    wire feed_message=phase==SIGN_WAIT && message_offset<message_length;
    assign program_address=booting ? boot_program_address[5:0] : feed_message ? 6'd44+{3'd0,message_offset[6:4]} : core_program_address;
    assign template_address=booting ? scan[5:0] : core_template_address;
    wire [6:0] boot_descriptor_address=phase==HEADER ? 7'd0 : phase==PROFILE ? 7'd1 : scan;
    assign descriptor_addresses=booting ? {49'd0,boot_descriptor_address} : core_descriptor_addresses;
    wire [63:0] boot_descriptor=descriptor_data[63:0];
    wire [5:0] node_bytes=profile_descriptor[53:48];
    wire stateful=profile_descriptor[59];
    wire [2:0] family=profile_descriptor[58:56];
    wire [3:0] omega=profile_descriptor[47:44], hp=profile_descriptor[43:40], a=profile_descriptor[39:36];
    wire [5:0] k=profile_descriptor[23:18],m=profile_descriptor[12:7];
    wire [4:0] d=profile_descriptor[17:13];
    wire [6:0] h=profile_descriptor[6:0];
    wire slh_profile=!stateful && family==1 && omega==4 &&
        ((node_bytes==16 && hp==3 && a==6 && k==33 && d==22 && m==34 && h==66) ||
         (node_bytes==24 && hp==3 && a==8 && k==33 && d==22 && m==42 && h==66) ||
         (node_bytes==32 && hp==4 && a==9 && k==35 && d==17 && m==49 && h==68));
    wire stateful_profile=stateful && (family==2 || family==3) && node_bytes==32 &&
        (omega==2 || omega==4) && hp==10 && a==0 && k==0 && d==1 && m==32 && h==10;
    wire [15:0] profile_recipe_mask=family==1 ? 16'h101e : family==2 ? 16'h01e0 : 16'hee00;
    wire core_job_ready,core_done,core_error,core_busy;
    wire [15:0] core_error_code;
    wire [31:0] core_cycles;
    wire commit_valid;
    logic commit_ready;
    logic [10:0] consumed_index;
    wire core_rst_n=rst_n && core_released;
    assign result_kind=operation;
    uhbs_hbs #(.UNROLL(UNROLL),.LANES(LANES),.PROFILE_ENABLE(1),.SWAP_PHYSICAL_LANES(SWAP_PHYSICAL_LANES)) core (
        .clk,.rst_n(core_rst_n),.image_header,.profile_descriptor,.program_count,.template_count,
        .program_address(core_program_address),.program_data,.template_address(core_template_address),.template_data,
        .descriptor_addresses(core_descriptor_addresses),.descriptor_data,
        .job_valid(phase==KEYGEN_REQUEST || phase==SIGN_REQUEST),.job_ready(core_job_ready),.job_operation(operation),
        .job_message_length(message_length),.job_initial_q(initial_q),
        .job_secret_seed(secret_seed),.job_secret_prf(secret_prf),.job_public_seed(public_seed),.job_randomizer(randomizer),.job_identifier(identifier),
        .message_valid(feed_message),.message_ready,.message_data,
        .state_commit_valid(commit_valid),.state_commit_ready(commit_ready && consumed_index==state_next_q),.state_next_q,
        .out_valid,.out_ready(1'b1),.out_data,.out_keep,.out_last,
        .busy(core_busy),.done(core_done),.error(core_error),.error_code(core_error_code),
        .hash_count,.permutation_count,.cycles(core_cycles),.tree_cache_valid
    );
    task automatic reject(input [15:0] code);
        begin phase<=HALTED;error<=1;error_code<=code;busy<=0;end
    endtask
    integer j;
    logic invalid_word;
    // Data padding is checked before the core can emit even a Keygen byte.
    always @* begin
        invalid_word=0;
        if(scan<32) begin
            if(scan>=program_count) invalid_word=program_data!=0;
            else case(program_data[127:126])
                0,1: invalid_word=program_data[125:120]>=template_count || |program_data[17:0] ||
                    (program_data[127:126]==0 && |program_data[71:18]) ||
                    (program_data[127:126]==1 && program_data[71:66]==0);
                2: invalid_word=|program_data[59:0] || program_data[113:108]==0 ||
                    ({1'b0,program_data[125:114]}+1)>scan;
                3: invalid_word=|program_data[125:0];
            endcase
        end else if(scan>=32 && scan<=39 && scan[0]) begin
            if(node_bytes==16) invalid_word=program_data!=0;
            else if(node_bytes==24) invalid_word=|program_data[127:64];
        end else if(scan==42 || scan==43 || scan>=50) invalid_word=program_data!=0;
        else if(scan>=44 && scan<=49) begin
            for(j=0;j<16;j=j+1) if((scan-44)*16+j>=message_length && program_data[j*8 +:8]!=0) invalid_word=1;
        end
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            phase<=HEADER;scan<=0;core_released<=0;operation<=0;
            busy<=1;done<=0;keygen_done<=0;error<=0;error_code<=0;
            boot_cycles<=0;keygen_cycles<=0;sign_cycles<=0;
            commit_ready<=0;consumed_index<=0;message_offset<=0;
            image_header<=0;profile_descriptor<=0;program_count<=0;template_count<=0;
            message_length<=0;initial_q<=0;secret_seed<=0;secret_prf<=0;public_seed<=0;randomizer<=0;identifier<=0;
        end else begin
            keygen_done<=0;
            if(!core_released && phase!=HALTED) boot_cycles<=boot_cycles+1;
            if(commit_valid && !commit_ready) begin consumed_index<=state_next_q;commit_ready<=1;end
            if(!commit_valid) commit_ready<=0;
            if(feed_message && message_ready) message_offset<=message_offset+7'd8;
            if(core_released && core_error) reject(core_error_code);
            else case(phase)
                HEADER: begin
                    image_header<=boot_descriptor;phase<=PROFILE;
                    if(boot_descriptor[63:56]!=8'ha4) reject(16'h4101);
                end
                PROFILE: begin profile_descriptor<=boot_descriptor;phase<=CONTROL;end
                CONTROL: begin
                    initial_q<=program_data[10:0];message_length<=program_data[17:11];
                    program_count<=program_data[23:18];template_count<=program_data[30:24];
                    scan<=0;phase<=CHECK_PROGRAM;
                    if(profile_descriptor[63:60]!=11 || profile_descriptor[55:54]!=0 || !(slh_profile || stateful_profile)) reject(16'h4102);
                    else if(|program_data[127:31] || program_data[23:18]==0 || program_data[23:18]>32 ||
                        program_data[30:24]==0 || program_data[30:24]>64 ||
                        program_data[17:11]==0 || program_data[17:11]>87 ||
                        image_header[55:47]>=image_header[46:38] || image_header[46:38]>=program_data[23:18]) reject(16'h4103);
                    else if((stateful && program_data[10:0]>=1024) || (!stateful && program_data[10:0]!=0)) reject(16'h4104);
                end
                CHECK_PROGRAM: begin
                    if(invalid_word) reject(16'h4105);
                    else begin
                        case(scan)
                            32:secret_seed[127:0]<=program_data;33:secret_seed[255:128]<=program_data;
                            34:secret_prf[127:0]<=program_data;35:secret_prf[255:128]<=program_data;
                            36:public_seed[127:0]<=program_data;37:public_seed[255:128]<=program_data;
                            38:randomizer[127:0]<=program_data;39:randomizer[255:128]<=program_data;
                            40:identifier<=program_data;
                            default: begin end
                        endcase
                        if(scan==63) begin scan<=0;phase<=CHECK_TEMPLATE;end else scan<=scan+1;
                    end
                end
                CHECK_TEMPLATE: begin
                    if(scan>=template_count && template_data!=0) reject(16'h4106);
                    else if(scan<template_count && (template_data[127:124]!=1 || !template_data[107] || template_data[106] ||
                        template_data[99:96]<1 || template_data[99:96]>5 || template_data[95] || template_data[87])) reject(16'h4106);
                    else if(scan==63) begin scan<=0;phase<=CHECK_DESCRIPTOR;end else scan<=scan+1;
                end
                CHECK_DESCRIPTOR: begin
                    if(boot_descriptor!=0 && !(boot_descriptor[63:60]==1 || boot_descriptor[63:60]==2 || boot_descriptor[63:60]==4 ||
                        boot_descriptor[63:60]==5 || boot_descriptor[63:60]==6 || boot_descriptor[63:60]==8 || boot_descriptor[63:60]==9 ||
                        boot_descriptor[63:60]==10 || boot_descriptor[63:60]==11)) reject(16'h4107);
                    else if(boot_descriptor[63:60]==1 && (boot_descriptor[29:24]==0 || boot_descriptor[29:24]>32 || boot_descriptor[37:32]==0 || boot_descriptor[37:32]>49)) reject(16'h4107);
                    else if(boot_descriptor[63:60]==1 && !profile_recipe_mask[boot_descriptor[59:56]]) reject(16'h4108);
                    else if(boot_descriptor[63:60]==4 && (boot_descriptor[59] || boot_descriptor[51] || boot_descriptor[43] || boot_descriptor[35] ||
                        boot_descriptor[27:20]==0 || boot_descriptor[27:20]>133 || boot_descriptor[19:15]>15 || boot_descriptor[13:12]>2)) reject(16'h4107);
                    else if(boot_descriptor[63:60]==5 && (boot_descriptor[59] || boot_descriptor[51] || boot_descriptor[43:40]==0 || boot_descriptor[43:40]>10 ||
                        boot_descriptor[37:36]>2 || boot_descriptor[33:32]>2 || boot_descriptor[29])) reject(16'h4107);
                    else if(boot_descriptor[63:60]==9 && (boot_descriptor[51:48]==0 || {1'b0,boot_descriptor[59:52]}+{5'd0,boot_descriptor[51:48]}>128)) reject(16'h4107);
                    else if(boot_descriptor[63:60]==2 && (boot_descriptor[59:56]>7 || boot_descriptor[55:48]==0 || boot_descriptor[55:48]>node_bytes ||
                        (boot_descriptor[59:56]>=6 && boot_descriptor[55:48]>4) || (boot_descriptor[59:56]==5 && boot_descriptor[55:48]>16))) reject(16'h4107);
                    else if(scan==127) begin core_released<=1;phase<=RELEASE_CORE;end else scan<=scan+1;
                end
                RELEASE_CORE:phase<=KEYGEN_REQUEST;
                KEYGEN_REQUEST:if(core_job_ready) phase<=KEYGEN_WAIT;
                KEYGEN_WAIT:if(core_done) begin keygen_cycles<=core_cycles;keygen_done<=1;operation<=1;phase<=SIGN_REQUEST;end
                SIGN_REQUEST:if(core_job_ready) begin message_offset<=0;phase<=SIGN_WAIT;end
                SIGN_WAIT:if(core_done) begin sign_cycles<=core_cycles;done<=1;busy<=0;phase<=HALTED;end
                HALTED:begin end
                default:reject(16'h4100);
            endcase
        end
    end
endmodule
`default_nettype wire
