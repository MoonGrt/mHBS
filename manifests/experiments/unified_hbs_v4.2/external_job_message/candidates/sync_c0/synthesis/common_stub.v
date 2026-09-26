// Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// Copyright 2022-2025 Advanced Micro Devices, Inc. All Rights Reserved.
// --------------------------------------------------------------------------------
// Tool Version: Vivado v.2025.2 (lin64) Build 6299465 Fri Nov 14 12:34:56 MST 2025
// Date        : Sat Sep 26 15:08:42 2026
// Host        : user-Z890-EAGLE-WIFI7 running 64-bit Ubuntu 24.04.4 LTS
// Command     : write_verilog -force -mode synth_stub
//               /media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/idea/slh-dsa-acceleration/projects/μHBS/build/v4.2/external_job_message/sync_c0/synth_source/build/v4.2/external_job_message/sync_c0/synthesis/common_stub.v
// Design      : uhbs_common
// Purpose     : Stub declaration of top-level module interface
// Device      : xc7a200tffg1156-3
// --------------------------------------------------------------------------------

// This empty module with port declaration file causes synthesis tools to infer a black box for IP.
// The synthesis directives are for Synopsys Synplify support to prevent IO buffer insertion.
// Please paste the declaration into a Verilog source file or add the file as an additional source.
(* LANES = "2" *) (* SWAP_PHYSICAL_LANES = "1'b0" *) (* UNROLL = "2" *) 
module uhbs_common(clk, rst, program_address, template_address, 
  program_data, template_data, descriptor_addresses, descriptor_data, job_secret_seed, 
  job_secret_prf, job_public_seed, job_randomizer, job_public_root, job_operation, 
  message_length, message_data, message_valid, message_ready, out_valid, out_data, out_keep, 
  out_last, result_kind, busy, done, keygen_done, error, error_code, boot_cycles, keygen_cycles, 
  sign_cycles, hash_count, permutation_count)
/* synthesis syn_black_box black_box_pad_pin="rst,program_address[4:0],template_address[3:0],program_data[63:0],template_data[63:0],descriptor_addresses[9:0],descriptor_data[127:0],job_secret_seed[255:0],job_secret_prf[255:0],job_public_seed[255:0],job_randomizer[255:0],job_public_root[255:0],job_operation,message_length[6:0],message_data[63:0],message_valid,message_ready,out_valid,out_data[63:0],out_keep[7:0],out_last,result_kind,busy,done,keygen_done,error,error_code[15:0],boot_cycles[31:0],keygen_cycles[31:0],sign_cycles[31:0],hash_count[31:0],permutation_count[31:0]" */
/* synthesis syn_force_seq_prim="clk" */;
  input clk /* synthesis syn_isclock = 1 */;
  input rst;
  output [4:0]program_address;
  output [3:0]template_address;
  input [63:0]program_data;
  input [63:0]template_data;
  output [9:0]descriptor_addresses;
  input [127:0]descriptor_data;
  input [255:0]job_secret_seed;
  input [255:0]job_secret_prf;
  input [255:0]job_public_seed;
  input [255:0]job_randomizer;
  input [255:0]job_public_root;
  input job_operation;
  input [6:0]message_length;
  input [63:0]message_data;
  input message_valid;
  output message_ready;
  output out_valid;
  output [63:0]out_data;
  output [7:0]out_keep;
  output out_last;
  output result_kind;
  output busy;
  output done;
  output keygen_done;
  output error;
  output [15:0]error_code;
  output [31:0]boot_cycles;
  output [31:0]keygen_cycles;
  output [31:0]sign_cycles;
  output [31:0]hash_count;
  output [31:0]permutation_count;
endmodule
