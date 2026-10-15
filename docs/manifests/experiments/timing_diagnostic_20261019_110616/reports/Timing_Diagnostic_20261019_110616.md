# P12U1 低频综合关键路径诊断

更新时间：2026-10-19T12:05:48+08:00；状态：结束。

两版本均使用 common、xc7a200tffg1156-3、P12U1、10 ns（100 MHz）诊断约束、默认时序驱动综合和通用 Keccak；每个 Vivado 两线程，本次最多1个新综合并发，全机主 Vivado 达到12个时等待。未启动仿真或布局布线。

**本次只定位组合路径和比较低频综合映射；面积、WNS不能作为原高频约束的验收结果，不计算频率上限或ATP。** 候选验证状态：passed；通过数 43 / 43。仅按验证摘要已完成项报告，周期增幅及Hash/置换计数逐项列出，不预先假定周期一致。

| 版本 | LUT | FF | 等效 Slice | WNS ns | 数据路径 ns | 逻辑级数 | 综合耗时 s | 状态 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| baseline | 49,421 | 24,865 | 15,463.375 | 3.052 | 6.730 | 10 | 227.8 | passed；复用已校验结果（本轮未重跑） |
| candidate | 49,944 | 24,865 | 15,594.125 | 2.860 | 6.804 | 12 | 232.5 | passed |

## 关键路径

- **baseline**：`core/task_recipe_reg[58]/C` → `core/batch_issue_phase_reg/CE`。
  复用来源：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/timing_diagnostic/20261019_103518/baseline`；耗时列为原始测量耗时，本轮新增综合耗时为0。
- **candidate**：`core/fors_base_reg[5]/C` → `core/continuation_reg[0]/CE`。

## 本轮候选已完成 Sign 验证

| 测试 | 基线周期 | 实测周期 | 周期增加 | 增幅 % | Hash/置换相同 |
|---|---:|---:|---:|---:|---|
| sign_P1U1_slh_128f_syn0 | 2,619,846 | 2,619,846 | 0 | 0.000 | True |
| sign_P4U1_slh_128f_syn0 | 733,370 | 734,602 | 1,232 | 0.168 | True |
| sign_P1U1_lms_h10_syn0 | 28,524,614 | 28,524,614 | 0 | 0.000 | True |
| sign_P4U1_lms_h10_syn0 | 7,374,126 | 7,390,510 | 16,384 | 0.222 | True |
| sign_P4U2_slh_128f_syn0 | 385,862 | 387,094 | 1,232 | 0.319 | True |
| sign_P1U1_xmss_h10_syn0 | 86,567,075 | 86,567,075 | 0 | 0.000 | True |
| sign_P4U2_lms_h10_syn0 | 3,807,714 | 3,824,098 | 16,384 | 0.430 | True |
| sign_P4U1_xmss_h10_syn0 | 21,521,048 | 21,537,432 | 16,384 | 0.076 | True |
| sign_P12U1_slh_128f_syn0 | 289,067 | 289,375 | 308 | 0.107 | True |
| sign_P4U2_xmss_h10_syn0 | 10,872,476 | 10,888,860 | 16,384 | 0.151 | True |
| sign_P12U1_lms_h10_syn0 | 3,015,453 | 3,020,573 | 5,120 | 0.170 | True |
| sign_P4U1_slh_128f_syn1 | 733,370 | 734,602 | 1,232 | 0.168 | True |
| sign_P4U1_lms_h10_syn1 | 7,374,126 | 7,390,510 | 16,384 | 0.222 | True |
| sign_P12U1_xmss_h10_syn0 | 8,021,471 | 8,026,591 | 5,120 | 0.064 | True |
| sign_P4U1_xmss_h10_syn1 | 21,521,048 | 21,537,432 | 16,384 | 0.076 | True |

每版目录保存冻结RTL压缩包、SOURCE.json逐文件SHA、综合日志、hierarchical.rpt、timing.rpt和前20条关键路径报告。缺项在ARTIFACTS.json明确列出，后台完成后自动补齐；原始DCP留在build运行目录。

运行目录：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/timing_diagnostic/20261019_110616`。
