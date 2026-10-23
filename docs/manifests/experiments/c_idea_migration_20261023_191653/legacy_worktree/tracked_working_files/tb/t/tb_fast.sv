`timescale 1ns/1ps
// Direct C++ clock driver for full-tree regression. Same production common/cache.
module tb_fast #(parameter integer PIPELINE=1,UNROLL=1)(
 input wire clk,rst,
 input wire message_valid,input wire [63:0] message_data,output wire message_ready,
 input wire verify_valid,input wire [255:0] verify_data,output wire verify_ready,
 output wire verify_pass,done,error,output wire [15:0] error_code,
 output wire out_valid,output wire [255:0] out_data,output wire [5:0] out_bytes,
 output wire [63:0] execution_cycles,hash_count,permutation_count,
 output wire hash_event,permutation_event,batch_event,execution_reset,execution_active,debug_stats,statistics_zero,
 input wire signature_read_enable,input wire [10:0] signature_read_address,
 output wire signature_read_valid,output wire [255:0] signature_read_data,
 output wire [5:0] signature_read_bytes,output wire signature_complete,signature_error,
 output wire [10:0] signature_nodes,output wire [15:0] signature_length,
 output wire [31:0] configuration_pipeline,configuration_unroll,
 output wire command_event,child_chain_event,output wire [3:0] command_opcode,
 output wire trace_block_event,trace_result_event,
 output wire [1087:0] trace_block_data,output wire [391:0] trace_result_data,
 output wire [7:0] trace_block_bytes,output wire [5:0] trace_result_bytes
);
 reg [63:0] pm[0:15],tm[0:15],dm[0:31];reg [255:0] cfg[0:8];
 wire [3:0] program_address,template_address;wire [9:0] descriptor_addresses;
 wire [63:0] program_data=pm[program_address],template_data=tm[template_address];
 wire [127:0] descriptor_data={dm[descriptor_addresses[9:5]],dm[descriptor_addresses[4:0]]};
 wire [255:0] job_secret_seed=cfg[0],job_secret_prf=cfg[1],job_public_seed=cfg[2],job_randomizer=cfg[3],job_public_root=cfg[4];
 wire [127:0] job_identifier=cfg[5][127:0];wire [31:0] job_index=cfg[6][31:0];
 wire [1:0] job_operation=cfg[7][1:0];wire [6:0] message_length=job_operation==0 ? 0 : cfg[8][6:0];
 wire [63:0] boot_cycles,keygen_cycles,sign_cycles;wire busy,keygen_done;
 wire [1:0] result_kind;wire [5:0] cache_node_bytes;
 assign configuration_pipeline=PIPELINE;
 assign configuration_unroll=UNROLL;
 common #(.PIPELINE(PIPELINE),.UNROLL(UNROLL)) dut(.*);
 // The C++ wrapper keeps a stable interface; production diagnostics are absent
 // in the synthesis view. Functional events still measure cycles and work.
`ifdef SYNTHESIS
 assign error_code=0;
 assign boot_cycles=0;
 assign keygen_cycles=0;
 assign sign_cycles=0;
 assign execution_cycles=0;
 assign hash_count=0;
 assign permutation_count=0;
 assign debug_stats=0;
 assign statistics_zero=1;
`else
 assign execution_cycles=job_operation==0 ? keygen_cycles : job_operation==1 ? sign_cycles : dut.core.cycles;
 assign debug_stats=1;
 assign statistics_zero=!(boot_cycles|keygen_cycles|sign_cycles|hash_count|permutation_count|dut.core.cycles);
`endif
 assign execution_active=dut.core.state!=0 && dut.core.state!=32;
 assign execution_reset=dut.core.execution_rst;
 // A command is counted once when the sequencer hands it to the executor.
 assign command_event=dut.core.cmd_valid && dut.core.state==3;
 assign command_opcode=dut.core.cmd[47:44];
 assign child_chain_event=dut.core.state==7 && !dut.core.standalone_chain && dut.core.chain_cursor==0;
`ifdef MHBS_SHA2
 assign hash_event=dut.core.lane.hash_complete_event;
 assign permutation_event=dut.core.lane.compression_complete_event;
 assign batch_event=0;
 // Count the compressor input handshake, including the direct replay path.
 wire [511:0] trace_sha2_block=dut.core.lane.block_ready ?
     dut.core.lane.block_buffer : dut.core.lane.replay_block;
 assign trace_block_event=!execution_reset &&
     (dut.core.lane.block_ready || dut.core.lane.replay_take) && dut.core.lane.compression_ready;
 assign trace_block_bytes=64;
 assign trace_result_event=dut.core.lane.hash_complete_event;
 assign trace_result_bytes=32;
 assign trace_result_data={136'd0,dut.core.lane.returned};
 for(genvar b=0;b<64;b++)begin: trace_sha2_bytes
  assign trace_block_data[b*8+:8]=trace_sha2_block[511-b*8-:8];
 end
 assign trace_block_data[1087:512]=0;
`else
 assign hash_event=dut.core.lane.permutation_complete && dut.core.lane.running_last;
 assign permutation_event=dut.core.lane.permutation_complete;
 assign batch_event=dut.core.lane.batch_perm_done;
 if(PIPELINE==1)begin: scalar_trace
  logic [1087:0] stream_block;
  wire fast=dut.core.lane.scalar_execution.take_fast || dut.core.lane.scalar_execution.take_feedback;
  wire stream=dut.core.lane.scalar_execution.take_stream;
  wire [3:0] index=dut.core.lane.scalar_execution.append_index;
  always_ff @(posedge clk)begin
   if(execution_reset)stream_block<=0;
   else if(stream)begin
    if(index==8)stream_block[1024+:64]<=dut.core.lane.scalar_execution.staged_data[63:0];
    else stream_block[index*128+:128]<=dut.core.lane.scalar_execution.staged_data;
   end
  end
  assign trace_block_event=fast || (stream && index==8);
  assign trace_block_data=fast ? dut.core.lane.scalar_execution.fast_block :
      {dut.core.lane.scalar_execution.staged_data[63:0],stream_block[1023:0]};
  assign trace_result_data=dut.core.lane.scalar_execution.advanced_state[391:0];
 end else begin: no_scalar_trace
  assign trace_block_event=0;
  assign trace_block_data=0;
  assign trace_result_data=0;
 end
 assign trace_result_event=dut.core.lane.permutation_complete && dut.core.lane.running_last;
 assign trace_block_bytes=136;
 assign trace_result_bytes=49;
`endif
 signature cache(.clk,.rst,.finish(done),.abort(error),.write_valid(out_valid&&job_operation==1),
  .write_data(out_data),.write_bytes(out_bytes),.read_enable(signature_read_enable),
  .read_address(signature_read_address),.read_valid(signature_read_valid),
  .read_data(signature_read_data),.read_bytes(signature_read_bytes),.node_bytes(cache_node_bytes),
  .complete(signature_complete),.error(signature_error),.nodes(signature_nodes),.length(signature_length));
 string vector_file;
 initial begin
  if(!$value$plusargs("VECTOR=%s",vector_file))$fatal(1,"VECTOR");
  $readmemh({vector_file,"/program.mem"},pm);$readmemh({vector_file,"/template.mem"},tm);
  $readmemh({vector_file,"/descriptor.mem"},dm);$readmemh({vector_file,"/job.mem"},cfg);
 end
endmodule
