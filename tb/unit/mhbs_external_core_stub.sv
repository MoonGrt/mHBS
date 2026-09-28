`timescale 1ns/1ps
`default_nettype none
// One ABI 4 SLH macro executor for n=16/24/32.
module mhbs_hbs #(
    parameter integer UNROLL=2, LANES=2,
    parameter bit PROFILE_ENABLE=0, SWAP_PHYSICAL_LANES=0
) (
    input wire [63:0] image_header, profile_descriptor,
    output wire [3:0] program_address,
    output wire [3:0] template_address,
    input wire [63:0] program_data, template_data,
    input wire [3:0] job_entry,
    output wire [9:0] descriptor_addresses,
    input wire [127:0] descriptor_data,
    input wire clk, rst,
    input wire job_valid, output wire job_ready, input wire [1:0] job_operation,
    input wire [6:0] job_message_length,
    input wire [255:0] job_secret_seed, job_secret_prf, job_public_seed, job_randomizer, job_public_root,
    input wire message_valid, output wire message_ready,
    input wire [63:0] message_data,
    input wire verify_valid, output wire verify_ready,
    input wire [255:0] verify_data, output wire verify_pass,
    output wire out_valid, output wire [255:0] out_data,
    output wire [5:0] out_bytes,
    output wire busy, output logic done, error, output logic [15:0] error_code,
    output wire [31:0] hash_count, permutation_count,
    output logic [31:0] cycles
);
    assign verify_ready=0;assign verify_pass=0;
    logic active;
    logic [6:0] accepted_length;
    integer received,starts;
    logic [63:0] first_word,last_word;
    assign program_address=0;assign template_address=0;assign descriptor_addresses=0;
    assign job_ready=!active;assign message_ready=active && job_operation && received<accepted_length;
    assign busy=active;assign out_valid=0;assign out_data=0;assign out_bytes=0;
    assign hash_count=0;assign permutation_count=0;
    always_ff @(posedge clk)begin
     if(rst)begin active<=0;accepted_length<=0;received<=0;starts<=0;done<=0;error<=0;error_code<=0;cycles<=0;end
     else begin
      done<=0;
      if(job_valid && job_ready)begin
       if(job_secret_seed!=256'h1122 || job_secret_prf!=256'h3344 || job_public_seed!=256'h5566 || job_randomizer!=256'h7788 || job_public_root!=256'h99aa)$fatal(1,"Job parameters changed");
       if(job_entry!=(job_operation ? 3 : 0))$fatal(1,"entry selection");
       active<=1;accepted_length<=job_message_length;received<=0;starts<=starts+1;cycles<=0;
      end
      if(active)begin
       cycles<=cycles+1;
       if(message_valid && message_ready)begin
        if(received==0)first_word<=message_data;
        last_word<=message_data;received<=received+8;
       end
       if((!job_operation || received>=accepted_length) && cycles>=3)begin active<=0;done<=1;end
      end
     end
    end
endmodule
`default_nettype wire
