# Unified three-profile core status

## Scope

`micro_hbs_unified_top` is the runtime-selected integration top for:

- SLH-DSA-SHAKE-128f Keygen and Sign;
- XMSS-SHAKE256_10_256 Keygen and Sign;
- LMS-SHAKE h10/w4 research-profile Keygen and Sign.

`job_algorithm` and `job_operation` select the operation at runtime. Invalid
encodings fail closed. Starting SLH, changing the stateful family, reset, or a
new stateful Keygen invalidates the stateful cache as required.

## Implemented structure

The current candidate has exactly two physical
`micro_hbs_compact_shake_context_lane` instances. Both the SLH frontend and the
XMSS/LMS frontend request service from these shared, structurally identical U2
lanes. `SWAP_PHYSICAL_LANES` swaps the physical instances below both frontends.

The compiler emits one deterministic logical `256 x 128-bit` read-only product
image. It contains a four-word directory followed by the three profile token,
template, descriptor, and constant regions. The current image uses 203 of 256
words (25,984 of 32,768 bits) and contains no message or key material. Its
physical organization is one synchronous `512 x 64-bit` ROM; two consecutive
reads reconstruct one logical word, allowing the whole image to map to one
RAMB36 on 7-series.

That ROM now drives one `micro_hbs_unified_task_sequencer` for all six runtime
entries. `job_algorithm/job_operation` are used only to fetch a directory
entry. SINGLE/RUN/LOOP/HALT expansion, the event scoreboard, and command issue
are shared after startup. The old local sequencers are elaborated out of both
frontends in the unified build.

The stateful control image is now profile-specific. XMSS emits 67 explicit
`TREE_PUSH` commands per leaf, while LMS emits independent endpoint-list Hash,
leaf Hash, and outer `TREE_PUSH` commands. Keygen fields, Sign headers, and
cached authentication paths are selected by generic EMIT segment descriptors.
The former RTL `profile_list_reduce`, algorithm-specific output case, implicit
CHAIN header emission, and TREE authentication-output mode have been removed.

This is a functional migration of XMSS/LMS tree and output control into
microcode, but it does not yet complete the single materializer milestone.
SLH still uses the separate n=16 descriptor executor, and both executors still
hold local combinational descriptor views. The packed descriptor region is
readable through the unified sequencer but is not yet the only descriptor
storage. The two wide stateful fast-block formatters also remain.

## Functional and cycle results

All values below use `out_ready=1`; the unified wrapper adds one cycle to the
reference cores.

| Operation | Result | Cycles | Required counter |
|---|---:|---:|---:|
| SLH Sign tc137 | pass, 2,136 words exact | 851,713 | 10,680 contexts / 105,641 permutations |
| SLH Keygen tc31 | pass, 96 bytes exact | 32,385 | 295 contexts / 4,527 permutations |
| XMSS Keygen | pass, 196 bytes exact | 25,618,667 | 3,430,396 contexts/permutations |
| XMSS Sign q=5 | pass, 2,500 bytes exact | 17,210 | 1,554 contexts / 1,555 permutations |
| LMS Keygen | pass, 140 bytes exact | 8,212,693 | 1,100,799 contexts / 1,116,159 permutations |
| LMS Sign q=5 | pass, 2,508 bytes exact | 7,939 | 548 contexts/permutations |

The SLH Sign lane-swap regression produces the same signature, counts, and
cycle class. Combined physical-lane swap and randomized output backpressure
also passes for XMSS and LMS Keygen followed by q=5 and q=6 Sign. Random
backpressure is checked separately from PPA cycles.

Cycle gates currently pass for SLH Sign, XMSS Sign, and LMS Sign. XMSS Keygen
exceeds its 24,000,000-cycle gate by 1,618,667 cycles; LMS Keygen exceeds its
8,000,000-cycle gate by 212,693 cycles. Explicit XMSS L-tree pushes add 135,168
control cycles relative to the prior hidden RTL loop; Hash and permutation
counts are unchanged. The serial physical ROM adds only
control-fetch latency; it does not change any Hash or permutation count.

The Python target-architecture scheduler gives Hash-granularity lower bounds
of 633,857 cycles for SLH Sign, 20,582,405 for XMSS Keygen, 9,377 for XMSS
Sign, 6,696,965 for LMS Keygen, and 3,305 for LMS Sign. These values include
logical ROM startup and output drain, but require template patching to be
hidden under permutation. They are optimization targets, not measurements of
the current materializers.

## Post-synthesis PPA

Target: `xc7a200tffg1156-3`, U2, `PROFILE_ENABLE=0`, out-of-context Vivado
synthesis with `AreaOptimized_high`.

