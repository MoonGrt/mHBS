# SHAKE P12U1／P4U1 时序架构对照

更新时间：2026-10-20T01:43:59+08:00；9 轮测量：全部结束。

C7 保留为功能验证通过的当前候选，频率与最终 ATP 结论等待独立布线。当前工作区 10 个 RTL SHA 与 C7 全部一致。

报告不自动替换 RTL。100 MHz 综合用于面积和路径诊断，不能证明实际最高频率或 ATP 改善。150／130 MHz 布线另列，完整布通、DRC、setup／hold 均通过才记录该目标下时间与 ATP；失败目标不能推导成较低频率已闭合。

共同口径：SHAKE、单 Hash lane、common OOC、xc7a200tffg1156-3、通用 Keccak、默认时序驱动、每个 Vivado 两线程；无新增 false-path／multicycle。算法执行互斥，未引入 P/U 专用优化。h20 完整 Keygen／Sign 保持停止。

| 阶段 | 冻结版本 | 内容 | Sign 通过 | 完成 |
|---|---|---|---:|---|
| B0 | `baseline_20261019_211532` | 当前基线 | 6/6 | 是 |
| B0r | `baseline_20261019_211543` | 同源基线重复综合 | 6/6 | 是 |
| C1 | `candidate_20261019_211536` | 统一输入寄存器；中间级取消 reset 数据使能 | 6/6 | 是 |
| C2 | `candidate_20261019_211601` | C1＋末级前一拍预读上下文 | 6/6 | 是 |
| C3 | `candidate_20261019_211718` | C2＋流式窗口与填充间寄存器 | 6/6 | 是 |
| C4 | `candidate_20261019_211827` | 保留上下文预读及流式级；撤销统一输入级，按模式选择输入 | 6/6 | 是 |
| C5 | `candidate_20261019_212211` | C4＋固定标量引擎由寄存的 FIXED_WAIT 所有权驱动 | 6/6 | 是 |
| C6 | `candidate_20261019_212542` | C5＋FORS 目标相对索引提前登记，范围比较及父节点索引复用 | 6/6 | 是 |
| C7 | `candidate_20261019_213301` | C6＋上下文控制预读、反馈预约和已保留槽位的直接 ready | 6/6 | 是 |

## 关键路径与改动依据

原 P12U1 的 100 MHz 实际布线最差内部路径为末级 tag→captured 上下文 RAM→固定块格式化→首轮 Keccak→第一级状态寄存器，9.884 ns、8 级，连线占 88.699%。其 tag→RAM 地址网扇出 178、连线 3.042 ns；瓶颈包含上下文选择和宽数据布局，并非仅有 Keccak 轮逻辑。原始证据见 [100 MHz 布线报告](/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/docs/manifests/experiments/timing_targets_20261019_120529/jobs/P12U1_100MHz/route/timing.rpt:225)。

C1 在格式化与首轮之间加入弹性输入寄存器，并去掉中间无效数据流水级的 reset 使能；有效位及末级共享 sponge 的功能控制保留。C2 用倒数第二级 tag 提前读取上下文，使 key／digest／captured、地址和格式控制与最后一级置换结果对齐。C3 在流式窗口选择与填充间加入数据／控制寄存器，减少端点 RAM→窗口选择→填充的串联级数。C4 保留后两项，撤销额外统一输入级，通过 engine_mode 选择固定与流式状态，避免 request-valid 串入宽 mux。C5 将 engine_mode 中的标量分支改为已登记的 FIXED_WAIT 所有权，使首次请求的组合配方译码不再串入引擎 ready；scalar_bridge 仍负责初次请求字段选择。C6 提前登记 FORS 目标相对索引，并共用范围比较与父节点索引。C7 在数据预读之外同步预读 phase／format／iteration／node 控制，提前登记反馈预约；pending 已保留槽位的下游 ready 直接使用物理流水容量，去掉重复模式判断。C7 相对 C6 保持三个 Sign 周期，同时 P12 的诊断面积与路径下降；P4 诊断路径略降、面积略增，实际收益仍由布线 ATP 判定。各阶段是否有效由下列实测决定；失败或未完成阶段同样保留。

## 面积与低频综合诊断

