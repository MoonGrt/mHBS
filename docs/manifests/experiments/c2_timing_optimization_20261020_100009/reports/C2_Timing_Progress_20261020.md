# C2 基础 SHAKE 时序优化进展

更新时间：2026-10-20T10:54:42+08:00；当前已发现测量全部结束。

唯一基线为 C2（211601）；旧 B0 不参与本轮比较。聚焦 P12U1／P4U1。100 MHz 综合仅用于面积、组合路径诊断，不转换为实际 Fmax。150／130 MHz 等显式目标只有完整布线、DRC、setup／hold 全通过才填写已闭合频率和 ATP；失败 WNS 不能推算成较低频率已通过。

口径：common OOC、xc7a200tffg1156-3、通用 Keccak、统计由 SYNTHESIS 裁剪、默认时序驱动。每个 Vivado 两线程、最多十二个；不新增时序例外、不搜索频率。综合超过十分钟只延后分析，后台继续；h20 完整 Keygen／Sign 保持停止。

当前工作区匹配冻结 RTL：R5。

当前开发候选按工作区源码 SHA 确认；最新冻结候选为 R5（published_owner_checksum）。报告所在归档固定，不随新候选迁移；最终保留选择另列。

| 阶段 | 候选 | Sign通过 | 额外验证 | 源码／基线绑定 | 状态 |
|---|---|---:|---|---|---|
| C2 | 原始 C2（211601） | 6/6 | — | 匹配 | 完成 |
| R1 | R1: registered context read ownership | 6/6 | 52/52（passed） | 匹配 | 完成 |
| R2 | published_response | 6/6 | 52/52（passed） | 匹配 | 完成 |
| R3 | published_registered_owner | 6/6 | 52/52（passed） | 匹配 | 完成 |
| C2-ref | C2_reference_130 | 6/6 | — | 匹配 | 完成 |
| R4 | published_response_stream_fors | 6/6 | 59/59（passed） | 匹配 | 完成 |
| R5 | published_owner_checksum | 6/6 | 71/71（passed） | 匹配 | 完成 |

尚无绑定冻结源码的最终候选选择记录。报告不自动替换 RTL。

## 100 MHz 面积与路径诊断

| 阶段 | 配置 | LUT | FF | BRAM36 | Slice | 相对C2面积 % | 路径 ns | 级数 | 耗时 s | 状态 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| C2 | P12U1 | 49,865 | 27,371 | 0.000 | 15,887.625 | 0.000 | 7.043 | 12 | 407.510 | passed |
| C2 | P4U1 | 31,756 | 13,825 | 0.000 | 9,667.125 | 0.000 | 6.804 | 12 | 260.375 | passed |
| R1 | P12U1 | 50,421 | 27,342 | 0.000 | 16,023.000 | 0.852 | 6.621 | 11 | 194.774 | passed |
| R1 | P4U1 | 31,632 | 13,844 | 0.000 | 9,638.500 | -0.296 | 6.799 | 11 | 195.823 | passed |
| R2 | P12U1 | 51,201 | 27,877 | 0.000 | 16,284.875 | 2.500 | 7.515 | 14 | 198.784 | passed |
| R2 | P4U1 | 33,056 | 14,350 | 0.000 | 10,057.750 | 4.041 | 6.926 | 12 | 194.874 | passed |
| R3 | P12U1 | 51,092 | 27,870 | 0.000 | 16,256.750 | 2.323 | 6.923 | 10 | 175.983 | passed |
| R3 | P4U1 | 32,149 | 14,361 | 0.000 | 9,832.375 | 1.709 | 7.015 | 12 | 141.134 | passed |
| C2-ref | P12U1 | 49,865 | 27,371 | 0.000 | 15,887.625 | 0.000 | 7.043 | 12 | 407.510 | passed |
| C2-ref | P4U1 | 31,756 | 13,825 | 0.000 | 9,667.125 | 0.000 | 6.804 | 12 | 260.375 | passed |
| R4 | P12U1 | 50,751 | 28,175 | 0.000 | 16,209.625 | 2.027 | 7.709 | 11 | 217.164 | passed |
| R4 | P4U1 | 32,467 | 14,657 | 0.000 | 9,948.875 | 2.915 | 6.743 | 14 | 198.018 | passed |
| R5 | P12U1 | 50,434 | 28,148 | 0.000 | 16,127.000 | 1.507 | 6.586 | 11 | 175.176 | passed |
| R5 | P4U1 | 33,336 | 14,629 | 0.000 | 10,162.625 | 5.126 | 6.496 | 12 | 154.770 | passed |

