# μHBS 预期收益与当前证据

更新：2026-09-16。本文区分“已测局部收益”和“待端到端验证的预期收益”。

## 已测局部收益

| 机制 | 对照 | 实测结果 | 可得结论 |
|---|---|---|---|
| Keccak unroll | U1 vs U2，同 RTL/器件/工具/100 MHz | U1 4,689 LUT/3,213 FF/24 cycles；U2 7,071 LUT/3,211 FF/12 cycles | U2 的 LUT×cycle=0.754×，局部改善 24.6% |
| TreeHash 工作集 | 64 KiB full proxy vs 672 B min proxy | 16 vs 1 RAMB36 | 存储宏 BRAM 减少 93.75% |
| TreeHash 功能 | h=10 Python oracle vs RTL | 1,024 leaves、1,023 parents，root/auth 零 mismatch | `TREEHASH_MIN` 的 O(h) 语义可行 |
| 标准 XMSS parent 联合切片 | RFC 8391 SHAKE256/n=32 Python oracle vs RTL | 一 Job，4 leaves、3 randomized-H parents，ADRS height/index 硬件派生，root/auth 一致 | TreeHash 不再仅依赖 `SHAKE(left||right)` 测试布局 |
| WOTS+ leaf→TreeHash | RFC 8391 WOTS+/L-tree/TreeHash oracle vs RTL | 每叶 67 PRF_keygen、1,005 F、66 L-tree H；一 Job 生成 1,024 叶/1,023 parent；h=10 root 与 10 层 auth 一致；57,204,676 cycles | 叶不需 testbench 预装；当前是串行融合 leaf capability，尚非通用 composer/P2 性能点 |
| FIPS 205 SLH parent | SLH-DSA-SHAKE-128f n=16 oracle vs RTL | `PK.seed||ADRS||left||right` 80 B；1 SHAKE/parent；3 向量及 fault/backpressure 通过；已接入 FORS 和 22 层 Hypertree | 标准 parent 与 XMSS randomized H 分离；完整 Sign 中 1,969 次 parent 已硬件计数 |
| 数据表示 lowering | 现有逻辑槽/move vs 64-bit Scratchpad/v1-v2 descriptor | XMSS `R5+R7 -> R6+R3` 降为2条 binding，v2 RTL 以单 Job 完成 affine STORE→OUTPUT，缺失 binding/越界 fail-closed | 软件只在离线初始化生成镜像；尚未接完整 XMSS replay |
| JSON layout→RTL composer | XMSS/SLH-DSA JSON vs 静态镜像 | 支持 16/32-byte slot、136-byte SHAKE 输出、仿射/移位表达式、ordered-pair、memory-range 和 relocation；无 DMA Job 完成整个 tc137 Sign；rate-wide + prefetch + feedback 后为 6,002,014 cycles | 无手写 SLH-DSA 算法 FSM；144-word JSON 微程序是唯一算法控制源 |
| descriptor-selected TreeHash | 同一 RTL elaboration 中 h=2/h=3 MIN | 一次 start + descriptor ID，root/auth 精确匹配；SUBTREE/FULL 和非32-byte节点 fail-closed | 高度与 parent layout 已不是综合常数；cache 模式尚未接入 |
| RFC 8554 LMS parent | 86-byte `I||u32(r)||0x8383||left||right` vs hashlib | 4 组独立向量及顺序/身份/背压通过，每 parent 两个 SHA-256 block | 真实 LMS parent primitive 已闭合；尚未接入完整 LMS TreeHash |
| TreeHash transaction recovery | partial tree fault/cancel 后下一树 | 排空旧 scratch/parent response，无全局 reset 后 root/auth 仍一致 | 数字事务隔离成立；不代表掉电原子性或物理清零 |
| 组合数据/TreeHash 路径 | descriptor+AGU+data/TreeHash/OUTPUT 共享单端口 Scratchpad | 一 Job 完成 13 指令；data/tree/emit 交易 32/16/1，root/auth/output 一致 | 固定仲裁与响应归属成立；尚不是完整 XMSS replay |
| TreeHash cache RTL | h=10 FULL vs SUBTREE(h≥4) cache store，同流程 post-route | 14 vs 4 RAMB36；3,778 vs 591 LUT；2,118 vs 198 FF | cache store BRAM 降 71.4%，但尚未测 cache-assisted Sign latency |
| warm active-subtree cache | 127 upper-only vs 127 upper + 30 active lower，h=10/w=4 | BRAM 均为 4；warm 为 1,244 LUT/691 FF/WNS +0.556 ns；当前窗口 auth 10/10 hit | 用 653 LUT/493 FF 换取当前 16-leaf 窗口零 auth miss；未含 refill/Sign 延迟 |
| 自主执行 | 3-step SHAKE chain | 1 Job、3 Hash、BUSY 期间 0 host writes | 不需软件逐 Hash 驱动 |
| XMSS 微码表达 | RFC 8391 oracle 与官方 C KAT | Keygen 93 words/744 B；Sign 114 words/912 B；完整有序 SHAKE trace 零 mismatch | 无 XMSS opcode、无 host-supplied chain lengths 即可在模型层展开完整流程 |
| 冻结模型后 XMSS Verify 扩展 | 有效 KAT + 1-bit 签名变异 | 177 words/1,416 B；2,826 动态指令；1,835 SHAKE/1,836 permutations；有序 trace 一致 | 未增 ISA/解释器/verifier/RTL；但只是模型层扩展，且输入仍需 admission 一次性拆分 |
| XMSS randomized-F RTL 垂直切片 | 动态 chain bound=3、U2 | 1 Job、3 layout 请求、9 SHAKE、36 读/12 写、260 cycles、oracle 一致 | 自主数据回写已连通；当前串行 Scratchpad 路径仍有显著开销 |
| 真实 datapath PPA | P1/U2 randomized-F slice，Artix-7 post-route | 7,685 LUT、6,039 FF、2 RAMB36、WNS +0.568 ns @100 MHz | 可实现且当前路由满足 100 MHz；进入 P2 前仍需压缩宽寄存器并流水化 composer |
| SLH-DSA 微码表达 | FIPS 205 SHAKE-128f Keygen vs NIST ACVP tc31 | 12 words/96 B；9,275 动态指令；4,495 SHAKE / 4,527 permutations；有序 trace 一致 | 最终标准 Keygen 可由通用循环/layout 表达，无逐 Hash 软件输入 |
| SLH-DSA Sign 微码表达 | FIPS 205 SHAKE-128f deterministic Sign vs NIST ACVP tc137 | 144 words/1,152 B；221,811 动态指令；完整 17,088 B 签名一致；104,937 SHAKE / 105,641 permutations；逐 Hash trace 一致 | 完整 FORS + 22 层 Hypertree 已在同一 P1/U2 RTL 中从一条 Job 展开 |
| SLH-DSA 完整 RTL 周期 | P1/U2、ACVP tc137、无 DMA | 6,002,014 cycles（60.02014 ms@100 MHz 归一化）；2,136 输出字逐字一致；硬件计数闭合 104,937 SHAKE / 105,641 permutations | 较 14,333,951-cycle 基线减少 58.127%；component 预取 732,201/732,201 命中，Hash 反馈缓存命中 187,612 次；这是完整当前 RTL 路径，不是 P2 或论文 draft workload 比较点 |
| SLH-DSA 完整 RTL PPA | xc7a200t-2、Vivado 2025.2、100 MHz OOC post-route | 34,874 LUT、23,903 FF、7 RAMB36、0 DSP、WNS −1.489 ns；约 87.04 MHz / 68.96 ms；LUT×cycles 与 timing-aware LUT×time 较原基线改善 57.032% / 52.560% | 读请求降 29.766%，但 Wave 3 的 35% 读/25% 写退出门槛尚未达到；100 MHz 时序、banked/coalesced Scratchpad 仍待闭合 |
| layout 表达宽度 | 288-bit 通用栈 vs 32-bit ADRS/index 栈，同流程 post-route | 10,929 LUT/6,307 FF/WNS −7.749 ns vs 993/922/+0.253 ns | 拒绝全宽 barrel-shifter；LUT/FF 降 90.9%/85.4% |
| digest digit unpack | ACVP tc137 33×6-bit FORS index 与 4-bit 模式 | 逐项一致；Vivado post-synthesis 0 LUT/0 FF | 宽摘要拆位用静态 wiring，不进入 layout ALU |
| 静态 P2/U2 batch | 4-hash even 与 3-hash odd batch | 34 cycles；mask `11/11` 与 `11/01`；7 KAT 一致 | 固定双 lane 映射成立；理论窗口吞吐为单 lane 的 2.0×/1.5× |
| 宽 P2 batch PPA | 5-entry×1088-bit latch，Artix-7 post-route | 41,633 LUT、15,757 FF、WNS +0.033 ns；其中 batch control/storage 24,420 LUT | 拒绝整批宽锁存，改为硬件内部 banked 小窗口 |
| 窗口化 P2/U2 垂直切片 | 512-word sequencer + 2×64-bit banks + 2 U2 lanes，6-message 容量 | 20,204 LUT、11,294 FF、3 RAMB36、WNS +0.368 ns；相宽 latch LUT/FF 降 51.5%/28.3% | 单 Job 静态双 lane 与 banked input 成立；84-cycle/4-hash window 仍被 38 compose cycles 限制 |
| raw-Job randomized-F P2/U2 | 2 条 U2 lane，Job 只含 seed/ADRS/2 nodes/bound | 14,811 LUT、10,850 FF、1 RAMB36、WNS +0.788 ns；chain 2/3 各 9 SHAKE，150 active/26 idle cycles | 不需要外部预组 Hash 消息；相邻 chain address 硬件派生；尚非完整 OTS/签名 |