面积均取各自配置的 common；等效 Slice=LUT/4＋FF/8＋232.4×BRAM36＋102.4×DSP。综合路径含未布局连线估计，不转换为 Fmax。

| 阶段 | 配置 | LUT | FF | BRAM36 | Slice | 面积变化 % | 综合路径 ns | 级数 | 耗时 s | 状态 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| B0 | P12U1 | 49,421 | 24,865 | 0.000 | 15,463.375 | 0.000 | 6.730 | 10 | 285.187 | passed |
| B0 | P4U1 | 31,174 | 11,345 | 0.000 | 9,211.625 | 0.000 | 7.074 | 12 | 272.151 | passed |
| B0r | P12U1 | 49,421 | 24,865 | 0.000 | 15,463.375 | 0.000 | 6.730 | 10 | 289.572 | passed |
| B0r | P4U1 | 31,174 | 11,345 | 0.000 | 9,211.625 | 0.000 | 7.074 | 12 | 269.093 | passed |
| C1 | P12U1 | 49,462 | 26,437 | 0.000 | 15,670.125 | 1.337 | 7.090 | 13 | 304.853 | passed |
| C1 | P4U1 | 30,968 | 12,935 | 0.000 | 9,358.875 | 1.599 | 7.065 | 12 | 247.419 | passed |
| C2 | P12U1 | 49,865 | 27,371 | 0.000 | 15,887.625 | 2.744 | 7.043 | 12 | 407.510 | passed |
| C2 | P4U1 | 31,756 | 13,825 | 0.000 | 9,667.125 | 4.945 | 6.804 | 12 | 260.375 | passed |
| C3 | P12U1 | 50,286 | 27,600 | 0.000 | 16,021.500 | 3.609 | 7.054 | 12 | 222.829 | passed |
| C3 | P4U1 | 32,701 | 14,112 | 0.000 | 9,939.250 | 7.899 | 6.600 | 13 | 209.512 | passed |
| C4 | P12U1 | 50,253 | 26,023 | 0.000 | 15,816.125 | 2.281 | 7.388 | 11 | 311.842 | passed |
| C4 | P4U1 | 31,537 | 12,496 | 0.000 | 9,446.250 | 2.547 | 7.120 | 13 | 198.180 | passed |
| C5 | P12U1 | 48,904 | 26,008 | 0.000 | 15,477.000 | 0.088 | 6.816 | 12 | 287.199 | passed |
| C5 | P4U1 | 30,918 | 12,494 | 0.000 | 9,291.250 | 0.864 | 6.511 | 12 | 265.679 | passed |
| C6 | P12U1 | 50,304 | 26,041 | 0.000 | 15,831.125 | 2.378 | 7.002 | 12 | 278.838 | passed |
| C6 | P4U1 | 31,128 | 12,512 | 0.000 | 9,346.000 | 1.459 | 6.417 | 12 | 185.411 | passed |
| C7 | P12U1 | 49,480 | 26,025 | 0.000 | 15,623.125 | 1.033 | 6.740 | 10 | 265.763 | passed |
| C7 | P4U1 | 31,308 | 12,521 | 0.000 | 9,392.125 | 1.959 | 6.404 | 12 | 227.418 | passed |