| 阶段 | 配置 | 综合路径起点 | 综合路径终点 |
|---|---|---|---|
| C2 | P12U1 | `core/task_recipe_reg[56]/C` | `core/batch_issue_phase_reg/CE` |
| C2 | P4U1 | `core/fors_base_reg[5]/C` | `core/continuation_reg[0]/CE` |
| R1 | P12U1 | `core/fors_base_reg[5]/C` | `core/continuation_reg[0]/CE` |
| R1 | P4U1 | `core/read_addresses.address_reg[6]/C` | `core/lane/scheduled_execution.staged_data_reg[33]/D` |
| R2 | P12U1 | `core/fors_base_reg[5]/C` | `core/state_reg[0]/D` |
| R2 | P4U1 | `core/fors_base_reg[5]/C` | `core/continuation_reg[0]/CE` |
| R3 | P12U1 | `core/task_recipe_reg[57]/C` | `core/batch_issue_phase_reg/CE` |
| R3 | P4U1 | `core/fors_base_reg[5]/C` | `core/continuation_reg[0]/CE` |
| C2-ref | P12U1 | `core/task_recipe_reg[56]/C` | `core/batch_issue_phase_reg/CE` |
| C2-ref | P4U1 | `core/fors_base_reg[5]/C` | `core/continuation_reg[0]/CE` |
| R4 | P12U1 | `core/lane/FSM_sequential_scheduled_execution.state_reg[1]/C` | `core/lane/scheduled_execution.fixed_context.ctx_request_start_reg[0]/R` |
| R4 | P4U1 | `core/state_reg[4]/C` | `core/checksum_reg[11]/D` |
| R5 | P12U1 | `core/lane/FSM_sequential_scheduled_execution.state_reg[2]/C` | `core/batch_issue_phase_reg/CE` |
| R5 | P4U1 | `core/node_level_reg[3]/C` | `core/node_level_reg[2]/R` |

## slh_128f 完整 Sign

| 阶段 | 配置 | 周期 | 相对C2 % | Hash | 置换 | 工作量相同 | 状态 |
|---|---|---:|---:|---:|---:|---|---|
| C2 | P12U1 | 299,833 | 0.000000 | 104,937 | 105,641 | 是 | passed |
| C2 | P4U1 | 762,329 | 0.000000 | 104,937 | 105,641 | 是 | passed |
| R1 | P12U1 | 299,833 | 0.000000 | 104,937 | 105,641 | 是 | passed |
| R1 | P4U1 | 762,329 | 0.000000 | 104,937 | 105,641 | 是 | passed |
| R2 | P12U1 | 299,833 | 0.000000 | 104,937 | 105,641 | 是 | passed |
| R2 | P4U1 | 762,329 | 0.000000 | 104,937 | 105,641 | 是 | passed |
| R3 | P12U1 | 299,833 | 0.000000 | 104,937 | 105,641 | 是 | passed |
| R3 | P4U1 | 762,329 | 0.000000 | 104,937 | 105,641 | 是 | passed |
| C2-ref | P12U1 | 299,833 | 0.000000 | 104,937 | 105,641 | 是 | passed |
| C2-ref | P4U1 | 762,329 | 0.000000 | 104,937 | 105,641 | 是 | passed |
| R4 | P12U1 | 300,011 | 0.059366 | 104,937 | 105,641 | 是 | passed |
| R4 | P4U1 | 762,507 | 0.023349 | 104,937 | 105,641 | 是 | passed |
| R5 | P12U1 | 300,011 | 0.059366 | 104,937 | 105,641 | 是 | passed |
| R5 | P4U1 | 762,507 | 0.023349 | 104,937 | 105,641 | 是 | passed |

