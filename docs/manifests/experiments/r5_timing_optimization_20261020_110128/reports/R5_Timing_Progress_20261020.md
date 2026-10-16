# R5 基础 SHAKE 时序优化进展

更新时间：2026-10-20T11:52:46+08:00；已发现测量全部结束。

本轮唯一比较基线为冻结 R5（20261020_100441），聚焦 P12U1／P4U1。R5 在两配置均通过 130 MHz 布线，因此选为共同优化起点；旧 R1 的 P4U1@130MHz 面积和 ATP 更低，但其 P12U1@130MHz 未闭合。选定 R5 不代表每个配置的 ATP 都优于 R1。

common OOC、xc7a200tffg1156-3、通用 Keccak、SYNTHESIS 统计裁剪、默认时序驱动；100 MHz 综合仅诊断面积和关键路径。每个 Vivado 两线程，全机最多十二个；异常综合只延后分析，后台继续，不新增时序例外。h20 完整 Keygen／Sign 保持停止。

工作区当前匹配冻结 RTL：S4。报告归档固定在 S1，不因后续候选迁移。

| 阶段 | 候选 | Sign通过 | 额外验证 | 源码绑定 | 状态 |
|---|---|---:|---|---|---|
| R5 | R5：两配置 130MHz 布线通过的选定起点 | 6/6 | — | 匹配 | 完成 |
| S1 | S1_live_windows_response_queue_target_path | 6/6 | 71/71（passed） | 匹配 | 完成 |
| S2 | S2_registered_adjacent_auth_controls | 6/6 | 75/75（passed） | 匹配 | 完成 |
| S3 | S3_registered_recipe_phase_encoding | 6/6 | 75/75（passed） | 匹配 | 完成 |
| S4 | S4_parallel_address_pair_selection | 6/6 | 75/75（passed） | 匹配 | 完成 |

## 100 MHz 综合面积及路径诊断

| 阶段 | 配置 | LUT | FF | BRAM36 | Slice | 相对R5面积 % | 路径 ns | 级数 | 耗时 s | 状态 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| R5 | P12U1 | 50,434 | 28,148 | 0.000 | 16,127.000 | 0.000 | 6.586 | 11 | 175.176 | passed |
| R5 | P4U1 | 33,336 | 14,629 | 0.000 | 10,162.625 | 0.000 | 6.496 | 12 | 154.770 | passed |
| S1 | P12U1 | 50,548 | 28,171 | 0.000 | 16,158.375 | 0.195 | 6.357 | 11 | 255.394 | passed |
| S1 | P4U1 | 31,850 | 14,666 | 0.000 | 9,795.750 | -3.610 | 5.818 | 8 | 193.248 | passed |
| S2 | P12U1 | 50,846 | 28,181 | 0.000 | 16,234.125 | 0.664 | 7.140 | 11 | 186.837 | passed |
| S2 | P4U1 | 31,905 | 14,658 | 0.000 | 9,808.500 | -3.485 | 5.858 | 10 | 157.365 | passed |
| S3 | P12U1 | 50,385 | 28,192 | 0.000 | 16,120.250 | -0.042 | 7.018 | 12 | 227.819 | passed |
| S3 | P4U1 | 33,139 | 14,679 | 0.000 | 10,119.625 | -0.423 | 6.000 | 8 | 194.947 | passed |
| S4 | P12U1 | 51,057 | 28,221 | 0.000 | 16,291.875 | 1.022 | 5.729 | 8 | 317.263 | passed |
| S4 | P4U1 | 32,746 | 14,666 | 0.000 | 10,019.750 | -1.406 | 4.976 | 6 | 144.397 | passed |

## slh_128f 完整 Sign

