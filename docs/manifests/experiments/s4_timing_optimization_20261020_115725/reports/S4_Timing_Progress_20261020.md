# S4 基础 SHAKE 时序优化进展

更新时间：2026-10-20T13:24:45+08:00；后台测量继续。

本轮唯一比较基线为冻结 S4（20261020_110957），聚焦 P12U1／P4U1。基线按各自最佳实测闭合 ATP 比较：P12U1 为139.997200 MHz，P4U1 为149.992500 MHz。精确名义目标因时钟量化未满足，与实际 STA 闭合分开记录；P12U1 的150MHz负 WNS不计ATP。

common OOC、xc7a200tffg1156-3、通用 Keccak、SYNTHESIS 统计裁剪、默认时序驱动；100 MHz 综合仅诊断面积和关键路径。每个 Vivado 两线程，全机最多十二个；异常综合只延后分析，后台继续，不新增时序例外。h20 完整 Keygen／Sign 保持停止。

工作区当前匹配冻结 RTL：T2。报告归档固定在 T1，不因后续候选迁移。

| 阶段 | 候选 | Sign通过 | 额外验证 | 源码绑定 | 状态 |
|---|---|---:|---|---|---|
| S4 | S4：P12U1@139.997200MHz、P4U1@149.992500MHz 实际 STA 闭合 | 6/6 | — | 匹配 | 完成 |
| T1 | T1_local_context_reads | 6/6 | 76/76（passed） | 匹配 | 完成 |
| T2 | T2_registered_batch_completion | 6/6 | 76/76（passed） | 匹配 | 完成 |
| T3 | T3_registered_workspace_commit | 6/6 | 75/75（passed） | 匹配 | 后台运行 |

## 100 MHz 综合面积及路径诊断

| 阶段 | 配置 | LUT | FF | BRAM36 | Slice | 相对S4面积 % | 路径 ns | 级数 | 耗时 s | 状态 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| S4 | P12U1 | 51,057 | 28,221 | 0.000 | 16,291.875 | 0.000 | 5.729 | 8 | 317.263 | passed |
| S4 | P4U1 | 32,746 | 14,666 | 0.000 | 10,019.750 | 0.000 | 4.976 | 6 | 144.397 | passed |
| T1 | P12U1 | 50,130 | 28,212 | 0.000 | 16,059.000 | -1.429 | 5.776 | 10 | 242.001 | passed |
| T1 | P4U1 | 32,654 | 14,669 | 0.000 | 9,997.125 | -0.226 | 4.963 | 6 | 153.460 | passed |
| T2 | P12U1 | 50,180 | 28,219 | 0.000 | 16,072.375 | -1.347 | 5.575 | 8 | 282.573 | passed |
| T2 | P4U1 | 32,752 | 14,660 | 0.000 | 10,020.500 | 0.007 | 4.979 | 6 | 164.164 | passed |
| T3 | P12U1 | 50,806 | 28,478 | 0.000 | 16,261.250 | -0.188 | 6.464 | 8 | 271.181 | passed |
| T3 | P4U1 | 33,390 | 14,928 | 0.000 | 10,213.500 | 1.934 | 5.190 | 12 | 215.314 | passed |

## slh_128f 完整 Sign

| 阶段 | 配置 | 周期 | 相对S4周期 % | 假设100MHz时间 ms | 假设ATP Slice·ms | 相对S4假设ATP % | Hash／置换 | 工作量相同 | 状态 |
|---|---|---:|---:|---:|---:|---:|---|---|---|
| S4 | P12U1 | 300,011 | 0.000000 | 3.000110 | 48,877.417106 | 0.000000 | 104,937／105,641 | 是 | passed |
| S4 | P4U1 | 762,507 | 0.000000 | 7.625070 | 76,401.295133 | 0.000000 | 104,937／105,641 | 是 | passed |
| T1 | P12U1 | 300,011 | 0.000000 | 3.000110 | 48,178.766490 | -1.429393 | 104,937／105,641 | 是 | passed |
| T1 | P4U1 | 762,507 | 0.000000 | 7.625070 | 76,228.777924 | -0.225804 | 104,937／105,641 | 是 | passed |
| T2 | P12U1 | 300,561 | 0.183327 | 3.005610 | 48,307.291024 | -1.166441 | 104,937／105,641 | 是 | passed |
| T2 | P4U1 | 763,717 | 0.158687 | 7.637170 | 76,528.261985 | 0.166184 | 104,937／105,641 | 是 | passed |
| T3 | P12U1 | 300,561 | 0.183327 | 3.005610 | 48,874.975612 | -0.004995 | 104,937／105,641 | 是 | passed |
| T3 | P4U1 | 763,717 | 0.158687 | 7.637170 | 78,002.235795 | 2.095437 | 104,937／105,641 | 是 | passed |

