// Compare each active U-round group with the frozen independent round function.
`include "tb/reference/keccak_round_frozen.svh"
reg [1599:0] expected_rounds;
always @(posedge clk)if(!rst && dut.hash_state==2)begin
 expected_rounds=dut.rounds[0];
 for(integer gr=0;gr<UNROLL;gr++)
  expected_rounds=keccak_round(expected_rounds,5'(dut.round_index+gr));
 if(expected_rounds!==dut.advanced_state)$fatal(1,"unrolled round mismatch");
end