| 阶段 | 配置 | 周期 | 相对R5周期 % | 假设100MHz时间 ms | 假设ATP Slice·ms | 相对R5假设ATP % | Hash／置换 | 工作量相同 | 状态 |
|---|---|---:|---:|---:|---:|---:|---|---|---|
| R5 | P12U1 | 300,011 | 0.000000 | 3.000110 | 48,382.773970 | 0.000000 | 104,937／105,641 | 是 | passed |
| R5 | P4U1 | 762,507 | 0.000000 | 7.625070 | 77,490.727009 | 0.000000 | 104,937／105,641 | 是 | passed |
| S1 | P12U1 | 300,011 | 0.000000 | 3.000110 | 48,476.902421 | 0.194550 | 104,937／105,641 | 是 | passed |
| S1 | P4U1 | 762,507 | 0.000000 | 7.625070 | 74,693.279453 | -3.610042 | 104,937／105,641 | 是 | passed |
| S2 | P12U1 | 300,011 | 0.000000 | 3.000110 | 48,704.160754 | 0.664259 | 104,937／105,641 | 是 | passed |
| S2 | P4U1 | 762,507 | 0.000000 | 7.625070 | 74,790.499095 | -3.484582 | 104,937／105,641 | 是 | passed |
| S3 | P12U1 | 300,011 | 0.000000 | 3.000110 | 48,362.523228 | -0.041855 | 104,937／105,641 | 是 | passed |
| S3 | P4U1 | 762,507 | 0.000000 | 7.625070 | 77,162.848999 | -0.423119 | 104,937／105,641 | 是 | passed |
| S4 | P12U1 | 300,011 | 0.000000 | 3.000110 | 48,877.417106 | 1.022354 | 104,937／105,641 | 是 | passed |
| S4 | P4U1 | 762,507 | 0.000000 | 7.625070 | 76,401.295133 | -1.405887 | 104,937／105,641 | 是 | passed |

## xmss_h10 完整 Sign

| 阶段 | 配置 | 周期 | 相对R5周期 % | 假设100MHz时间 ms | 假设ATP Slice·ms | 相对R5假设ATP % | Hash／置换 | 工作量相同 | 状态 |
|---|---|---:|---:|---:|---:|---:|---|---|---|
| R5 | P12U1 | 8,349,402 | 0.000000 | 83.494020 | 1,346,508.060540 | 0.000000 | 3,431,815／3,431,815 | 是 | passed |
| R5 | P4U1 | 22,408,430 | 0.000000 | 224.084300 | 2,277,284.709288 | 0.000000 | 3,431,815／3,431,815 | 是 | passed |
| S1 | P12U1 | 8,349,402 | 0.000000 | 83.494020 | 1,349,127.685418 | 0.194550 | 3,431,815／3,431,815 | 是 | passed |
| S1 | P4U1 | 22,408,430 | 0.000000 | 224.084300 | 2,195,073.781725 | -3.610042 | 3,431,815／3,431,815 | 是 | passed |
| S2 | P12U1 | 8,349,402 | 0.000000 | 83.494020 | 1,355,452.357432 | 0.664259 | 3,431,815／3,431,815 | 是 | passed |
| S2 | P4U1 | 22,408,430 | 0.000000 | 224.084300 | 2,197,930.856550 | -3.484582 | 3,431,815／3,431,815 | 是 | passed |
| S3 | P12U1 | 8,349,402 | 0.000000 | 83.494020 | 1,345,944.475905 | -0.041855 | 3,431,815／3,431,815 | 是 | passed |
| S3 | P4U1 | 22,408,430 | 0.000000 | 224.084300 | 2,267,649.084387 | -0.423119 | 3,431,815／3,431,815 | 是 | passed |
| S4 | P12U1 | 8,349,402 | 0.000000 | 83.494020 | 1,360,274.137087 | 1.022354 | 3,431,815／3,431,815 | 是 | passed |
| S4 | P4U1 | 22,408,430 | 0.000000 | 224.084300 | 2,245,268.664925 | -1.405887 | 3,431,815／3,431,815 | 是 | passed |

## lms_h10 完整 Sign

| 阶段 | 配置 | 周期 | 相对R5周期 % | 假设100MHz时间 ms | 假设ATP Slice·ms | 相对R5假设ATP % | Hash／置换 | 工作量相同 | 状态 |
|---|---|---:|---:|---:|---:|---:|---|---|---|
| R5 | P12U1 | 3,133,307 | 0.000000 | 31.333070 | 505,308.419890 | 0.000000 | 1,101,392／1,116,752 | 是 | passed |
| R5 | P4U1 | 7,672,352 | 0.000000 | 76.723520 | 779,712.362440 | 0.000000 | 1,101,392／1,116,752 | 是 | passed |
| S1 | P12U1 | 3,133,307 | 0.000000 | 31.333070 | 506,291.494961 | 0.194550 | 1,101,392／1,116,752 | 是 | passed |
| S1 | P4U1 | 7,672,352 | 0.000000 | 76.723520 | 751,564.421040 | -3.610042 | 1,101,392／1,116,752 | 是 | passed |
| S2 | P12U1 | 3,133,307 | 0.000000 | 31.333070 | 508,664.975014 | 0.664259 | 1,101,392／1,116,752 | 是 | passed |
| S2 | P4U1 | 7,672,352 | 0.000000 | 76.723520 | 752,542.645920 | -3.484582 | 1,101,392／1,116,752 | 是 | passed |
| S3 | P12U1 | 3,133,307 | 0.000000 | 31.333070 | 505,096.921667 | -0.041855 | 1,101,392／1,116,752 | 是 | passed |
| S3 | P4U1 | 7,672,352 | 0.000000 | 76.723520 | 776,413.251080 | -0.423119 | 1,101,392／1,116,752 | 是 | passed |
| S4 | P12U1 | 3,133,307 | 0.000000 | 31.333070 | 510,474.459806 | 1.022354 | 1,101,392／1,116,752 | 是 | passed |
| S4 | P4U1 | 7,672,352 | 0.000000 | 76.723520 | 768,750.489520 | -1.405887 | 1,101,392／1,116,752 | 是 | passed |