除表中明确标为“SLH-DSA 完整 RTL”的两项外，其余均为局部或垂直切片结果，不是完整算法 PPA。

完整 Sign 的三点时序分段对比说明了当前取舍：未分段为
13,291,152 cycles、34,492 LUT、22,770 FF、WNS −9.513 ns；仅分段 component
地址为 14,961,490 cycles、34,025 LUT、23,035 FF、WNS −6.480 ns；进一步
分段 layout 目的地址后为 15,167,426 cycles、34,185 LUT、23,289 FF、WNS
−1.050 ns。第二次分段只增加 205,936 cycles（较上一版 +1.376%），
却把关键路径从 16.480 ns 降至 11.050 ns。按各自后布线关键路径估算，
端到端时延从 246.57 ms 降至 167.60 ms，较上一版改善约 32.03%，
较未分段的 259.35 ms 改善约 35.38%。在此基础上，将每个
component 的 operand 捕获折叠进 RAM 响应周期，得到 14,332,257 cycles、
34,001 LUT、23,228 FF 和 WNS −1.485 ns。周期较上一点减少 5.506%，
LUT×cycle 改善 6.015%；路由 WNS 退化 0.435 ns，但按 11.485 ns 临界
周期估算的端到端延迟仍由 167.60 ms 降至 164.61 ms（1.786%）。
再将 bitfield adapter 的可变寄存器选择和仿射乘法分成两级，
847 次 LOAD 共增加 1,694 cycles（0.0118%），但 WNS 改善到
−0.406 ns，面积为 33,985 LUT/23,269 FF。按 10.406 ns 临界周期估算，
延迟由 164.61 ms 降至 149.16 ms（9.384%）。这仍不是 100 MHz
时序收敛；最长路径已移至 composer 目的地址到 block-buffer CE。

