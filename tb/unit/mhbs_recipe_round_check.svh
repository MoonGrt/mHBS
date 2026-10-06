// Test-only observer: no raw permutation port in production RTL.
 `include "tb/reference/keccak_round_frozen.svh"
 for(genvar gs=0;gs<PIPELINE;gs=gs+1)begin: round_checks
  reg [1599:0] expected_stage;
  reg [4:0] expected_base;
  reg [(PIPELINE>1 ? $clog2(PIPELINE) : 1)-1:0] expected_tag;
  always @(posedge clk)if(!rst && (PIPELINE==1 ? dut.hash_state==2 : dut.stages[gs].source_valid))begin
   expected_stage=dut.stages[gs].rounds[0];
   expected_base=dut.stages[gs].start_round;expected_tag=dut.stages[gs].source_tag;
   for(integer gr=0;gr<UNROLL;gr=gr+1)
    expected_stage=keccak_round(expected_stage,5'(expected_base+gs*UNROLL+gr));
   if(expected_stage!==dut.stage_result[gs])$fatal(1,"recipe round stage %0d",gs);
   if(PIPELINE>1)begin
    #1;
    if(!dut.stage_valid[gs] || dut.stage_tag[gs]!==expected_tag || dut.stage_base[gs]!==expected_base || dut.state_reg[gs]!==expected_stage)
     $fatal(1,"recipe stage register/tag %0d",gs);
   end
  end
 end