| 阶段 | 配置 | 综合路径起点 | 综合路径终点 |
|---|---|---|---|
| B0 | P12U1 | `core/task_recipe_reg[58]/C` | `core/batch_issue_phase_reg/CE` |
| B0 | P4U1 | `core/read_addresses.address_reg[6]/C` | `core/lane/scheduled_execution.staged_data_reg[32]/D` |
| B0r | P12U1 | `core/task_recipe_reg[58]/C` | `core/batch_issue_phase_reg/CE` |
| B0r | P4U1 | `core/read_addresses.address_reg[6]/C` | `core/lane/scheduled_execution.staged_data_reg[32]/D` |
| C1 | P12U1 | `core/fors_base_reg[5]/C` | `core/state_reg[4]/D` |
| C1 | P4U1 | `core/read_addresses.address_reg[6]/C` | `core/lane/scheduled_execution.staged_data_reg[88]/D` |
| C2 | P12U1 | `core/task_recipe_reg[56]/C` | `core/batch_issue_phase_reg/CE` |
| C2 | P4U1 | `core/fors_base_reg[5]/C` | `core/continuation_reg[0]/CE` |
| C3 | P12U1 | `core/task_recipe_reg[57]/C` | `core/batch_issue_phase_reg/CE` |
| C3 | P4U1 | `core/target_reg[11]/C` | `core/chain_cursor_reg[0]/CE` |
| C4 | P12U1 | `core/task_recipe_reg[57]/C` | `core/batch_issue_phase_reg/CE` |
| C4 | P4U1 | `core/fors_base_reg[5]/C` | `core/state_reg[0]/D` |
| C5 | P12U1 | `core/lane/FSM_sequential_scheduled_execution.state_reg[0]/C` | `core/batch_issue_phase_reg/CE` |
| C5 | P4U1 | `core/node_level_reg[3]/C` | `core/endpoints/banks[0].regular.words_reg_0_63_0_2/RAMA/WE` |
| C6 | P12U1 | `core/lane/scheduled_execution.fixed_context.feedback_required_reg[11]/C` | `core/lane/scheduled_execution.stages[0].words[0].advancing.state_reg_reg[0][61]/D` |
| C6 | P4U1 | `core/node_level_reg[3]/C` | `core/node_level_reg[2]/R` |
| C7 | P12U1 | `core/task_recipe_reg[56]/C` | `core/read_addresses.address_reg[3]/R` |
| C7 | P4U1 | `core/node_level_reg[3]/C` | `core/node_level_reg[2]/R` |

## slh_128f 完整 Sign

| 阶段 | 配置 | 周期 | 相对 B0 % | Hash | 置换 | 相同工作量 | 输出／缓存逐字节 | 状态 |
|---|---|---:|---:|---:|---:|---|---|---|
| B0 | P12U1 | 289,067 | 0.000000 | 104,937 | 105,641 | 是 | — | passed |
| B0 | P4U1 | 733,370 | 0.000000 | 104,937 | 105,641 | 是 | — | passed |
| B0r | P12U1 | 289,067 | 0.000000 | 104,937 | 105,641 | 是 | — | passed |
| B0r | P4U1 | 733,370 | 0.000000 | 104,937 | 105,641 | 是 | — | passed |
| C1 | P12U1 | 299,833 | 3.724396 | 104,937 | 105,641 | 是 | — | passed |
| C1 | P4U1 | 762,329 | 3.948757 | 104,937 | 105,641 | 是 | — | passed |
| C2 | P12U1 | 299,833 | 3.724396 | 104,937 | 105,641 | 是 | — | passed |
| C2 | P4U1 | 762,329 | 3.948757 | 104,937 | 105,641 | 是 | — | passed |
| C3 | P12U1 | 300,011 | 3.785973 | 104,937 | 105,641 | 是 | 是 | passed |
| C3 | P4U1 | 762,507 | 3.973029 | 104,937 | 105,641 | 是 | 是 | passed |
| C4 | P12U1 | 289,245 | 0.061577 | 104,937 | 105,641 | 是 | 是 | passed |
| C4 | P4U1 | 733,548 | 0.024272 | 104,937 | 105,641 | 是 | 是 | passed |
| C5 | P12U1 | 289,245 | 0.061577 | 104,937 | 105,641 | 是 | 是 | passed |
| C5 | P4U1 | 733,548 | 0.024272 | 104,937 | 105,641 | 是 | 是 | passed |
| C6 | P12U1 | 289,245 | 0.061577 | 104,937 | 105,641 | 是 | 是 | passed |
| C6 | P4U1 | 733,548 | 0.024272 | 104,937 | 105,641 | 是 | 是 | passed |
| C7 | P12U1 | 289,245 | 0.061577 | 104,937 | 105,641 | 是 | 是 | passed |
| C7 | P4U1 | 733,548 | 0.024272 | 104,937 | 105,641 | 是 | 是 | passed |

## xmss_h10 完整 Sign