## 最可能形成的论文收益

### 1. BRAM 收益的把握最高

论文对照报告 16.5 BRAM，其中 14.5 BRAM 保存整层中间树，2 BRAM 保存签名段。μHBS 的 672 B 存储代理已实测为 1 RAMB36，program store 实测为 1 RAMB36。新增实际 h=10 cache-store RTL 显示 FULL 为 14 RAMB36，而仅保留 height≥4 的 127 个上层节点为 4 RAMB36；后者比前者减少 71.4%。

若把尚未集成、可能共享的 program store、minimum scratch budget 和
SUBTREE cache 简单相加，已知宏为 6 RAMB36，距 8.25 BRAM 门槛尚有
2.25 RAMB36。这个和只能作预算压力测试，不能当完整设计 BRAM 总量。

要通过预注册的“相对 16.5 BRAM 减少至少 50%”条件，完整集成后总量需不高于 8.25 BRAM；即除已知 2 BRAM 外，其余模块仍有 6.25 BRAM 预算。从容量上看该目标有较大可行性，但必须用完整 post-route 证明。

主要风险是签名延迟：`TREEHASH_MIN` 不保留整树时，LMS/XMSS 的快速 Sign 需要重算认证路径。因此最可能的论文主点不是纯 `TREEHASH_MIN`，而是在 `SUBTREE_CACHE` 中找到 BRAM 明显低于 8.25、Sign P95 仍可接受的 Pareto 点。

