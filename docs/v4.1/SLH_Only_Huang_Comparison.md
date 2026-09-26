# μHBS v4.1：仅 SLH 的共同硬件与 Huang 等人处理器对照

## 口径

- 项目：FIPS 205 SLH-DSA SHAKE 128f/192f/256f，一次上电 Keygen→Sign；同一候选的三点仅替换 ABI 4 ROM INIT。
- 论文：Huang 等，*An Efficient and Reconfigurable Post-Quantum Crypto-Processor for SPHINCS+*，IEEE TCAS-I 2025，表 I/II/V；Artix-7 XC7A100T，179.8 MHz，29,410 LUT、14,090 FF、4 BRAM、0 DSP。
- 两者算法版本、器件、数据路径与签名输入不完全一致；以下逐点 ATP 为 **NON_STRICT** 性能对照。论文采用四路交错、8-round Keccak；项目固定 U2 并扫描 1/2/4 个独立 Hash lane。
- 等效面积公式：LUT/4 + FF/8 + BRAM36×232.4 + DSP×102.4；论文面积重算为 **10,043.350 Slice**。
- 选择规则：初次 SLH 裁剪相对原七点共同核验收；后续优化相对各 inputs.json 固定的已验收基线，三个点 ATP 均须降低。再最小化三点中最大的项目/论文 ATP 比值，同分选较小面积。论文数值是对照，不是硬通过门槛。
- 旧 V3 三点 ATP 仅作历史参考，不参与本轮 SLH-only 选型。

## 论文原值与原七点共同核基线

| 参数 | 论文 Sign ms | 论文 Sign ATP Slice·ms | 原共同核 Sign 周期 | 原共同核 Sign ATP Slice·ms |
|---|---:|---:|---:|---:|
| slh_128f | 1.950 | 19,584.533 | 730,773 | 71,246.714 |
| slh_192f | 3.195 | 32,088.503 | 1,252,185 | 122,081.777 |
| slh_256f | 6.613 | 66,416.674 | 2,583,685 | 251,896.369 |

## SLH-only 候选

| 候选 | 阶段 | Lane | LUT | FF | LUTRAM | BRAM36 | Slice | MHz | 最大论文 ATP 比值 | 三点均优于登记基线 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| slh_only_l1_c1 | post_synth | 1 | 18,191 | 9,028 | 2,588 | 0 | 5,676.250 | 100.000 | 3.975 | 否 |
| slh_only_l1_c2 | post_synth | 1 | 17,398 | 9,023 | 1,904 | 0 | 5,477.375 | 100.000 | 3.836 | 否 |
| slh_only_l2_c1 | post_synth | 2 | 26,726 | 12,285 | 2,588 | 0 | 8,217.125 | 100.000 | 3.207 | 是 |
| slh_only_l2_c2 | post_synth | 2 | 26,091 | 12,287 | 1,904 | 0 | 8,058.625 | 100.000 | 3.145 | 是 |
| slh_only_l2_c2_route | post_route | 2 | 25,753 | 12,287 | 1,904 | 0 | 7,974.125 | 99.010 | 3.143 | 是 |
| slh_only_l4_c1 | post_synth | 4 | 42,311 | 18,710 | 2,588 | 0 | 12,916.500 | 100.000 | 3.255 | 是 |
| slh_only_l4_c2 | post_synth | 4 | 41,386 | 18,708 | 1,904 | 0 | 12,685.000 | 100.000 | 3.197 | 是 |
| slh_only_u2_l2_hil_cursor_c2 | post_synth | 2 | 25,332 | 12,322 | 1,904 | 0 | 7,873.250 | 100.000 | 3.072 | 是 |
| slh_only_u2_l2_hil_cursor_c2_route | post_route | 2 | 25,073 | 12,322 | 1,904 | 0 | 7,808.500 | 102.041 | 2.986 | 是 |
| slh_only_u2_l2_hil_predecode_c1 | post_synth | 2 | 26,262 | 12,320 | 1,904 | 0 | 8,105.500 | 100.000 | 3.163 | 否 |

## 最优 ATP：`slh_only_u2_l2_hil_cursor_c2_route`

| 参数 | Boot 周期 | Keygen 周期 | Sign 周期 | Slice | MHz | Keygen ATP Slice·ms | Sign ATP Slice·ms | 项目/论文 ATP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| slh_128f | 262 | 29,864 | 730,773 | 7,808.500 | 102.041 | 2,285.292 | 55,921.162 | 2.855 |
| slh_192f | 262 | 43,662 | 1,252,185 | 7,808.500 | 102.041 | 3,341.160 | 95,821.328 | 2.986 |
| slh_256f | 262 | 115,780 | 2,583,685 | 7,808.500 | 102.041 | 8,859.868 | 197,712.102 | 2.977 |

相对原七点共同核，等效面积下降 19.91%，三个 SLH 点的签名 ATP 均下降 21.51%。

最小面积候选：`slh_only_l1_c2`，5,477.375 Slice（post_synth；综合候选的 100 MHz 仅作归一化）。

三份 INIT 检查点具有相同单元、连接、布局及路由指纹 `ca0599a5ec1f75b181e4f1198540438193b1fd4a9e25b950bb05f6c00121b947`；最终 setup/hold 裕量分别为 0.116/0.095 ns。

布线、时序覆盖和三份 INIT 结构证据见 [候选记录](../../manifests/experiments/unified_hbs_v4.1/slh_only/candidates/slh_only_u2_l2_hil_cursor_c2_route/ppa.json)。

## 复现与限制

- 后续两篇论文架构分析、优化增量和 U1/U3 探索见 [论文启发优化报告](SLH_Paper_Guided_Optimization.md)。
- 当前生产核只接收三个 SLH profile；Job 的 q 必须为零，镜像中的有状态配方、索引片段和认证路径缓存模式在上电校验阶段被拒绝。旧七点镜像和结果仍由封存源码核验。
- 功能检查：`make area-software-test compile-microcode rtl-unit-test architecture-test rtl-verification`。
- 证据核验：`make reproduce-slh-only reproduce-paper-comparison`；候选源码、镜像、仿真、工具报告和检查点保存在 `manifests/experiments/unified_hbs_v4.1/slh_only/`。
- 当前时序口径是 OOC 内部寄存器路径；外部输出路径未赋予板级时序要求。
原七点报告及其证据保持在 v4.1 历史路径中。论文原文 DOI：[10.1109/TCSI.2025.3544341](https://doi.org/10.1109/TCSI.2025.3544341)。
