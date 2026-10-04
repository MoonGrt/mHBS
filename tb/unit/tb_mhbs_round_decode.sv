`timescale 1ns/1ps
module tb_mhbs_round_decode;
 parameter integer STRIDE=1,SPECIALIZED=0;
 logic [1599:0] state_in;
 logic [4:0] pass_index;
 wire [1599:0] result[0:STRIDE-1];
 `include "tb/reference/keccak_round_frozen.svh"
 for(genvar stage=0;stage<STRIDE;stage=stage+1)begin: stages
  if(SPECIALIZED)begin: fixed_map
   mhbs_keccak #(.ROUND_STRIDE(STRIDE),.ROUND_OFFSET(stage)) dut(
    .state_in,.round_index(pass_index),.state_out(result[stage]));
  end else begin: absolute_map
   mhbs_keccak dut(.state_in,
    .round_index(pass_index<24/STRIDE ? 5'(pass_index*STRIDE+stage) : 5'd31),.state_out(result[stage]));
  end
 end
 integer checks=0;
 initial begin
  for(integer pattern=0;pattern<34;pattern=pattern+1)begin
   for(integer w=0;w<50;w=w+1)state_in[32*w +:32]=pattern==0 ? 0 : pattern==1 ? '1 : $random;
   for(integer pass=0;pass<32;pass=pass+1)begin
    pass_index=5'(pass);#1;
    for(integer stage=0;stage<STRIDE;stage=stage+1)begin
     if(result[stage]!==keccak_round(state_in,pass<24/STRIDE ? 5'(pass*STRIDE+stage) : 5'd31))
      $fatal(1,"round mismatch stride=%0d pass=%0d stage=%0d",STRIDE,pass,stage);
     checks=checks+1;
    end
   end
  end
  $display("ROUND_DECODE_PASS stride=%0d specialized=%0d checks=%0d",STRIDE,SPECIALIZED,checks);$finish;
 end
endmodule