| Candidate | LUT | FF | LUTRAM | RAMB36 | RAMB18 | DSP | Equivalent Slice |
|---|---:|---:|---:|---:|---:|---:|---:|
| naive integration, four lanes | 63,702 | 24,022 | 1,654 | 14 | 1 | 0 | 22,298.05 |
| shared two-lane candidate | 52,579 | 20,821 | 1,654 | 14 | 1 | 0 | 19,117.18 |
| single sequencer, 128-bit physical ROM | 52,075 | 21,088 | 1,654 | 16 | 1 | 0 | 19,489.35 |
| single sequencer, serialized 64-bit ROM | 52,064 | 21,302 | 1,654 | 15 | 1 | 0 | 19,280.95 |
| rejected fixed-slice list composer | 52,993 | 21,297 | 1,654 | 15 | 1 | 0 | 19,512.58 |
| pruned unreachable stateful composer paths | 45,648 | 21,282 | 1,654 | 15 | 1 | 0 | 17,674.45 |
| rejected stateful descriptor prefetch | 46,533 | 21,460 | 1,654 | 15 | 1 | 0 | 17,917.95 |
| pruned composer + unreset guarded SLH data | 45,422 | 21,284 | 1,654 | 15 | 1 | 0 | 17,618.20 |
| plus unreset valid-guarded cache payload | 45,297 | 21,028 | 1,654 | 15 | 1 | 0 | 17,554.95 |
| plus unreset guarded output/ROM payload | 45,237 | 21,027 | 1,654 | 15 | 1 | 0 | 17,539.83 |
| target | <24,184 | - | - | <=16 equivalent | - | 0 | <11,587.98 |

Equivalent Slice uses `LUT/4 + FF/8 + RAMB36eq*232.4`, counting one RAMB18 as
half a RAMB36. The serialized-ROM candidate removes 515 LUT relative to the
earlier shared-lane result, but adds 481 FF and one RAMB36, so Equivalent Slice
is 163.78 higher. It is retained as the required unified-control foundation,
not accepted as the final PPA winner. It misses the LUT target by 27,880 and
the Equivalent Slice target by 7,692.97.

The fixed-slice list-composer ablation reduced TNS from -3,074.673 ns to
-60.233 ns, but increased LUT and Equivalent Slice, so it was reverted under
the stated two-metric acceptance rule.

The accepted composer-pruning candidate removes short-Hash byte-source cases
that were unreachable because those primitives always use the pre-padded
fast-block path.  XMSS/LMS KATs and all measured cycles are unchanged.  It
removes 6,416 LUT and 20 FF relative to the serialized-ROM foundation, lowering
Equivalent Slice by 1,606.50.  It still misses the LUT target by 21,464 and the
Equivalent Slice target by 6,086.47.  Post-synthesis WNS improves slightly from
-6.706 ns to -6.662 ns; timing closure is still not attempted at route level.

A stateful macro-descriptor prefetch experiment used the unified ROM port and a
two-entry descriptor cache.  It passed all KATs, but the remaining profile and
constant accesses kept the local descriptor LUTRAM intact; handshake/cache
logic instead added 885 LUT and 178 FF.  It also added 1,599 cycles to each
stateful Keygen.  The experiment was therefore reverted.

Removing asynchronous reset from guarded SLH data payload registers (while
retaining reset on FSM, valid, error, and counter state) removes another 226
LUT and 13 control sets without changing Keygen or Sign output/cycles.  This is
followed by removal of reset from the valid-guarded 256-bit cache response
payload, output-packer payload, and valid-guarded ROM payload.  The combined
candidate is the current area winner and misses the LUT target by 21,053 and
Equivalent Slice by 5,951.85.
Its post-synthesis WNS is -7.941 ns, so the area win does not yet constitute a
timing-closed candidate.

The two shared lanes each synthesize to 7,630 LUT and 2,183 FF, so their
post-synthesis area is exactly equal. The remaining dominant costs are the two
n=32 recipe/materializer lanes (12,517 LUT together), the stateful frontend
(21,871 LUT total), and the still separate SLH/stateful materializer and
descriptor paths. The unified sequencer itself is 544 LUT, 700 FF and one
RAMB36. Current post-synthesis WNS is -7.941 ns at 100 MHz.
No post-route run is permitted until function, cycle, area, and post-synthesis
timing gates pass.

## Remaining work before production replacement

1. Convert both executors from local combinational descriptor images to
   sequential macro-start prefetch from the packed ROM; retain only the active
   macro's descriptor records.
2. Migrate the SLH whole-tree macro to explicit CHAIN_REPEAT/TREE_PUSH control,
   then merge the n=16 and n=32 macro paths into one executor and add the
   specified issue/completion queues.
3. Replace the wide combinational stateful fast-block materializers with the
   specified shadow-rate-block template/patch engine and hide its work under
   each 12-cycle permutation.
4. Re-run all six operations, lane swap, state/cache failures, state-commit
   stalls, randomized backpressure, post-synthesis gates, and only then the
   single post-route run.