| 阶段 | 配置 | 周期 | 相对 B0 % | Hash | 置换 | 相同工作量 | 输出／缓存逐字节 | 状态 |
|---|---|---:|---:|---:|---:|---|---|---|
| B0 | P12U1 | 8,021,471 | 0.000000 | 3,431,815 | 3,431,815 | 是 | — | passed |
| B0 | P4U1 | 21,521,048 | 0.000000 | 3,431,815 | 3,431,815 | 是 | — | passed |
| B0r | P12U1 | 8,021,471 | 0.000000 | 3,431,815 | 3,431,815 | 是 | — | passed |
| B0r | P4U1 | 21,521,048 | 0.000000 | 3,431,815 | 3,431,815 | 是 | — | passed |
| C1 | P12U1 | 8,349,401 | 4.088153 | 3,431,815 | 3,431,815 | 是 | — | passed |
| C1 | P4U1 | 22,408,429 | 4.123317 | 3,431,815 | 3,431,815 | 是 | — | passed |
| C2 | P12U1 | 8,349,401 | 4.088153 | 3,431,815 | 3,431,815 | 是 | — | passed |
| C2 | P4U1 | 22,408,429 | 4.123317 | 3,431,815 | 3,431,815 | 是 | — | passed |
| C3 | P12U1 | 8,349,402 | 4.088165 | 3,431,815 | 3,431,815 | 是 | 是 | passed |
| C3 | P4U1 | 22,408,430 | 4.123322 | 3,431,815 | 3,431,815 | 是 | 是 | passed |
| C4 | P12U1 | 8,021,472 | 0.000012 | 3,431,815 | 3,431,815 | 是 | 是 | passed |
| C4 | P4U1 | 21,521,049 | 0.000005 | 3,431,815 | 3,431,815 | 是 | 是 | passed |
| C5 | P12U1 | 8,021,472 | 0.000012 | 3,431,815 | 3,431,815 | 是 | 是 | passed |
| C5 | P4U1 | 21,521,049 | 0.000005 | 3,431,815 | 3,431,815 | 是 | 是 | passed |
| C6 | P12U1 | 8,021,472 | 0.000012 | 3,431,815 | 3,431,815 | 是 | 是 | passed |
| C6 | P4U1 | 21,521,049 | 0.000005 | 3,431,815 | 3,431,815 | 是 | 是 | passed |
| C7 | P12U1 | 8,021,472 | 0.000012 | 3,431,815 | 3,431,815 | 是 | 是 | passed |
| C7 | P4U1 | 21,521,049 | 0.000005 | 3,431,815 | 3,431,815 | 是 | 是 | passed |

## lms_h10 完整 Sign

| 阶段 | 配置 | 周期 | 相对 B0 % | Hash | 置换 | 相同工作量 | 输出／缓存逐字节 | 状态 |
|---|---|---:|---:|---:|---:|---|---|---|
| B0 | P12U1 | 3,015,453 | 0.000000 | 1,101,392 | 1,116,752 | 是 | — | passed |
| B0 | P4U1 | 7,374,126 | 0.000000 | 1,101,392 | 1,116,752 | 是 | — | passed |
| B0r | P12U1 | 3,015,453 | 0.000000 | 1,101,392 | 1,116,752 | 是 | — | passed |
| B0r | P4U1 | 7,374,126 | 0.000000 | 1,101,392 | 1,116,752 | 是 | — | passed |
| C1 | P12U1 | 3,132,282 | 3.874343 | 1,101,392 | 1,116,752 | 是 | — | passed |
| C1 | P4U1 | 7,671,327 | 4.030322 | 1,101,392 | 1,116,752 | 是 | — | passed |
| C2 | P12U1 | 3,132,282 | 3.874343 | 1,101,392 | 1,116,752 | 是 | — | passed |
| C2 | P4U1 | 7,671,327 | 4.030322 | 1,101,392 | 1,116,752 | 是 | — | passed |
| C3 | P12U1 | 3,133,307 | 3.908335 | 1,101,392 | 1,116,752 | 是 | 是 | passed |
| C3 | P4U1 | 7,672,352 | 4.044222 | 1,101,392 | 1,116,752 | 是 | 是 | passed |
| C4 | P12U1 | 3,016,478 | 0.033992 | 1,101,392 | 1,116,752 | 是 | 是 | passed |
| C4 | P4U1 | 7,375,151 | 0.013900 | 1,101,392 | 1,116,752 | 是 | 是 | passed |
| C5 | P12U1 | 3,016,478 | 0.033992 | 1,101,392 | 1,116,752 | 是 | 是 | passed |
| C5 | P4U1 | 7,375,151 | 0.013900 | 1,101,392 | 1,116,752 | 是 | 是 | passed |
| C6 | P12U1 | 3,016,478 | 0.033992 | 1,101,392 | 1,116,752 | 是 | 是 | passed |
| C6 | P4U1 | 7,375,151 | 0.013900 | 1,101,392 | 1,116,752 | 是 | 是 | passed |
| C7 | P12U1 | 3,016,478 | 0.033992 | 1,101,392 | 1,116,752 | 是 | 是 | passed |
| C7 | P4U1 | 7,375,151 | 0.013900 | 1,101,392 | 1,116,752 | 是 | 是 | passed |

