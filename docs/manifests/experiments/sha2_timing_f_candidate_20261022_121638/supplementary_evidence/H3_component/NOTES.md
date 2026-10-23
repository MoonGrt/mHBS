# H3: 16+16 carry-select A/E final sums

H3 is a private fallback derived from the exact H2 SHA256 primitive SHA256=140c3a7d13addd05aa60f4972164facc5c463df348f2a8d779999c907e1c3d11. Production remains H2. This component task launches no Vivado process.

## Change

Only the final 32-bit carry-propagating additions that form `next_a` and `next_e` inside `advance_round` are replaced. A generic function computes the low 16-bit sum and its carry with a 17-bit result. In parallel, it computes the high 16-bit sums for carry-in zero and carry-in one; the low carry selects the high result. Algebraically, writing `x=2^16*xh+xl`, `y=2^16*yh+yl`, `l=xl+yl`, the result is `{(xh+yh+l[16]) mod 2^16,l[15:0]}` and equals `(x+y) mod 2^32` for every input.

The message-schedule adder, H2 carry-save ordering, prefix lookahead, K values, valid/traversal/return/tag/stall/reset control, 64-round execution and tail bypass, stages, contexts, and final feed-forward register remain byte-identical. No P/U feature branch is added. Register and cycle counts are unchanged by construction and are checked in all legal P/U simulations.

## Why split at 16

A single 32-bit FPGA ripple sum normally uses eight CARRY4 groups. A balanced 16/16 split exposes two independent four-group high sums and a four-group low carry followed by a high-half mux, instead of requiring the full eight-group carry chain. An 8/24 split leaves a six-group upper path and duplicates more upper-adder bits; a 24/8 split duplicates less arithmetic but leaves a six-group lower path. The 16/16 choice targets delay first because U2 crosses two rounds and the observed G1 P12U2 path contains 12 CARRY4 cells. Actual technology mapping may share, merge or restructure these expressions, so this structural intent is not proof of mapped depth.

## Area and timing risks

Each result duplicates the upper 16-bit addition and adds 16 selection muxes. Nominal arithmetic width rises from 32 to 48 bit-adder slices per result, before optimization; both A and E are changed. This is not a LUT estimate. No FF, lane, context, or pipeline cycle is added. Selection control fanout, mux delay and routing can erase the carry-chain benefit. Vivado may also merge the upper-zero/upper-one expressions. There are no keep/dont_touch attributes, hand-instantiated carry primitives, constraint changes or timing exceptions to force a favorable result. Only source-bound synthesis and hard-target actual routing can determine whether H3 helps area, timing or ATP.

## Validation

The unchanged independent primitive checker and testbench run all 30 legal P/U configurations in normal and SYNTHESIS views, 181 compression vectors per point. The oracle uses an independent full 64-word message schedule and cross-checks complete message hashes against hashlib; arbitrary initial CVs, 55/56/63/64/65 and 119/120-byte boundaries, multi-block messages, random output stalls, tag alignment, simultaneous admission/retirement and reset replay are covered. Cycles, stalls, simultaneous-operation and reset-replay counts are compared exactly against H2 archived logs. Source hashes, a minimal H2 patch and summary JSON accompany the candidate. Detailed logs remain under `fixture/build/`.
