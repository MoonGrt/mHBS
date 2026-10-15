# P12U1 低频综合关键路径诊断

更新时间：2026-10-19T10:18:07+08:00；状态：结束。

两版本均使用 common、xc7a200tffg1156-3、P12U1、50 ns（20 MHz）诊断约束、默认时序驱动综合和通用 Keccak；每个 Vivado 两线程，本次最多1个新综合并发，全机主 Vivado 达到12个时等待。未启动仿真或布局布线。

**本次只定位组合路径和比较低频综合映射；面积、WNS不能作为原高频约束的验收结果，不计算频率上限或ATP。** 候选验证状态：passed；通过数 40 / 40。仅按验证摘要已完成项报告，周期增幅及Hash/置换计数逐项列出，不预先假定周期一致。

| 版本 | LUT | FF | 等效 Slice | WNS ns | 数据路径 ns | 逻辑级数 | 综合耗时 s | 状态 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| baseline | 50,029 | 24,864 | 15,615.250 | 42.774 | 7.008 | 12 | 327.0 | passed；复用已校验结果（本轮未重跑） |
| candidate | 49,421 | 24,865 | 15,463.375 | 43.052 | 6.730 | 10 | 217.0 | passed |

## 关键路径

- **baseline**：`core/task_recipe_reg[57]/C` → `core/batch_issue_phase_reg/CE`。
  复用来源：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/timing_diagnostic/20261015_164939/candidate`；耗时列为原始测量耗时，本轮新增综合耗时为0。
- **candidate**：`core/task_recipe_reg[58]/C` → `core/batch_issue_phase_reg/CE`。

## 本轮候选已完成 Sign 验证

| 测试 | 基线周期 | 实测周期 | 周期增加 | 增幅 % | Hash/置换相同 |
|---|---:|---:|---:|---:|---|
| sign_P4U1_slh_128f_syn0 | 733,370 | 733,370 | 0 | 0.000 | True |
| sign_P4U2_slh_128f_syn0 | 385,862 | 385,862 | 0 | 0.000 | True |
| sign_P4U1_lms_h10_syn0 | 7,374,126 | 7,374,126 | 0 | 0.000 | True |
| sign_P4U2_lms_h10_syn0 | 3,807,714 | 3,807,714 | 0 | 0.000 | True |
| sign_P4U2_xmss_h10_syn0 | 10,872,476 | 10,872,476 | 0 | 0.000 | True |
| sign_P12U1_slh_128f_syn0 | 289,067 | 289,067 | 0 | 0.000 | True |
| sign_P4U1_xmss_h10_syn0 | 21,521,048 | 21,521,048 | 0 | 0.000 | True |
| sign_P12U1_lms_h10_syn0 | 3,015,453 | 3,015,453 | 0 | 0.000 | True |
| sign_P4U1_slh_128f_syn1 | 733,370 | 733,370 | 0 | 0.000 | True |
| sign_P12U1_xmss_h10_syn0 | 8,021,471 | 8,021,471 | 0 | 0.000 | True |
| sign_P4U1_lms_h10_syn1 | 7,374,126 | 7,374,126 | 0 | 0.000 | True |
| sign_P4U1_xmss_h10_syn1 | 21,521,048 | 21,521,048 | 0 | 0.000 | True |

每版目录保存冻结RTL压缩包、SOURCE.json逐文件SHA、综合日志、hierarchical.rpt、timing.rpt和前20条关键路径报告。缺项在ARTIFACTS.json明确列出，后台完成后自动补齐；原始DCP留在build运行目录。

运行目录：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/timing_diagnostic/20261019_101429`。