相同工作量逐项要求 Hash、置换及全部 Sign 向量文件 SHA 与 B0 一致。JSON 保留未舍入周期、面积、SHA、假定 100 MHz 的诊断时间／ATP；这些假定值不作为布线 ATP 验收。

## 150 MHz 布线

| 阶段 | 配置 | 目标 MHz | 布线 Slice | WNS ns | WHS ns | DRC 错误 | 完整布通 | 状态 |
|---|---|---:|---:|---:|---:|---:|---|---|
| B0 | P12U1 | — | — | — | — | — | — | not_requested |
| B0 | P4U1 | — | — | — | — | — | — | not_requested |
| B0r | P12U1 | — | — | — | — | — | — | not_requested |
| B0r | P4U1 | — | — | — | — | — | — | not_requested |
| C1 | P12U1 | — | — | — | — | — | — | not_requested |
| C1 | P4U1 | — | — | — | — | — | — | not_requested |
| C2 | P12U1 | 150.000 | 16,122.625 | -1.407 | 0.130 | 0 | 是 | target_not_met |
| C2 | P4U1 | 150.000 | 9,856.250 | -1.088 | 0.096 | 0 | 是 | target_not_met |
| C3 | P12U1 | 150.000 | 16,299.250 | -1.502 | 0.082 | 0 | 是 | target_not_met |
| C3 | P4U1 | 150.000 | 10,143.500 | -1.289 | 0.094 | 0 | 是 | target_not_met |
| C4 | P12U1 | 150.000 | 16,018.250 | -2.694 | 0.056 | 0 | 是 | target_not_met |
| C4 | P4U1 | 150.000 | 9,664.250 | -2.218 | 0.124 | 0 | 是 | target_not_met |
| C5 | P12U1 | 150.000 | 15,746.750 | -3.086 | 0.128 | 0 | 是 | target_not_met |
| C5 | P4U1 | 150.000 | 9,670.250 | -2.141 | 0.094 | 0 | 是 | target_not_met |
| C6 | P12U1 | 150.000 | 16,068.125 | -2.882 | 0.118 | 0 | 是 | target_not_met |
| C6 | P4U1 | 150.000 | 9,484.250 | -2.178 | 0.099 | 0 | 是 | target_not_met |
| C7 | P12U1 | — | — | — | — | — | — | not_requested |
| C7 | P4U1 | — | — | — | — | — | — | not_requested |

| 阶段 | 配置 | 算法 | 已闭合目标 MHz | Sign 时间 ms | 布线 ATP Slice·ms |
|---|---|---|---:|---:|---:|
| — | — | — | — | — | — |

尚无本轮通过的完整布线结果，实际频率与 ATP 收益待验证。

## C7 独立 150／130 MHz 四目标布线

此矩阵由显式请求的独立 timing_targets 运行器执行，各目标重新综合并布局布线。报告逐文件复核其 10 个 RTL 及 sources.txt 与 C7 相同，并核对验证来源和冻结源码。只有对应目标完整布线、DRC、setup／hold 全部通过，才计算该目标下的实际时间与 ATP。