## xmss_h10 完整 Sign

| 阶段 | 配置 | 周期 | 相对C2 % | Hash | 置换 | 工作量相同 | 状态 |
|---|---|---:|---:|---:|---:|---|---|
| C2 | P12U1 | 8,349,401 | 0.000000 | 3,431,815 | 3,431,815 | 是 | passed |
| C2 | P4U1 | 22,408,429 | 0.000000 | 3,431,815 | 3,431,815 | 是 | passed |
| R1 | P12U1 | 8,349,401 | 0.000000 | 3,431,815 | 3,431,815 | 是 | passed |
| R1 | P4U1 | 22,408,429 | 0.000000 | 3,431,815 | 3,431,815 | 是 | passed |
| R2 | P12U1 | 8,349,401 | 0.000000 | 3,431,815 | 3,431,815 | 是 | passed |
| R2 | P4U1 | 22,408,429 | 0.000000 | 3,431,815 | 3,431,815 | 是 | passed |
| R3 | P12U1 | 8,349,401 | 0.000000 | 3,431,815 | 3,431,815 | 是 | passed |
| R3 | P4U1 | 22,408,429 | 0.000000 | 3,431,815 | 3,431,815 | 是 | passed |
| C2-ref | P12U1 | 8,349,401 | 0.000000 | 3,431,815 | 3,431,815 | 是 | passed |
| C2-ref | P4U1 | 22,408,429 | 0.000000 | 3,431,815 | 3,431,815 | 是 | passed |
| R4 | P12U1 | 8,349,402 | 0.000012 | 3,431,815 | 3,431,815 | 是 | passed |
| R4 | P4U1 | 22,408,430 | 0.000004 | 3,431,815 | 3,431,815 | 是 | passed |
| R5 | P12U1 | 8,349,402 | 0.000012 | 3,431,815 | 3,431,815 | 是 | passed |
| R5 | P4U1 | 22,408,430 | 0.000004 | 3,431,815 | 3,431,815 | 是 | passed |

## lms_h10 完整 Sign

| 阶段 | 配置 | 周期 | 相对C2 % | Hash | 置换 | 工作量相同 | 状态 |
|---|---|---:|---:|---:|---:|---|---|
| C2 | P12U1 | 3,132,282 | 0.000000 | 1,101,392 | 1,116,752 | 是 | passed |
| C2 | P4U1 | 7,671,327 | 0.000000 | 1,101,392 | 1,116,752 | 是 | passed |
| R1 | P12U1 | 3,132,282 | 0.000000 | 1,101,392 | 1,116,752 | 是 | passed |
| R1 | P4U1 | 7,671,327 | 0.000000 | 1,101,392 | 1,116,752 | 是 | passed |
| R2 | P12U1 | 3,132,282 | 0.000000 | 1,101,392 | 1,116,752 | 是 | passed |
| R2 | P4U1 | 7,671,327 | 0.000000 | 1,101,392 | 1,116,752 | 是 | passed |
| R3 | P12U1 | 3,132,282 | 0.000000 | 1,101,392 | 1,116,752 | 是 | passed |
| R3 | P4U1 | 7,671,327 | 0.000000 | 1,101,392 | 1,116,752 | 是 | passed |
| C2-ref | P12U1 | 3,132,282 | 0.000000 | 1,101,392 | 1,116,752 | 是 | passed |
| C2-ref | P4U1 | 7,671,327 | 0.000000 | 1,101,392 | 1,116,752 | 是 | passed |
| R4 | P12U1 | 3,133,307 | 0.032724 | 1,101,392 | 1,116,752 | 是 | passed |
| R4 | P4U1 | 7,672,352 | 0.013361 | 1,101,392 | 1,116,752 | 是 | passed |
| R5 | P12U1 | 3,133,307 | 0.032724 | 1,101,392 | 1,116,752 | 是 | passed |
| R5 | P4U1 | 7,672,352 | 0.013361 | 1,101,392 | 1,116,752 | 是 | passed |

