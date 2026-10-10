// Exported execution region of top; external runtime Job/ROM ports.
`timescale 1ns/1ps
`default_nettype none
module common #(parameter integer UNROLL=2,PIPELINE=1,parameter bit PROFILE_ENABLE=1)(
 input wire clk,rst,
 output wire [3:0] program_address,output wire [3:0] template_address,
 input wire [63:0] program_data,template_data,
 output wire [9:0] descriptor_addresses,input wire [127:0] descriptor_data,
 input wire [255:0] job_secret_seed,job_secret_prf,job_public_seed,job_randomizer,job_public_root,
 input wire [31:0] job_index,input wire [127:0] job_identifier,
 input wire [1:0] job_operation,input wire [6:0] message_length,
 input wire verify_valid,output wire verify_ready,
 input wire [255:0] verify_data,output wire verify_pass,
 input wire [63:0] message_data,input wire message_valid,output wire message_ready,
 output wire out_valid,output wire [255:0] out_data,output wire [5:0] out_bytes,
 output wire [1:0] result_kind,output logic busy,done,keygen_done,error,
 output logic [15:0] error_code,output logic [63:0] boot_cycles,keygen_cycles,sign_cycles,
 output wire [63:0] hash_count,permutation_count
);
    typedef enum logic [2:0] {HEADER,PROFILE,RELEASE,REQUEST,RUN,HALTED} phase_t;
    phase_t phase;
    logic [63:0] image_header,profile_descriptor;
    logic core_released;
    wire [9:0] core_descriptor_addresses;
    wire core_message_ready,core_job_ready,core_done,core_error;
    wire [15:0] core_error_code;
    wire [63:0] core_cycles;
    wire [3:0] entry=job_operation ? image_header[44:41] : image_header[39:36];
    wire message_length_valid=job_operation<=2 && (job_operation ? (message_length>=7'd1 && message_length<=7'd87)
                                        : (message_length==7'd0));
    wire core_rst=rst || !core_released;
    assign descriptor_addresses=!core_released ? {5'd0,(phase==HEADER ? 5'd0 : 5'd1)}
                                               : core_descriptor_addresses;
    assign result_kind=job_operation;
    assign message_ready=(phase==RUN) && core_message_ready;
    executor #(.UNROLL(UNROLL),.PIPELINE(PIPELINE),.PROFILE_ENABLE(PROFILE_ENABLE)) core (
        .clk,.rst(core_rst),.image_header,.profile_descriptor,.job_entry(entry),
        .program_address,.program_data,.template_address,.template_data,
        .descriptor_addresses(core_descriptor_addresses),.descriptor_data,
        .job_valid(phase==REQUEST && message_length_valid),.job_ready(core_job_ready),
        .job_index(job_index),.job_identifier(job_identifier),
        .job_operation(job_operation),.job_message_length(message_length),
        .job_secret_seed(job_secret_seed),.job_secret_prf(job_secret_prf),
        .job_public_seed(job_public_seed),.job_randomizer(job_randomizer),.job_public_root(job_public_root),
        .message_valid(message_valid && phase==RUN),.message_ready(core_message_ready),.message_data,
        .verify_valid(verify_valid && phase==RUN),.verify_ready,.verify_data,.verify_pass,
        .out_valid,.out_data,.out_bytes,
        .busy(),.done(core_done),.error(core_error),.error_code(core_error_code),
        .hash_count,.permutation_count,.cycles(core_cycles)
    );
    always_ff @(posedge clk) begin
        if(rst) begin
            phase<=HEADER;core_released<=0;
            busy<=1;done<=0;keygen_done<=0;error<=0;error_code<=0;
            boot_cycles<=0;keygen_cycles<=0;sign_cycles<=0;
            image_header<=0;profile_descriptor<=0;
        end else begin
            keygen_done<=0;
            if(PROFILE_ENABLE && !core_released) boot_cycles<=boot_cycles+1;
            if(core_released && core_error) begin
                error<=1;error_code<=core_error_code;busy<=0;phase<=HALTED;
            end else case(phase)
                HEADER:begin image_header<=descriptor_data[63:0];phase<=PROFILE;end
                PROFILE:begin profile_descriptor<=descriptor_data[63:0];core_released<=1;phase<=RELEASE;end
                RELEASE:phase<=REQUEST;
                REQUEST:begin
                    if(!message_length_valid) begin
                        error<=1;error_code<=16'h3002;busy<=0;phase<=HALTED;
                    end else if(core_job_ready) phase<=RUN;
                end
                RUN:if(core_done) begin
                    if(PROFILE_ENABLE) begin
                        if(job_operation==1) sign_cycles<=core_cycles;
                        else if(job_operation==0) keygen_cycles<=core_cycles;
                    end
                    if(!job_operation) keygen_done<=1;
                    done<=1;busy<=0;phase<=HALTED;
                end
                HALTED:begin end
                default:phase<=HALTED;
            endcase
        end
    end
endmodule
`default_nettype wire
