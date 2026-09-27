# 七参数点结果与复现入口

当前 ABI 4 七点结果以 [论文对比报告](Unified_HBS_Paper_Comparison.md) 和
[机器可读结果](../manifests/experiments/unified_hbs_v4/final.json) 为准。
完整 Keygen/Sign 时间、ATP、论文原始毫秒与 108 MHz 重算数据见
[comparison.csv](../manifests/experiments/unified_hbs_v4/comparison.csv)。

```bash
make reproduce-paper-comparison
python3 scripts/replay_profile.py slh_256f --run rtl-profile-test
```

重建硬件可将 `--run` 改为 `route-profile`，会依次执行仿真、综合与布线。
复现目录必须为空，避免覆盖工作文件。重新布线的资源和时序可能随工具
实现发生变化；归档报告的核验与重新运行实现是两个独立步骤。

以下保留历史 ABI 3 三点基线；历史构建命令必须在固定源码版本运行。

# Historical μHBS ABI 3 implementation and ATP

## Scope and evidence

The software interpreter executes all five macros from the serialized image.
The initial software gate passed before RTL migration. The completed gate also
compares all 2,047 XMSS and LMS tree nodes and exact hash/permutation counts
with independent algorithm models. SLH-DSA matches ACVP SigGen tc137; stateful
outputs match the committed KAT byte streams. Software checks messages of
multiple lengths, q=0/1023, exhaustion, commit refusal and failure after commit.

Production wrappers share `mhbs_hbs` and immutable ABI 3 images. The defaults
are complete Keygen/Sign fixtures with fixed keys, q and message length; message
content is streamed. The candidates compare UNROLL=2/4, with two lanes for
SLH-DSA and one lane for XMSS/LMS after lane-count screening. Icarus 12.0 units and Verilator 5.008
`--binary --timing` full runs check outputs, counts, backpressure stability,
physical lane exchange, errors and durable-index acknowledgment.

Verification summaries and inherited historical-test failures are archived in
`manifests/experiments/unified_hbs_V3/`. `make test-unified` passes. The retired
historical suite had 7 failures and 1 error, reproduced in its original HEAD.
It was removed during project cleanup; `make test` now runs the current unified gate.

## Measurement contract

Device: xc7a200tffg1156-3. Tool: Vivado 2025.2. Each family is synthesized and
routed independently from the same core source. PROFILE_ENABLE=0 for PPA;
profiling counters are enabled only in functional simulations. Sources, image
hashes and parameters are saved with each build.

Equivalent Slice = LUT/4 + FF/8 + BRAM36-equivalent×232.4 + DSP×102.4.
Sign time (ms) = Sign cycles × clock period (ns) / 1,000,000.
ATP = equivalent Slice × Sign time.

Post-synth screening uses a common 100 MHz normalization and separately reports
estimated setup slack. Retained candidates alone proceed to route. Final clock
selection rechecks the routed netlist at a period rounded upward to 0.1 ns with
at least 0.1 ns setup margin; final setup, hold, pulse-width and routing reports
must pass. This is FPGA OOC timing of internal register paths. Unplaced external data/control
ports and reset are excluded; their paths cannot be timed physically without
parent-design or board pin constraints. Internal setup/hold/pulse checks remain
enabled, including the registered execution-abort path. These are not board-clock
measurements or interface timing closure. Board pads,
external storage and the durable-index persistence service are outside the area.

Cycle counts include streaming and state-commit waits. The normal benchmark
provides the message immediately, keeps output ready and acknowledges the
commit immediately. The wrapper adds four control cycles around the two
internally measured operations. Stress-run cycle increases are reported
separately and are not used to claim a fixed external persistence latency.

## Comparison limitations

All external comparisons are **NON_STRICT**. The paper uses one configurable
multi-algorithm design; these products are separately specialized fixed Jobs.
SLH-DSA-SHAKE-128f differs from the paper's SPHINCS+ workload. LMS retains this
repository's SHAKE256/256 research profile. The one fixed message is not a
1,000-message average. Fixed keys and message lengths allow constant pruning.

XMSS/LMS Keygen still computes the entire h=10 tree, but caches only the current
q's ten authentication nodes and root. Sign therefore needs no tree hashing.
The next start rebuilds the complete tree for the next q; no amortized multi-sign
throughput claim is made. Reset loses volatile index/cache state. The paper
retains more tree data and signature buffering, so its memory workload differs.

The supplied paper table reports LUT=24,184, FF=13,659, BRAM=16.5, DSP=0:
11,587.975 equivalent Slices. Its rounded Sign times 4.95, 0.13 and 0.05 ms
produce the approved numerical targets 57,360.476, 1,506.437 and 579.399
Slice·ms. See the local paper reader, Table 7 and its area footnote.

