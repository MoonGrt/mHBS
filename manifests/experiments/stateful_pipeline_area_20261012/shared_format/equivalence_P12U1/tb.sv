`timescale 1ns/1ps
// Independent Python SHAKE vectors exercise the production shared datapath.
module tb_mhbs_stateful_pipeline;
 parameter integer PIPELINE=4,UNROLL=1;
 localparam integer T=$clog2(PIPELINE), CASES=72;
 logic clk=0,rst=1,valid=0,ready_out=0;
 always #5 clk=~clk;
 logic [T-1:0] tag=0,read_tag=0;
 wire ready,done;wire [T-1:0] done_tag;
 logic [511:0] req=0;
 wire [255:0] result,capture,read_result,read_capture;
 wire [31:0] hashes,perms;
 wire [255:0] secret_seed=256'h1f1e1d1c1b1a191817161514131211100f0e0d0c0b0a09080706050403020100;
 wire [255:0] public_seed=256'h5f5e5d5c5b5a595857565554535251504f4e4d4c4b4a49484746454443424140;
 mhbs_recipe_lane #(.N(32),.DIGEST_BYTES(49),.INDEX_BITS(8),.PIPELINE(PIPELINE),.UNROLL(UNROLL),.PROFILE_ENABLE(1)) dut(
  .clk,.rst,.batch_mode(1'b1),.batch_request_valid(valid),.batch_request_ready(ready),.batch_request_tag(tag),
  .batch_family(req[1:0]),.batch_no_seed(req[2]),.batch_start(req[7:4]),.batch_steps(req[12:8]),
  .batch_capture_after(req[20:16]),.batch_capture_enable(req[21]),.batch_a(req[31:24]),.batch_leaf(req[41:32]),
  .batch_b(32'd0),.batch_initial_value(req[511:256]),.batch_seed_domain(8'd0),.batch_step_domain(8'd0),
  .batch_read_tag(read_tag),.batch_read_digest(read_result),.batch_read_capture(read_capture),
  .batch_response_valid(done),.batch_response_ready(ready_out),.batch_response_tag(done_tag),
  .batch_response_digest(result),.batch_response_capture(capture),.batch_hashes(hashes),.batch_permutations(perms),
  .secret_seed,.public_seed,.identifier(128'h0f0e0d0c0b0a09080706050403020100),.node_bytes(6'd32),
  .request_valid(1'b0),.request_recipe(64'd0),.request_step_recipe(64'd0),.request_chain(1'b0),
  .request_steps(5'd0),.request_capture_after(5'd0),.request_capture(1'b0),.request_layer(5'd0),.request_tree(64'd0),
  .secret_prf(256'd0),.root(256'd0),.randomizer(256'd0),.message_buffer(696'd0),.message_length(7'd0),
  .request_leaf(10'd0),.request_a(8'd0),.request_b(32'd0),.request_left(256'd0),.request_right(256'd0),
  .list_data0(256'd0),.list_data1(256'd0),.response_ready(1'b0));
 `include "tb/unit/mhbs_recipe_round_check.svh"
 reg [511:0] requests[0:CASES-1];reg [255:0] results[0:CASES-1],captures[0:CASES-1];
 integer ids[0:PIPELINE-1],received=0,count=0,observed=0,live=0,max_live=0,cycles=0;
 reg [PIPELINE-1:0] pending=0;
 reg held=0;reg [T-1:0] held_tag;reg [255:0] held_result,held_capture;
 string dir;
 always @(posedge clk)begin
  if(rst)begin pending=0;held=0;count=0;observed=0;live=0;end
  else begin
   cycles++;
   if(cycles>200000)$fatal(1,"unit timeout");
   if(dut.batch_perm_done)observed++;
   if(held && (!done || done_tag!==held_tag || result!==held_result || capture!==held_capture))$fatal(1,"held response changed");
   held=done&&!ready_out;held_tag=done_tag;held_result=result;held_capture=capture;
   if(valid&&ready)begin
    if(pending[tag])$fatal(1,"busy slot reused");
    pending[tag]=1;live++;count+=(req[2]?0:1)+req[12:8]*(req[1:0]==1?3:1);
   end
   if(live>max_live)max_live=live;
   if(done&&ready_out)begin
    if(!pending[done_tag] || result!==results[ids[done_tag]] || capture!==captures[ids[done_tag]])
     $fatal(1,"stateful result id=%0d result=%h expected=%h capture=%h expected=%h",ids[done_tag],result,results[ids[done_tag]],capture,captures[ids[done_tag]]);
    pending[done_tag]=0;live--;received++;
   end
   if(dut.batch_perm_done && dut.chain_pipeline.engine.again && !dut.batch_perm_ready)$fatal(1,"feedback lost");
  end
 end
 task load(input integer id,input integer slot);
  begin ids[slot]=id;tag=T'(slot);req=requests[id];valid=1;end
 endtask
 initial begin
  if(!$value$plusargs("VECTORS=%s",dir))$fatal(1,"vectors");
  $readmemh({dir,"/requests.mem"},requests);$readmemh({dir,"/results.mem"},results);$readmemh({dir,"/captures.mem"},captures);
  repeat(3)@(negedge clk);rst=0;
  load(0,PIPELINE-1);do @(posedge clk);while(!ready);
  @(negedge clk);valid=0;repeat(9)@(negedge clk);rst=1;
  repeat(2)@(negedge clk);rst=0;
  for(integer base=0;base<CASES;base+=PIPELINE)begin
   ready_out=0;
   for(integer slot=0;slot<PIPELINE && base+slot<CASES;slot++)begin
    load(base+slot,slot);do @(posedge clk);while(!ready);
    @(negedge clk);valid=0;
    if(slot==0 && base%2)repeat(37)@(negedge clk);
   end
   repeat(50)@(negedge clk);
   while(pending!=0)begin ready_out=($random&3)!=0;@(negedge clk);end
   ready_out=0;
   for(integer slot=0;slot<PIPELINE && base+slot<CASES;slot++)begin
    read_tag=T'(slot);@(negedge clk);
    if(read_result!==results[ids[slot]] || read_capture!==captures[ids[slot]])$fatal(1,"retained storage");
   end
   if(hashes!=count||perms!=count||observed!=count)$fatal(1,"counts %0d %0d %0d",hashes,observed,count);
  end
  if(max_live!=PIPELINE)$fatal(1,"highest tag/overlap");
  $display("STATEFUL_PIPE_UNIT_PASS P%0dU%0d cases=%0d max_live=%0d",PIPELINE,UNROLL,received,max_live);$finish;
 end