### 2. U2 预计能改善 Hash-core ATP，但不保证整机 cycles

U2 把置换周期减半，LUT 只增加 50.8%，因此局部 LUT×cycle 改善 24.6%。但整机还受 input compose、BRAM 读写、microcode fetch 和 lane idle 影响。如果这些非置换周期占比过高，U2 的 2×理论吞吐收益会被稀释。

新的 randomized-F 垂直切片把这一风险量化出来：9 次 U2 置换只有
108 个 active-round cycles 的理想下界，而当前单端口适配器实测为
260 cycles，即 2.41× 下界。多出的 152 cycles 覆盖 48 次串行
Scratchpad 访问、SHAKE 启停、微指令 fetch/loop 和写回。它不是最终性能
点，但给出了明确优化目标：若 banked composer/feedback 不能把每次 F 的
12 读+4 写降为 rate-wide 装载与本地链反馈，μHBS 不可能实现预期的
Sign-latency 优势。

同工具 U2 Keccak 单核为 7,071 LUT/3,211 FF；完整 randomized-F
垂直切片为 7,685 LUT/6,039 FF。局部差值显示控制、Scratchpad 和
composer 增加 614 LUT，宽状态寄存器增加 2,828 FF。当前两个
OOC 点的 WNS 分别为 +0.389 ns 和 +0.568 ns，路由差异不能当作模块时序可加分解。
面积竞争力仍有机会，宽状态 FF 和完整 P2 集成仍是现实风险；
在完成 banked composer 前不能线性外推双 lane。

静态双 lane 实验进一步分离了调度与搬运：固定 even/odd 分配可让 4 个
单块 SHAKE 在 34 cycles 完成，按相同 17-cycle 单 lane 服务时间计算正好
是 2×吞吐；3 个 SHAKE 因尾部 mask 为 `01`，收益降为 1.5×。但把 5 个
1088-bit 消息一次性锁存并用可变索引选择，使切片膨胀到 41,633 LUT，
其中 lane 外开销就有 24,420 LUT。因此可预期收益来自“双 lane + 硬件内部
banked 小窗口”，而不是宽 batch；后者已经被实测否决。

窗口化点现在把这个方向量化了：即使多包含 512-word
Microsequencer 和容量更大的 6-message bank，LUT 仍从 41,633
降到 20,204、FF 从 15,757 降到 11,294，时序裕量也由
+0.033 ns 增至 +0.368 ns。但 4-hash Job 的 84 cycles 中有 38 cycles
用于 64-bit compose；相对宽 batch 34 cycles 的延迟回退表明，下一步
必须是 layout-driven OTS rate-wide 快路，而不是继续扩大 banked 窗口。

raw-Job randomized-F P2/U2 点表明预组消息并非双 lane 自主执行
的必要条件：两条 lane 从 seed、ADRS 和 node 自行生成 18 次
SHAKE 输入，一条 Job 在 176-cycle 记账窗口完成两条三步链。
这一点占 14,811 LUT，低于预组消息 window 的 20,204 LUT，
但两者功能边界和存储不同，不能把 26.2% 差值直接归因为
composer 节省。它强化的只是架构可行性：静态双 lane、链内本地反馈
和 BUSY 期间零软件 Hash 输入可同时实现。最终性能收益仍取决于
任意 chain pair 的微码寻址、OTS rate-wide 以及完整签名的 lane 利用率。