| 阶段 | 目标 | 目标 MHz | 源码绑定 | 综合 Slice | 布线 Slice | WNS ns | WHS ns | DRC 错误 | 状态 |
|---|---|---:|---|---:|---:|---:|---:|---:|---|
| C7 | [独立矩阵报告](/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/docs/manifests/experiments/timing_targets_20261019_213925/reports/Timing_Targets_20261019_213925.md) | — | 匹配 | — | — | — | — | — | 已结束 |
| C7 | P12U1_150MHz | 150.000 | 匹配 | 15,682.500 | 15,844.750 | -2.633 | 0.119 | 0 | target_not_met |
| C7 | P4U1_150MHz | 150.000 | 匹配 | 9,575.500 | 9,783.000 | -1.512 | 0.094 | 0 | target_not_met |
| C7 | P12U1_130MHz | 130.000 | 匹配 | 15,632.000 | 15,731.000 | -0.774 | 0.102 | 0 | target_not_met |
| C7 | P4U1_130MHz | 130.000 | 匹配 | 9,362.000 | 9,507.750 | -0.686 | 0.096 | 0 | target_not_met |

| 阶段 | 目标 | 算法 | 已闭合目标 MHz | Sign 时间 ms | 布线 ATP Slice·ms |
|---|---|---|---:|---:|---:|
| — | — | — | — | — | — |

C7 尚无已通过的四目标布线结果；不填实际频率或 ATP。

## 验证与历史证据范围

- C3：额外验证 46/46，状态 `passed`；冻结源码绑定 匹配。P4U1/P12U1 three-profile Verify stall/reset/replay/truncation/tamper and scalar/batch/FSM faults; P4/P12 SYNTHESIS recipes; P2U12/P4U2 recipe smoke. Full Sign run independently by candidate runner; no h20 Keygen/Sign.
- C4：额外验证 15/15，状态 `passed`；冻结源码绑定 匹配。P2U12 SHAKE recipes plus P4U1/P12U1 three-profile Verify stall/reset/replay/truncation, chain-node tamper, and in-flight batch faults; no h20 Keygen/Sign.
- C4：额外验证 1/1，状态 `passed`；冻结源码绑定 匹配。P2U12 full XMSS h10 Verify with stalls, replay, in-flight reset and truncation recovery; checks two live contexts in the short physical pipeline.
- C5：额外验证 46/46，状态 `passed`；冻结源码绑定 匹配。P4U1/P12U1 three-profile Verify stall/reset/replay/truncation/tamper and scalar/batch/FSM faults; P4/P12 SYNTHESIS recipes; P2U12/P4U2 recipe smoke. Full Sign run independently by candidate runner; no h20 Keygen/Sign.
- C6：额外验证 46/46，状态 `passed`；冻结源码绑定 匹配。P4U1/P12U1 three-profile Verify stall/reset/replay/truncation/tamper and scalar/batch/FSM faults; P4/P12 SYNTHESIS recipes; P2U12/P4U2 recipe smoke. Full Sign run independently by candidate runner; no h20 Keygen/Sign.
- C6：额外验证 12/12，状态 `passed`；冻结源码绑定 匹配。
- C7：额外验证 46/46，状态 `passed`；冻结源码绑定 匹配。P4U1/P12U1 three-profile Verify stall/reset/replay/truncation/tamper and scalar/batch/FSM faults; P4/P12 SYNTHESIS recipes; P2U12/P4U2 recipe smoke. Full Sign run independently by candidate runner; no h20 Keygen/Sign.

原始 SLH 13 点报告明确写明“不布局布线”和“U1 假定 150 MHz，频率未经布线验证”，不能将其当作历史 150 MHz 布线通过证据。见 [原报告](/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/docs/manifests/experiments/single_lane_13_20261009_v4/reports/SLH_DSA_128f_sign_ATP_150_110.md:5)。
- 用户引用的历史报告 `docs/manifests/experiments/legacy_113648d7_pu_route_20261019_203925/reports/Legacy_PU_Route_20261019_203925.md`：当前 checkout 中报告文件缺失；目录存在也不能代替布线证据。
- 用户引用的历史报告 `docs/manifests/experiments/legacy_01486e3f_p12u1_route_20261019_200221/reports/Legacy_P12U1_Route_20261019_200221.md`：当前 checkout 中报告文件缺失；目录存在也不能代替布线证据。

本轮修改 SHAKE 执行路径及两后端共用的 FORS 控制；SHA2 配方保持原样，兼容性由对应冻结版本的新回归支持。各轮冻结 RTL、SOURCE.json、综合 hierarchical／timing／critical_paths 及布线日志留在各自实验目录。详细仿真日志保留 build，汇总归档不复制 sim／validation 日志。后台超过十分钟的综合只标记分析延后，报告程序不停止任何测量进程。
