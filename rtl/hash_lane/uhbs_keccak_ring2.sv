`timescale 1ns/1ps
`default_nettype none
// Two resident contexts, two U2 stages. Four physical rounds total.
// Recirculation has priority; a completed slot can immediately accept a new hash.
module uhbs_keccak_ring2(
 input wire clk,rst,input wire [1:0] request_valid,output logic [1:0] request_ready,
 input wire [1599:0] request_state0,request_state1,
 output wire [1:0] result_valid,output wire [1599:0] result_state
);
 logic valid0,valid1,tag0,tag1;
 logic [4:0] count0,count1;
 logic [1599:0] state0,state1;
 logic input_valid,input_tag;
 logic [4:0] input_count;
 logic [1599:0] input_state;
 wire [1599:0] stage0_mid,stage0_out,stage1_mid,stage1_out;
 always_comb begin
  input_valid=0;input_tag=0;input_count=0;input_state=request_state0;request_ready=0;
  if(valid1 && count1<24)begin
   input_valid=1;input_tag=tag1;input_count=count1;input_state=state1;
  end else if(request_valid[0])begin input_valid=1;request_ready[0]=1;end
  else if(request_valid[1])begin input_valid=1;input_tag=1;input_state=request_state1;request_ready[1]=1;end
 end
 uhbs_keccak s0r0(.state_in(input_state),.round_index(input_count),.state_out(stage0_mid));
 uhbs_keccak s0r1(.state_in(stage0_mid),.round_index(input_count+5'd1),.state_out(stage0_out));
 uhbs_keccak s1r0(.state_in(state0),.round_index(count0),.state_out(stage1_mid));
 uhbs_keccak s1r1(.state_in(stage1_mid),.round_index(count0+5'd1),.state_out(stage1_out));
 always_ff @(posedge clk)begin
  if(input_valid)state0<=stage0_out;
  if(valid0)state1<=stage1_out;
 end
 always_ff @(posedge clk)begin
  if(rst)begin valid0<=0;valid1<=0;tag0<=0;tag1<=0;count0<=0;count1<=0;end
  else begin
   valid0<=input_valid;valid1<=valid0;
   if(input_valid)begin tag0<=input_tag;count0<=input_count+5'd2;end
   if(valid0)begin tag1<=tag0;count1<=count0+5'd2;end
  end
 end
 assign result_valid=valid1 && count1==24 ? (tag1 ? 2'b10 : 2'b01) : 2'b00;
 assign result_state=state1;
endmodule
`default_nettype wire
