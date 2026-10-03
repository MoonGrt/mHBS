`timescale 1ns/1ps
module tb_mhbs_keccak_pipeline;
 parameter integer UNROLL=1,PIPELINE=2;
 logic clk=0,rst=1,request_valid=0;
 wire request_ready,response_valid;
 logic [1599:0] request_state;
 logic [1:0] request_tag;
 wire [1599:0] response_state;
 wire [1:0] response_tag;
 reg [1599:0] expected[0:3];reg [3:0] outstanding=0;
 integer sent=0,received=0,cycles=0;
 `include "tb/reference/keccak_round_frozen.svh"
 mhbs_keccak_pipeline #(.UNROLL(UNROLL),.PIPELINE(PIPELINE)) dut(.*);
 always #5 clk=~clk;
 always @(posedge clk)if(!rst)begin
  cycles=cycles+1;
  if(response_valid)begin
   if(!outstanding[response_tag] || response_state!==expected[response_tag])$fatal(1,"permutation mismatch tag=%0d",response_tag);
   outstanding[response_tag]=0;received=received+1;
  end
  if(request_valid && request_ready)begin
   if(outstanding[request_tag])$fatal(1,"duplicate tag");
   expected[request_tag]=request_state;
   for(integer r=0;r<24;r=r+1)expected[request_tag]=keccak_round(expected[request_tag],5'(r));
   outstanding[request_tag]=1;sent=sent+1;
  end
  if(cycles>10000)$fatal(1,"timeout");
 end
 initial begin
  repeat(3)@(negedge clk);rst=0;
  for(integer run=0;run<2;run=run+1)begin
   for(integer n=0;n<40;n=n+1)begin
    @(negedge clk);request_valid=0;request_tag=2'(n%PIPELINE);
    while(outstanding[request_tag])@(negedge clk);
    for(integer w=0;w<50;w=w+1)request_state[w*32 +:32]=n==0 ? 0 : n==1 ? '1 : $random;
    request_valid=1;do @(posedge clk);while(!request_ready);
    @(negedge clk);request_valid=0;
    if(n%7==0)repeat(2)@(negedge clk);
   end
   if(run==0)begin rst=1;outstanding=0;repeat(3)@(negedge clk);rst=0;end
  end
  while(outstanding!=0)@(negedge clk);
  repeat(40)@(negedge clk);
  $display("KECCAK_PIPELINE_PASS U=%0d P=%0d accepted=%0d checked=%0d reset_cancel=1",UNROLL,PIPELINE,sent,received);$finish;
 end
endmodule
