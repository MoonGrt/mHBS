# P12U1 低频综合关键路径诊断

更新时间：2026-10-15T16:01:43+08:00；状态：结束。

两版本均使用 common、xc7a200tffg1156-3、P12U1、50 ns（20 MHz）诊断约束、默认时序驱动综合和通用 Keccak；每个 Vivado 两线程，本次最多两个并发，全机主 Vivado 达到12个时等待。未启动仿真或布局布线。

**本次只定位组合路径和比较低频综合映射；面积、WNS不能作为原高频约束的验收结果，不计算频率上限或ATP。** 已补充同一候选冻结RTL的完整 Sign 实测：P12U1/P4U1，6 项全通过；周期、总周期、Hash/置换计数与对应基线逐项相同。

| 版本 | LUT | FF | 等效 Slice | WNS ns | 数据路径 ns | 逻辑级数 | 综合耗时 s | 状态 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| baseline | 49,407 | 24,784 | 15,449.750 | 41.364 | 8.418 | 11 | 408.2 | passed |
| candidate | 49,457 | 24,788 | 15,462.750 | 41.846 | 7.936 | 11 | 410.3 | passed |

## 关键路径

- **baseline**：`core/lane/FSM_sequential_scheduled_execution.state_reg[2]/C` → `core/fors_leaves_reg/CE`。
- **candidate**：`core/lane/scheduled_execution.fixed_context.complete_reg[0]/C` → `core/fors_leaves_reg/CE`。

每版目录保存冻结RTL压缩包、SOURCE.json逐文件SHA、综合日志、hierarchical.rpt、timing.rpt和前20条关键路径报告。缺项在ARTIFACTS.json明确列出，后台完成后自动补齐；原始DCP留在build运行目录。

运行目录：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/timing_diagnostic/20261015_154836`。