## Results

All three U2 products pass the approved numerical targets with complete routing
and internally constrained setup/hold/pulse timing. These are the selected builds
and the lowest ATP among completed, source-matched candidates. This is not a
claim of a global optimum. The optional U4 routes were stopped after more than
30 minutes in congestion repair once all three U2 acceptance gates had passed;
their partial logs and post-synth results are retained under
`{slh,xmss,lms}_u4_incomplete/`. No final timing or ATP ranking is claimed for U4.
The machine-readable final selection is `manifests/experiments/unified_hbs_final.json`.

| Profile | Lanes / Unroll | LUT | FF | BRAM / DSP | Equivalent Slice | MHz | Sign ATP | Target |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| slh | 2 / 2 | 19,236 | 8,033 | 0 / 0 | 5,813.125 | 91.743 | 48,225.754 | 57,360.476 |
| xmss | 1 / 2 | 13,176 | 6,114 | 0 / 0 | 4,058.250 | 96.154 | 888.939 | 1,506.437 |
| lms | 1 / 2 | 14,549 | 5,357 | 0 / 0 | 4,306.875 | 91.743 | 373.916 | 579.399 |

| Profile | Keygen cycles | Keygen ms | Sign cycles | Sign ms | Setup slack ns | Hold slack ns |
|---|---:|---:|---:|---:|---:|---:|
| slh | 29,710 | 0.323839 | 761,102 | 8.296012 | 0.122 | 0.099 |
| xmss | 45,220,862 | 470.296965 | 21,062 | 0.219045 | 0.119 | 0.099 |
| lms | 14,998,561 | 163.484315 | 7,965 | 0.086819 | 0.132 | 0.094 |

These are arithmetic improvements against the numerical thresholds, not strict
same-workload speedups. Keygen cost is shown separately and is not amortized.
All retained products have zero TNS/THS/TPWS and zero unconstrained internal
endpoints. All routable nets are fully routed; external port nets are implicit
OOC boundaries.

### Reproduction

From the project directory, run the software and RTL gates described in
`Architecture.md`, then (example for XMSS):

```bash
make synth-xmss XMSS_TAG=unified_xmss_v7_u2p1 UNROLL=2 LANES=1
vivado -mode batch -nojournal -nolog -source experiments/route_unified_hbs.tcl \
  -tclargs unified_xmss_v7_u2p1 11 unified_xmss_v7_u2p1_core_route
vivado -mode batch -nojournal -nolog -source experiments/finalize_unified_clock.tcl \
  -tclargs unified_xmss_v7_u2p1_core_route
python3 scripts/collect_unified_ppa.py unified_xmss_v7_u2p1_core_route xmss \
  --route --period 10.4 --cycles 21062 --keygen-cycles 45220862
```

For another route realization, use the period from its `final_clock.json`;
place/route is not guaranteed to produce identical timing on another machine.
The `_core_route/post_route_final_clock.dcp` checkpoint and `constraints.xdc`
retain the rechecked clock. Reviewable JSON, source hashes, utilization,
hierarchical utilization, timing, coverage and route-status reports are archived
under `manifests/experiments/unified_hbs_V3/{slh,xmss,lms}_u2/`.
`make reproduce-paper-comparison` recalculates the comparison from those raw
reports, the U2 cycle logs, and the paper reader's Tables 5/7. It checks source
digests, derived JSON/CSV and report numbers. The retained U4 archives are
checked for presence but are not ranked.
The route script digest in each synthesis-time `inputs.json` predates the final
route script revision. The actual routed flow is recorded separately in
`route_inputs.json`; the reproduction check uses that digest for the route flow.

### Optimization decisions

1. Replace variable-position padding writes with constant offsets; replace
   multiplication by the SHAKE rate with shifts/addition. DSP use becomes zero.
2. Infer parity-banked value storage and reset-free stack/auth data arrays.
3. Retain only the selected authentication path without changing Keygen/Sign
   hash counts; statically prune absent recipes and the fixed-length message
   buffer. The second logical lane carries only chain recipes.
4. Compare lane count and round unroll with full KAT runs and post-synth area.
   U4 single-lane XMSS/LMS beats U4 dual-lane in normalized ATP (653.31 vs
   729.63 and 262.11 vs 281.72 in the pre-abort-register screen).
5. The post-synth archive contains 31 candidates. U2 Sign spends 95.11% / 96.39% / 90.41% of cycles in HASH_WAIT for
   SLH-DSA / XMSS / LMS (`residency.json`). Compare U2 and U4 at routed timing;
   U4's lower cycles do not imply lower ATP.
   Keep the error-abort pulse in an independent register and assert its presence
   after synthesis; an asynchronous reset must not be driven by a binary state
   decode.