## xmss_h10 完整 Sign

| 阶段 | 配置 | 周期 | 相对S4周期 % | 假设100MHz时间 ms | 假设ATP Slice·ms | 相对S4假设ATP % | Hash／置换 | 工作量相同 | 状态 |
|---|---|---:|---:|---:|---:|---:|---|---|---|
| S4 | P12U1 | 8,349,402 | 0.000000 | 83.494020 | 1,360,274.137087 | 0.000000 | 3,431,815／3,431,815 | 是 | passed |
| S4 | P4U1 | 22,408,430 | 0.000000 | 224.084300 | 2,245,268.664925 | 0.000000 | 3,431,815／3,431,815 | 是 | passed |
| T1 | P12U1 | 8,349,402 | 0.000000 | 83.494020 | 1,340,830.467180 | -1.429393 | 3,431,815／3,431,815 | 是 | passed |
| T1 | P4U1 | 22,408,430 | 0.000000 | 224.084300 | 2,240,198.757637 | -0.225804 | 3,431,815／3,431,815 | 是 | passed |
| T2 | P12U1 | 8,360,666 | 0.134908 | 83.606660 | 1,343,757.592017 | -1.214207 | 3,431,815／3,431,815 | 是 | passed |
| T2 | P4U1 | 22,429,934 | 0.095964 | 224.299340 | 2,247,591.536470 | 0.103456 | 3,431,815／3,431,815 | 是 | passed |
| T3 | P12U1 | 8,360,666 | 0.134908 | 83.606660 | 1,359,548.799925 | -0.053323 | 3,431,815／3,431,815 | 是 | passed |
| T3 | P4U1 | 22,429,934 | 0.095964 | 224.299340 | 2,290,881.309090 | 2.031501 | 3,431,815／3,431,815 | 是 | passed |

## lms_h10 完整 Sign

| 阶段 | 配置 | 周期 | 相对S4周期 % | 假设100MHz时间 ms | 假设ATP Slice·ms | 相对S4假设ATP % | Hash／置换 | 工作量相同 | 状态 |
|---|---|---:|---:|---:|---:|---:|---|---|---|
| S4 | P12U1 | 3,133,307 | 0.000000 | 31.333070 | 510,474.459806 | 0.000000 | 1,101,392／1,116,752 | 是 | passed |
| S4 | P4U1 | 7,672,352 | 0.000000 | 76.723520 | 768,750.489520 | 0.000000 | 1,101,392／1,116,752 | 是 | passed |
| T1 | P12U1 | 3,133,307 | 0.000000 | 31.333070 | 503,177.771130 | -1.429393 | 1,101,392／1,116,752 | 是 | passed |
| T1 | P4U1 | 7,672,352 | 0.000000 | 76.723520 | 767,014.619880 | -0.225804 | 1,101,392／1,116,752 | 是 | passed |
| T2 | P12U1 | 3,134,331 | 0.032681 | 31.343310 | 503,761.432061 | -1.315057 | 1,101,392／1,116,752 | 是 | passed |
| T2 | P4U1 | 7,673,376 | 0.013347 | 76.733760 | 768,910.642080 | 0.020833 | 1,101,392／1,116,752 | 是 | passed |
| T3 | P12U1 | 3,134,331 | 0.032681 | 31.343310 | 509,681.399738 | -0.155357 | 1,101,392／1,116,752 | 是 | passed |
| T3 | P4U1 | 7,673,376 | 0.013347 | 76.733760 | 783,720.257760 | 1.947286 | 1,101,392／1,116,752 | 是 | passed |