逐字节输出与签名缓存由冻结测试台检查，Hash／置换次数及向量 SHA 另与 C2 比较。JSON 保留未舍入结果及假定 100 MHz 的诊断 ATP；其不作为频率或 ATP 验收证据。

## 显式目标布线

150 MHz 是名义请求值；Vivado 若将实际约束记录为 6.667 ns，STA 闭合后对应的实际频率为 149.9925 MHz，应按该实际值报告。严格 150 MHz 目标判定保持不变；尚未完成或未通过 STA 时，已闭合频率与 ATP 继续留空。

| 阶段 | 配置 | 目标 MHz | 目标周期 ns | 实际约束 ns | 布线 Slice | WNS ns | WHS ns | 布通 | DRC错误 | 达到目标 | 状态 |
|---|---|---:|---:|---:|---:|---:|---:|---|---:|---|---|
| C2 | P12U1 | 150.000 | 6.667 | 6.667 | 16,122.625 | -1.407 | 0.130 | 是 | 0 | 否 | target_not_met |
| C2 | P4U1 | 150.000 | 6.667 | 6.667 | 9,856.250 | -1.088 | 0.096 | 是 | 0 | 否 | target_not_met |
| R1 | P12U1 | 150.000 | 6.667 | 6.667 | 16,189.500 | -1.074 | 0.080 | 是 | 0 | 否 | target_not_met |
| R1 | P12U1 | 130.000 | 7.692 | 7.692 | 16,086.000 | -0.281 | 0.080 | 是 | 0 | 否 | target_not_met |
| R1 | P4U1 | 150.000 | 6.667 | 6.667 | 9,839.875 | -0.889 | 0.096 | 是 | 0 | 否 | target_not_met |
| R1 | P4U1 | 130.000 | 7.692 | 7.692 | 9,627.250 | 0.095 | 0.096 | 是 | 0 | 是 | passed |
| C2-ref | P12U1 | 130.000 | 7.692 | 7.692 | 15,966.250 | -0.558 | 0.130 | 是 | 0 | 否 | target_not_met |
| C2-ref | P4U1 | 130.000 | 7.692 | 7.692 | 9,726.500 | 0.045 | 0.099 | 是 | 0 | 是 | passed |
| R5 | P12U1 | 150.000 | 6.667 | 6.667 | 16,276.625 | -1.140 | 0.099 | 是 | 0 | 否 | target_not_met |
| R5 | P12U1 | 130.000 | 7.692 | 7.692 | 16,104.125 | 0.016 | 0.132 | 是 | 0 | 是 | passed |
| R5 | P4U1 | 150.000 | 6.667 | 6.667 | 10,222.125 | -0.658 | 0.075 | 是 | 0 | 否 | target_not_met |
| R5 | P4U1 | 130.000 | 7.692 | 7.692 | 10,130.125 | 0.065 | 0.099 | 是 | 0 | 是 | passed |

