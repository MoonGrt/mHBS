# 与 Unified HBS Architecture 的比较协议

版本：v0.1.0（测量前冻结）

## 1. 对照身份

- `B0`：论文报告值。它不是本地重测，也不用于控制器因果归因。
- `B1`：依据论文描述重建的 fixed-task controller，并与 μHBS 使用完全相同的 Hash lane、HIL、存储模式、时钟约束和测试向量。
- `B2`：展平微码。
- `B3`：循环压缩微码但关闭跨阶段 forwarding。
- `B4`：循环压缩微码、FULL_CACHE、关闭 TreeHash 优化。
- `M`：完整 μHBS。

论文主张中的严格 speedup 只来自 B1–M 的同源实验；B0 仅在 `PAPER_COMPARABLE` 成立的点上列相对值，否则并排报告而不计算比值。

## 2. 冻结的 B0 报告值

实现环境：Artix-7 `xc7a200t`、Vivado 2018.3、108 MHz、P=2、U=2。

| 算法/profile | Keygen cycles | Sign cycles | Sign 统计边界 |
|---|---:|---:|---|
| SPHINCS+ n=128 fast | 23,688 | 537,636 | 固定 |
| SPHINCS+ n=192 fast | 34,687 | 926,398 | 固定 |
| SPHINCS+ n=256 fast | 91,510 | 1,929,154 | 固定 |
| LMS h=10,w=2 | 3,808,440 | 3,572 | 1,000 随机签名均值 |
| LMS h=10,w=4 | 5,843,438 | 5,429 | 1,000 随机签名均值 |
| XMSS h=10,w=2 | 7,829,494 | 7,334 | 1,000 随机签名均值 |
| XMSS h=10,w=4 | 15,682,342 | 14,549 | 1,000 随机签名均值 |

资源报告值：24,184 LUT、13,659 FF、16.5 BRAM、0 DSP；其中 Control 4,222 LUT/5,137 FF，Data RAM 14.5 BRAM，Sig RAM 2 BRAM。

## 3. 可比性清单

每个数据点必须绑定并核验：

1. 规范 revision 与全部算法参数；
2. Keygen/Sign/Verify 的输入、输出和是否包含预计算；
3. Hash 函数、domain separation、ADRS 编码、padding 与输出长度；
4. Hash 调用数、吸收 block、挤出 block和 Keccak-p[1600] permutation 数；
5. P、U、lane 调度和 OTS rate-wide 输入能力；
6. FULL_CACHE/SUBTREE_CACHE/TREEHASH_MIN 以及计时前缓存状态；
7. first input、START、first output、last output 与 DONE 的 cycle 定义；
8. FPGA part、speed grade、Vivado 版本、综合/实现 strategy、clock constraint 与 seed。

缺一项即为 `NON_STRICT`。`NON_STRICT` 可用于背景讨论，不得进入 speedup、ATP 改善或“优于”结论。

## 4. 计时规则

- `cycles_total`：接受唯一 Job 的上升沿到 DONE/ERROR 上升沿，包含输出背压；主表以 `out_ready=1`。
- `cycles_compute`：扣除可明确归因的外部输入/输出等待，但不扣内部 memory stall。
- `first_output_cycles`：START 到第一个有效签名字节。
- 逐项记录 issue、input compose、Keccak round、memory、barrier、lane idle 和 output stall 周期。
- LMS/XMSS Sign 用固定 PRNG seed `0x6d75484253` 生成 1,000 条消息，报告 mean/P50/P95/max；同时报告 q=0、q=2^h-1。

## 5. 面积与时序规则

- 主点为 P=2/U=2；P=1/2、U=1/2 为消融。
- B1–M 必须共用 Hash/HIL RTL。不同存储模式分别列出，不横跨模式计算控制器收益。
- 报告 post-route LUT、FF、BRAM、DSP、Fmax/WNS；pre-synthesis 只能标作估计。
- 当前本机 Vivado 2025.2 结果不得标作论文同版本复现；若没有 Vivado 2018.3，工具差异保留为限制。

## 6. 预注册 Gate

| 维度 | Pass 条件 |
|---|---|
| 正确性 | 主 profile 零 mismatch |
| 自主性 | 每操作 1 Job；BUSY 期间 host/task/hash 写入均为 0 |
| 解耦 | 不含 HashFlow 的副本中 `make ci` 通过 |
| 扩展性 | RTL 冻结后增加一个完整流程，核心 RTL 修改模块数=0 |
| 程序 | 主 profile 静态镜像不超过 4 KiB |
| 性能 | 同源 B1 的 cycles 比值不高于 1.15 |
| 面积 | 同源 B1 的总 LUT 比值不高于 1.10 |
| 存储 | 至少一模式相对 16.5 BRAM 降低至少 50%，并披露延迟 |
| 时序 | post-route 满足冻结 clock target |

测量后不修改阈值。若 B0 工作量无法闭合，论文外部数据降为非严格背景，B1 保留为主因果基线。