输出和签名缓存逐字节核对，Hash／置换次数及向量 SHA 与 S4 比较。以上 100 MHz ATP 是固定假设频率的诊断值，不代表布线收益。

## 布线 STA

| 阶段 | 配置 | 名义目标 MHz | 实际周期 ns | WNS ns | WHS ns | 布通 | DRC错误 | 严格目标达到 | 状态 |
|---|---|---:|---:|---:|---:|---|---:|---|---|
| S4 | P12U1 | 150.000 | 6.667 | -0.063 | 0.119 | 是 | 0 | 否 | target_not_met |
| S4 | P12U1 | 140.000 | 7.143 | 0.078 | 0.130 | 是 | 0 | 否 | target_not_met |
| S4 | P12U1 | 135.000 | 7.407 | 0.123 | 0.094 | 是 | 0 | 是 | passed |
| S4 | P4U1 | 150.000 | 6.667 | 0.014 | 0.096 | 是 | 0 | 否 | target_not_met |
| S4 | P4U1 | 140.000 | 7.143 | 0.134 | 0.094 | 是 | 0 | 否 | target_not_met |
| S4 | P4U1 | 135.000 | 7.407 | 0.180 | 0.068 | 是 | 0 | 是 | passed |
| T1 | P12U1 | 150.000 | 6.667 | -0.374 | 0.097 | 是 | 0 | 否 | target_not_met |
| T1 | P12U1 | 160.000 | 6.250 | -0.456 | 0.065 | 是 | 0 | 否 | target_not_met |
| T1 | P4U1 | 150.000 | 6.667 | -0.203 | 0.096 | 是 | 0 | 否 | target_not_met |
| T1 | P4U1 | 160.000 | 6.250 | -0.116 | 0.096 | 是 | 0 | 否 | target_not_met |
| T2 | P12U1 | 150.000 | 6.667 | 0.004 | 0.099 | 是 | 0 | 否 | target_not_met |
| T2 | P12U1 | 160.000 | 6.250 | -0.443 | 0.096 | 是 | 0 | 否 | target_not_met |
| T2 | P4U1 | 150.000 | 6.667 | 0.075 | 0.093 | 是 | 0 | 否 | target_not_met |
| T2 | P4U1 | 160.000 | 6.250 | -0.285 | 0.094 | 是 | 0 | 否 | target_not_met |
| T3 | P12U1 | 150.000 | 6.667 | -0.335 | 0.094 | 是 | 0 | 否 | target_not_met |
| T3 | P12U1 | 160.000 | — | — | — | — | — | — | cancelled_by_user |
| T3 | P4U1 | 150.000 | — | — | — | — | — | — | cancelled_by_user |
| T3 | P4U1 | 160.000 | 6.250 | -0.232 | 0.074 | 是 | 0 | 否 | target_not_met |

## 按实际约束闭合的频率及 ATP

只有源码／工作量绑定、完整布通、DRC=0、setup／hold 全通过才填写本表。名义 150 MHz 若被 Vivado 量化为 6.667 ns，实际闭合频率为约 149.9925 MHz，保留该实测值且严格目标列保持“否”。负 WNS 不外推较低频率。

