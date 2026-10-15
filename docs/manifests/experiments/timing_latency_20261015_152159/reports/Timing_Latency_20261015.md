# P1U1 / P4U1 / P4U2 / P12U1 布线时序优化

更新时间：2026-10-19T10:09:05+08:00。本轮由用户明确授权布局布线；候选选择尚待实测。

工作区候选：`01_registered_intake`；与冻结 RTL 逐字节一致：`False`。综合结果和布线结果分别报告。

保持标准参数、单 Hash lane和模块接口。面积采用对应配置 common；使用通用 Keccak、同器件和默认时序驱动综合，不增加时序例外。综合约束沿用 6.666667 ns；布线起点 U1=150 MHz、U2=100 MHz。

验收预算：周期与总周期增幅各不超过 5%，独立报告变化；综合面积增幅警示线为 5%，超限单列并以实测时序/ATP取舍，不阻塞其他点布线。Hash/置换计数及逐字节输出必须一致；周期、面积超限属于性能预算问题，单独列出。

综合 WNS 只用于筛选，不能视为布线频率。本轮配置的基线及候选搜索预算均为最多 2 次独立实现，每轮做 0.1 ns STA 网格扫描并保留相邻失败证据；报告该搜索预算下实测闭合频率，不称全局最高频率。原长耗时综合继续后台，缺项保持空白，不借用其他配置。

## 基线瓶颈

| 配置 | 综合 WNS ns | 数据路径 ns | 逻辑级数 | 关键路径 |
|---|---:|---:|---:|---|
| P1U1 | -0.696 | 7.322 | 11 | `core/read_addresses.address_reg[6]/C` → `core/lane/scalar_execution.staged_data_reg[85]/D` |
| P4U1 | -1.505 | 8.131 | 13 | `core/read_addresses.address_reg[6]/C` → `core/lane/scheduled_execution.stages[0].words[0].state_reg_reg[0][25]/D` |
| P4U2 | -3.807 | 10.433 | 17 | `core/state_reg[1]_rep__6/C` → `core/lane/scheduled_execution.stages[0].words[0].state_reg_reg[0][47]/D` |
| P12U1 | -1.729 | 8.355 | 14 | `core/read_addresses.address_reg[6]/C` → `core/lane/scheduled_execution.stages[0].words[6].state_reg_reg[0][396]/D` |

上述关键路径直接提取自本轮冻结基线的综合 timing.rpt；未完成项留空，不沿用其他候选的路径归因。

## 候选与功能验证

### 01_registered_intake

P1提前登记两组13位流式来源选择并共享8字节尾块填充判定；P>1新增外部请求弹性接收级，链反馈保持原路径；固定/流式类型随有效位、标签和循环阶段传递，去除完成反馈中的外部模式选择。

逐字节输出、签名缓存及Hash/置换工作量核对：12/12 项通过；周期完全相同 3/12 项，满足周期预算 12/12 项。状态：`{'pending': 0, 'running': 0, 'passed': 16, 'failed': 0, 'cancelled': 0, 'skipped': 0}`。

## 综合对照

| 候选 | 配置 | 等效 Slice | 面积变化 | WNS ns | WNS 改善 ns | 级数 | 综合耗时 s | 状态 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| 01_registered_intake | P1U1 | 5,432.875 | 2.247% | -0.334 | 0.362 | 10 | 360.2 | passed |
| 01_registered_intake | P4U1 | 9,050.625 | -0.972% | -1.172 | 0.333 | 15 | 2,809.6 | passed |
| 01_registered_intake | P4U2 | 11,198.250 | -0.860% | -2.226 | 1.581 | 13 | 8,659.6 | passed |
| 01_registered_intake | P12U1 | 15,547.375 | 1.709% | -1.969 | -0.240 | 11 | 446.2 | passed |

## 布线对照

