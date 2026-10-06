`timescale 1ns/1ps
`default_nettype none
// Per-context SLH chain metadata and completion slots. No Keccak duplication:
// permutations use the same pipeline as the recipe/sponge path.
module mhbs_chain_pipeline_lane #(
 parameter integer PIPELINE=2, parameter bit PROFILE_ENABLE=0,
 localparam integer TAG_BITS=PIPELINE>1 ? $clog2(PIPELINE) : 1
)(
 input wire clk,rst,input wire [5:0] node_bytes,
 input wire request_valid,output wire request_ready,input wire [TAG_BITS-1:0] request_tag,
 input wire [4:0] request_steps,request_capture_after,input wire request_capture,
 input wire [255:0] secret_seed,public_seed,
 input wire [4:0] request_layer,input wire [63:0] request_tree,
 input wire [9:0] request_leaf,input wire [6:0] request_a,input wire [31:0] request_b,
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
 wire [255:0] seed_address={be32(request_b),be32({25'd0,request_a}),be32({22'd0,request_leaf}),be32({24'd0,seed_domain}),be32(request_tree[31:0]),be32(request_tree[63:32]),32'd0,be32({27'd0,request_layer})};
 wire [255:0] step_address={be32(request_b),be32({25'd0,request_a}),be32({22'd0,request_leaf}),be32({24'd0,step_domain}),be32(request_tree[31:0]),be32(request_tree[63:32]),32'd0,be32({27'd0,request_layer})};
 logic [255:0] address[0:PIPELINE-1];
 logic [4:0] steps[0:PIPELINE-1],iteration[0:PIPELINE-1],capture_after[0:PIPELINE-1];
 logic [PIPELINE-1:0] busy,complete,capture_enable,preserve_counter;
 logic [255:0] digest[0:PIPELINE-1],captured[0:PIPELINE-1];
 logic [PIPELINE-1:0] captured_valid;
 assign read_digest=digest[read_tag];
 assign read_capture=captured_valid[read_tag] ? captured[read_tag] : 256'd0;
 wire [TAG_BITS-1:0] t=perm_result_tag;
 wire again=perm_done && iteration[t]<steps[t];
 wire capture_now=perm_done && capture_enable[t] && iteration[t]==capture_after[t];
 logic [255:0] next_address;
 always_comb begin
  next_address=address[t];
  if(!preserve_counter[t])next_address[224 +:32]=be32({28'd0,iteration[t][3:0]});
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
 assign request_ready=!rst && !again && perm_ready && request_tag<PIPELINE && !busy[request_tag];
 wire accept=request_valid && request_ready;
 assign perm_valid=again || accept;
 // Select operands before the common width and padding formatter.
 wire [255:0] block_address=again ? next_address : seed_address;
 wire [255:0] block_value=again ? perm_digest[255:0] : secret_seed;
 assign perm_state=block_for(block_address,block_value);
 assign perm_tag=again ? t : request_tag;
 logic response_held;
 logic [TAG_BITS-1:0] held_tag;
 assign response_valid=|complete;
 always_comb begin
  response_tag=0;
  for(integer j=PIPELINE-1;j>=0;j=j-1)if(complete[j])response_tag=TAG_BITS'(j);
  if(response_held)response_tag=held_tag;
 end
 assign response_digest=digest[response_tag];
 assign response_capture=captured_valid[response_tag] ? captured[response_tag] : 256'd0;
 always_ff @(posedge clk)begin
  if(rst)begin captured_valid<=0;response_held<=0;held_tag<=0;busy<=0;complete<=0;capture_enable<=0;preserve_counter<=0;hash_count<=0;permutation_count<=0;end
  else begin
   if(response_valid && !response_ready && !response_held)begin response_held<=1;held_tag<=response_tag;end
   if(response_valid && response_ready)response_held<=0;
   if(response_valid && response_ready)begin complete[response_tag]<=0;busy[response_tag]<=0;end
   if(accept)begin
    busy[request_tag]<=1;steps[request_tag]<=request_steps;iteration[request_tag]<=0;
    capture_after[request_tag]<=request_capture_after;capture_enable[request_tag]<=request_capture;
    preserve_counter[request_tag]<=step_domain==3;address[request_tag]<=step_address;
    captured_valid[request_tag]<=0;
   end
   if(perm_done)begin
    if(PROFILE_ENABLE)begin hash_count<=hash_count+1'b1;permutation_count<=permutation_count+1'b1;end
    if(capture_now)begin captured[t]<=perm_digest[255:0];captured_valid[t]<=1;end
    if(again)iteration[t]<=iteration[t]+1'b1;
    else begin complete[t]<=1;digest[t]<=perm_digest[255:0];end
   end
  end
 end
endmodule
`default_nettype wire
