# Frozen local-subunit evidence: stream_subunit

This archive binds **only the stream_subunit** to the frozen `u5_atp_optimization_20261020_150014` RTL. `LOCAL_BINDING.json` verifies the relevant frozen source fragment is byte-identical to the fragment in the actual passing local equivalence bench, and verifies the complete frozen recipe against both `SOURCE.json` and `rtl.tar.gz`. The original full A/B source files used to construct the bench are not the complete later V3/V4 snapshots; unrelated later edits are outside this test. This is extracted local RTL equivalence, **not full-core snapshot validation**.

Run `python3 reproduce.py` to verify evidence checksums and rebuild the exact combined local bench in a temporary directory. Both historical local A/B subtests are retained for faithful reproduction; the unrelated subtest is not attributed as verification of this archive's other RTL. Detailed compile/simulation logs remain under `tmp/u5_recipe_candidate/` and are omitted here. No production or frozen RTL was modified.

# U5 recipe candidates

Both independent patches target the captured `baseline.sv` (U5), change only the P>1 scheduled recipe implementation, and add no cycles. Production RTL was not edited. No Vivado was launched.

## A: common SLH32 / XMSS32 placement

`A_common_layout.patch` replaces two complete 1088-bit formatting candidates with one common layout. Both original layouts placed their value at bytes 64–95, optional right node at 96–127, SHAKE suffix at byte 96 or 128, and the terminal bit at byte 135. The first 64 bytes and selected value/right operands differ by family; these are selected before placement. The n=16/24 SLH and LMS layouts are untouched.

No state is added, removed, or shared across time. Inputs are exactly the same old operands from the pending request or prefetched return snapshot. The resulting 1600-bit permutation state is combinationally identical, including unsupported two-bit family values and unsupported node widths. The potential saving is less wide OR/masking around the common upper 576 bits; actual synthesis may already factor some of this, so measurement is required.

## B: one stream payload snapshot

`B_stream_payload.patch` replaces `fetched_source[127:0]`, `fetched_list[127:0]`, and `fetched_use_list` with a single selected `fetched_payload[127:0]`. The source data, list data, and selection are sampled on precisely the original `stream_accept && state==STREAM` edge. All prefix/padding/control snapshots remain unchanged. `fetched_valid` and all ready/valid logic remain unchanged.

Lifetime proof: a fetch owns at most one payload; source and list windows are mutually exclusive for the same beat. With `stream_accept==0`, both old operands plus their select and the new selected payload hold. On an accepted beat, the new register captures exactly the operand chosen by the old select snapshot, and padding consumes that same payload on the same cycle. Reset clears `fetched_valid`; payloads may remain unspecified while invalid, exactly as before. No context/capture bank is reused or overwritten.

A simulation-only original dual-payload snapshot oracle is retained under `ifndef SYNTHESIS`. It checks each valid fetched payload against the original stage, including stalls. The local sequential equivalence harness extracts the actual old/new fetch and padding RTL.

B removes 129 functional FF and a post-stage 128-bit mux, but moves that mux in front of the fetch register. This adds up to one LUT level to endpoint RAM→list_window→fetched_payload and possibly to the source path. U5 P4 endpoint→fetched_source already has 5.013 ns data delay, so B may trade area for a slower path. Treat it as a measurement candidate and reject if ATP/timing regresses.

## Local validation

The original runtime extraction script `tmp/u5_recipe_candidate/check_equivalence.py` constructed the archived `equivalence.sv` from the exact formatter and stream stages. The archived `reproduce.py` compiles that fixed bench and runs Verilator without depending on mutable production RTL. It covers 2048 directed formatter combinations (all 4 family values, all 64 node widths, all 8 format controls), 100000 randomized formatter cases, and 100000 sequential stream cycles with independent resets, stalls, selected windows, prefix controls and padding controls. This is an implementation equivalence check, not a replacement for full algorithm/reference tests or area measurements.

The parent's separate intake-enable optimization was reviewed: updating only payload registers when `queue_open` instead of `receive` preserves every live pending request. `queue_open` is false for a stalled valid pending request; true for an empty queue or an old request dispatched on that edge. In the latter case, a new receive replaces the consumed payload; absent a new receive, the payload becomes invalid and may freely change. All context/bank writes remain gated by `accept`, and pending-tag slot exclusion remains gated by `pending_valid`.
