# μHBS v4.1：两篇论文启发的 SLH 优化

本报告由 `python3 scripts/report_slh_paper_optimization.py` 根据封存数据生成；`--check` 检查报告是否与记录一致。当前生产架构保持 U2、双 lane、五类宏指令和三个独立 ROM。

## 1. 两篇论文的架构及可借鉴部分

| 项目 | Unified HBS Architecture | Huang 等 SPHINCS+ 处理器 | 当前 μHBS |
|---|---|---|---|
| 控制 | 11 类共享任务、分层计数器 | 面向 SPHINCS+ 的控制与统一链地址生成 | program/template/descriptor 驱动 HASH/CHAIN/TREE/TRANSFORM/EMIT |
| Keccak | 两个独立 U2 核 | 8-round 数据通路插入四组 1600 位寄存器，交错四个上下文 | 两个独立 U2 lane |
| Hash 输入 | OTS 的 1088 位快速通路与其他任务的灵活填充通路 | 四组 1088 位 HIL 阵列，输入准备与置换重叠 | 短 Hash 整块装载，长 Hash 每拍生成 64 位，链内直接反馈 |
| 存储 | 保留支持 XMSS/LMS 快速签名的树层数据 | 分组子树、分段签名输出 | SLH 树栈、端点及 FORS 根；结果直接流出 |
| 功能范围 | 三算法 Keygen/Sign | SPHINCS+ Keygen/Sign/Verify | SLH-DSA 128f/192f/256f Keygen/Sign |

Huang 的四个 SHAKE 操作在交错运行时用 12 拍完成各自 24 轮；这个吞吐率来自流水和多上下文配合，不能直接套用于增加组合展开轮数的独立 lane。其 HIL 利用置换期间准备下一批输入，链反馈避免反复存取。本轮借鉴输入预处理思想，利用现有请求阶段缩短数据通路，不复制其八轮流水结构。

按论文的八轮与四组均匀寄存器推断，平均每级约两轮组合计算。只看满负荷单块置换的理想吞吐，Huang 为 4/12 次每拍，本核两条 U2 lane 为 2/12 次每拍；前者约为两倍，另有频率差异。这不是完整签名加速比，实际还受数据装载、链依赖、任务并行度和输出影响。

Unified HBS 的快速 OTS 输入与灵活长输入分工也适合本核。已有短 Hash 装载、链反馈和小容量流式存储继续保留；删除 SHAKE 的填充或域分隔会改变算法输出，不能作为等价优化。

