`timescale 1ns/1ps
`default_nettype none
// One shared ring of P registered stages, U combinational rounds per stage.
// Finished tokens leave without backpressure; the owner reserves result space.
// Internal round feedback has priority over fresh tokens and chain feedback.
module mhbs_keccak_pipeline #(
 parameter integer UNROLL=1, PIPELINE=2, TAG_BITS=2
)(
 input wire clk,rst,input wire request_valid,output wire request_ready,
 input wire [1599:0] request_state,input wire [TAG_BITS-1:0] request_tag,
 output wire response_valid,output wire [1599:0] response_state,
 output wire [TAG_BITS-1:0] response_tag
);
 localparam integer ROUNDS=UNROLL*PIPELINE;
 initial if(UNROLL<1 || PIPELINE<1 || ROUNDS>24 || 24%ROUNDS!=0)
  $fatal(1,"U*P must divide 24");
 logic [PIPELINE-1:0] valid;
 logic [1599:0] state_reg[0:PIPELINE-1];
 logic [4:0] base[0:PIPELINE-1];
 logic [TAG_BITS-1:0] tag[0:PIPELINE-1];
 wire recycle=valid[PIPELINE-1] && base[PIPELINE-1]+ROUNDS<24;
 assign request_ready=!rst && !recycle;
 assign response_valid=!rst && valid[PIPELINE-1] && !recycle;
 assign response_state=state_reg[PIPELINE-1];
 assign response_tag=tag[PIPELINE-1];
 for(genvar s=0;s<PIPELINE;s=s+1)begin: stages
  wire [1599:0] rounds[0:UNROLL];
  wire [4:0] start_round;
  wire [TAG_BITS-1:0] source_tag;
  wire source_valid;
  if(s==0)begin
   assign rounds[0]=recycle ? state_reg[PIPELINE-1] : request_state;
   assign start_round=recycle ? base[PIPELINE-1]+5'(ROUNDS) : 5'd0;
   assign source_tag=recycle ? tag[PIPELINE-1] : request_tag;
   assign source_valid=recycle || request_valid;
  end else begin
   assign rounds[0]=state_reg[s-1];assign start_round=base[s-1];
   assign source_tag=tag[s-1];assign source_valid=valid[s-1];
  end
  for(genvar r=0;r<UNROLL;r=r+1)begin: unrolled
   mhbs_keccak round_logic(.state_in(rounds[r]),
    .round_index(start_round+5'(s*UNROLL+r)),.state_out(rounds[r+1]));
  end
  always_ff @(posedge clk)begin
   if(rst)valid[s]<=0;
   else begin
    valid[s]<=source_valid;
    if(source_valid)begin state_reg[s]<=rounds[UNROLL];base[s]<=start_round;tag[s]<=source_tag;end
   end
  end
 end
endmodule
`default_nettype wire
