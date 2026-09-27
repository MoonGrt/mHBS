# 表格、数据与口径核对补充

更新：2026-09-24。来源：本目录原始阅读稿对应的 IACR ePrint 2026/194 PDF。

本补充保留原文报告值，提供可复制的 Markdown 表格及 CSV/JSON；单位解释、重算结果和当前 μHBS 对比另行标识。原文与中文全文仍见 [paper.md](paper.md)。

## 目录

- [Table 1：XMSS/LMS 参数](#audit-table1)
- [Table 2：SPHINCS+ 参数](#audit-table2)
- [Table 5：完整周期与时间](#audit-table5)
- [Table 6：模块资源](#audit-table6)
- [Table 7：全部 29 行报告值](#audit-table7)
- [原文口径核对与重算](#audit-findings)
- [μHBS 完整对比快照](UHBS_Comparison_2026-09-24.md)

## 提取与解释约定

| 项目 | 处理方式 |
|---|---|
| Source / 原始来源 | 本地 PDF；Table 1/2 在 p.9，Table 5/6 在 p.17，Table 7 在 p.19 |
| 原文数值 | 原样保留，不用派生量覆盖 |
| 合并单元格 | CSV/JSON 中按表格覆盖范围展开；主表中的重复资源不表示多个独立实例 |
| 空白和短横线 | JSON 使用 null、CSV 留空、Markdown 显示 —；不推定为 0 |
| Table 7 的 h | 未列出时按其脚注 b 取 10；在数据中显式展开 |
| ATP 显示列 | 保留原文数字；单位缩放不明处不自行补写成 Slice·ms |
| 第三方工作 | 仅转录本文 Table 7；未独立核对其引用论文 |
| 新分析与当前结果 | 属于阅读补充，不是作者原文，也不是原论文实验 |

表格中的 `n` 在 Table 1 对应字节数，在 Table 2 对应比特数。`ω/w` 为每个 Winternitz 数字的位数；XMSS ω=4 对应 base=16。Table 2 的 `h` 是单层子树高度，总高度 `H=h×d` 是派生量。

<a id="audit-table1"></a>
## Table 1：XMSS/LMS 参数集

**Source:** p.9，[T001 原图](paper.md#T001)。

**Original caption:** Parameters Set in XMSS/LMS

**中文图注：**XMSS/LMS 参数集。

| Scheme / 方案 | n（byte） | w（bit） | len | h 可选值 |
|---|---|---|---|---|
| XMSS | 32 | 2 | 133 | 10;16;20 |
| XMSS | 32 | 4 | 67 | 10;16;20 |
| LMS | 32 | 1 | 265 | 5;10;15;20;25 |
| LMS | 32 | 2 | 133 | 5;10;15;20;25 |
| LMS | 32 | 4 | 67 | 5;10;15;20;25 |
| LMS | 32 | 8 | 34 | 5;10;15;20;25 |

[CSV 数据](data/table1.csv)；[统一 JSON](data/paper_tables.json)。

<a id="audit-table2"></a>
## Table 2：SPHINCS+ 参数集

**Source:** p.9，[T002 原图](paper.md#T002)。

**Original caption:** Parameters Set in SPHINCS+

**中文图注：**SPHINCS+ 参数集。

| Scheme / 方案 | n（bit） | len | ω | k | a | h（子树） | d |
|---|---|---|---|---|---|---|---|
| SPHINCS+128-f | 128 | 35 | 4 | 33 | 6 | 3 | 22 |
| SPHINCS+192-f | 192 | 51 | 4 | 33 | 8 | 3 | 22 |
| SPHINCS+256-f | 256 | 67 | 4 | 35 | 9 | 4 | 17 |
| SPHINCS+128-s | 128 | 35 | 4 | 14 | 12 | 9 | 7 |
| SPHINCS+192-s | 192 | 51 | 4 | 17 | 14 | 9 | 7 |
| SPHINCS+256-s | 256 | 67 | 4 | 22 | 14 | 8 | 8 |

[CSV 数据](data/table2.csv)；[统一 JSON](data/paper_tables.json)。

**解释：**128-f 的 h=3、d=22，对应总高度 66；192-f 对应 66；256-f 对应 68。原文表内没有将 h 写成 66，不能把两种高度定义混用。

<a id="audit-table5"></a>
## Table 5：处理器周期与时间

**Source:** p.17，[T005 原图](paper.md#T005)。

**Original caption:** Latency of processor.

**中文图注：**处理器周期与时间。

| Algorithm / 算法 | Param / 参数 | Keygen CCs | Keygen ms | Sign CCs | Sign ms |
|---|---|---|---|---|---|
| SPHINCS+ | n=128 | 23,688 | 0.22 | 537,636 | 4.95 |
| SPHINCS+ | n=192 | 34,687 | 0.32 | 926,398 | 8.52 |
| SPHINCS+ | n=256 | 91,510 | 0.84 | 1,929,154 | 17.75 |
| LMS | h=10;omega=2 | 3,808,440 | 35.04 | 3,572 | 0.03 |
| LMS | h=10;omega=4 | 5,843,438 | 53.76 | 5,429 | 0.05 |
| XMSS | h=10;omega=2 | 7,829,494 | 72.03 | 7,334 | 0.07 |
| XMSS | h=10;omega=4 | 15,682,342 | 144.28 | 14,549 | 0.13 |

[CSV 数据](data/table5.csv)；[统一 JSON](data/paper_tables.json)。

**统计边界：**p.17 S342 说明 LMS/XMSS 签名时间为 1,000 次随机签名平均值；不应标作指定单消息的 KAT 周期。原文该段引用“Table II”，本补充保留其引用不一致事实，数据位置以实际 Table 5 为准。

<a id="audit-table6"></a>
## Table 6：按模块的资源占用

**Source:** p.17，[T006 原图](paper.md#T006)。

**Original caption:** Resource utilization by module.

**中文图注：**按模块的资源占用。

| Module / 模块 | LUT | FF | BRAM 原文值 | 层次 | LUT% 原文 | FF% 原文 |
|---|---|---|---|---|---|---|
| Control unit | 4,222 | 5,137 | 16.5 | 0 | 17.4 | 37.8 |
| Post Process | 895 | 1,090 | 0 | 0 | 3.7 | 8 |
| Hash LOOP | 19,067 | 7,432 | 0 | 0 | 78.4 | 54.8 |
| HASH LOOP0 | 9,657 | 3,717 | — | 1 | — | — |
| HASH LOOP0.HIL | 3,303 | 2,078 | — | 2 | — | — |
| HASH LOOP0.Keccak | 6,354 | 1,639 | — | 2 | — | — |
| HASH LOOP1 | 9,410 | 3,715 | — | 1 | — | — |
| HASH LOOP1.HIL | 3,056 | 2,076 | — | 2 | — | — |
| HASH LOOP1.Keccak | 6,354 | 1,639 | — | 2 | — | — |
| Sig RAM | 0 | 0 | 2 | 0 | — | — |
| Data RAM | 0 | 0 | 14.5 | 0 | — | — |
| Total | 24,184 | 13,659 | 16.5 | 0 | — | — |

[CSV 数据](data/table6.csv)；[统一 JSON](data/paper_tables.json)。

**层次解释：**Control unit 的 16.5 BRAM 与独立列出的 Sig RAM 2、Data RAM 14.5 表示归属关系；不可重复求和。Hash LOOP0/1 及其 HIL/Keccak 是父子层次。表中百分比为原显示值，部分与原始整数除以 Total 的结果不完全一致，不作静默修正。

<a id="audit-table7"></a>
## Table 7：跨实现资源与性能

**Source:** p.19，[T007 原图](paper.md#T007)。

**Original caption:** Comparison of resource usage and performance across schemes.

**中文图注：**跨实现资源与性能。

| 方案 | 文中引用 | 参数 | LUT/FF/BRAM/DSP | MHz | Sign ms | Keygen ms | ATP Sign 原显示 | ATP Keygen 原显示 |
|---|---|---|---|---|---|---|---|---|
| SPHINCS+ | ALCZ20 | n=128 | 47,991/72,505/11.5/1 | 250 | 1.01 | 1.01 | 2.41 | 2.41 |
| SPHINCS+ | ALCZ20 | n=192 | 48,398/73,476/17/1 | 250 | 1.17 | 1.17 | 2.96 | 2.96 |
| SPHINCS+ | ALCZ20 | n=256 | 51,009/74,539/22.5/1 | 250 | 2.52 | 2.52 | 6.91 | 6.91 |
| SPHINCS+ | HLL+25 | n=128 | 29,410/14,090/4/0 | 179.8 | 1.96 | 0.082 | 1.97 | 0.08 |
| SPHINCS+ | HLL+25 | n=192 | 29,410/14,090/4/0 | 179.8 | 3.19 | 0.12 | 3.21 | 0.12 |
| SPHINCS+ | HLL+25 | n=256 | 29,410/14,090/4/0 | 179.8 | 6.61 | 0.316 | 6.64 | 0.32 |
| SPHINCS+ | DLK+25 | n=128 | 10,197/7,357/8/0 | 150 | 19.3 | — | 10.28 | — |
| SPHINCS+ | DLK+25 | n=192 | 10,333/7,590/8/0 | 150 | 31.11 | — | 16.77 | — |
| SPHINCS+ | DLK+25 | n=256 | 10,416/7,072/8/0 | 150 | 61.77 | — | 33.03 | — |
| SPHINCS+ | This work | n=128 | 24,184/13,659/16.5/0 | 108 | 4.95 | 0.22 | 5.73 | 0.25 |
| SPHINCS+ | This work | n=192 | 24,184/13,659/16.5/0 | 108 | 8.52 | 0.32 | 9.88 | 0.37 |
| SPHINCS+ | This work | n=256 | 24,184/13,659/16.5/0 | 108 | 17.75 | 0.84 | 20.57 | 0.98 |
| LMS | SHTW23 | h=5;w=1 | 139,886/103,914/58/3 | 267 | 0.0022 | 0.21 | 0.01 | 1.17 |
| LMS | SHTW23 | h=10;w=1 | — | 267 | 0.0022 | 1.81 | — | — |
| LMS | SHTW23 | h=10;w=2 | — | 267 | 0.0021 | 0.92 | — | — |
| LMS | SHTW23 | h=10;w=4 | — | 267 | 0.0037 | 0.89 | — | — |
| LMS | SHTW23 | h=10;w=8 | — | 267 | 0.0264 | 7.09 | — | — |
| LMS | THG24 | h=10;w=4;Min | 15,860/13,914/15/0 | 100 | 1.18 | 785 | 0.97 | 647.55 |
| LMS | THG24 | h=10;w=4;Med | 26,828/19,515/15/0 | 100 | 0.34 | 223 | 0.37 | 245.57 |
| LMS | THG24 | h=10;w=4;Lar | 36,534/24,197/15/0 | 100 | 0.22 | 140 | 0.24 | 154.17 |
| LMS | This work | h=10;w=2 | 24,184/13,659/16.5/0 | 108 | 0.03 | 35.04 | 0.04 | 40.6 |
| LMS | This work | h=10;w=4 | 24,184/13,659/16.5/0 | 108 | 0.05 | 53.76 | 0.06 | 62.3 |
| XMSS | THG24 | h=10;w=4;Min | 15,860/13,914/15/0 | 100 | 6.9 | 4,680 | 5.88 | 3985.55 |
| XMSS | THG24 | h=10;w=4;Med | 26,828/19,515/15/0 | 100 | 1.6 | 1,100 | 1.84 | 1267.27 |
| XMSS | THG24 | h=10;w=4;Lar | 36,534/24,197/15/0 | 100 | 1.2 | 783 | 1.69 | 1104.98 |
| XMSS | CWW+22 | h=10;w=2 | 22,300/31,215/0/0 | 110 | 5.54 | 1799.82 | 5.25 | 1706.16 |
| XMSS | CWW+22 | h=10;w=4 | 22,300/31,215/0/0 | 110 | 11.09 | 2881.53 | 10.51 | 2731.58 |
| XMSS | This work | h=10;w=2 | 24,184/13,659/16.5/0 | 108 | 0.07 | 72.03 | 0.08 | 83.47 |
| XMSS | This work | h=10;w=4 | 24,184/13,659/16.5/0 | 108 | 0.13 | 144.28 | 0.16 | 167.19 |

[CSV 数据](data/table7.csv)；[统一 JSON](data/paper_tables.json)。

**原脚注含义：**短横线表示没有数据；除特别标注外，LMS/XMSS 采用 h=10。7-series 等效面积公式见下一节；Ultrascale+ 的 BRAM/DSP 权重分别为 116.2、51.2。表中引用工作的器件和 Hash 函数差异不能忽略。本次主比较只使用 This work 的三条对应配置。

<a id="audit-findings"></a>
## 原文口径核对与重算

### 1. 等效面积、时间、ATP

原文依据：p.19 Table 7 脚注 c；资源为 p.17 Table 6 的总计行。

- 7-series 等效 Slice = LUT/4 + FF/8 + BRAM×232.4 + DSP×102.4。
- 24,184 LUT、13,659 FF、16.5 BRAM、0 DSP → **11,587.975 等效 Slice**。
- ATP（Slice·ms）= 等效 Slice × 毫秒数。
- 这个等效指标不是 Vivado 实际占用的 Slice 数，也不是 ASIC 硅面积。

下表前两项时间是原文报告值；108 MHz 换算和 ATP 是本次重算，不是作者新增测量：

| 方案 | 参数 | Keygen 原 ms | Sign 原 ms | Keygen 周期/108MHz ms | Sign 周期/108MHz ms | Keygen 重算 ATP | Sign 重算 ATP |
|---|---|---|---|---|---|---|---|
| SPHINCS+ | n=128 | 0.22 | 4.95 | 0.219333 | 4.978111 | 2,549.354500 | 57,360.476250 |
| SPHINCS+ | n=192 | 0.32 | 8.52 | 0.321176 | 8.577759 | 3,708.152000 | 98,729.547000 |
| SPHINCS+ | n=256 | 0.84 | 17.75 | 0.847315 | 17.862537 | 9,733.899000 | 205,686.556250 |
| LMS | h=10;omega=2 | 35.04 | 0.03 | 35.263333 | 0.033074 | 406,042.644000 | 347.639250 |
| LMS | h=10;omega=4 | 53.76 | 0.05 | 54.105907 | 0.050269 | 622,969.536000 | 579.398750 |
| XMSS | h=10;omega=2 | 72.03 | 0.07 | 72.495315 | 0.067907 | 834,681.839250 | 811.158250 |
| XMSS | h=10;omega=4 | 144.28 | 0.13 | 145.206870 | 0.134713 | 1,671,913.033000 | 1,506.436750 |

[重算 JSON](data/paper_recomputed.json) / [CSV](data/paper_recomputed.csv)。

### 2. 周期、108 MHz 与毫秒值没有完全闭合

例如 537,636 周期除以 108 MHz 得到 4.978111 ms，而 Table 5 报告 4.95 ms；XMSS ω=4 的 Keygen 15,682,342 周期对应 145.206870 ms，原表为 144.28 ms。现有材料不足以确定原因，不擅自修改原文值。

μHBS 的已约定验收门槛继续采用原文毫秒值：57,360.476、1,506.437、579.399 Slice·ms。按 108 MHz 重算的结果单独保存，不混用。

### 3. ATP 列的显示尺度与精度

Table 7 的 SPHINCS+ n=128 显示 ATP=5.73，但按脚注公式与 4.95 ms 计算为 57,360.47625 Slice·ms。可观察到约 10⁴ 的尺度差异；表头没有明确给出这个缩放，不能直接将 5.73 作为 Slice·ms。

XMSS ω=4 显示 0.16，而资源与 0.13 ms 的乘积为 1,506.43675 Slice·ms。显示精度、未公布的小数或其他口径可能影响结果，但不能推定原因。因此数据同时保留 `*_atp_display_raw` 和另表重算值。

### 4. Hash 函数与 profile

依据 [p.10 S162](paper.md#S162) 及其后续 SHAKE-only 说明，论文自己的 LMS/XMSS/SPHINCS+ 均使用 SHAKE256。不能把它与 Table 7 中采用 SHA-256 的引用工作混淆。

当前 μHBS 的 LMS 仍是私有类型码的 SHAKE256/256 研究 profile；与论文 LMS 未逐项核对序列化及 Hash trace。SLH-DSA 与论文 SPHINCS+ 也不作为严格同工作量。XMSS 的主要参数可以对齐，但固定 Job 与随机消息平均值、缓存和硬件配置仍不同。

### 5. 树缓存、签名缓冲和流式输出

原文依据：[p.16 S322](paper.md#S322)，§3.4 Memory。

| 项目 | 论文原文描述 | 当前 μHBS 快照 |
|---|---|---|
| DataRAM | 256×2¹¹ bit，14.5 BRAM | 分布式工作存储，不永久保留全树 |
| SigRAM | 256×2⁸ bit，2 BRAM | 小型输出打包缓冲，流式输出 |
| 树存储 | 为 h=10 的完整 Merkle 树保留存储 | 计算完整树，保留当前 q 的认证路径和根 |
| 当前路径有效数据 | 包含于树存储 | 10×32+32=352 byte；不是核总存储容量 |
| 后续索引 | 全树设计可提供对应认证节点 | 下次启动重新计算完整树 |

论文也采用分段流式签名输出，不能说它必须先缓存整条签名。当前 0 BRAM 仍使用 LUTRAM/寄存器；面积下降包含存储策略差异，不是同等缓存能力下的纯存储替换。

### 6. μHBS 对比结论（外部实现分析）

当前三项 Sign ATP 分别为 48,225.754、888.939、373.916 Slice·ms，较指定论文数值门槛低约 15.93%、40.99%、35.46%。但三项 Sign 时间均更长；XMSS/LMS 的 Keygen ATP 分别高约 14.16%、13.02%。

这些是 NON_STRICT 描述性数值比较。当前为分别静态综合的固定 Job 产品，采用 OOC 内部时序；不等于论文同能力网表、板级频率或同消息统计。

当前 Keygen 已计算完整树并选出 q 的认证路径；Sign 使用该路径，所以 Sign 远短于 Keygen。单 lane 降低面积，通常使计算更慢。XMSS/LMS 的下一索引需重新 Keygen，持续签名成本不能用 Sign 时间单独表示。当前索引保护器在即时确认场景的 `RESERVE` 状态各驻留 3 周期；延迟确认测试额外驻留 9 周期。详见 [比较报告 §8.4](UHBS_Comparison_2026-09-24.md) 与 [§12.1](UHBS_Comparison_2026-09-24.md)。

完整限制、Keygen→Sign 生命周期和资源分解见 [比较报告](UHBS_Comparison_2026-09-24.md)。

### 7. 已修复的图表裁切与提取限制

- Table 1：补齐左侧方案名和底部 LMS w=8 行。
- Table 2：补齐底部 small 参数集行；区分子树高度与总高度。
- Table 5：补齐底部 XMSS ω=4 行。
- 三张图均由原始 PDF 在 120 dpi 重新裁取并逐张查看，稳定锚点 T001/T002/T005 保持不变。
- Table 3/4 的旧原图仍在阅读稿中；本次未新增其结构化转录，不能将本补充称为全部七张表的结构化数据集。
- PDF 的 trailer/xref 警告此前已记录；本次相关页仍能完成文本提取和渲染。

## 数据与证据文件

- [论文原始表格 JSON](data/paper_tables.json)：Table 1/2/5/6/7，共 60 行（含层次行与引用实现）。
- [原文重算数据](data/paper_recomputed.json)：原文时间、周期/频率换算与 ATP 并列。
- [当前 μHBS 结果快照](data/uhbs_current_snapshot.json)、[模型 gate](data/uhbs_model_gate_snapshot.json)、[验证快照](data/verification/verification.json)。
- [μHBS 比较 JSON](data/uhbs_comparison.json) / [CSV](data/uhbs_comparison.csv)。
- 原始页文本：[p.9](data/source_page_09.txt)、[p.16](data/source_page_16.txt)、[p.17](data/source_page_17.txt)、[p.18](data/source_page_18.txt)、[p.19](data/source_page_19.txt)。
- [补充来源清单](data/supplement_manifest.json)：PDF 摘要、数据文件摘要、源锚点和裁切坐标。
