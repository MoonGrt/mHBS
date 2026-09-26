// Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// Copyright 2022-2025 Advanced Micro Devices, Inc. All Rights Reserved.
// --------------------------------------------------------------------------------
// Tool Version: Vivado v.2025.2 (lin64) Build 6299465 Fri Nov 14 12:34:56 MST 2025
// Date        : Sat Sep 26 14:41:10 2026
// Host        : user-Z890-EAGLE-WIFI7 running 64-bit Ubuntu 24.04.4 LTS
// Command     : write_verilog -force -mode synth_stub
//               /media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/idea/slh-dsa-acceleration/projects/μHBS/build/v4.2/external_job_message/inline_synth_c2/synth_source/build/v4.2/external_job_message/inline_synth_c2/synthesis/core_stub.v
// Design      : uhbs_hbs
// Purpose     : Stub declaration of top-level module interface
// Device      : xc7a200tffg1156-3
// --------------------------------------------------------------------------------

// This empty module with port declaration file causes synthesis tools to infer a black box for IP.
// The synthesis directives are for Synopsys Synplify support to prevent IO buffer insertion.
// Please paste the declaration into a Verilog source file or add the file as an additional source.
(* DIGEST_BYTES = "49" *) (* INDEX_BITS = "7" *) (* LANES = "2" *) 
(* MAX_MESSAGE_BYTES = "87" *) (* N = "32" *) (* PROFILE_ENABLE = "1'b1" *) 
(* SWAP_PHYSICAL_LANES = "1'b0" *) (* TREE_BYTES = "8" *) (* UNROLL = "2" *) 
(* V = "392" *) (* W = "256" *) 
module uhbs_hbs(image_header, profile_descriptor, 
  program_address, template_address, program_data, template_data, job_entry, 
  descriptor_addresses, descriptor_data, clk, rst_n, job_valid, job_ready, job_operation, 
  job_message_length, job_secret_seed, job_secret_prf, job_public_seed, job_randomizer, 
  job_public_root, message_valid, message_ready, message_data, out_valid, out_ready, out_data, 
  out_keep, out_last, busy, done, error, error_code, hash_count, permutation_count, cycles)
/* synthesis syn_black_box black_box_pad_pin="image_header[63:0],profile_descriptor[63:0],program_address[4:0],template_address[3:0],program_data[63:0],template_data[63:0],job_entry[4:0],descriptor_addresses[9:0],descriptor_data[127:0],rst_n,job_valid,job_ready,job_operation,job_message_length[6:0],job_secret_seed[255:0],job_secret_prf[255:0],job_public_seed[255:0],job_randomizer[255:0],job_public_root[255:0],message_valid,message_ready,message_data[63:0],out_valid,out_ready,out_data[63:0],out_keep[7:0],out_last,busy,done,error,error_code[15:0],hash_count[31:0],permutation_count[31:0],cycles[31:0]" */
/* synthesis syn_force_seq_prim="clk" */;
  input [63:0]image_header;
  input [63:0]profile_descriptor;
  output [4:0]program_address;
  output [3:0]template_address;
  input [63:0]program_data;
  input [63:0]template_data;
  input [4:0]job_entry;
  output [9:0]descriptor_addresses;
  input [127:0]descriptor_data;
  input clk /* synthesis syn_isclock = 1 */;
  input rst_n;
  input job_valid;
  output job_ready;
  input job_operation;
  input [6:0]job_message_length;
  input [255:0]job_secret_seed;
  input [255:0]job_secret_prf;
  input [255:0]job_public_seed;
  input [255:0]job_randomizer;
  input [255:0]job_public_root;
  input message_valid;
  output message_ready;
  input [63:0]message_data;
  output out_valid;
  input out_ready;
  output [63:0]out_data;
  output [7:0]out_keep;
  output out_last;
  output busy;
  output done;
  output error;
  output [15:0]error_code;
  output [31:0]hash_count;
  output [31:0]permutation_count;
  output [31:0]cycles;
endmodule