### 3. 微码的主收益应是扩展成本，而不是绝对性能

当前 LMS h10/w4 Keygen 的模型程序只有 13 words/104 B，却展开 2,269,187 条动态微操作和 1,100,799 次 Hash。这证明静态表示对动态 trace 有强压缩性，但同步 BRAM fetch 使普通指令目前有显式 `FETCH -> RUN` 周期。预期微码相对 fixed-task controller 可能有小幅面积/周期代价，论文主张应依赖“冻结 RTL 后新流程零核心模块修改”的 Gate 6 证据。

新增 XMSS Verify 已给出更接近 Gate 6 的模型层证据：保持
ISA、interpreter、verifier 和 RTL 不变，只新增 1,416 B 微码即重建
正确 public root，且签名单 bit 变异被拒绝。但完整 Gate 6 仍要求
冻结的完整 RTL 数据路上运行，并将当前 Job admission 中的签名
固定字段由原子 Job 锁存，消息由 payload-only stream 搬入内部 Scratchpad；
该路径不需要 DMA，且 SLH-DSA-SHAKE-128f Sign 已在完整
P1/U2 RTL 中闭合。冻结后扩展 Gate 仍需另一个 held-out profile/流程。

XMSS 的模型结果进一步表明，静态 Sign 程序仅 912 B，却可在不接收
task/Hash descriptor、也不由 host 输入 chain length 的条件下展开
4,779,374 条微指令。这是“无 runtime 的窗口化循环控制”证据，
不是整机性能证据。

### 4. XMSS 的性能收益只可能出现在缓存签名点

已验证的 RFC 8391 `XMSS-SHAKE256_10_256` 工作量为：

| 流程 | SHAKE 调用 | Keccak permutation | 理想 P2/U2 置换下界 |
|---|---:|---:|---:|
| Keygen | 3,430,396 | 3,430,396 | 20,582,376 cycles |
| Sign + `TREEHASH_MIN` 全树重算 | 3,431,950 | 3,431,951 | 20,591,712 cycles |
| Sign + 当前 upper-only SUBTREE(h≥4) 冷重算 | 51,788 | 51,789 | 310,740 cycles |
| Sign 核心，FULL 或 warm active-subtree 全 auth hit | 1,554 | 1,555 | 9,336 cycles |

下界按两个 lane、每次 U2 置换 12 active cycles 计算，未计 composer、
微码 issue、依赖、存储和尾部不平衡，因此只是不可突破的理想界。
对照论文的 XMSS h10/w4 报告值为 Keygen 15,682,342 cycles、Sign mean
14,549 cycles：

- 严格 RFC 工作量的 Keygen 理想下界已是论文报告值的 1.312×，
  因此在工作量未对齐前，不应预期 Keygen 速度胜出；
- `TREEHASH_MIN` Sign 的理想下界是论文 Sign 的 1,415×，它只能是低存储端点；
- 当前 4-BRAM upper-only SUBTREE 有 6 个上层 auth hit，但 4 个低层 miss
  需要重建 15 个 WOTS 叶和 11 个父节点；每个叶的严格工作量为 3,346 次
  SHAKE，所以 310,740-cycle 理想下界仍是论文报告点的 21.36×；
- 若 `FULL_CACHE` 或 warm active-subtree 能直接提供完整 auth path，高度理想化的
  9,336-cycle 下界相对 14,549 cycles 有最多约 1.56× 的空间；
  实际收益必然更小，并且需要 B1 同源 RTL 才能归因。

因此预期最有价值的论文 Pareto 已进一步收敛为“127 个上层节点 + 当前
16-leaf 活动子树 h0--h3 的 30 个节点”。h4 根已在上层区，不重复保存。
该窗口内可把所有 auth 访问变成 hit；逻辑容量从 127 增至 157 nodes
（4,064→5,024 B）。RTL 已证明它仍映射为 4 RAMB36，低层窗口用
172 个 distributed-RAM LUT。尚未测量的是窗口 refill 成本、跨子树更新的
摊销延迟以及完整 Sign replay；在这些数据出来之前，仍不能把
9,336-cycle 理想下界当成实测快速 Sign 点。