wire [0:0] ready_ref;
wire [0:0] done_ref;
wire [3:0] done_tag_ref;
wire [255:0] result_ref;
wire [255:0] capture_ref;
wire [255:0] read_result_ref;
wire [255:0] read_capture_ref;
wire [31:0] hashes_ref;
wire [31:0] perms_ref;
 mhbs_recipe_lane_area_ref #(.N(32),.DIGEST_BYTES(49),.INDEX_BITS(8),.PIPELINE(PIPELINE),.UNROLL(UNROLL),.PROFILE_ENABLE(1)) ref_dut(
  .clk,.rst,.batch_mode(1'b1),.batch_request_valid(valid),.batch_request_ready(ready_ref),.batch_request_tag(tag),
  .batch_family(req[1:0]),.batch_no_seed(req[2]),.batch_start(req[7:4]),.batch_steps(req[12:8]),
  .batch_capture_after(req[20:16]),.batch_capture_enable(req[21]),.batch_a(req[31:24]),.batch_leaf(req[41:32]),
  .batch_b(32'd0),.batch_initial_value(req[511:256]),.batch_seed_domain(8'd0),.batch_step_domain(8'd0),
  .batch_read_tag(read_tag),.batch_read_digest(read_result_ref),.batch_read_capture(read_capture_ref),
  .batch_response_valid(done_ref),.batch_response_ready(ready_out),.batch_response_tag(done_tag_ref),
  .batch_response_digest(result_ref),.batch_response_capture(capture_ref),.batch_hashes(hashes_ref),.batch_permutations(perms_ref),
  .secret_seed,.public_seed,.identifier(128'h0f0e0d0c0b0a09080706050403020100),.node_bytes(6'd32),
  .request_valid(1'b0),.request_recipe(64'd0),.request_step_recipe(64'd0),.request_chain(1'b0),
  .request_steps(5'd0),.request_capture_after(5'd0),.request_capture(1'b0),.request_layer(5'd0),.request_tree(64'd0),
  .secret_prf(256'd0),.root(256'd0),.randomizer(256'd0),.message_buffer(696'd0),.message_length(7'd0),
  .request_leaf(10'd0),.request_a(8'd0),.request_b(32'd0),.request_left(256'd0),.request_right(256'd0),
  .list_data0(256'd0),.list_data1(256'd0),.response_ready(1'b0));
 reg [PIPELINE-1:0] readable=0;
 integer concurrent_accept_return=0, initial_transfers=0;
 always @(posedge clk)begin
  if(rst)readable=0;
  else begin
   if(valid&&ready)readable[tag]=req[2];
   if(dut.batch_perm_done && dut.chain_pipeline.engine.node_done)
    readable[dut.batch_perm_result_tag]=1;
   if(valid&&ready&&dut.batch_perm_done)concurrent_accept_return++;
  end
 end
 always @(negedge clk)if(!rst)begin
  if({ready,done,hashes,perms}!=={ready_ref,done_ref,hashes_ref,perms_ref})$fatal(1,"cycle control equivalence");
  if(done && {done_tag,result,capture}!=={done_tag_ref,result_ref,capture_ref})$fatal(1,"cycle result equivalence");
  if(read_capture!==read_capture_ref)$fatal(1,"cycle capture equivalence");
  if(readable[read_tag] && read_result!==read_result_ref)$fatal(1,"cycle digest equivalence");
  if({dut.batch_perm_valid,dut.batch_perm_ready,dut.batch_perm_done}!=={ref_dut.batch_perm_valid,ref_dut.batch_perm_ready,ref_dut.batch_perm_done})$fatal(1,"cycle permutation handshake");
  if(dut.batch_perm_valid && {dut.batch_perm_tag,dut.batch_perm_state}!=={ref_dut.batch_perm_tag,ref_dut.batch_perm_state})$fatal(1,"cycle block equivalence");
 end
endmodule
