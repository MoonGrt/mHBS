# μHBS Final Gate Report

更新：2026-09-16；结论：**IN PROGRESS / 不能形成优越性结论**。

| Gate | 状态 | 当前证据 | 未完成项 |
|---|---|---|---|
| 0 边界与工作量 | PASS_WITH_NON_STRICT_B0 | 标准/论文边界、报告值、自动审计已冻结 | B0 无精确 trace，14 点均不可直接算 speedup |
| 1 独立模型与微码 | PASS_LMS_KEYGEN_SLICE | RFC 8554 H10/W4 KAT；104 B 程序；1,100,799 Hash trace digest 匹配 | XMSS/SLH-DSA 属 Gate 4 |
| 2 单 lane RTL | PASS_COMPLETE_SLH_SIGN_P1_U2 | Microsequencer–动态循环–Scratchpad–composer–TreeHash–SHAKE–EMIT 完整连通；`HASH_LAYOUT` 支持 16/32-byte logical slot、136-byte SHAKE 输出、仿射/移位表达式、conditional ordered-pair、memory-range 和静态 relocation；SLH-DSA 使用原子 Job + payload-only message stream，无 DMA | 通用变长消息 descriptor selection；banked OTS-wide/P2 |
| 3 TreeHash | PARTIAL_DYNAMIC_MIN | 模型三模式一致；RTL `TREEHASH_MIN` h=10 root/auth 一致；版本化 tree descriptor 在同一 elaboration 选择 h=2/h=3 MIN 并精确产生 root/auth；SUBTREE/FULL 在 cache 未接入时 fail-closed；RFC 8554 86-byte/two-block LMS parent 独立向量通过；XMSS 和 FIPS 205 parent、fault/cancel recovery、warm cache 157 nodes/5,024 B 及 provider 两窗口10/10 hit 已验证 | LMS parent 接入完整 TreeHash；SUBTREE/FULL descriptor 接入真实 cache refill/miss 重算；cache-assisted Sign replay 与集成 BRAM–Sign-latency Pareto |
| 4 XMSS/SLH-DSA | PASS_COMPLETE_SLH_SIGN | XMSS h=10 通用 Keygen 流水版为 675,417,082 cycles；SLH-DSA tc137 无 DMA RTL 已用原始 144-word JSON 微程序完成 PRF_msg/H_msg、FORS 和 22 层 Hypertree/WOTS+，17,088-byte 签名逐字匹配，15,167,426 cycles | 其他 SLH-DSA profile、通用变长消息和 P2 replay |
| 5 P2/U2 | PARTIAL_RAW_JOB_P2_U2 | static P2 even/odd masks 与 7 KAT 通过；banked window 点 20,204 LUT/11,294 FF/3 RAMB36/WNS +0.368 ns；raw-Job randomized-F 从 seed/ADRS/2 nodes/bound 自主组合并本地反馈，lane 1 相邻 chain address 硬件派生，14,811 LUT/10,850 FF/1 RAMB36/WNS +0.788 ns | 任意 chain pair 微码寻址、OTS 单周期 rate-wide、完整算法 P2/U2 与 B1 消融 |
| 6 冻结后扩展 | PARTIAL_MODEL_FREEZE | 不改 ISA/interpreter/verifier/RTL，只新增 177-word XMSS Verify 微码；1,835 次 SHAKE 有序 trace 与 oracle 一致；1-bit 变异拒绝 | 完整 RTL 冻结快照与 replay；将 Job admission 的签名字段拆分改为内部 DMA byte-slice；再增 held-out profile |
| 7 状态安全 | PARTIAL_RTL_PROTOCOL | 模型与 RTL 均通过 persist-before-release、cancel/soft-reset burn、consume、回滚和耗尽；Scratchpad scrub 锁住外部端口并在 16 cycles 后逐字检查全零 | 真实原子 NVM 集成、掉电 fault injection、Hash lane/反馈/顶层敏感寄存器清零断言 |
| 8 PPA/论文 | PARTIAL_TIMING_FAIL | 完整 SLH-DSA P1/U2 post-route 为 34,185 LUT / 23,289 FF / 7 RAMB36 / 0 DSP；component 和 layout 目的地址分段将 WNS 从 −9.513 ns 改善到 −1.050 ns | 100 MHz 尚差 1.050 ns，下一路径是 bitfield adapter；需复用 parent SHAKE、P2 组合、B1–M 消融 |

## 已验证数值

