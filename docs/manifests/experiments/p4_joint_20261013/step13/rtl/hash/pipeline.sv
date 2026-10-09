`timescale 1ns/1ps
`default_nettype none
// Per-context SLH/XMSS/LMS chain metadata and completion slots. No Keccak duplication:
// permutations use the same pipeline as the recipe/sponge path.
module pipeline #(
 parameter integer PIPELINE=2, parameter bit PROFILE_ENABLE=0, UNIFIED_FIXED=0,
 localparam integer TAG_BITS=PIPELINE>1 ? $clog2(PIPELINE) : 1
)(
 input wire clk,rst,input wire [5:0] node_bytes,
 input wire request_valid,output wire request_ready,input wire [TAG_BITS-1:0] request_tag,
 input wire [4:0] request_steps,request_capture_after,input wire request_capture,
 input wire [1:0] request_family,input wire request_no_seed,
 input wire [3:0] request_start,input wire [255:0] request_initial_value,
 input wire [3:0] request_fixed_shape,input wire request_pair,
 input wire [255:0] request_right,
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
 input wire [TAG_BITS-1:0] perm_result_tag,perm_prefetch_tag,
 output logic [31:0] hash_count,permutation_count
);
 function automatic [31:0] be32(input [31:0] v);be32={v[7:0],v[15:8],v[23:16],v[31:24]};endfunction
 wire [255:0] seed_address={be32(request_b),be32({24'd0,request_a}),be32({22'd0,request_leaf}),be32({24'd0,seed_domain}),be32(request_tree[31:0]),be32(request_tree[63:32]),32'd0,be32({27'd0,request_layer})};
 wire [255:0] step_address={be32(request_b),be32({24'd0,request_a}),be32({22'd0,request_leaf}),be32({24'd0,step_domain}),be32(request_tree[31:0]),be32(request_tree[63:32]),32'd0,be32({27'd0,request_layer})};
 wire [255:0] address[0:PIPELINE-1];
 logic [4:0] steps[0:PIPELINE-1],iteration[0:PIPELINE-1],capture_after[0:PIPELINE-1];
 logic [PIPELINE-1:0] busy,complete,capture_enable,preserve_counter;
 logic [255:0] digest[0:PIPELINE-1],captured[0:PIPELINE-1];
 localparam [2:0] SEED=0,STEP=1,KEY=2,MASK=3,FINAL=4,MASK1=5,SINGLE=6;
 wire [1:0] family[0:PIPELINE-1];
 wire [3:0] fixed_shape[0:PIPELINE-1];
 wire [PIPELINE-1:0] paired;
 logic [3:0] shared_shape;logic shared_pair;
 logic [2:0] phase[0:PIPELINE-1];
 logic [255:0] key_value[0:PIPELINE-1];
 logic [PIPELINE-1:0] captured_valid,initial_pending,capture_initial;
 assign read_digest=initial_pending[read_tag] ? key_value[read_tag] : digest[read_tag];
 assign read_capture=captured_valid[read_tag] ? (capture_initial[read_tag] ? key_value[read_tag] : captured[read_tag]) : 256'd0;
 wire [TAG_BITS-1:0] t=perm_result_tag;
 // Select the next return's metadata during the preceding Keccak stage.
 // Phase updates for a context are at least one full permutation apart.
 wire [2:0] feedback_phase,next_phase;
 wire node_done,continue_node,capture_match;
 wire [4:0] feedback_iteration,next_step;
 wire feedback_preserve;
 generate if(UNIFIED_FIXED)begin: metadata_prefetch
  wire [TAG_BITS-1:0] p=perm_prefetch_tag;
  wire done=phase[p]==SEED || phase[p]==STEP || phase[p]==FINAL || phase[p]==SINGLE;
  logic [2:0] prefetched_phase,prefetched_next;
  logic [4:0] prefetched_iteration,prefetched_step;
  logic prefetched_done,prefetched_continue,prefetched_capture,prefetched_preserve;
  always_ff @(posedge clk)begin
   prefetched_phase<=phase[p];prefetched_iteration<=iteration[p];
   prefetched_done<=done;prefetched_continue<=!done || iteration[p]<steps[p];
   prefetched_capture<=done && capture_enable[p] && iteration[p]==capture_after[p];
   prefetched_next<=phase[p]==KEY ? MASK : phase[p]==MASK ? (paired[p] ? MASK1 : FINAL)
     : phase[p]==MASK1 ? FINAL : family[p]==1 ? KEY : STEP;
   prefetched_step<=done ? iteration[p] : iteration[p]-1'b1;
   prefetched_preserve<=preserve_counter[p];
  end
  assign feedback_phase=prefetched_phase;assign feedback_iteration=prefetched_iteration;
  assign node_done=prefetched_done;assign continue_node=prefetched_continue;assign capture_match=prefetched_capture;
  assign next_phase=prefetched_next;assign next_step=prefetched_step;assign feedback_preserve=prefetched_preserve;
 end else begin
  assign feedback_phase=phase[t];assign feedback_iteration=iteration[t];
  assign node_done=phase[t]==SEED || phase[t]==STEP || phase[t]==FINAL || phase[t]==SINGLE;
  assign continue_node=!node_done || iteration[t]<steps[t];
  assign capture_match=node_done && capture_enable[t] && iteration[t]==capture_after[t];
  assign next_phase=phase[t]==KEY ? MASK : phase[t]==MASK ? (paired[t] ? MASK1 : FINAL)
     : phase[t]==MASK1 ? FINAL : family[t]==1 ? KEY : STEP;
  assign next_step=node_done ? iteration[t] : iteration[t]-1'b1;
  assign feedback_preserve=preserve_counter[t];
 end endgenerate
 wire again=perm_done && continue_node;
 wire capture_now=perm_done && capture_match;
 logic [255:0] next_address;
 always_comb begin
  next_address=address[t];
  if(!feedback_preserve)next_address[224 +:32]=be32({27'd0,next_step});
 end
 function automatic [1599:0] block_for(input [255:0] adr,input [255:0] val,right,input bit pair);
  reg [1599:0] block_data;
  begin
   block_data=0;
   case(node_bytes)
    16:begin block_data[511:0]={val[127:0],adr,public_seed[127:0]};
        if(pair)begin block_data[639:512]=right[127:0];block_data[640 +:8]=8'h1f;end
        else block_data[512 +:8]=8'h1f;end
    24:begin block_data[639:0]={val[191:0],adr,public_seed[191:0]};
        if(pair)begin block_data[831:640]=right[191:0];block_data[832 +:8]=8'h1f;end
        else block_data[640 +:8]=8'h1f;end
    default:begin block_data[767:0]={val,adr,public_seed};
        if(pair)begin block_data[1023:768]=right;block_data[1024 +:8]=8'h1f;end
        else block_data[768 +:8]=8'h1f;end
   endcase
   block_data[1087]=1;block_for=block_data;
  end
 endfunction
 function automatic [1599:0] stateful_block(input [1:0] kind,input [2:0] subphase,
     input [255:0] adr,val,key,right,input [3:0] step,shape,input bit pair);
  reg [1599:0] data;
  reg [255:0] masked_address;
  begin
   data=0;
   masked_address={be32(subphase==MASK ? 32'd1 : subphase==MASK1 ? 32'd2 : 32'd0),
       shape!=0 ? adr[255:224] : be32({28'd0,step}),adr[223:192],adr[191:160],adr[159:128],96'd0};
   if(shape==5)begin
    data[255:248]=8'd3;data[511:256]=val;
    data[767:512]={adr[191:160],224'd0};data[775:768]=8'h1f;
   end else if(shape==14 || shape==15)begin
    data[127:0]=identifier;data[159:128]=adr[255:224];
    data[175:160]=shape==14 ? 16'h8282 : 16'h8383;data[431:176]=val;
    if(pair)begin data[687:432]=right;data[695:688]=8'h1f;end
    else data[439:432]=8'h1f;
   end else if(kind==2)begin
    data[127:0]=identifier;data[159:128]=adr[191:160];
    data[167:160]=0;data[175:168]=adr[223:216];data[183:176]=(subphase==SEED || shape==9) ? 8'hff : shape==10 ? adr[255:248] : {4'd0,step};
    data[439:184]=val;data[447:440]=8'h1f;
   end else if(subphase==SEED || shape==7)begin
    // XMSS seed domain: 32-byte 4 || SK.seed || PK.seed || ADRS || 0.
    data[255:248]=8'd4;data[511:256]=secret_seed;data[767:512]=public_seed;
    data[1023:768]=masked_address;data[1031:1024]=8'h1f;
   end else if(subphase==KEY || subphase==MASK || subphase==MASK1)begin
    data[255:248]=8'd3;data[511:256]=public_seed;data[767:512]=masked_address;data[775:768]=8'h1f;
   end else begin
    data[255:248]=pair ? 8'd1 : 8'd0;data[511:256]=key;data[767:512]=val;
    if(pair)begin data[1023:768]=right;data[1031:1024]=8'h1f;end
    else data[775:768]=8'h1f;
   end
   data[1087]=1;stateful_block=data;
  end
 endfunction
 assign request_ready=!rst && !again && perm_ready && request_tag<PIPELINE && (!busy[request_tag] || (UNIFIED_FIXED && response_valid && response_ready && response_tag==request_tag));
 wire accept=request_valid && request_ready;
 wire [3:0] requested_shape=UNIFIED_FIXED ? request_fixed_shape : 4'd0;
 wire requested_pair=UNIFIED_FIXED && request_pair;
 wire zero_request=request_no_seed && request_steps==0 && requested_shape==0;
 assign perm_valid=again || (accept && !zero_request);
 // Select operands before the common width and padding formatter.
 wire [255:0] block_address=again ? next_address : request_no_seed ? step_address : seed_address;
 wire [1:0] block_family=again ? family[t] : request_family;
 wire [2:0] first_phase=requested_shape==8 ? KEY : requested_shape==7 ? SEED
     : requested_shape!=0 ? SINGLE : !request_no_seed ? SEED : request_family==1 ? KEY : STEP;
 wire [2:0] block_phase=again ? next_phase : first_phase;
 wire [3:0] block_step=again ? next_step[3:0] : request_start;
 wire [3:0] block_shape=again ? fixed_shape[t] : requested_shape;
 wire block_pair=again ? paired[t] : requested_pair;
 wire [255:0] block_value=again ? (feedback_phase==MASK1 ? digest[t]
     : feedback_phase==MASK ? digest[t]^perm_digest[255:0] : perm_digest[255:0])
     : requested_shape==1 || requested_shape==9 ? secret_seed : request_no_seed ? request_initial_value : secret_seed;
 wire [255:0] block_right=again ? captured[t]^perm_digest[255:0] : request_right;
 wire [1599:0] unified_state;
 generate if(UNIFIED_FIXED)begin: formatter
  logic [255:0] f0,f1,f2,f3,masked_address;
  logic [183:0] prefix;
  logic [7:0] domain;
  logic [1:0] layout;
  logic two;
  logic [1599:0] data;
  wire seed=block_phase==SEED || block_shape==7;
  wire prf=block_phase==KEY || block_phase==MASK || block_phase==MASK1;
  always_comb begin
   masked_address={be32(block_phase==MASK ? 32'd1 : block_phase==MASK1 ? 32'd2 : 32'd0),
    block_shape!=0 ? block_address[255:224] : be32({28'd0,block_step}),
    block_address[223:192],block_address[191:160],block_address[159:128],96'd0};
   f0=public_seed;f1=block_address;f2=block_value;f3=block_right;
   layout=0;two=block_pair;prefix=0;domain=0;
   if(block_family==1)begin
    layout=1;
    domain=block_shape==5 || prf ? 8'd3 : seed ? 8'd4 : block_pair ? 8'd1 : 8'd0;
    f1=block_shape==5 ? block_value : seed ? secret_seed : prf ? public_seed : key_value[t];
    f2=block_shape==5 ? {block_address[191:160],224'd0} : seed ? public_seed : prf ? masked_address : block_value;
    f3=seed ? masked_address : block_right;
    two=seed || (block_pair && !prf);
   end else if(block_family==2)begin
    if(block_shape==14 || block_shape==15)begin
     layout=3;prefix={8'd0,block_shape==14 ? 16'h8282 : 16'h8383,block_address[255:224],identifier};
    end else begin
     layout=2;two=0;
     prefix={(seed || block_shape==9) ? 8'hff : block_shape==10 ? block_address[255:248] : {4'd0,block_step},block_address[223:216],8'd0,block_address[191:160],identifier};
    end
    f1=block_value;f2=block_right;
   end
   data=0;
   case(node_bytes)
    16:begin data[511:0]={block_value[127:0],block_address,public_seed[127:0]};
     if(two)begin data[639:512]=block_right[127:0];data[647:640]=8'h1f;end else data[519:512]=8'h1f;end
    24:begin data[639:0]={block_value[191:0],block_address,public_seed[191:0]};
     if(two)begin data[831:640]=block_right[191:0];data[839:832]=8'h1f;end else data[647:640]=8'h1f;end
    default:case(layout)
     0:begin data[767:0]={f2,f1,f0};if(two)begin data[1023:768]=f3;data[1031:1024]=8'h1f;end else data[775:768]=8'h1f;end
     1:begin data[255:248]=domain;data[511:256]=f1;data[767:512]=f2;
       if(two)begin data[1023:768]=f3;data[1031:1024]=8'h1f;end else data[775:768]=8'h1f;end
     2:begin data[183:0]=prefix;data[439:184]=f1;data[447:440]=8'h1f;end
     3:begin data[175:0]=prefix[175:0];data[431:176]=f1;
       if(two)begin data[687:432]=f2;data[695:688]=8'h1f;end else data[439:432]=8'h1f;end
    endcase
   endcase
   data[1087]=1;
  end
  assign unified_state=data;
 end else begin assign unified_state=0;end endgenerate
 assign perm_state=UNIFIED_FIXED ? unified_state : block_family==0 ? block_for(block_address,block_value,block_right,block_pair)
     : stateful_block(block_family,block_phase,block_address,block_value,key_value[t],block_right,block_step,block_shape,block_pair);
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
 wire key_return=perm_done && feedback_phase==KEY;
 wire initial_transfer=key_return && initial_pending[t];
 wire key_write=key_return || (accept && request_no_seed);
 wire [TAG_BITS-1:0] key_write_tag=key_return ? t : request_tag;
 wire [255:0] key_write_data=key_return ? perm_digest[255:0] : request_initial_value;
 wire mask_left=perm_done && paired[t] && feedback_phase==MASK;
 wire digest_write=perm_done && (node_done || initial_transfer || mask_left);
 wire [255:0] digest_write_data=initial_transfer ? key_value[t] : mask_left ? digest[t]^perm_digest[255:0] : perm_digest[255:0];
 wire capture_transfer=initial_transfer && capture_initial[t];
 wire right_write=accept && requested_pair && requested_shape==8;
 wire captured_write=capture_now || capture_transfer || right_write;
 wire [TAG_BITS-1:0] captured_write_tag=right_write ? request_tag : t;
 wire [255:0] captured_write_data=right_write ? request_right : capture_transfer ? key_value[t] : perm_digest[255:0];
 always_ff @(posedge clk)begin
  if(!rst)begin
   if(key_write)key_value[key_write_tag]<=key_write_data;
   if(digest_write)digest[t]<=digest_write_data;
   if(captured_write)captured[captured_write_tag]<=captured_write_data;
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
    phase[request_tag]<=first_phase;
    if(busy==0)begin shared_shape<=requested_shape;shared_pair<=requested_pair;end
    initial_pending[request_tag]<=request_no_seed;
    if(zero_request)complete[request_tag]<=1;
    capture_after[request_tag]<=request_capture_after;capture_enable[request_tag]<=request_capture;
    preserve_counter[request_tag]<=step_domain==3 || requested_shape!=0;
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
     if(node_done)iteration[t]<=feedback_iteration+1'b1;
    end else complete[t]<=1;
   end
  end
 end
 generate if(UNIFIED_FIXED)begin: shared_coordinates
  logic [4:0] layer;
  logic [63:0] tree;
  logic [7:0] domain;
  logic [1:0] kind;
  logic [9:0] leaves[0:PIPELINE-1];
  logic [7:0] chains[0:PIPELINE-1];
  logic [31:0] indices[0:PIPELINE-1];
  always_ff @(posedge clk)if(!rst && accept)begin
   if(busy==0)begin layer<=request_layer;tree<=request_tree;domain<=step_domain;kind<=request_family;end
   leaves[request_tag]<=request_leaf;chains[request_tag]<=request_a;indices[request_tag]<=request_b;
  end
  for(genvar j=0;j<PIPELINE;j++)begin
   assign address[j]={be32(indices[j]),be32({24'd0,chains[j]}),be32({22'd0,leaves[j]}),be32({24'd0,domain}),be32(request_tree[31:0]),be32(request_tree[63:32]),32'd0,be32({27'd0,request_layer})};
   assign family[j]=request_family;
   assign fixed_shape[j]=shared_shape;assign paired[j]=shared_pair;
  end
 end else begin: legacy_coordinates
  logic [255:0] saved_address[0:PIPELINE-1];
  logic [1:0] saved_family[0:PIPELINE-1];
  always_ff @(posedge clk)if(!rst && accept)begin saved_address[request_tag]<=step_address;saved_family[request_tag]<=request_family;end
  for(genvar j=0;j<PIPELINE;j++)begin assign address[j]=saved_address[j];assign family[j]=saved_family[j];assign fixed_shape[j]=0;assign paired[j]=0;end
 end endgenerate
`ifndef SYNTHESIS
 always @(posedge clk)if(UNIFIED_FIXED && !rst && perm_done)begin
  if(feedback_phase!==phase[t] || feedback_iteration!==iteration[t] || continue_node!==(!node_done || iteration[t]<steps[t]))$fatal(1,"return metadata prefetch mismatch");
 end
`endif
endmodule
`default_nettype wire