输出和签名缓存逐字节核对，Hash／置换次数及向量 SHA 与 R5 比较。以上 100 MHz ATP 是固定假设频率的诊断值，不代表布线收益。

## 布线 STA

| 阶段 | 配置 | 名义目标 MHz | 实际周期 ns | WNS ns | WHS ns | 布通 | DRC错误 | 严格目标达到 | 状态 |
|---|---|---:|---:|---:|---:|---|---:|---|---|
| R5 | P12U1 | 150.000 | 6.667 | -1.140 | 0.099 | 是 | 0 | 否 | target_not_met |
| R5 | P12U1 | 130.000 | 7.692 | 0.016 | 0.132 | 是 | 0 | 是 | passed |
| R5 | P4U1 | 150.000 | 6.667 | -0.658 | 0.075 | 是 | 0 | 否 | target_not_met |
| R5 | P4U1 | 130.000 | 7.692 | 0.065 | 0.099 | 是 | 0 | 是 | passed |
| S1 | P12U1 | 150.000 | 6.667 | -0.425 | 0.126 | 是 | 0 | 否 | target_not_met |
| S1 | P12U1 | 140.000 | 7.143 | -0.300 | 0.095 | 是 | 0 | 否 | target_not_met |
| S1 | P4U1 | 150.000 | 6.667 | -0.347 | 0.096 | 是 | 0 | 否 | target_not_met |
| S1 | P4U1 | 140.000 | 7.143 | 0.068 | 0.094 | 是 | 0 | 否 | target_not_met |
| S4 | P12U1 | 150.000 | 6.667 | -0.063 | 0.119 | 是 | 0 | 否 | target_not_met |
| S4 | P12U1 | 140.000 | 7.143 | 0.078 | 0.130 | 是 | 0 | 否 | target_not_met |
| S4 | P12U1 | 135.000 | 7.407 | 0.123 | 0.094 | 是 | 0 | 是 | passed |
| S4 | P4U1 | 150.000 | 6.667 | 0.014 | 0.096 | 是 | 0 | 否 | target_not_met |
| S4 | P4U1 | 140.000 | 7.143 | 0.134 | 0.094 | 是 | 0 | 否 | target_not_met |
| S4 | P4U1 | 135.000 | 7.407 | 0.180 | 0.068 | 是 | 0 | 是 | passed |
| R1历史 | P12U1 | 150.000 | 6.667 | -1.074 | 0.080 | 是 | 0 | 否 | target_not_met |
| R1历史 | P12U1 | 130.000 | 7.692 | -0.281 | 0.080 | 是 | 0 | 否 | target_not_met |
| R1历史 | P4U1 | 150.000 | 6.667 | -0.889 | 0.096 | 是 | 0 | 否 | target_not_met |
| R1历史 | P4U1 | 130.000 | 7.692 | 0.095 | 0.096 | 是 | 0 | 是 | passed |

## 按实际约束闭合的频率及 ATP

只有源码／工作量绑定、完整布通、DRC=0、setup／hold 全通过才填写本表。名义 150 MHz 若被 Vivado 量化为 6.667 ns，实际闭合频率为约 149.9925 MHz，保留该实测值且严格目标列保持“否”。负 WNS 不外推较低频率。

