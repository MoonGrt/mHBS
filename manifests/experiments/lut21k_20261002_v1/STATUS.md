# 共同核 21k LUT 自动优化

基线：21,071 LUT / 8,324 FF / 1,112 LUTRAM / 6308.250 等效 Slice。
口径：K2U2，六参数 KG/SG/Verify，Vivado 2025.2，10 ns 共同核综合；未测新布线频率。

状态：**stopped**；当前：lut21k_20261002_v1_bank/synthesis；完成候选：0/7。

| 候选 | LUT | FF | LUTRAM | 等效 Slice | 结果 |
|---|---:|---:|---:|---:|---|
| bank | 21044.0 | 8323.0 | 1112.0 | 6301.375 | stopped_during_synthesis_reporting |
| tail | - | - | - | - | pending |
| shake | - | - | - | - | pending |
| bank_tail | - | - | - | - | pending |
| bank_shake | - | - | - | - | pending |
| tail_shake | - | - | - | - | pending |
| all | - | - | - | - | pending |

## 验收与证据

总 LUT 包含 LUTRAM；通过门槛为 LUT ≤21,000、等效 Slice <6308.250、BRAM/DSP 为零及完整回归通过。
冻结源码、补丁、阶段日志、原始综合报告和证据哈希保存在本目录 candidates/ 下；未完成数据用 `-`。
未达标时仅保留完整回归通过且面积优于基线的最佳项，不将失败候选应用到生产。

状态详情见 [state.json](state.json)，配置见 [config.json](config.json)。
