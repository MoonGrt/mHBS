`timescale 1ns/1ps
module tb_mhbs_chain_overlap;
 parameter integer UNROLL=1,PIPELINE=2;
 logic clk=0,rst=1,request_valid=0,response_ready=0;
 logic [1:0] request_tag=0;
 wire request_ready,response_valid;
 wire [1:0] response_tag;
 wire [255:0] response_digest,response_capture;
 logic [5:0] node_bytes;
 logic [4:0] request_steps,request_capture_after,request_layer;
 logic request_capture=1;
 logic [9:0] request_leaf;
 logic [6:0] request_a;
 logic [31:0] request_b;
 logic [63:0] request_tree;
 logic [7:0] seed_domain,step_domain;
 wire [255:0] secret_seed=256'h1f1e1d1c1b1a191817161514131211100f0e0d0c0b0a09080706050403020100;
 wire [255:0] public_seed=256'h3f3e3d3c3b3a393837363534333231302f2e2d2c2b2a29282726252423222120;
 logic [1:0] read_tag=0;wire [255:0] read_digest,read_capture;
 wire pv,pr,pd;wire [1599:0] ps,po;wire [1:0] pt,ot;
 wire [31:0] hash_count,permutation_count;
 mhbs_chain_pipeline_lane #(.PIPELINE(PIPELINE),.PROFILE_ENABLE(1)) dut(
  .clk,.rst,.node_bytes,.request_valid,.request_ready,.request_tag,
  .request_steps,.request_capture_after,.request_capture,.secret_seed,.public_seed,
  .request_layer,.request_tree,.request_leaf,.request_a,.request_b,.seed_domain,.step_domain,
  .response_valid,.response_ready,.response_tag,.response_digest,.response_capture,
  .perm_valid(pv),.perm_ready(pr),.perm_state(ps),.perm_tag(pt),.perm_done(pd),.perm_digest(po),.perm_result_tag(ot),
  .read_tag,.read_digest,.read_capture,.hash_count,.permutation_count);
 mhbs_keccak_pipeline #(.UNROLL(UNROLL),.PIPELINE(PIPELINE)) pipe(
  .clk,.rst,.request_valid(pv),.request_ready(pr),.request_state(ps),.request_tag(pt),
  .response_valid(pd),.response_state(po),.response_tag(ot));
 reg [255:0] requests[0:95],digests[0:95],captures[0:95];
 integer ids[0:3],received=0,expected_hashes=0,observed=0,cycles=0,max_live=0,live=0;
 reg [3:0] pending=0;
 reg held=0;reg [1:0] hold_tag;reg [255:0] hold_digest,hold_capture;
 string dir;
 always #5 clk=~clk;
 always @(posedge clk)begin
  if(rst)begin pending=0;held=0;expected_hashes=0;observed=0;live=0;end
  else begin
   cycles=cycles+1;
   if(cycles>100000)$fatal(1,"overlap timeout");
   if(pd)observed=observed+1;
   if(held && (!response_valid || response_tag!==hold_tag || response_digest!==hold_digest || response_capture!==hold_capture))$fatal(1,"response changed under backpressure");
   held=response_valid && !response_ready;
   hold_tag=response_tag;hold_digest=response_digest;hold_capture=response_capture;
   if(request_valid && request_ready)begin pending[request_tag]=1;live=live+1;expected_hashes=expected_hashes+request_steps+1;end
   if(live>max_live)max_live=live;
   if(response_valid && response_ready)begin
    if(!pending[response_tag])$fatal(1,"stale/duplicate completion");
    for(integer b=0;b<32;b=b+1)if(b<node_bytes)begin
     if(response_digest[b*8 +:8]!==digests[ids[response_tag]][b*8 +:8])$fatal(1,"digest id=%0d",ids[response_tag]);
     if(response_capture[b*8 +:8]!==captures[ids[response_tag]][b*8 +:8])$fatal(1,"capture id=%0d",ids[response_tag]);
    end
    pending[response_tag]=0;received=received+1;live=live-1;
   end
  end
 end
 task load(input integer id,input integer tag);
  begin
   ids[tag]=id;request_tag=2'(tag);
   node_bytes=requests[id][5:0];request_steps=requests[id][12:8];request_capture_after=requests[id][20:16];
   step_domain=requests[id][31:24];seed_domain=step_domain==3 ? 6 : 5;
   request_a=requests[id][38:32];request_b=requests[id][71:40];request_leaf=requests[id][81:72];
   request_tree=requests[id][151:88];request_layer=requests[id][156:152];request_valid=1;
  end
 endtask
 initial begin
  if(!$value$plusargs("VECTORS=%s",dir))$fatal(1,"vectors required");
  $readmemh({dir,"/chain_requests.mem"},requests);$readmemh({dir,"/chain_digest.mem"},digests);$readmemh({dir,"/chain_capture.mem"},captures);
  repeat(3)@(negedge clk);rst=0;
  // Cancel an occupied pipeline, then immediately reuse every tag.
  load(0,0);do @(posedge clk);while(!request_ready);
  @(negedge clk);request_valid=0;repeat(3)@(negedge clk);rst=1;
  repeat(2)@(negedge clk);rst=0;
  for(integer width=0;width<3;width=width+1)begin
   for(integer base=0;base<32;base=base+PIPELINE)begin
    response_ready=0;
    for(integer t=0;t<PIPELINE && base+t<32;t=t+1)begin
     load(width*32+base+t,t);
     do @(posedge clk);while(!request_ready);
     @(negedge clk);request_valid=0;
     if(t==0)repeat(27)@(negedge clk); // second request arrives after short first chain can finish
    end
    repeat(420)@(negedge clk);
    while(pending!=0)begin response_ready=($random & 3)!=0;@(negedge clk);end
    response_ready=0;
    for(integer t=0;t<PIPELINE && base+t<32;t=t+1)begin
     read_tag=2'(t);repeat(2)@(negedge clk);
     for(integer b=0;b<32;b=b+1)if(b<node_bytes)begin
      if(read_digest[b*8 +:8]!==digests[ids[t]][b*8 +:8])$fatal(1,"retained digest");
      if(read_capture[b*8 +:8]!==captures[ids[t]][b*8 +:8])$fatal(1,"retained capture");
     end
    end
    if(hash_count!=expected_hashes || permutation_count!=observed || observed!=expected_hashes)$fatal(1,"counters");
   end
  end
  if(max_live<PIPELINE)$fatal(1,"no full overlap");
  $display("CHAIN_OVERLAP_PASS U=%0d P=%0d cases=%0d max_live=%0d",UNROLL,PIPELINE,received,max_live);$finish;
 end
endmodule