| 阶段 | 配置 | 算法 | 名义目标 MHz | 实际STA频率 MHz | 严格目标达到 | 布线 Slice | 时间 ms | ATP Slice·ms | 相对R5@130MHz % |
|---|---|---|---:|---:|---|---:|---:|---:|---:|
| R5 | P12U1 | slh_128f | 130.000 | 130.0052 | 是 | 16,104.125 | 2.307685 | 37,163.241452 | 0.000000 |
| R5 | P12U1 | xmss_h10 | 130.000 | 130.0052 | 是 | 16,104.125 | 64.223600 | 1,034,264.885313 | 0.000000 |
| R5 | P12U1 | lms_h10 | 130.000 | 130.0052 | 是 | 16,104.125 | 24.101397 | 388,131.917113 | 0.000000 |
| R5 | P4U1 | slh_128f | 130.000 | 130.0052 | 是 | 10,130.125 | 5.865204 | 59,415.248090 | 0.000000 |
| R5 | P4U1 | xmss_h10 | 130.000 | 130.0052 | 是 | 10,130.125 | 172.365644 | 1,746,085.514968 | 0.000000 |
| R5 | P4U1 | lms_h10 | 130.000 | 130.0052 | 是 | 10,130.125 | 59.015732 | 597,836.737912 | 0.000000 |
| S1 | P4U1 | slh_128f | 140.000 | 139.9972 | 否 | 9,745.625 | 5.446588 | 53,080.399314 | -10.661992 |
| S1 | P4U1 | xmss_h10 | 140.000 | 139.9972 | 否 | 9,745.625 | 160.063415 | 1,559,918.023585 | -10.661992 |
| S1 | P4U1 | lms_h10 | 140.000 | 139.9972 | 否 | 9,745.625 | 54.803610 | 534,095.434981 | -10.661992 |
| S4 | P12U1 | slh_128f | 140.000 | 139.9972 | 否 | 16,051.250 | 2.142979 | 34,397.484820 | -7.442184 |
| S4 | P12U1 | xmss_h10 | 140.000 | 139.9972 | 否 | 16,051.250 | 59.639778 | 957,292.994423 | -7.442184 |
| S4 | P12U1 | lms_h10 | 140.000 | 139.9972 | 否 | 16,051.250 | 22.381212 | 359,246.427526 | -7.442184 |
| S4 | P12U1 | slh_128f | 135.000 | 135.0074 | 是 | 16,052.000 | 2.222181 | 35,670.457069 | -4.016830 |
| S4 | P12U1 | xmss_h10 | 135.000 | 135.0074 | 是 | 16,052.000 | 61.844021 | 992,720.218896 | -4.016830 |
| S4 | P12U1 | lms_h10 | 135.000 | 135.0074 | 是 | 16,052.000 | 23.208405 | 372,541.316241 | -4.016830 |
| S4 | P4U1 | slh_128f | 150.000 | 149.9925 | 否 | 9,989.750 | 5.083634 | 50,784.234440 | -14.526597 |
| S4 | P4U1 | xmss_h10 | 150.000 | 149.9925 | 否 | 9,989.750 | 149.397003 | 1,492,438.708821 | -14.526597 |
| S4 | P4U1 | lms_h10 | 150.000 | 149.9925 | 否 | 9,989.750 | 51.151571 | 510,991.404239 | -14.526597 |
| S4 | P4U1 | slh_128f | 140.000 | 139.9972 | 否 | 9,967.750 | 5.446588 | 54,290.222563 | -8.625775 |
| S4 | P4U1 | xmss_h10 | 140.000 | 139.9972 | 否 | 9,967.750 | 160.063415 | 1,595,472.109750 | -8.625775 |
| S4 | P4U1 | lms_h10 | 140.000 | 139.9972 | 否 | 9,967.750 | 54.803610 | 546,268.686927 | -8.625775 |
| S4 | P4U1 | slh_128f | 135.000 | 135.0074 | 是 | 9,964.625 | 5.647889 | 56,279.099404 | -5.278357 |
| S4 | P4U1 | xmss_h10 | 135.000 | 135.0074 | 是 | 9,964.625 | 165.979241 | 1,653,920.894449 | -5.278357 |
| S4 | P4U1 | lms_h10 | 135.000 | 135.0074 | 是 | 9,964.625 | 56.829111 | 566,280.782829 | -5.278357 |
| R1历史 | P4U1 | slh_128f | 130.000 | 130.0052 | 是 | 9,627.250 | 5.863835 | 56,452.602308 | -4.986339 |
| R1历史 | P4U1 | xmss_h10 | 130.000 | 130.0052 | 是 | 9,627.250 | 172.365636 | 1,659,407.067910 | -4.964158 |
| R1历史 | P4U1 | lms_h10 | 130.000 | 130.0052 | 是 | 9,627.250 | 59.007847 | 568,083.297765 | -4.976850 |

## 验证与源码证据

