# H: SHA256 carry-save tree candidates

## Trigger and scope

G1 P12U2 actual 10.000 ns routing failed setup by 0.094 ns. The reported critical path traverses stage 10 E[6] to stage 11 A[30], spanning both unrolled rounds, 22 logic levels, 12 CARRY4 cells, 10.053 ns data delay (3.763 ns logic, 6.290 ns routing). This is evidence for a small generic arithmetic change before considering extra register phases or changing cycle counts. No synthesis or routing is launched by this component task.

Both private candidates are derived exactly from production G SHA256 SHA256=81a8e9a5f9b2ce64b550f3fe3330a639b4dcf457b086f9df947cd9e90c9b0542. Only the combinational carry-save tree inside `advance_round` changes. Lookahead prefix format, K values, schedule recurrence, 64-round tail bypass, tags, input/output backpressure, valid/traversal/return control, feed-forward register, number of stages, number of contexts, and all core cycle counts are unchanged. There is no P/U branch or specialization.

## Arithmetic identity

Write `CSA(x,y,z)=(s,c)` for `s=x xor y xor z` and `c=majority(x,y,z)<<1`, so `s+c = x+y+z (mod 2^32)`. Let the stored prefix be `(p,c)` with `p+c=H+K+W`, let `sE=Sigma1(E)`, `ch=Ch(E,F,G)`, `sA=Sigma0(A)`, `maj=Maj(A,B,C)`. The required outputs are `A'=p+c+sE+ch+sA+maj`, `E'=p+c+sE+ch+D`, both modulo 2^32.

The G order is `t0=CSA(sE,ch,p)`, `T1=CSA(c,t0.s,t0.c)`, then one E compressor or two A compressors followed by the final 32-bit add. Sigma(E) consequently sees four compressors to A and three to E, while Sigma(A) sees two to A.

### H2: weighted shared-T1 ordering (preferred first diagnostic)

`early=CSA(p,c,ch)`, `T1=CSA(early.s,early.c,sE)`, then the unchanged G A/E reductions. Sigma(E) arrives after the first compressor: its path to A falls 4 to 3 CSA levels, and to E 3 to 2; Sigma(A)/Maj paths remain two levels to A. Ch paths remain four/three levels, but Ch is one Boolean level whereas Sigma(E) uses a three-rotation XOR. The five-compressor total per round excluding H/K/W preparation and schedule is identical to G. No registers or arithmetic operators are added. A material tradeoff is that the prepared-prefix carry input now traverses four compressors to A rather than three; that input is registered and does not incur Sigma(E) logic, but a new prefix-critical path is possible. FPGA LUT mapping and routing still must be measured; this is not evidence of frequency closure.

### H1: independently balanced A/E outputs

A uses `left=CSA(p,c,sA)`, `right=CSA(sE,ch,maj)`, `merge=CSA(left.s,left.c,right.s)`, `pair=CSA(merge.s,merge.c,right.c)`. Both nonlinear terms have at most three CSA levels to A, reducing G E-to-A 4 to 3 but increasing A-to-A 2 to 3. E uses `early=CSA(D,p,c)`, `late=CSA(sE,ch,early.s)`, `pair=CSA(late.s,late.c,early.c)`, shortening nonlinear E-to-E 3 to 2. This deliberately spends two additional 32-bit compressors per physical round (seven vs five), without registers or cycles. More LUTs and the deeper A path are material risks, so H1 remains an alternate pending actual synthesis/route comparison.

## Validation and provenance

`run_validation.py` uses unchanged independent G `check_sha256.py`/`tb_sha256.sv`. Each candidate runs all 30 legal P/U pairs in normal and SYNTHESIS views, 181 arbitrary-initial-CV compression vectors per configuration, full-message checks against hashlib, padding/message boundaries, random output stalls, input/output tag checks, complete 64-round execution and inactive tail bypass, simultaneous admission/retirement, and in-flight reset replay. Result, cycles, stalls, simultaneous-operation count, and reset-replay count are compared exactly to G's archived logs. Validation is source-hashed; detailed logs remain under private fixture build directories, with summary JSON and patch beside each candidate. No production source is overwritten by this task.
