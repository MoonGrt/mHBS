`timescale 1ns/1ps
`default_nettype none
// Per-context SLH/XMSS/LMS chain metadata and completion slots. No Keccak duplication:
// permutations use the same pipeline as the recipe/sponge path.
module pipeline #(
 parameter integer PIPELINE=2, parameter bit PROFILE_ENABLE=0,
 localparam integer TAG_BITS=PIPELINE>1 ? $clog2(PIPELINE) : 1
)(
 input wire clk,rst,input wire [5:0] node_bytes,
 input wire request_valid,output wire request_ready,input wire [TAG_BITS-1:0] request_tag,
 input wire [4:0] request_steps,request_capture_after,input wire request_capture,
 input wire [1:0] request_family,input wire request_no_seed,
 input wire [3:0] request_start,input wire [255:0] request_initial_value,
 input wire [127:0] identifier,
 input wire [255:0] secret_seed,public_seed,
 input wire [4:0] request_layer,input wire [63:0] request_tree,
 input wire [9:0] request_leaf,input wire [7:0] request_a,input wire [31:0] request_b,
 input wire [7:0] seed_domain,step_domain,
 input wire [TAG_BITS-1:0] read_tag,
 output wire [255:0] read_digest,read_capture,
 output wire response_valid,input wire response_ready,output logic [TAG_BITS-1:0] response_tag,
 output wire [255:0] response_digest,response_capture,
 output wire perm_valid,input wire perm_ready,output wire [1599:0] perm_state,
 output wire [TAG_BITS-1:0] perm_tag,input wire perm_done,input wire [1599:0] perm_digest,
 input wire [TAG_BITS-1:0] perm_result_tag,
 output logic [31:0] hash_count,permutation_count
);
 function automatic [31:0] be32(input [31:0] v);be32={v[7:0],v[15:8],v[23:16],v[31:24]};endfunction
 wire [255:0] seed_address={be32(request_b),be32({24'd0,request_a}),be32({22'd0,request_leaf}),be32({24'd0,seed_domain}),be32(request_tree[31:0]),be32(request_tree[63:32]),32'd0,be32({27'd0,request_layer})};
 wire [255:0] step_address={be32(request_b),be32({24'd0,request_a}),be32({22'd0,request_leaf}),be32({24'd0,step_domain}),be32(request_tree[31:0]),be32(request_tree[63:32]),32'd0,be32({27'd0,request_layer})};
 logic [255:0] address[0:PIPELINE-1];
 logic [4:0] steps[0:PIPELINE-1],iteration[0:PIPELINE-1],capture_after[0:PIPELINE-1];
 logic [PIPELINE-1:0] busy,complete,capture_enable,preserve_counter;
 logic [255:0] digest[0:PIPELINE-1],captured[0:PIPELINE-1];
 localparam [2:0] SEED=0,STEP=1,KEY=2,MASK=3,FINAL=4;
 logic [1:0] family[0:PIPELINE-1];
 logic [2:0] phase[0:PIPELINE-1];
 logic [255:0] key_value[0:PIPELINE-1];
 logic [PIPELINE-1:0] captured_valid,initial_pending,capture_initial;
 assign read_digest=initial_pending[read_tag] ? key_value[read_tag] : digest[read_tag];
 assign read_capture=captured_valid[read_tag] ? (capture_initial[read_tag] ? key_value[read_tag] : captured[read_tag]) : 256'd0;
 wire [TAG_BITS-1:0] t=perm_result_tag;
 wire node_done=phase[t]==SEED || phase[t]==STEP || phase[t]==FINAL;
 wire again=perm_done && (!node_done || iteration[t]<steps[t]);
 wire capture_now=perm_done && node_done && capture_enable[t] && iteration[t]==capture_after[t];
 wire [2:0] next_phase=phase[t]==KEY ? MASK : phase[t]==MASK ? FINAL : family[t]==1 ? KEY : STEP;
 wire [4:0] next_step=node_done ? iteration[t] : iteration[t]-1'b1;
 logic [255:0] next_address;
 always_comb begin
  next_address=address[t];
  if(!preserve_counter[t])next_address[224 +:32]=be32({27'd0,next_step});
 end
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
 assign request_ready=!rst && !again && perm_ready && request_tag<PIPELINE && !busy[request_tag];
 wire accept=request_valid && request_ready;
 wire zero_request=request_no_seed && request_steps==0;
 assign perm_valid=again || (accept && !zero_request);
 // Select operands before the common width and padding formatter.
 wire [255:0] block_address=again ? next_address : request_no_seed ? step_address : seed_address;
 wire [1:0] block_family=again ? family[t] : request_family;
 wire [2:0] block_phase=again ? next_phase : !request_no_seed ? SEED : request_family==1 ? KEY : STEP;
 wire [3:0] block_step=again ? next_step[3:0] : request_start;
 wire [255:0] block_value=again ? (phase[t]==MASK ? digest[t]^perm_digest[255:0] : perm_digest[255:0]) : request_no_seed ? request_initial_value : secret_seed;
 assign perm_state=block_family==0 ? block_for(block_address,block_value) : stateful_block(block_family,block_phase,block_address,block_value,key_value[t],block_step);
 assign perm_tag=again ? t : request_tag;
 logic response_held;
 logic [TAG_BITS-1:0] held_tag;
 assign response_valid=|complete;
 always_comb begin
  response_tag=0;
  for(integer j=PIPELINE-1;j>=0;j=j-1)if(complete[j])response_tag=TAG_BITS'(j);
  if(response_held)response_tag=held_tag;
 end
 assign response_digest=initial_pending[response_tag] ? key_value[response_tag] : digest[response_tag];
 assign response_capture=captured_valid[response_tag] ? (capture_initial[response_tag] ? key_value[response_tag] : captured[response_tag]) : 256'd0;
 // A KEY return always feeds MASK immediately, so feedback priority excludes
 // accepting an initial value on the same edge. Each bank has one write port.
 wire key_return=perm_done && phase[t]==KEY;
 wire initial_transfer=key_return && initial_pending[t];
 wire key_write=key_return || (accept && request_no_seed);
 wire [TAG_BITS-1:0] key_write_tag=key_return ? t : request_tag;
 wire [255:0] key_write_data=key_return ? perm_digest[255:0] : request_initial_value;
 wire digest_write=perm_done && (node_done || initial_transfer);
 wire [255:0] digest_write_data=initial_transfer ? key_value[t] : perm_digest[255:0];
 wire capture_transfer=initial_transfer && capture_initial[t];
 wire captured_write=capture_now || capture_transfer;
 wire [255:0] captured_write_data=capture_transfer ? key_value[t] : perm_digest[255:0];
 always_ff @(posedge clk)begin
  if(!rst)begin
   if(key_write)key_value[key_write_tag]<=key_write_data;
   if(digest_write)digest[t]<=digest_write_data;
   if(captured_write)captured[t]<=captured_write_data;
  end
 end
 always_ff @(posedge clk)begin
  if(rst)begin initial_pending<=0;capture_initial<=0;captured_valid<=0;response_held<=0;held_tag<=0;busy<=0;complete<=0;capture_enable<=0;preserve_counter<=0;hash_count<=0;permutation_count<=0;end
  else begin
   if(response_valid && !response_ready && !response_held)begin response_held<=1;held_tag<=response_tag;end
   if(response_valid && response_ready)response_held<=0;
   if(response_valid && response_ready)begin complete[response_tag]<=0;busy[response_tag]<=0;end
   if(accept)begin
    busy[request_tag]<=1;steps[request_tag]<=request_steps+{1'b0,request_start};iteration[request_tag]<=request_no_seed ? {1'b0,request_start}+1'b1 : 5'd0;
    family[request_tag]<=request_family;
    phase[request_tag]<=!request_no_seed ? SEED : request_family==1 ? KEY : STEP;
    initial_pending[request_tag]<=request_no_seed;
    if(zero_request)complete[request_tag]<=1;
    capture_after[request_tag]<=request_capture_after;capture_enable[request_tag]<=request_capture;
    preserve_counter[request_tag]<=step_domain==3;address[request_tag]<=step_address;
    captured_valid[request_tag]<=0;
    capture_initial[request_tag]<=0;
    if(request_no_seed && request_capture && request_capture_after=={1'b0,request_start})begin
     capture_initial[request_tag]<=1;captured_valid[request_tag]<=1;
    end
   end
   if(perm_done)begin
    if(PROFILE_ENABLE)begin hash_count<=hash_count+1'b1;permutation_count<=permutation_count+1'b1;end
    if(capture_now)begin capture_initial[t]<=0;captured_valid[t]<=1;end
    if(capture_transfer)capture_initial[t]<=0;
    if(digest_write)initial_pending[t]<=0;
    if(again)begin
     phase[t]<=next_phase;
     if(node_done)iteration[t]<=iteration[t]+1'b1;
    end else complete[t]<=1;
   end
  end
 end
endmodule
`default_nettype wire