| 阶段 | 配置 | 算法 | 已闭合频率 MHz | Sign时间 ms | 布线ATP Slice·ms | 同目标C2 ATP变化 % |
|---|---|---|---:|---:|---:|---:|
| R1 | P4U1 | slh_128f | 130.005 | 5.863835 | 56,452.602308 | -1.020 |
| R1 | P4U1 | xmss_h10 | 130.005 | 172.365636 | 1,659,407.067910 | -1.020 |
| R1 | P4U1 | lms_h10 | 130.005 | 59.007847 | 568,083.297765 | -1.020 |
| C2-ref | P4U1 | slh_128f | 130.005 | 5.863835 | 57,034.587898 | 0.000 |
| C2-ref | P4U1 | xmss_h10 | 130.005 | 172.365636 | 1,676,514.357270 | 0.000 |
| C2-ref | P4U1 | lms_h10 | 130.005 | 59.007847 | 573,939.826608 | 0.000 |
| R5 | P12U1 | slh_128f | 130.005 | 2.307685 | 37,163.241452 | — |
| R5 | P12U1 | xmss_h10 | 130.005 | 64.223600 | 1,034,264.885313 | — |
| R5 | P12U1 | lms_h10 | 130.005 | 24.101397 | 388,131.917113 | — |
| R5 | P4U1 | slh_128f | 130.005 | 5.865204 | 59,415.248090 | 4.174 |
| R5 | P4U1 | xmss_h10 | 130.005 | 172.365644 | 1,746,085.514968 | 4.150 |
| R5 | P4U1 | lms_h10 | 130.005 | 59.015732 | 597,836.737912 | 4.164 |

## 按实际约束闭合的 STA 结果

下表单独接受完整布通、DRC=0、setup／hold 全通过及源码／工作量绑定的实测。即使实际 6.667 ns 对应约 149.9925 MHz、未达到严格 150 MHz，也保留其实际频率和 ATP；严格目标达到列保持“否”。负 WNS、负 hold 或尚未完成的项目不进入此表。

| 阶段 | 配置 | 算法 | 名义目标 MHz | 实际周期 ns | STA闭合频率 MHz | 严格目标达到 | 时间 ms | ATP Slice·ms |
|---|---|---|---:|---:|---:|---|---:|---:|
| R1 | P4U1 | slh_128f | 130.000 | 7.692 | 130.0052 | 是 | 5.863835 | 56,452.602308 |
| R1 | P4U1 | xmss_h10 | 130.000 | 7.692 | 130.0052 | 是 | 172.365636 | 1,659,407.067910 |
| R1 | P4U1 | lms_h10 | 130.000 | 7.692 | 130.0052 | 是 | 59.007847 | 568,083.297765 |
| C2-ref | P4U1 | slh_128f | 130.000 | 7.692 | 130.0052 | 是 | 5.863835 | 57,034.587898 |
| C2-ref | P4U1 | xmss_h10 | 130.000 | 7.692 | 130.0052 | 是 | 172.365636 | 1,676,514.357270 |
| C2-ref | P4U1 | lms_h10 | 130.000 | 7.692 | 130.0052 | 是 | 59.007847 | 573,939.826608 |
| R5 | P12U1 | slh_128f | 130.000 | 7.692 | 130.0052 | 是 | 2.307685 | 37,163.241452 |
| R5 | P12U1 | xmss_h10 | 130.000 | 7.692 | 130.0052 | 是 | 64.223600 | 1,034,264.885313 |
| R5 | P12U1 | lms_h10 | 130.000 | 7.692 | 130.0052 | 是 | 24.101397 | 388,131.917113 |
| R5 | P4U1 | slh_128f | 130.000 | 7.692 | 130.0052 | 是 | 5.865204 | 59,415.248090 |
| R5 | P4U1 | xmss_h10 | 130.000 | 7.692 | 130.0052 | 是 | 172.365644 | 1,746,085.514968 |
| R5 | P4U1 | lms_h10 | 130.000 | 7.692 | 130.0052 | 是 | 59.015732 | 597,836.737912 |

## 额外验证与证据

