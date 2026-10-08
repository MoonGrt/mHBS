`timescale 1ns/1ps
// Frozen adapter oracle: legal interleaved completions, deterministic stalls,
// all node widths, disabled/missed captures, tag reuse and simultaneous events.
module tb_mhbs_chain_format_equiv;
 parameter integer PIPELINE=4;
 logic clk=0,rst=1;
 always #5 clk=~clk;
 logic [5:0] node_bytes=16;
 logic request_valid=0,response_ready=0,perm_ready=1,perm_done=0;
 localparam integer T=$clog2(PIPELINE);
 logic [T-1:0] request_tag=0,read_tag=0,perm_result_tag=0;
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
 wire [T-1:0] response_tag,perm_tag;
 wire [255:0] read_digest,read_capture,response_digest,response_capture;
 wire [1599:0] perm_state;

 localparam [2:0] SEED=0,STEP=1,KEY=2,MASK=3,FINAL=4;
 wire [1:0] block_family;wire [2:0] block_phase;wire [3:0] block_step;
 wire [255:0] block_address,block_value,block_key;
 function automatic [31:0] be32(input [31:0] v);be32={v[7:0],v[15:8],v[23:16],v[31:24]};endfunction
 function automatic [1599:0] block_for(input [255:0] adr,input [255:0] val);
  reg [1599:0] block_data;
  begin
   block_data=0;
   case(node_bytes)
    16:begin block_data[511:0]={val[127:0],adr,public_seed[127:0]};block_data[512 +:8]=8'h1f;end
    24:begin block_data[639:0]={val[191:0],adr,public_seed[191:0]};block_data[640 +:8]=8'h1f;end
    default:begin block_data[767:0]={val,adr,public_seed};block_data[768 +:8]=8'h1f;end
   endcase
   block_data[1087]=1;block_for=block_data;
  end
 endfunction
 function automatic [1599:0] stateful_block(input [1:0] kind,input [2:0] subphase,
     input [255:0] adr,val,key,input [3:0] step);
  reg [1599:0] data;
  reg [255:0] masked_address;
  begin
   data=0;
   masked_address={be32(subphase==MASK ? 32'd1 : 32'd0),be32({28'd0,step}),adr[223:192],adr[191:160],adr[159:128],96'd0};
   if(kind==2)begin
    data[127:0]=identifier;data[159:128]=adr[191:160];
    data[167:160]=0;data[175:168]=adr[223:216];data[183:176]=subphase==SEED ? 8'hff : {4'd0,step};
    data[439:184]=val;data[447:440]=8'h1f;
   end else if(subphase==SEED)begin
    // XMSS seed domain: 32-byte 4 || SK.seed || PK.seed || ADRS || 0.
    data[255:248]=8'd4;data[511:256]=secret_seed;data[767:512]=public_seed;
    data[1023:768]=masked_address;data[1031:1024]=8'h1f;
   end else if(subphase==KEY || subphase==MASK)begin
    data[255:248]=8'd3;data[511:256]=public_seed;data[767:512]=masked_address;data[775:768]=8'h1f;
   end else begin
    data[511:256]=key;data[767:512]=val;data[775:768]=8'h1f;
   end
   data[1087]=1;stateful_block=data;
  end
 endfunction

 assign perm_state=block_family==0 ? block_for(block_address,block_value) : stateful_block(block_family,block_phase,block_address,block_value,block_key,block_step);
 wire [31:0] hash_count,permutation_count;
 wire rr,rv,pv;wire [T-1:0] rt,pt;
 wire [255:0] rd,rc,vd,vc;wire [1599:0] ps;wire [31:0] hc,pc;
 mhbs_chain_pipeline_lane #(.PIPELINE(PIPELINE),.PROFILE_ENABLE(1)) dut(
 .request_family,.request_no_seed,.request_start,.request_initial_value,.identifier,.*);
 mhbs_chain_pipeline_lane_ref #(.PIPELINE(PIPELINE),.PROFILE_ENABLE(1)) ref_dut(
 .request_family,.request_no_seed,.request_start,.request_initial_value,.identifier,.clk,.rst,.node_bytes,.request_valid,.request_tag,.request_steps,.request_capture_after,.request_capture,
 .secret_seed,.public_seed,.request_layer,.request_tree,.request_leaf,.request_a,.request_b,.seed_domain,.step_domain,
 .read_tag,.response_ready,.perm_ready,.perm_done,.perm_digest,.perm_result_tag,
 .request_ready(rr),.read_digest(rd),.read_capture(rc),.response_valid(rv),.response_tag(rt),
 .response_digest(vd),.response_capture(vc),.perm_valid(pv),.perm_state(ps),.perm_tag(pt),.hash_count(hc),.permutation_count(pc));

 logic [1:0] request_family=0;
 logic request_no_seed=0;
 logic [3:0] request_start=0;
 logic [255:0] request_initial_value=256'h12345678;
 wire [127:0] identifier=128'habcdef;
 integer initial_with_return=0,key_returns=0;
 always @(posedge clk)if(!rst)begin
  if(request_valid&&request_ready&&request_no_seed&&perm_done)initial_with_return++;
  if(perm_done&&ref_dut.phase[perm_result_tag]==2)key_returns++;
 end
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
    request_valid=i<500 && i%5!=0;request_tag=T'(i%PIPELINE);read_tag=T'((i/3)%PIPELINE);
    request_family=width==2 ? 2'(i%3) : 0;request_no_seed=width==2 && i%4!=0;request_start=4'(i%4);request_initial_value=256'(i)*256'h123456789abcdef;
    request_steps=5'(i%6);request_capture_after=i%2 ? {1'b0,request_start} : 5'((i/7)%8);request_capture=i%3!=0;
    request_b=32'hffffffff-i;request_a=7'(i);request_leaf=10'(i*3);request_tree=64'hfedcba9876543210+i;request_layer=5'(i);
    step_domain=i%2 ? 3 : 0;seed_domain=i%2 ? 6 : 5;response_ready=i%7!=0;
    perm_done=0;
    for(integer t=PIPELINE-1;t>=0;t=t-1)if(pending[t])begin perm_done=1;perm_result_tag=T'(t);end
    perm_ready=perm_done || i%4!=0;
    for(integer w=0;w<50;w=w+1)perm_digest[w*32 +:32]=$random;
   end
  end
  @(negedge clk);request_valid=0;
  if(accepted<30 || (PIPELINE>1 && simultaneous==0))$fatal(1,"coverage missing accepted=%0d simultaneous=%0d",accepted,simultaneous);
  if(initial_with_return==0 || key_returns==0)$fatal(1,"stateful collision coverage");
  $display("COLLISION_COVERAGE initial_with_return=%0d key_returns=%0d",initial_with_return,key_returns);
  $display("CHAIN_FORMAT_EQUIV_PASS P=%0d accepted=%0d simultaneous=%0d",PIPELINE,accepted,simultaneous);$finish;
 end
endmodule