```text
LMS program static words/bytes       13 / 104
LMS dynamic instructions             2,269,187
LMS SHA-256 calls                    1,100,799
RFC 8554 expected/actual root        32a58885...f1ad5a8e / equal
per-Hash rolling trace digest        47fcc30a...3bb93eb3 / equal
accepted Job commands                1
host writes while BUSY               0
external task/hash descriptors       0 / 0
control-only post-route              720 LUT / 725 FF / 1 RAMB36 / 0 DSP
control-only 100 MHz WNS             +0.921 ns
Keccak-f[1600] active cycles U1/U2   24 / 12
SHAKE256 RTL KAT lengths             0, 3, 135, 136, 200 bytes
Keccak OOC U1                        4,689 LUT / 3,213 FF / 24 cycles
Keccak OOC U2                        7,071 LUT / 3,211 FF / 12 cycles
Keccak U2/U1 LUT×cycle             0.754×
SHAKE feedback integration           1 Job / 3 Hash / 0 BUSY host writes
TreeHash-min h10                     1,024 leaves / 1,023 parent Hash
TreeHash-min h10 peak stack          10 stored + 1 working node
storage proxy full/min               64 KiB / 672 B; 16 / 1 RAMB36
state release before persist ack     impossible in RTL protocol test
cancel/soft-reset reserved indices   burned
Scratchpad scrub                      external port locked / all 16 words zero / 16 cycles
isolated parallel smoke              μHBS CI-core PASS / sibling 81 tests PASS
current standalone-copy CI           53 Python tests + model replays + all RTL targets PASS
XMSS official-reference signature    2,500 B / SHA256 d4382f3c...0127dbb0
XMSS Keygen program                   93 words / 744 B / loop depth 3
XMSS Keygen dynamic instructions      4,776,963
XMSS Keygen SHAKE/permutations        3,430,396 / 3,430,396
XMSS Keygen per-Hash trace digest     40562309...b9c5f53 / equal
XMSS Keygen autonomy                  1 Job / 0 BUSY host/task/hash writes
XMSS Sign program                     114 words / 912 B / loop depth 3
XMSS Sign dynamic instructions        4,779,374
XMSS Sign SHAKE/permutations          3,431,950 / 3,431,951
XMSS Sign per-Hash trace digest       b0df4558...b7c5b424 / equal
XMSS Sign result                      2,500 B / official KAT byte-equal
XMSS Verify program                   177 words / 1,416 B / loop depth 2
XMSS Verify SHAKE/permutations        1,835 / 1,836; ordered trace equal
XMSS Verify valid/mutated             root equal / one-bit mutation rejected
dynamic loop RTL                      bound=0 skip / bound=3 execute PASS
bounded AGU RTL                       base/base-reg/index×stride/span PASS
sequencer data register writeback    valid/index/value + bounds PASS
sequencer TREE_PUSH channel          backpressure/error/counter PASS
Scratchpad STORE/XOR RTL              3-word copy / 2-word XOR PASS
EMIT stream RTL                       keep/last/backpressure/error PASS
descriptor-driven data slice          LOAD/XOR/STORE/EMIT / one Job PASS
descriptor SHAKE composer              five component kinds / affine XOR / cross-rate resume PASS
XMSS JSON layout image                 10 layouts / 91 components / deterministic export
XMSS Sign PRF + H_msg RTL              1 Job / 2 Hash / 400 cycles / KAT-equal
XMSS generic component leaf RTL        1 Job / 3,346 Hash / 659,517 cycles / KAT-equal
XMSS generic h10 TreeHash RTL           1 Job / 1,024 leaves / 675,417,082 cycles / root+auth+EMIT equal
shared Scratchpad integration         data 32 / TreeHash 16 / EMIT 1 transactions
TREE_PUSH one-Job vertical slice      4 leaves / 3 SHAKE parents / h2 root+auth PASS
XMSS randomized-H TreeHash slice      RFC8391 ADRS/root/auth PASS
XMSS WOTS+ leaf RTL                    67 PRF_keygen / 1,005 F / 66 L-tree H
XMSS WOTS+ SHAKE per leaf              3,346 / oracle-equal leaf
WOTS-to-TreeHash h10 Job                1024 HASH_LAYOUT / 1024 TREE_PUSH / root+10 auth PASS
WOTS-to-TreeHash h10 cycles             57,204,676
WOTS-to-TreeHash Scratchpad             4-word reused leaf buffer / 8,192 total transactions
SLH-DSA SHAKE-n16 parent RTL           80-byte input / 1 SHAKE / 1 permutation / 3 vectors PASS
TreeHash abort recovery                scratch/parent fault + cancel / next tree PASS without reset
offline data lowering                  v1 + XMSS multi-register v2 side table / 7 tests PASS
descriptor-v2 data slice               R5+R7 -> R6+R3 / STORE->EMIT / one Job PASS
descriptor-v2 negative paths           missing binding 0x080a / affine OOB 0x0312 / no leaked output
bounded SHA-256 RTL                     0/3/55/56/86/119-byte vectors / 120-byte reject PASS
RFC8554 LMS parent RTL                  86 bytes / 2 blocks / 4 independent vectors PASS
dynamic TreeHash descriptor             same RTL h2/h3 MIN root+auth PASS
dynamic TreeHash rejected modes         SUBTREE/FULL 0x0a01 / node width 0x0a02
base-w/checksum RTL                   XMSS digest + all-0/all-1 PASS
randomized-hash RTL                   F/H oracle match / 3 and 4 SHAKE calls
randomized-F integrated RTL           1 Job / dynamic bound 3 / 9 SHAKE
integrated Scratchpad traffic         36 reads / 12 writes / result equal
integrated slice latency              260 cycles; ideal Keccak-round floor 108
randomized-F P1/U2 post-route         7,685 LUT / 6,039 FF / 2 RAMB36 / 0 DSP
randomized-F P1/U2 100 MHz WNS        +0.568 ns
SLH-DSA SHAKE-128f Keygen program     12 words / 96 B / loop depth 3
SLH-DSA Keygen dynamic instructions   9,275
SLH-DSA Keygen SHAKE/permutations     4,495 / 4,527
SLH-DSA Keygen result                 NIST ACVP tc31 root equal
SLH-DSA Keygen trace digest           bdd9eeb4...11ad223 / equal
SLH-DSA deterministic Sign oracle     NIST ACVP tc137 / 17,088 B
SLH-DSA Sign SHAKE/permutations       104,937 / 105,641
SLH-DSA Sign signature SHA256         3f67c542...f8c6419 / equal
SLH-DSA Sign verify/mutation           accept / reject
SLH-DSA Sign program                   144 words / 1,152 B / call depth 2
SLH-DSA Sign dynamic instructions      221,811
SLH-DSA Sign ordered trace digest      c4a46c56...63e82e7 / equal
SLH-DSA Sign autonomy                  1 Job / 0 host task/hash inputs
SLH-DSA RTL complete FORS              33 trees / 3,696 B output / compressed root equal
SLH-DSA RTL complete Sign output       17,088 B / 2,136 words / every word equal
SLH-DSA RTL complete Sign cycles       15,167,426 / 151.67426 ms normalized at 100 MHz
SLH-DSA RTL SHAKE accounting           102,968 sequencer + 1,969 TreeHash = 104,937
SLH-DSA RTL permutation accounting     103,672 sequencer + 1,969 TreeHash = 105,641
SLH-DSA RTL micro/data/tree traffic    221,811 instructions / 5,542 data / 2,178 TREE_PUSH
SLH-DSA RTL scratch/component traffic  630,294 reads / 205,939 writes / 835,169 components
SLH-DSA complete top post-route        34,185 LUT / 23,289 FF / 7 RAMB36 / 0 DSP
SLH-DSA complete top 100 MHz timing    WNS -1.050 ns / 11.050 ns critical path / FAIL
SLH-DSA complete top critical path     layout descriptor -> block-buffer enable / 29 levels
U2 SHAKE stream cycle calibration     1/2/5 blocks -> 15/30/75 cycles
64-bit output cycle calibration       1/2/3 words -> 3/6/9 cycles, no stall
SLH-DSA Keygen accounted lower bound  86,461 cycles / 0.86461 ms at 100 MHz
SLH-DSA Sign old analytical lower bound 2,034,645 cycles / superseded by complete RTL replay
SLH-DSA Sign ideal P2/U2 round floor  633,852 cycles (not complete P2 replay)
layout expression W288                 10,929 LUT / 6,307 FF / WNS -7.749 ns (rejected)
layout expression W32                  993 LUT / 922 FF / WNS +0.253 ns
tc137 FORS digit unpack                33 x 6-bit exact / post-synth 0 cells
TreeHash cache h3 functional           FULL 15 / SUBTREE(h>=2) 3 nodes; root/auth equal
TreeHash auth provider h3              FULL 3/0/0; SUBTREE 1/2/2 hit/miss/recompute
TreeHash cache h10 FULL store          3,778 LUT / 2,118 FF / 14 RAMB36 / WNS +2.529 ns
TreeHash cache h10 SUBTREE(h>=4)        591 LUT / 198 FF / 4 RAMB36 / WNS +5.296 ns
TreeHash warm cache h10/w4              1,244 LUT / 691 FF / 4 RAMB36 / WNS +0.556 ns
TreeHash warm cache capacity            127 upper + 30 lower / 157 nodes / 5,024 B
TreeHash warm auth integration          target 5/21: 10/10 hits / 0 recompute / 1 start each
XMSS upper-only SUBTREE cold floor      51,788 SHAKE / 310,740 ideal P2/U2 cycles
XMSS FULL/warm-active Sign core floor   1,554 SHAKE / 9,336 ideal P2/U2 cycles
static P2/U2 even batch                4 hashes / 34 cycles / masks 11,11
static P2/U2 odd batch                 3 hashes / 34 cycles / masks 11,01
static P2/U2 wide-batch post-route     41,633 LUT / 15,757 FF / WNS +0.033 ns (rejected path)
windowed P2/U2 integrated slice        20,204 LUT / 11,294 FF / 3 RAMB36 / WNS +0.368 ns
windowed P2/U2 4-hash Job              84 cycles / 38 compose cycles / 1 Job
raw-Job randomized-F P2/U2             14,811 LUT / 10,850 FF / 1 RAMB36 / WNS +0.788 ns
raw-Job P2/tail internal SHAKE         9/9 and 9/0; 0 BUSY host Hash inputs
raw-Job P2 lane accounting             each 150 active / 26 idle cycles
```

## 当前论文边界

这些结果证明循环压缩表达能力和自主执行模型，不证明 μHBS 已比 Unified HBS Architecture 更快、更小或更省 BRAM。只有 Gate 5/6/8 和 B1 同源对照完成后才能判断论文 Go/No-Go。