机器可读推导见
`manifests/experiments/xmss_cache_sign_projection_v0.1.0.json`。

### 5. SLH-DSA 的现有证据支持扩展性，不支持绝对加速

FIPS 205 SHAKE-128f Keygen 已测得 4,527 次 permutation，理想 P2/U2
下界为 27,168 cycles；论文 draft SPHINCS+ 对应报告值只有 23,688
cycles。下界已经高出 14.7%，所以即使控制开销为零，当前严格 FIPS
工作负载也不可能在同一置换吞吐假设下复现该报告值。预期收益应放在：

- 96-byte 微程序对最终标准流程的静态表达压缩；
- 与 LMS/XMSS 共用 sequencer、Scratchpad、TreeHash 与 SHAKE 数据路；
- 后续 Sign/FORS/Hypertree 在不新增算法专用 opcode 下的扩展证据。

它不能支持“SLH-DSA Keygen 比论文快”的主张，除非先取得论文精确 trace
并解释至少 579 次 permutation 的等价差异。

完整 deterministic Sign oracle 与微码又把边界收紧了一步：最终 FIPS 205
SHAKE-128f 需要 104,937 次 SHAKE、105,641 次 Keccak permutation。
在 P=2、U=2 且两个 lane 永不空闲的理想条件下，仅置换就至少需要
`ceil(105641/2) × 12 = 633,852 cycles`；论文 draft SPHINCS+ 128f Sign
报告 537,636 cycles。μHBS 的不可突破下界已高出 17.9%，而且尚未计入
composer、微码、存储和输出开销。因此：

完整 RTL replay 实测为 8,800,104 cycles；旧的 2,034,645
只是未包含 composer/AGU/Scratchpad/TreeHash 的分析下界。实测与
633,852 的理想 P2/U2 置换下界相差约 13.9×，显示当前主要问题
已转为 component 控制、Scratchpad 交易和单有效 lane，不是微程序静态大小。

- 不应把最终 FIPS 205 Sign 对论文 draft 数据宣称 cycle speedup；
- 可比较的主指标应转为标准兼容下的静态程序压缩、共享硬件面积、BRAM
  Pareto 和自主执行；
- 若要讨论 Sign 性能，必须先取得论文完整 Hash trace 或构建相同 profile、
  相同工作量、相同计时边界的 B1 RTL。

Sign 程序本身只有 144 个 64-bit words（1,152 B），相对把 104,937 次
Hash 各保存一个 64-bit descriptor 的 839,496 B 展平表示，指令 word
部分缩小约 729×。这是循环压缩证据，但尚未包含 layout descriptor 的
最终二进制存储开销；在 layout ROM 编码和 post-route 面积完成前，不能把
729×表述成完整控制存储节省。

## 当前不能给出的数字

- 不能将 control-only 720 LUT 与论文整机 24,184 LUT 相除；
- 不能将 randomized-F P1/U2 切片的 7,685 LUT 与论文完整 P2/U2 整机相除；
- 不能将 raw-Job randomized-F P2/U2 切片的 14,811 LUT 与论文完整整机相除；
- 不能用 Keccak primitive 的 U1/U2 比例代替完整 Keygen/Sign cycles；
- 不能把 1-BRAM 存储宏当成完整 μHBS 的 BRAM 总量；
- 不能把 4-BRAM SUBTREE cache-store 与其他 OOC 模块直接相加成整机面积；
- 不能把静态 P2 batch 的 2×窗口吞吐当成完整 Keygen/Sign speedup；
- 不能把 2,034,645 的历史分析下界称为 SLH-DSA 完整 RTL 总周期；完整实测为 8,800,104；
- 不能对论文 B0 的 14 个 cycle 点计算 speedup，因为它们当前都是 `NON_STRICT`；
- 不能声称冻结后扩展性优越，直到 held-out flow 在冻结 RTL 上通过。