| 阶段 | 配置 | 算法 | 名义目标 MHz | 实际STA频率 MHz | 严格目标达到 | 布线 Slice | 时间 ms | ATP Slice·ms | 相对S4各自最佳闭合 % |
|---|---|---|---:|---:|---|---:|---:|---:|---:|
| S4 | P12U1 | slh_128f | 140.000 | 139.9972 | 否 | 16,051.250 | 2.142979 | 34,397.484820 | 0.000000 |
| S4 | P12U1 | xmss_h10 | 140.000 | 139.9972 | 否 | 16,051.250 | 59.639778 | 957,292.994423 | 0.000000 |
| S4 | P12U1 | lms_h10 | 140.000 | 139.9972 | 否 | 16,051.250 | 22.381212 | 359,246.427526 | 0.000000 |
| S4 | P12U1 | slh_128f | 135.000 | 135.0074 | 是 | 16,052.000 | 2.222181 | 35,670.457069 | 3.700771 |
| S4 | P12U1 | xmss_h10 | 135.000 | 135.0074 | 是 | 16,052.000 | 61.844021 | 992,720.218896 | 3.700771 |
| S4 | P12U1 | lms_h10 | 135.000 | 135.0074 | 是 | 16,052.000 | 23.208405 | 372,541.316241 | 3.700771 |
| S4 | P4U1 | slh_128f | 150.000 | 149.9925 | 否 | 9,989.750 | 5.083634 | 50,784.234440 | 0.000000 |
| S4 | P4U1 | xmss_h10 | 150.000 | 149.9925 | 否 | 9,989.750 | 149.397003 | 1,492,438.708821 | 0.000000 |
| S4 | P4U1 | lms_h10 | 150.000 | 149.9925 | 否 | 9,989.750 | 51.151571 | 510,991.404239 | 0.000000 |
| S4 | P4U1 | slh_128f | 140.000 | 139.9972 | 否 | 9,967.750 | 5.446588 | 54,290.222563 | 6.903694 |
| S4 | P4U1 | xmss_h10 | 140.000 | 139.9972 | 否 | 9,967.750 | 160.063415 | 1,595,472.109750 | 6.903694 |
| S4 | P4U1 | lms_h10 | 140.000 | 139.9972 | 否 | 9,967.750 | 54.803610 | 546,268.686927 | 6.903694 |
| S4 | P4U1 | slh_128f | 135.000 | 135.0074 | 是 | 9,964.625 | 5.647889 | 56,279.099404 | 10.820021 |
| S4 | P4U1 | xmss_h10 | 135.000 | 135.0074 | 是 | 9,964.625 | 165.979241 | 1,653,920.894449 | 10.820021 |
| S4 | P4U1 | lms_h10 | 135.000 | 135.0074 | 是 | 9,964.625 | 56.829111 | 566,280.782829 | 10.820021 |
| T2 | P12U1 | slh_128f | 150.000 | 149.9925 | 否 | 16,054.750 | 2.003840 | 32,171.153242 | -6.472367 |
| T2 | P12U1 | xmss_h10 | 150.000 | 149.9925 | 否 | 16,054.750 | 55.740560 | 894,900.759224 | -6.517569 |
| T2 | P12U1 | lms_h10 | 150.000 | 149.9925 | 否 | 16,054.750 | 20.896585 | 335,489.444449 | -6.613005 |
| T2 | P4U1 | slh_128f | 150.000 | 149.9925 | 否 | 10,185.500 | 5.091701 | 51,861.522970 | 2.121305 |
| T2 | P4U1 | xmss_h10 | 150.000 | 149.9925 | 否 | 10,185.500 | 149.540370 | 1,523,143.438411 | 2.057353 |
| T2 | P4U1 | lms_h10 | 150.000 | 149.9925 | 否 | 10,185.500 | 51.158398 | 521,073.860710 | 1.973117 |

## 验证与源码证据

