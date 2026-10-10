`timescale 1ns/1ps
// Direct C++ clock driver for full-tree regression. Same production common/cache.
module tb_fast(
 input wire clk,rst,
 input wire message_valid,input wire [63:0] message_data,output wire message_ready,
 input wire verify_valid,input wire [255:0] verify_data,output wire verify_ready,
 output wire verify_pass,done,error,output wire [15:0] error_code,
 output wire out_valid,output wire [255:0] out_data,output wire [5:0] out_bytes,
 output wire [63:0] execution_cycles,hash_count,permutation_count,
 output wire hash_event,permutation_event,batch_event,execution_reset,
 input wire signature_read_enable,input wire [10:0] signature_read_address,
 output wire signature_read_valid,output wire [255:0] signature_read_data,
 output wire [5:0] signature_read_bytes,output wire signature_complete,signature_error,
 output wire [10:0] signature_nodes,output wire [15:0] signature_length
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
 common #(.PIPELINE(4),.UNROLL(1),.PROFILE_ENABLE(1)) dut(.*);
 assign execution_cycles=job_operation==0 ? keygen_cycles : job_operation==1 ? sign_cycles : dut.core.cycles;
 assign execution_reset=dut.core.execution_rst;
 assign hash_event=dut.core.lane.permutation_complete && dut.core.lane.running_last;
 assign permutation_event=dut.core.lane.permutation_complete;
 assign batch_event=dut.core.lane.batch_perm_done;
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