| 候选 | 配置 | 基线 MHz | 候选 MHz | 频率变化 | 候选布线 Slice | 搜索进度 |
|---|---|---:|---:|---:|---:|---|
| 01_registered_intake | P1U1 | 136.986 | 138.889 | 1.389% | 5,547.250 | passed |
| 01_registered_intake | P4U1 | 92.593 | 105.263 | 13.684% | 9,154.625 | passed |
| 01_registered_intake | P4U2 | — | — | — | — | failed |
| 01_registered_intake | P12U1 | 93.458 | 82.645 | -11.570% | 15,383.875 | passed |

## SLH-DSA 128f Sign 实测布线 ATP

| 候选 | 配置 | 基线周期 | 候选周期 | 周期变化 | 周期预算 | 基线 ATP Slice·ms | 候选 ATP Slice·ms | ATP 变化 |
|---|---|---:|---:|---:|---|---:|---:|---:|
| 01_registered_intake | P1U1 | 2,619,846 | 2,619,846 | 0.000% | 通过 | 103,580.327 | 104,637.173 | 1.020% |
| 01_registered_intake | P4U1 | 725,742 | 729,556 | 0.526% | 通过 | 70,064.983 | 63,448.710 | -9.443% |
| 01_registered_intake | P4U2 | 378,234 | 382,048 | 1.008% | 通过 | — | — | — |
| 01_registered_intake | P12U1 | 285,531 | 287,299 | 0.619% | 通过 | 47,141.836 | 53,479.240 | 13.443% |

## XMSS h10 Sign 实测布线 ATP

| 候选 | 配置 | 基线周期 | 候选周期 | 周期变化 | 周期预算 | 基线 ATP Slice·ms | 候选 ATP Slice·ms | ATP 变化 |
|---|---|---:|---:|---:|---|---:|---:|---:|
| 01_registered_intake | P1U1 | 86,567,075 | 86,567,075 | 0.000% | 通过 | 3,422,585.131 | 3,457,506.289 | 1.020% |
| 01_registered_intake | P4U1 | 21,443,190 | 21,482,119 | 0.182% | 通过 | 2,070,180.243 | 1,868,277.065 | -9.753% |
| 01_registered_intake | P4U2 | 10,794,618 | 10,833,547 | 0.361% | 通过 | — | — | — |
| 01_registered_intake | P12U1 | 7,986,643 | 8,004,057 | 0.218% | 通过 | 1,318,613.428 | 1,489,914.290 | 12.991% |

## LMS h10 Sign 实测布线 ATP

| 候选 | 配置 | 基线周期 | 候选周期 | 周期变化 | 周期预算 | 基线 ATP Slice·ms | 候选 ATP Slice·ms | ATP 变化 |
|---|---|---:|---:|---:|---|---:|---:|---:|
| 01_registered_intake | P1U1 | 28,524,614 | 28,524,614 | 0.000% | 通过 | 1,127,771.959 | 1,139,278.788 | 1.020% |
| 01_registered_intake | P4U1 | 7,335,182 | 7,354,654 | 0.265% | 通过 | 708,157.175 | 639,626.444 | -9.677% |
| 01_registered_intake | P4U2 | 3,768,770 | 3,788,242 | 0.517% | 通过 | — | — | — |
| 01_registered_intake | P12U1 | 2,999,059 | 3,007,256 | 0.273% | 通过 | 495,151.651 | 559,785.330 | 13.053% |

## 附加验证摘要

- `COMPATIBILITY_VALIDATION`：passed；详见同目录 JSON 的 validation 字段。
- `COMBINED_VALIDATION`：passed；详见同目录 JSON 的 validation 字段。
- `INTAKE_REVIEW`：见 JSON 摘要；详见同目录 JSON 的 validation 字段。
- `READY_SIGN_VALIDATION`：passed；详见同目录 JSON 的 validation 字段。

当前 RTL 为待验收候选。未结束的布线不报告最终频率或 ATP 收益；原始综合与仿真明细保留在各 build 目录。归档仅保留验证摘要、冻结源码及综合/布线证据，不保留 sim/validation 明细日志。

实验控制：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/timing_latency_20261015`。