- T1：76/76（passed）；冻结源码绑定：匹配。T1: local context prefetch tag and reused return operands; S4 frozen source with parallel workspace address-pair selection (scheduled recipe FSM one-hot implementation attribute) with narrowed scheduled list-word source, registered response queue ownership, and target-at-level shadow index: P4/P12 published+deferred pipeline KAT in normal and SYNTHESIS views; P4/P12 three-profile Verify stall/replay/reset/cut/tamper/fault; P4/P12 SYNTHESIS recipes and P2U12 normal/SYNTHESIS recipes, P2U12 full XMSS Verify; SHA2 P4 SLH Sign executor compatibility. P1U1 all scalar recipes and three-profile Verify smoke; P6U1 three-target full Sign exercises 8-leaf FORS microgroups in 6+2 waves and odd L-tree. Root executes P4/P12 six SHAKE Sign independently. Both normal and SYNTHESIS P4/P12 complete recipe KAT plus all six SLH parameter Verify. No h20 Keygen/Sign.
- T2：76/76（passed）；冻结源码绑定：匹配。T2: local context prefetch tag, reused return operands and registered batch completion; S4 frozen source with parallel workspace address-pair selection (scheduled recipe FSM one-hot implementation attribute) with narrowed scheduled list-word source, registered response queue ownership, and target-at-level shadow index: P4/P12 published+deferred pipeline KAT in normal and SYNTHESIS views; P4/P12 three-profile Verify stall/replay/reset/cut/tamper/fault; P4/P12 SYNTHESIS recipes and P2U12 normal/SYNTHESIS recipes, P2U12 full XMSS Verify; SHA2 P4 SLH Sign executor compatibility. P1U1 all scalar recipes and three-profile Verify smoke; P6U1 three-target full Sign exercises 8-leaf FORS microgroups in 6+2 waves and odd L-tree. Root executes P4/P12 six SHAKE Sign independently. Both normal and SYNTHESIS P4/P12 complete recipe KAT plus all six SLH parameter Verify. No h20 Keygen/Sign.
- T3：75/75（passed）；冻结源码绑定：匹配。T3 frozen source based on S4, registered retirement, selected prefetch control, and forwarded workspace write commit with parallel workspace address-pair selection (scheduled recipe FSM one-hot implementation attribute) with narrowed scheduled list-word source, registered response queue ownership, and target-at-level shadow index: P4/P12 published+deferred pipeline KAT in normal and SYNTHESIS views; P4/P12 three-profile Verify stall/replay/reset/cut/tamper/fault; P4/P12 SYNTHESIS recipes and P2U12 normal/SYNTHESIS recipes, P2U12 full XMSS Verify; SHA2 P4 SLH Sign executor compatibility. P1U1 all scalar recipes and three-profile Verify smoke; P6U1 three-target full Sign exercises 8-leaf FORS microgroups in 6+2 waves and odd L-tree. Root executes P4/P12 six SHAKE Sign independently. Both normal and SYNTHESIS P4/P12 complete recipe KAT plus all six SLH parameter Verify. No h20 Keygen/Sign.
- 工作区单元验证：2/2（passed）；冻结源码绑定：T3。`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/s4_timing_optimization/validation_t3/WORKSPACE_VALIDATION.json`；T3 frozen actual executor commit/forward network: independent logical-capture and physical-commit scoreboards; both forwarding ports, back-to-back writes, same-address overwrite, odd/even adjacent pairs, guard pair, authentication-first/deferred-stack-second collision, and pending write physically landing on reset edge. Legal register-state setup supplements full functional regressions. No production/frozen RTL modification, no h20 full-tree execution, no Vivado.
- 工作区单元验证：2/2（passed）；冻结源码绑定：S4。`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/docs/manifests/experiments/r5_timing_optimization_20261020_110957/validation_summary/WORKSPACE_VALIDATION.json`；Direct legal register-state setup to exercise 126/127 and 127/126 protection, authentication write priority, next-cycle deferred stack write, and retained RAM data after reset. No full-tree generation or RTL modification.
- S4：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/r5_timing_optimization/candidate_20261020_110957`；SOURCE SHA `ba124444f1084d76ee7db167121a0d52f21138a3bc2f5f7c425bd05c596bdfe4`。
- T1：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/s4_timing_optimization/candidate_20261020_115725`；SOURCE SHA `52b1809b5a2d536652e4e64f52650608473eeb8abd55675795007e42b9639e42`。
- T2：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/s4_timing_optimization/candidate_20261020_115729`；SOURCE SHA `68ece10f4699bce1fe25171d833d40ffab0845379400fc32f1e45a0d63e5b03d`。
- T3：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/s4_timing_optimization/candidate_20261020_115825`；SOURCE SHA `5e34070f534d800fce6b8ddf37e56599fe40dc7cc58cb3b05f731e4eee1146ec`。

归档仅保存 MD／JSON、冻结 RTL、源码校验、综合／布线报告及验证摘要；仿真明细留 build。全部测量及额外验证结束前，本进展报告列为 volatile；不可变原始证据的哈希不会被重写。
