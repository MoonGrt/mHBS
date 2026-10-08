`timescale 1ns/1ps
// Frozen adapter oracle: legal interleaved completions, deterministic stalls,
// all node widths, disabled/missed captures, tag reuse and simultaneous events.
module tb_mhbs_chain_format_equiv;
 parameter integer PIPELINE=4;
 logic clk=0,rst=1;
 always #5 clk=~clk;
 logic [5:0] node_bytes=16;
 logic request_valid=0,response_ready=0,perm_ready=1,perm_done=0;
 logic [1:0] request_tag=0,read_tag=0,perm_result_tag=0;
 logic [4:0] request_steps=0,request_capture_after=0,request_layer=0;
 logic request_capture=0;
 logic [255:0] secret_seed=256'hdeadbeef,public_seed=256'hfeed1234;
 logic [63:0] request_tree=0;
 logic [9:0] request_leaf=0;
 logic [6:0] request_a=0;
 logic [31:0] request_b=0;
 logic [7:0] seed_domain=5,step_domain=0;
 logic [1599:0] perm_digest=0;
 wire request_ready,response_valid,perm_valid;
 wire [1:0] response_tag,perm_tag;
 wire [255:0] read_digest,read_capture,response_digest,response_capture;
 wire [1599:0] perm_state;
 wire [1:0] block_family;
 wire [2:0] block_phase;
 wire [3:0] block_step;
 wire [255:0] block_address,block_value,block_key;
 reg [1599:0] test_block;
 always @* begin
  test_block=0;
  case(node_bytes)
   16:begin test_block[511:0]={block_value[127:0],block_address,public_seed[127:0]};test_block[519:512]=8'h1f;end
   24:begin test_block[639:0]={block_value[191:0],block_address,public_seed[191:0]};test_block[647:640]=8'h1f;end
   default:begin test_block[767:0]={block_value,block_address,public_seed};test_block[775:768]=8'h1f;end
  endcase
  test_block[1087]=1;
 end
 assign perm_state=test_block;
 wire [31:0] hash_count,permutation_count;
 wire rr,rv,pv;wire [1:0] rt,pt;
 wire [255:0] rd,rc,vd,vc;wire [1599:0] ps;wire [31:0] hc,pc;
 mhbs_chain_pipeline_lane #(.PIPELINE(PIPELINE),.PROFILE_ENABLE(1)) dut(
 .request_family(2'd0),.request_no_seed(1'b0),.request_start(4'd0),
 .request_initial_value(256'd0),.identifier(128'd0),.*);
 mhbs_chain_pipeline_lane_ref #(.PIPELINE(PIPELINE),.PROFILE_ENABLE(1)) ref_dut(
 .clk,.rst,.node_bytes,.request_valid,.request_tag,.request_steps,.request_capture_after,.request_capture,
 .secret_seed,.public_seed,.request_layer,.request_tree,.request_leaf,.request_a,.request_b,.seed_domain,.step_domain,
 .read_tag,.response_ready,.perm_ready,.perm_done,.perm_digest,.perm_result_tag,
 .request_ready(rr),.read_digest(rd),.read_capture(rc),.response_valid(rv),.response_tag(rt),
 .response_digest(vd),.response_capture(vc),.perm_valid(pv),.perm_state(ps),.perm_tag(pt),.hash_count(hc),.permutation_count(pc));
 logic [PIPELINE-1:0] pending=0,known=0;
 integer cycle=0,accepted=0,simultaneous=0;
 always @(posedge clk)if(!rst)begin
  if({request_ready,response_valid,perm_valid,hash_count,permutation_count}!=={rr,rv,pv,hc,pc})$fatal(1,"control mismatch");
  if(perm_valid && {perm_state,perm_tag}!=={ps,pt})$fatal(1,"block/tag mismatch");
  if(response_valid && {response_tag,response_digest,response_capture}!=={rt,vd,vc})$fatal(1,"response mismatch");
  if(known[read_tag] && read_capture!==rc)$fatal(1,"capture readback mismatch");
  if(request_valid && request_ready)begin known[request_tag]=1;accepted=accepted+1;if(perm_done)simultaneous=simultaneous+1;end
  if(perm_done)pending[perm_result_tag]=0;
  if(perm_valid && perm_ready)pending[perm_tag]=1;
  if($test$plusargs("DEBUG") && cycle<25)$display("DEBUG cycle=%0d req=%b/%b tag=%0d perm=%b/%b tag=%0d done=%b pending=%b busy=%b complete=%b",cycle,request_valid,request_ready,request_tag,perm_valid,perm_ready,perm_tag,perm_done,pending,dut.busy,dut.complete);
  cycle++;
 end
 initial begin
  for(integer width=0;width<3;width=width+1)begin
   @(negedge clk);rst=1;request_valid=0;perm_done=0;pending=0;known=0;
   repeat(2)@(negedge clk);rst=0;node_bytes=6'(16+8*width);
   for(integer i=0;i<600;i=i+1)begin
    @(negedge clk);
    request_valid=i<500 && i%5!=0;request_tag=2'(i%PIPELINE);read_tag=2'((i/3)%PIPELINE);
    request_steps=5'(i%6);request_capture_after=5'((i/7)%8);request_capture=i%3!=0;
    request_b=32'hffffffff-i;request_a=7'(i);request_leaf=10'(i*3);request_tree=64'hfedcba9876543210+i;request_layer=5'(i);
    step_domain=i%2 ? 3 : 0;seed_domain=i%2 ? 6 : 5;response_ready=i%7!=0;
    perm_done=0;
    for(integer t=PIPELINE-1;t>=0;t=t-1)if(pending[t])begin perm_done=1;perm_result_tag=2'(t);end
    perm_ready=perm_done || i%4!=0;
    for(integer w=0;w<50;w=w+1)perm_digest[w*32 +:32]=$random;
   end
  end
  @(negedge clk);request_valid=0;
  if(accepted<30 || (PIPELINE>1 && simultaneous==0))$fatal(1,"coverage missing accepted=%0d simultaneous=%0d",accepted,simultaneous);
  $display("CHAIN_FORMAT_EQUIV_PASS P=%0d accepted=%0d simultaneous=%0d",PIPELINE,accepted,simultaneous);$finish;
 end
endmodule
