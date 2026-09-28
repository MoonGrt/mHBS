`timescale 1ns/1ps
`ifdef MHBS_PARTITIONED
`define HBS_CORE dut.common.core
`else
`define HBS_CORE dut.core
`endif
module tb_mhbs_verify;
 parameter [255:0] PUBLIC_SEED=0,PUBLIC_ROOT=0;
 parameter integer MESSAGE_BYTES=1,NODE_BYTES=16,NODES=1068,SWAP=0,LANES=2,UNROLL=2;
 parameter bit PROFILE_ENABLE=1;
 logic clk=0,rst=1;
 wire busy,done,keygen_done,error,out_valid,verify_ready,verify_pass,message_ready;
 wire [1:0] result_kind;
 wire [15:0] error_code;wire [31:0] boot_cycles,keygen_cycles,sign_cycles,hash_count,permutation_count;
 wire [255:0] out_data;wire [5:0] out_bytes;
 logic [63:0] message_data=0;logic message_valid=0,verify_valid=0;
 logic [255:0] verify_data=0;
 wire [6:0] message_length=MESSAGE_BYTES;
 reg [255:0] nodes[0:4095];reg [7:0] message_bytes[0:86];
 integer sent=0,node_sent=0,cycles=0,wait_cycles=0,stall=0,replay=0,cut=0,fault=0;
 integer expected=1,flip=-1,bad_message=0,abort_at=0;
 integer delay_at=-1,delay_cycles=0,delay_left=0,poison_reset=0,abort_delay=7,noise=0;
 integer asymmetric=0,zero_left=0,zero_right=0,both_zero=0,auth_left=0,auth_right=0;
 reg [LANES-1:0] bypass_expected=0;reg [255:0] bypass_node[0:LANES-1];
 integer hashes[0:LANES-1],permutations[0:LANES-1],zero_steps=0,full_steps=0;
 integer total_hashes,total_permutations;
 always_comb begin total_hashes=0;total_permutations=0;for(integer h=0;h<LANES;h=h+1)begin total_hashes=total_hashes+hashes[h];total_permutations=total_permutations+permutations[h];end end
 reg [31:0] rng=32'h15c0ffee;
 string image_dir,vector_dir;
 mhbs_top #(.PUBLIC_SEED(PUBLIC_SEED),.PUBLIC_ROOT(PUBLIC_ROOT),.OPERATION(2),
 .PROFILE_ENABLE(PROFILE_ENABLE),.SWAP_PHYSICAL_LANES(SWAP),.LANES(LANES),.UNROLL(UNROLL),
 .PROGRAM_INIT_FILE(""),.TEMPLATE_INIT_FILE(""),.DESCRIPTOR_INIT_FILE("")) dut(.*);
 always #5 clk=~clk;
 `include "tb/integration/mhbs_shared_store_check.svh"
 task tick;begin @(posedge clk);#1;end endtask
 genvar l;
 generate for(l=0;l<LANES;l=l+1)begin: observe
  always @(posedge clk)begin
   if(`HBS_CORE.execution_rst)begin hashes[l]=0;permutations[l]=0;end
   else if(`HBS_CORE.lanes[l].lane.sponge.lane_state==2 &&
           `HBS_CORE.lanes[l].lane.sponge.round_index+UNROLL>=24)begin
    permutations[l]=permutations[l]+1;
    if(`HBS_CORE.lanes[l].lane.sponge.running_last)hashes[l]=hashes[l]+1;
   end
  end
 end endgenerate
 always @(negedge clk)begin
  if(rst)begin message_valid=0;verify_valid=0;message_data=0;verify_data=0;rng=32'h15c0ffee;delay_left=delay_cycles;end
  else begin
   rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
   if(!(message_valid && !message_ready))begin
    message_valid=sent<MESSAGE_BYTES && (!stall || rng[2:0]!=0);
    message_data=0;
    for(integer i=0;i<8;i=i+1)if(sent+i<MESSAGE_BYTES)message_data[8*i +:8]=message_bytes[sent+i];
   end
   if(!(verify_valid && !verify_ready))begin
    verify_valid=node_sent<NODES && (!cut || node_sent<cut) && (!stall || rng[1:0]!=0);
    if(node_sent==delay_at && delay_left>0)begin verify_valid=0;delay_left=delay_left-1;end
    verify_data=nodes[node_sent];
    if(noise)for(integer i=NODE_BYTES;i<32;i=i+1)verify_data[8*i +:8]=8'ha5;
   end
  end
 end
 always @(posedge clk)begin
  if(rst)begin sent=0;node_sent=0;cycles=0;wait_cycles=0;bypass_expected=0;zero_steps=0;full_steps=0;asymmetric=0;zero_left=0;zero_right=0;both_zero=0;auth_left=0;auth_right=0;end
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
   if(`HBS_CORE.state==8 /* CHAIN_STORE */ && `HBS_CORE.indexing!=1)begin
    for(integer i=0;i<LANES;i=i+1)if(`HBS_CORE.active_mask[i] && bypass_expected[i])
     for(integer b=0;b<NODE_BYTES;b=b+1)
      if(`HBS_CORE.result[i][8*b +:8]!==bypass_node[i][8*b +:8])$fatal(1,"zero-step endpoint changed lane=%0d",i);
   end
   if(`HBS_CORE.state==35 /* VERIFY_CHAIN_INPUT */ && `HBS_CORE.indexing!=1)begin
    if(!`HBS_CORE.verify_lane)bypass_expected=0;
    bypass_expected[`HBS_CORE.verify_lane]=`HBS_CORE.task_b[`HBS_CORE.verify_lane]==15;
    bypass_node[`HBS_CORE.verify_lane]=nodes[node_sent-1];
    if(`HBS_CORE.task_b[`HBS_CORE.verify_lane]==15)zero_steps=zero_steps+1;
    if(`HBS_CORE.task_b[`HBS_CORE.verify_lane]==0)full_steps=full_steps+1;
    if(`HBS_CORE.verify_lane==1 && LANES>=2)begin
     if(`HBS_CORE.task_b[0]!=`HBS_CORE.task_b[1])asymmetric=asymmetric+1;
     if(`HBS_CORE.task_b[0]==15 && `HBS_CORE.task_b[1]!=15)zero_left=zero_left+1;
     if(`HBS_CORE.task_b[1]==15 && `HBS_CORE.task_b[0]!=15)zero_right=zero_right+1;
     if(`HBS_CORE.task_b[0]==15 && `HBS_CORE.task_b[1]==15)both_zero=both_zero+1;
    end
   end
   if(`HBS_CORE.state==18 /* PARENT_SETUP */)begin
    if(`HBS_CORE.node_index[0])auth_left=auth_left+1;else auth_right=auth_right+1;
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
  if($value$plusargs("ABORT_DELAY=%d",abort_delay))begin end
  if($value$plusargs("POISON_RESET=%d",poison_reset))begin end
  if($value$plusargs("DELAY_AT=%d",delay_at))begin end
  if($value$plusargs("DELAY_CYCLES=%d",delay_cycles))begin end
  if($value$plusargs("NOISE=%d",noise))begin end
  $readmemh({image_dir,"/program.mem"},dut.program_memory);
  $readmemh({image_dir,"/template.mem"},dut.template_memory);
  $readmemh({image_dir,"/descriptor.mem"},dut.descriptor_memory);
  $readmemh({vector_dir,"/nodes.mem"},nodes,0,NODES-1);
  $readmemh({vector_dir,"/message.mem"},message_bytes,0,MESSAGE_BYTES-1);
  if(flip>=0)nodes[flip][0]=~nodes[flip][0];
  if(bad_message)message_bytes[0]=message_bytes[0]^bad_message[7:0];
  if(poison_reset)nodes[0][0]=~nodes[0][0];
  repeat(4)tick();rst=0;
  if(abort_at)begin
   while(node_sent<abort_at)tick();repeat(abort_delay)tick();rst=1;repeat(4)tick();
   if(poison_reset)nodes[0][0]=~nodes[0][0];rst=0;
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
    if(hash_count!=total_hashes || permutation_count!=total_permutations)$fatal(1,"verify statistics");
   end else if({boot_cycles,keygen_cycles,sign_cycles,hash_count,permutation_count}!==160'd0)$fatal(1,"statistics not pruned");
   if(keygen_cycles!=0 || sign_cycles!=0)$fatal(1,"verify polluted sign/keygen cycles");
   $display("VERIFY_PASS accepted=%0d nodes=%0d cycles=%0d waits=%0d hashes=%0d permutations=%0d zero=%0d full=%0d",verify_pass,node_sent,cycles,wait_cycles,total_hashes,total_permutations,zero_steps,full_steps);
   $display("VERIFY_COVERAGE asymmetric=%0d zero_left=%0d zero_right=%0d both_zero=%0d auth_left=%0d auth_right=%0d",asymmetric,zero_left,zero_right,both_zero,auth_left,auth_right);
   repeat(40)begin tick();if(!done || busy || verify_ready || message_ready)$fatal(1,"completion halt");end
   if(run<replay)begin rst=1;repeat(4)tick();rst=0;end
  end
  $finish;
 end
endmodule