- R1：52/52，passed；冻结源码绑定 匹配。R1 frozen source: P4/P12 deferred-only pipeline KAT in normal and SYNTHESIS views; P4/P12 three-profile Verify stall/replay/reset/cut/tamper/fault; P4/P12 SYNTHESIS recipes and P2U12 normal/SYNTHESIS recipes, P2U12 full XMSS Verify; SHA2 P4 SLH Sign executor compatibility. Root executes six SHAKE Sign independently. No h20 Keygen/Sign.
- R2：52/52，passed；冻结源码绑定 匹配。R2 frozen source: P4/P12 published+deferred pipeline KAT in normal and SYNTHESIS views; P4/P12 three-profile Verify stall/replay/reset/cut/tamper/fault; P4/P12 SYNTHESIS recipes and P2U12 normal/SYNTHESIS recipes, P2U12 full XMSS Verify; SHA2 P4 SLH Sign executor compatibility. Root executes six SHAKE Sign independently. No h20 Keygen/Sign.
- R3：52/52，passed；冻结源码绑定 匹配。R3 frozen source: P4/P12 published+deferred pipeline KAT in normal and SYNTHESIS views; P4/P12 three-profile Verify stall/replay/reset/cut/tamper/fault; P4/P12 SYNTHESIS recipes and P2U12 normal/SYNTHESIS recipes, P2U12 full XMSS Verify; SHA2 P4 SLH Sign executor compatibility. Root executes six SHAKE Sign independently. No h20 Keygen/Sign.
- R4：59/59，passed；冻结源码绑定 匹配。R4 frozen source: P4/P12 published+deferred pipeline KAT in normal and SYNTHESIS views; P4/P12 three-profile Verify stall/replay/reset/cut/tamper/fault; P4/P12 SYNTHESIS recipes and P2U12 normal/SYNTHESIS recipes, P2U12 full XMSS Verify; SHA2 P4 SLH Sign executor compatibility. P1U1 all scalar recipes and three-profile Verify smoke; P6U1 three-target full Sign exercises 8-leaf FORS microgroups in 6+2 waves and odd L-tree. Root executes P4/P12 six SHAKE Sign independently. No h20 Keygen/Sign.
- R5：71/71，passed；冻结源码绑定 匹配。R5 frozen source: P4/P12 published+deferred pipeline KAT in normal and SYNTHESIS views; P4/P12 three-profile Verify stall/replay/reset/cut/tamper/fault; P4/P12 SYNTHESIS recipes and P2U12 normal/SYNTHESIS recipes, P2U12 full XMSS Verify; SHA2 P4 SLH Sign executor compatibility. P1U1 all scalar recipes and three-profile Verify smoke; P6U1 three-target full Sign exercises 8-leaf FORS microgroups in 6+2 waves and odd L-tree. Root executes P4/P12 six SHAKE Sign independently. Both normal and SYNTHESIS P4/P12 complete recipe KAT plus all six SLH parameter Verify. No h20 Keygen/Sign.
- C2：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/shake_timing_optimization/candidate_20261019_211601`；归档 `/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/docs/manifests/experiments/shake_timing_optimization_candidate_20261019_211601`。
- R1：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/c2_timing_optimization/candidate_20261020_095359`；归档 `/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/docs/manifests/experiments/c2_timing_optimization_20261020_095359`。
- R2：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/c2_timing_optimization/candidate_20261020_095421`；归档 `/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/docs/manifests/experiments/c2_timing_optimization_20261020_095421`。
- R3：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/c2_timing_optimization/candidate_20261020_095545`；归档 `/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/docs/manifests/experiments/c2_timing_optimization_20261020_095545`。
- C2-ref：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/c2_timing_optimization/candidate_20261020_095821`；归档 `/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/docs/manifests/experiments/c2_timing_optimization_20261020_095821`。
- R4：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/c2_timing_optimization/candidate_20261020_100009`；归档 `/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/docs/manifests/experiments/c2_timing_optimization_20261020_100009`。
- R5：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/c2_timing_optimization/candidate_20261020_100441`；归档 `/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/docs/manifests/experiments/c2_timing_optimization_20261020_100441`。

归档保留冻结 RTL、源码校验、综合和布线报告／日志、验证摘要；仿真明细保留 build。动态进展报告在全部后台测量结束前列为 volatile，不修改原始测量证据。