- S1：71/71（passed）；冻结源码绑定：匹配。S1 frozen source with narrowed scheduled list-word source, registered response queue ownership, and target-at-level shadow index: P4/P12 published+deferred pipeline KAT in normal and SYNTHESIS views; P4/P12 three-profile Verify stall/replay/reset/cut/tamper/fault; P4/P12 SYNTHESIS recipes and P2U12 normal/SYNTHESIS recipes, P2U12 full XMSS Verify; SHA2 P4 SLH Sign executor compatibility. P1U1 all scalar recipes and three-profile Verify smoke; P6U1 three-target full Sign exercises 8-leaf FORS microgroups in 6+2 waves and odd L-tree. Root executes P4/P12 six SHAKE Sign independently. Both normal and SYNTHESIS P4/P12 complete recipe KAT plus all six SLH parameter Verify. No h20 Keygen/Sign.
- S2：75/75（passed）；冻结源码绑定：匹配。S2 frozen source with narrowed scheduled list-word source, registered response queue ownership, and target-at-level shadow index: P4/P12 published+deferred pipeline KAT in normal and SYNTHESIS views; P4/P12 three-profile Verify stall/replay/reset/cut/tamper/fault; P4/P12 SYNTHESIS recipes and P2U12 normal/SYNTHESIS recipes, P2U12 full XMSS Verify; SHA2 P4 SLH Sign executor compatibility. P1U1 all scalar recipes and three-profile Verify smoke; P6U1 three-target full Sign exercises 8-leaf FORS microgroups in 6+2 waves and odd L-tree. Root executes P4/P12 six SHAKE Sign independently. Both normal and SYNTHESIS P4/P12 complete recipe KAT plus all six SLH parameter Verify. No h20 Keygen/Sign.
- S3：75/75（passed）；冻结源码绑定：匹配。S3 frozen source (scheduled recipe FSM one-hot implementation attribute) with narrowed scheduled list-word source, registered response queue ownership, and target-at-level shadow index: P4/P12 published+deferred pipeline KAT in normal and SYNTHESIS views; P4/P12 three-profile Verify stall/replay/reset/cut/tamper/fault; P4/P12 SYNTHESIS recipes and P2U12 normal/SYNTHESIS recipes, P2U12 full XMSS Verify; SHA2 P4 SLH Sign executor compatibility. P1U1 all scalar recipes and three-profile Verify smoke; P6U1 three-target full Sign exercises 8-leaf FORS microgroups in 6+2 waves and odd L-tree. Root executes P4/P12 six SHAKE Sign independently. Both normal and SYNTHESIS P4/P12 complete recipe KAT plus all six SLH parameter Verify. No h20 Keygen/Sign.
- S4：75/75（passed）；冻结源码绑定：匹配。S4 frozen source with parallel workspace address-pair selection (scheduled recipe FSM one-hot implementation attribute) with narrowed scheduled list-word source, registered response queue ownership, and target-at-level shadow index: P4/P12 published+deferred pipeline KAT in normal and SYNTHESIS views; P4/P12 three-profile Verify stall/replay/reset/cut/tamper/fault; P4/P12 SYNTHESIS recipes and P2U12 normal/SYNTHESIS recipes, P2U12 full XMSS Verify; SHA2 P4 SLH Sign executor compatibility. P1U1 all scalar recipes and three-profile Verify smoke; P6U1 three-target full Sign exercises 8-leaf FORS microgroups in 6+2 waves and odd L-tree. Root executes P4/P12 six SHAKE Sign independently. Both normal and SYNTHESIS P4/P12 complete recipe KAT plus all six SLH parameter Verify. No h20 Keygen/Sign.
- R5：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/c2_timing_optimization/candidate_20261020_100441`；SOURCE SHA `fdc3f8f41e11b400e26e869741a79fb7974b4a6087f9d9bf529f9911b0fe5b4e`。
- S1：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/r5_timing_optimization/candidate_20261020_110128`；SOURCE SHA `596281e9ba99566cfa33b1be544938b0ba432a8e037fecf03b906547d692f23e`。
- S2：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/r5_timing_optimization/candidate_20261020_110315`；SOURCE SHA `e6f50680dd8de5f165bfe6ca31e37da2c05e025b278bb21abc971d4254424300`。
- S3：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/r5_timing_optimization/candidate_20261020_110653`；SOURCE SHA `cb591b50851f695e727323a660eb0d1fd4134c7c0e7c2b9dd7fc4cc826d24231`。
- S4：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/r5_timing_optimization/candidate_20261020_110957`；SOURCE SHA `ba124444f1084d76ee7db167121a0d52f21138a3bc2f5f7c425bd05c596bdfe4`。
- R1历史：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/c2_timing_optimization/candidate_20261020_095359`；SOURCE SHA `1e2849cdec2ab4934ecdbd6156822deba9af04a17ba481d77af956e62e6c052b`。

归档仅保存 MD／JSON、冻结 RTL、源码校验、综合／布线报告及验证摘要；仿真明细留 build。全部测量及额外验证结束前，本进展报告列为 volatile；不可变原始证据的哈希不会被重写。
