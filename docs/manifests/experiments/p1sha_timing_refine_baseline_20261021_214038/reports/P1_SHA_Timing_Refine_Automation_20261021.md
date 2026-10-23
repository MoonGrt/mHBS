# C3基础 D1／D2 最终固定频率协调

更新时间：2026-10-21T22:47:22+08:00；PID：2994362；阶段：`complete`。

四个P1配置就绪后确定最多两份候选。每配置仅等待自身3个完整Sign、对应100MHz common诊断和同源码36组功能验证；SHA2P4异常慢点保留后台，不阻塞P1路由。U1固定150MHz、U2固定100MHz，最多两份源码各六点。不搜索、降频或新增时序例外。

按各后端、各P/U、三个算法逐项比较假定ATP与诊断路径；不使用均值掩盖坏点。只有六点证据齐全且一候选各项都被另一候选支配时才排除；P4证据未齐时保留两份并先跑P1。诊断路径不代表Fmax，最终只按真实STA和布线ATP作结论。

| 候选 | 配置 | 就绪 | 待完成 | 失败 |
|---|---|---|---:|---:|
| candidate_20261021_214504 | shake/P1U1 | True | 0 | 0 |
| candidate_20261021_214504 | shake/P1U2 | True | 0 | 0 |
| candidate_20261021_214504 | sha2/P1U1 | True | 0 | 0 |
| candidate_20261021_214504 | sha2/P1U2 | True | 0 | 0 |
| candidate_20261021_214504 | sha2/P4U1 | True | 0 | 0 |
| candidate_20261021_214504 | sha2/P4U2 | True | 0 | 0 |
| candidate_20261021_215634 | shake/P1U1 | True | 0 | 0 |
| candidate_20261021_215634 | shake/P1U2 | True | 0 | 0 |
| candidate_20261021_215634 | sha2/P1U1 | True | 0 | 0 |
| candidate_20261021_215634 | sha2/P1U2 | True | 0 | 0 |
| candidate_20261021_215634 | sha2/P4U1 | True | 0 | 0 |
| candidate_20261021_215634 | sha2/P4U2 | True | 0 | 0 |

Keep both: preserve per-backend/P/U tradeoffs and do not wait for missing P4 diagnostics

- [D1_stream_mode_randomizer_lookaheadK](docs/manifests/experiments/p1sha_timing_refine_candidate_20261021_214504/reports/P1_SHA_Fixed_Targets_20261021_214504.md)：`04a994e51e438307f1855090fcaa6d7ea0b466d971a7f31f4de8325646ab6a1e`。
- [D2_stream_words_preparedH_shared_output_static_scheduler](docs/manifests/experiments/p1sha_timing_refine_candidate_20261021_215634/reports/P1_SHA_Fixed_Targets_20261021_215634.md)：`53987fe06e56a4fa8c1bcc2e06c8f2959f92a8e4d0c5e3f9b9bea226fec1a48e`。

跨进程预约共享旧任务锁，统计顶层job（wrapper/实际进程去重，忽略SYNTH_DESIGN_PARENT内部worker），全机最多12个Vivado，每个2线程。旧矩阵和旧协调器保留，不修改生产RTL。
