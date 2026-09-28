`timescale 1ns/1ps
`ifdef MHBS_PARTITIONED
`define HBS_CORE dut.common.core
`else
`define HBS_CORE dut.core
`endif
module tb_mhbs_verify;
 parameter [255:0] PUBLIC_SEED=0,PUBLIC_ROOT=0;
 parameter integer MESSAGE_BYTES=1,NODE_BYTES=16,NODES=1068,SWAP=0;
 parameter bit PROFILE_ENABLE=1;
 logic clk=0,rst=1;
 wire busy,done,keygen_done,error,out_valid,out_last,verify_ready,verify_pass,message_ready;
 wire [1:0] result_kind;
 wire [15:0] error_code;wire [31:0] boot_cycles,keygen_cycles,sign_cycles,hash_count,permutation_count;
 wire [63:0] out_data;wire [7:0] out_keep;
 logic [63:0] message_data=0;logic message_valid=0,verify_valid=0;
 logic [255:0] verify_data=0;
 wire [6:0] message_length=MESSAGE_BYTES;
 reg [255:0] nodes[0:4095];reg [7:0] message_bytes[0:86];
 integer sent=0,node_sent=0,cycles=0,wait_cycles=0,stall=0,replay=0,cut=0,fault=0;
 integer expected=1,flip=-1,bad_message=0,abort_at=0;
 integer hashes[0:1],permutations[0:1],zero_steps=0,full_steps=0;
 reg [31:0] rng=32'h15c0ffee;
 string image_dir,vector_dir;
 mhbs_top #(.PUBLIC_SEED(PUBLIC_SEED),.PUBLIC_ROOT(PUBLIC_ROOT),.OPERATION(2),
 .PROFILE_ENABLE(PROFILE_ENABLE),.SWAP_PHYSICAL_LANES(SWAP),
 .PROGRAM_INIT_FILE(""),.TEMPLATE_INIT_FILE(""),.DESCRIPTOR_INIT_FILE("")) dut(.*);
 always #5 clk=~clk;
 task tick;begin @(posedge clk);#1;end endtask
 genvar l;
 generate for(l=0;l<2;l=l+1)begin: observe
  always @(posedge clk)begin
   if(`HBS_CORE.execution_rst)begin hashes[l]=0;permutations[l]=0;end
   else if(`HBS_CORE.lanes[l].lane.sponge.lane_state==2 &&
           `HBS_CORE.lanes[l].lane.sponge.round_index+2>=24)begin
    permutations[l]=permutations[l]+1;
    if(`HBS_CORE.lanes[l].lane.sponge.running_last)hashes[l]=hashes[l]+1;
   end
  end
 end endgenerate
 always @(negedge clk)begin
  if(rst)begin message_valid=0;verify_valid=0;message_data=0;verify_data=0;rng=32'h15c0ffee;end
  else begin
   rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
   if(!(message_valid && !message_ready))begin
    message_valid=sent<MESSAGE_BYTES && (!stall || rng[2:0]!=0);
    message_data=0;
    for(integer i=0;i<8;i=i+1)if(sent+i<MESSAGE_BYTES)message_data[8*i +:8]=message_bytes[sent+i];
   end
   if(!(verify_valid && !verify_ready))begin
    verify_valid=node_sent<NODES && (!cut || node_sent<cut) && (!stall || rng[1:0]!=0);
    verify_data=nodes[node_sent];
   end
  end
 end
 always @(posedge clk)begin
  if(rst)begin sent=0;node_sent=0;cycles=0;wait_cycles=0;zero_steps=0;full_steps=0;end
  else begin
   cycles=cycles+1;
   if(message_valid && message_ready)sent=sent+8;
   if(verify_valid && verify_ready)begin
    if(node_sent>=NODES)$fatal(1,"excess node accepted");
    node_sent=node_sent+1;
   end
   if((message_ready && !message_valid)||(verify_ready && !verify_valid))wait_cycles=wait_cycles+1;
   if(cycles>2000000)$fatal(1,"verify timeout state=%0d node=%0d",`HBS_CORE.state,node_sent);
   if(out_valid || keygen_done)$fatal(1,"verify generated a signing output");
   if(error && !fault)$fatal(1,"verify error %h",error_code);
   if(`HBS_CORE.state==35 /* VERIFY_CHAIN_INPUT */ && `HBS_CORE.indexing!=1)begin
    if(`HBS_CORE.task_b[`HBS_CORE.verify_lane]==15)zero_steps=zero_steps+1;
    if(`HBS_CORE.task_b[`HBS_CORE.verify_lane]==0)full_steps=full_steps+1;
   end
  end
 end
 initial begin
  if(!$value$plusargs("IMAGE=%s",image_dir))$fatal(1,"IMAGE required");
  if(!$value$plusargs("VECTOR=%s",vector_dir))$fatal(1,"VECTOR required");
  if($value$plusargs("STALL=%d",stall))begin end
  if($value$plusargs("REPLAY=%d",replay))begin end
  if($value$plusargs("CUT=%d",cut))begin end
  if($value$plusargs("FAULT=%d",fault))begin end
  if($value$plusargs("FLIP=%d",flip))begin end
  if($value$plusargs("BAD_MESSAGE=%d",bad_message))begin end
  if($value$plusargs("EXPECT=%d",expected))begin end
  if($value$plusargs("ABORT_AT=%d",abort_at))begin end
  $readmemh({image_dir,"/program.mem"},dut.program_memory);
  $readmemh({image_dir,"/template.mem"},dut.template_memory);
  $readmemh({image_dir,"/descriptor.mem"},dut.descriptor_memory);
  $readmemh({vector_dir,"/nodes.mem"},nodes,0,NODES-1);
  $readmemh({vector_dir,"/message.mem"},message_bytes,0,MESSAGE_BYTES-1);
  if(flip>=0)nodes[flip][0]=~nodes[flip][0];
  if(bad_message)message_bytes[0]=message_bytes[0]^1;
  repeat(4)tick();rst=0;
  if(abort_at)begin
   while(node_sent<abort_at)tick();repeat(7)tick();rst=1;repeat(4)tick();rst=0;
  end
  if(cut)begin
   while(node_sent<cut)tick();
   repeat(1500)tick();
   if(done || error || !busy || !verify_ready || verify_pass)$fatal(1,"truncated node supply completed");
   rst=1;repeat(4)tick();cut=0;rst=0;
  end
  if(fault)begin
   while(!(`HBS_CORE.lane_valid[0] && `HBS_CORE.response_pending[0]))tick();
   force `HBS_CORE.lanes[0].lane.error=1;
   while(!error)tick();
   if(error_code!=16'h3007)$fatal(1,"fault code");
   repeat(40)begin tick();if(busy || done || verify_ready || verify_pass)$fatal(1,"fault halt");end
   $display("VERIFY_FAULT_PASS");$finish;
  end
  for(integer run=0;run<=replay;run=run+1)begin
   while(!done)tick();
   if(verify_pass!==expected[0] || node_sent!=NODES || result_kind!=2 || error)
    $fatal(1,"verify result=%0d expected=%0d nodes=%0d/%0d",verify_pass,expected,node_sent,NODES);
   if(PROFILE_ENABLE)begin
    if(hash_count!=hashes[0]+hashes[1] || permutation_count!=permutations[0]+permutations[1])$fatal(1,"verify statistics");
   end else if({boot_cycles,keygen_cycles,sign_cycles,hash_count,permutation_count}!==160'd0)$fatal(1,"statistics not pruned");
   if(keygen_cycles!=0 || sign_cycles!=0)$fatal(1,"verify polluted sign/keygen cycles");
   $display("VERIFY_PASS accepted=%0d nodes=%0d cycles=%0d waits=%0d hashes=%0d permutations=%0d zero=%0d full=%0d",verify_pass,node_sent,cycles,wait_cycles,hashes[0]+hashes[1],permutations[0]+permutations[1],zero_steps,full_steps);
   repeat(40)begin tick();if(!done || busy || verify_ready || message_ready)$fatal(1,"completion halt");end
   if(run<replay)begin rst=1;repeat(4)tick();rst=0;end
  end
  $finish;
 end
endmodule