原文：[Unified Reader](../../references/papers/Unified_HBS_Architecture_2026_Reader/paper.md)；[Huang 论文](https://doi.org/10.1109/TCSI.2025.3544341)（III.B–D、表 II/V）。原文文件 SHA-256 与数据口径保存在 [来源记录](../../manifests/experiments/unified_hbs_v4.1/slh_only/paper_optimization_sources.json)。

## 2. 当前瓶颈与本轮改动

原 U2 布线关键路径为 `task_recipe → 输入长度/填充选择 → staged_data`，约 9.815 ns。Hash 等待状态包含实际置换时间，不能把该状态的全部驻留周期当作调度浪费。

1. **C1，请求预译码：**在 IDLE 接收请求时寄存初始/链步输入长度和节点字数。利用原有 IDLE→START 阶段，避免 arity、节点长度运算反复进入每个字节的填充比较。保留配方决定的链步与短 Hash 行为。
2. **C2，流式位置计数器：**在 C1 上将 `rate_block×136 + beat×16 + half×8` 的组合计算替换为每个有效生产拍递增 8 的位置寄存器。计数器在新请求清零，受原有接收条件控制，阻塞时不前移。没有增加逐 Hash 等待拍。

C1 单独综合略增面积；C2 去掉宽组合位置计算后减少 LUT。两者的三个参数点 Keygen/Sign 周期均与基线相同。原微码编码、宏指令顺序、配方和路由语义不变；执行仍由镜像驱动。

## 3. 综合与布线记录

本轮比较基线为 `slh_only_l2_c2_route`，不是更早的七参数点共同核。综合表中的 100 MHz 仅用于归一化，不能作为实际频率。

| 候选 | 阶段 | LUT | FF | LUTRAM | 等效 Slice | MHz | 最大 Huang ATP 比值 | 最终验收 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| slh_only_l2_c2_route | post_route | 25,753 | 12,287 | 1,904 | 7,974.125 | 99.010 | 3.1428 | 通过 |
| slh_only_u2_l2_hil_cursor_c2 | post_synth | 25,332 | 12,322 | 1,904 | 7,873.250 | 100.000 | 3.0724 | 候选，未通过最终验收 |
| slh_only_u2_l2_hil_cursor_c2_route | post_route | 25,073 | 12,322 | 1,904 | 7,808.500 | 102.041 | 2.9862 | 通过 |
| slh_only_u2_l2_hil_predecode_c1 | post_synth | 26,262 | 12,320 | 1,904 | 8,105.500 | 100.000 | 3.1630 | 候选，未通过最终验收 |

以上候选的 BRAM、DSP 均为 0；LUTRAM 已包含在 LUT 中，不重复计入面积。等效 Slice = LUT/4 + FF/8 + BRAM36×232.4 + DSP×102.4。

## 4. 当前已验收最优：`slh_only_u2_l2_hil_cursor_c2_route`

共同面积 **7,808.500 Slice**，共同频率 **102.040816 MHz**，周期 **9.8 ns**。

| Profile | Boot 周期 | Keygen 周期 | Sign 周期 | Keygen ATP | Sign ATP | 相对本轮基线 ATP 降低 |
|---|---:|---:|---:|---:|---:|---:|
| slh_128f | 262 | 29,864 | 730,773 | 2,285.292 | 55,921.162 | 4.99% |
| slh_192f | 262 | 43,662 | 1,252,185 | 3,341.160 | 95,821.328 | 4.99% |
| slh_256f | 262 | 115,780 | 2,583,685 | 8,859.868 | 197,712.102 | 4.99% |

ATP 单位为 Slice·ms，Boot 单列。频率按 0.1 ns 周期粒度选择，并保留至少 0.1 ns setup 裕量。
最终 setup/hold 为 0.116/0.095 ns；三个仅 INIT 不同检查点的共同结构指纹为 `ca0599a5ec1f75b181e4f1198540438193b1fd4a9e25b950bb05f6c00121b947`。

原始资源、时序覆盖和布线证据：[候选目录](../../manifests/experiments/unified_hbs_v4.1/slh_only/candidates/slh_only_u2_l2_hil_cursor_c2_route/ppa.json)。

相对本轮基线，面积下降 **2.08%**，频率提高 **3.06%**。该候选综合耗时 131 秒；`route_design` 耗时 **00:39:46**，布线时间明显增加，已保留完整工具日志。

最终最长数据路径经过 U2 的两轮 Keccak 和链反馈选择，延迟 9.462 ns，其中逻辑 1.267 ns、布线 8.195 ns（86.61%）。输入长度计算已退出最长路径。下一轮应优先评估这条通路的连线长度和反馈选择逻辑，并单独测量面积与频率。

## 5. 与两篇论文的数值对照

| 设计 | LUT | FF | BRAM36 | 等效 Slice | MHz |
|---|---:|---:|---:|---:|---:|
| Unified HBS | 24,184 | 13,659 | 16.5 | 11,587.975 | 108 |
| Huang | 29,410 | 14,090 | 4 | 10,043.350 | 179.8 |
| μHBS 已验收 | 25,073 | 12,322 | 0 | 7,808.500 | 102.041 |

| Profile | Unified Sign 周期 | Unified 按 108 MHz 重算 ms | Unified 重算 ATP | Huang 报告 ms | Huang ATP | μHBS ms | μHBS ATP |
|---|---:|---:|---:|---:|---:|---:|---:|
| slh_128f | 815,706 | 7.552833 | 87,522.044 | 1.950 | 19,584.533 | 7.161575 | 55,921.162 |
| slh_192f | 926,398 | 8.577759 | 99,398.860 | 3.195 | 32,088.503 | 12.271413 | 95,821.328 |
| slh_256f | 1,929,154 | 17.862537 | 206,990.633 | 6.613 | 66,416.674 | 25.320113 | 197,712.102 |

Unified 128f 的 **815,706 周期**来自用户转述的作者更新，假定资源与 108 MHz 不变；192f/256f 仍为旧表 V 数值，未收到相应更新。旧表的四舍五入毫秒值与周期重算结果不完全相等。Huang 对照使用论文报告的毫秒值。

**NON_STRICT：**两文采用 SPHINCS+，本核采用 FIPS 205 SLH-DSA；算法版本、支持操作、输入向量、器件与 Keccak 结构不同。Unified 还承担 XMSS/LMS 存储和控制。论文用于分析差距，不是本轮硬通过门槛；本轮验收要求三个 SLH 点的 ATP 都比当前 U2 基线改善。

## 6. 已做的 U1/U3 探索

以下为输入路径优化前的独立探索，不能与 C2 周期/面积混搭。U3 布线曾被中断，没有最终频率。

| 配置 | 综合 Slice | 128f Sign 周期 | 192f Sign 周期 | 256f Sign 周期 | 按综合面积优于基线所需 MHz | 状态 |
|---|---:|---:|---:|---:|---:|---|
| U1/L2 | 6,972.875 | 1,400,709 | 2,354,601 | 4,845,925 | >165.948 | 综合筛除 |
| U3/L1 | 6,014.375 | 930,253 | 1,565,209 | 3,227,125 | >95.062 | 布线中断，未验收 |
| U3/L2 | 9,141.625 | 507,461 | 884,713 | 1,829,605 | >80.378 | 布线中断，未验收 |

所需频率只是以综合面积计算的盈亏平衡条件。U3 把关键路径转移到三个 Keccak round 的组合网络；后续若研究交错流水，需要独立评估上下文寄存器、输入重叠和任务并行度，不能据综合 ATP 认定更优。
探索归档为事后绑定当时未修改的提交，缺少运行时源码哈希；限制、原始日志和独立复现命令见 [探索 README](../../manifests/experiments/unified_hbs_v4.1/slh_only/exploratory/unroll_scan_20260926/README.md)。

## 7. 验证与复现

- 软件宏语义未改；已核对原软件门禁及模型源码哈希。
- Icarus：节点/存储/镜像拒绝、原有 Hash/链反馈；新增 hashlib 独立向量验证 135/136/137 字节及连续请求间切换节点长度和配方。
- Verilator 5.008：三个参数点全输出与计数、消息边界、lane 交换、复位中断重放、完成停机、执行前与输出中故障。
- 综合和布线来自同一候选源码；每个候选登记其比较基线，旧记录继续使用原基线。
- OOC 内部寄存器时序，不代表板级输入输出接口时序。

```bash
make rtl-unit-test rtl-verification
make synth-common TAG=<新候选名>
make route-common TAG=<新候选名>
make freeze-common TAG=<新候选名>
python3 scripts/autonomous_flow.py finalize --tag <新候选名>_route
make reproduce-slh-only
python3 scripts/report_slh_paper_optimization.py --check
```

精确复跑已有结果应在独立目录解开对应候选的 `source_snapshot.tar.gz`，按 `inputs.json` 与 `route_flow.tcl` 记录执行；当前源码继续优化时，不应覆盖已有 tag。
