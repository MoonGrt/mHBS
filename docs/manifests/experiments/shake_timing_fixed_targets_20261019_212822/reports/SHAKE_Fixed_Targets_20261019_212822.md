# SHAKE 两个固定目标的布线验证

更新时间：2026-10-20T03:31:27+08:00；状态：完成。

候选：`candidate_20261019_212542`。先等现有 P12U1／P4U1 的 150 MHz 布线终态；仅 setup／hold 未闭合的点额外执行一次 130 MHz 重新综合和布线。150 MHz 通过的点直接采用原证据；工具错误、DRC 或路由错误不被当作频率失败自动重跑。这是两个预先指定的固定目标，不进行频率搜索或新增时序例外。

common OOC、xc7a200tffg1156-3、SHAKE 通用 Keccak、默认时序驱动、SYNTHESIS 统计裁剪；每个 Vivado 两线程，全机最多 12 个。每个新增任务启动前核对冻结源码、控制脚本及三组完整 Sign 证据。异常耗时只延后分析，不停止任何原任务或新增任务。

| 配置 | 150MHz WNS ns | 150MHz WHS ns | 130MHz WNS ns | 130MHz WHS ns | 验收频率 MHz | 状态 |
|---|---:|---:|---:|---:|---:|---|
| P12U1 | -2.882 | 0.118 | — | — | — | additional_route_error |
| P4U1 | -2.178 | 0.099 | -0.629 | 0.094 | — | 130MHz_target_not_met |

| 配置 | 算法 | Sign周期 | 布线 Slice | 验收频率 MHz | 时间 ms | ATP Slice·ms |
|---|---|---:|---:|---:|---:|---:|
| P12U1 | slh_128f | 289,245.000 | — | — | — | — |
| P12U1 | lms_h10 | 3,016,478.000 | — | — | — | — |
| P12U1 | xmss_h10 | 8,021,472.000 | — | — | — | — |
| P4U1 | slh_128f | 733,548.000 | — | — | — | — |
| P4U1 | lms_h10 | 7,375,151.000 | — | — | — | — |
| P4U1 | xmss_h10 | 21,521,049.000 | — | — | — | — |

只有完整布线、DRC、受约束内部 setup／hold 及实际时钟周期全部满足目标时才填写频率与 ATP。100 MHz 诊断综合不作为布线验收；本报告不将失败目标的 WNS 代入公式估算最高频率。

本协调器未额外启动基线 100 MHz 布线。归档的 `BASELINE_PREPROCESSED_EQUIVALENCE.json` 仅证明此前 SHAKE SYNTHESIS common 可达的七个模块预处理源码一致；它不等于网表形式等价，也不新增基线布线结果。

运行目录：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/shake_timing_fixed_targets/20261019_212822`。完整 Vivado 日志、综合与布线报告及冻结 RTL／SHA 归档；未完成项保留空白并自动补齐。原仿真明细继续保存在候选运行目录。

P12U1：Additional fixed-target tool failure; see /media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/shake_timing_fixed_targets/20261019_212822/jobs/P12U1/vivado.log
