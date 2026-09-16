# Static P=2/U2 architecture decision

更新：2026-09-15。该实验验证固定双 lane 分配和尾批 lane mask；它不是
完整算法 P2/U2，也不与 Unified HBS Architecture 的整机结果直接比较。

## 功能结果

`micro_hbs_static_p2_shake_batch` 在一次 `batch_start` 接受时锁存整批输入，
随后按 `task 2k -> lane 0`、`task 2k+1 -> lane 1` 固定分配，不包含动态
scheduler，也没有逐 Hash/task 软件入口。

| batch | pair masks | 窗口周期 | lane active | lane idle | 相对单 lane 同延迟理想值 |
|---|---|---:|---|---|---:|
| 4 hashes | `11, 11` | 34 | 32 / 32 | 2 / 2 | 2.00× throughput |
| 3 hashes | `11, 01` | 34 | 32 / 16 | 2 / 18 | 1.50× throughput |

7 个 SHAKE256 KAT 全部匹配；输入在接受后立即改变不影响结果；count=0、
count>capacity 和 length>135 均在启动 lane 前拒绝。

## PPA 负结果

Artix-7 `xc7a200tffg1156-2`、Vivado 2025.2、100 MHz OOC post-route：

| 范围 | LUT | FF | BRAM/DSP | WNS |
|---|---:|---:|---:|---:|
| 完整 5-entry batch slice | 41,633 | 15,757 | 0 / 0 | +0.033 ns |
| 其中 batch control + 宽存储 | 24,420 | 9,345 | 0 / 0 | — |
| lane 0 | 8,158 | 3,206 | 0 / 0 | — |
| lane 1 | 9,059 | 3,206 | 0 / 0 | — |

固定映射在功能上可行，但 5×1088-bit 消息锁存和可变 pair 选择产生的
24,420 LUT / 9,345 FF 开销不可接受，且 WNS 只剩 +0.033 ns。该宽 batch
实现因此被拒绝为主数据路。

## 保留的设计边界

- 保留两个 U2 lane、静态偶/奇映射和 `11/01` lane mask；
- Job 仍只由软件提交一次，BUSY 期间无 task/Hash 输入；
- 消息 pair 必须由硬件 microsequencer + banked composer 以小窗口生成，不能
  通过软件逐项喂入，也不能预先摊成整个宽 batch 寄存器；
- 在当时尚未与 microsequencer 集成的这一历史决策点，Gate 5
  记为 `PARTIAL_STATIC_P2_U2`；后续 banked pair-window 证据已将
  状态推进为 `PARTIAL_WINDOWED_P2_U2`，再由 raw-Job randomized-F
  切片推进到当前的 `PARTIAL_RAW_JOB_P2_U2`。

机器可读证据：
`manifests/experiments/static_p2_u2_batch_v0.1.0.json`。

## Banked pair-window 后续点

`micro_hbs_windowed_p2_shake_slice` 把 512-word Microsequencer、两个
64-bit message bank、静态 `11/01` adapter 与两条真实 U2 SHAKE lane
连成一条 Job 垂直切片。消息和程序只能在 IDLE 预载；BUSY
时 message ready 必为 0，微码自主发出两个 pair 请求。偶数
4-hash 与奇数 3-hash 均通过 KAT，非法 `10` lane mask 在任何
bank read/lane dispatch 前 fail-closed。

Artix-7、Vivado 2025.2、100 MHz OOC post-route：

| 设计点 | message 容量 | LUT | FF | RAMB36 | WNS |
|---|---:|---:|---:|---:|---:|
| 拒绝的整批宽 latch | 5 | 41,633 | 15,757 | 0 | +0.033 ns |
| Microsequencer + 64-bit banked pair window | 6 | 20,204 | 11,294 | 3 | +0.368 ns |

新点虽多含 Microsequencer 和 3 个 BRAM，LUT/FF 仍分别降低
51.5%/28.3%。代价是每个 pair 需 18 个 64-bit read；两个 pair 的
Job BUSY window 为 84 cycles，其中 compose 为 38 cycles，显著慢于
宽 batch 的 34 cycles。

该点仍不是最终 composer：测试在 IDLE 阶段预装的是完整 SHAKE
消息，而非从 raw Job 数据、ADRS 和内部 node 现场组合；64-bit 路
也不满足 OTS 的单周期 rate-wide 边界。因此它只证明解耦、自主
双 lane 和面积收敛，不证明完整算法性能。机器可读证据见
`manifests/experiments/windowed_p2_u2_slice_v0.1.0.json`。

## Raw-Job randomized-F 后续点

`micro_hbs_randomized_f_p2_slice` 不再预载 SHAKE 消息；一条 Job
只提供 public seed、ADRS template、两个 node 和公开 chain bound。
微序列器用静态 `11/01` mask 发射，lane 内部组合 key/mask/core
预映像并完成本地链反馈。两 lane 各执行 3 步时，中间与
最终 node 逐步匹配 RFC 8391 oracle，各有 9 次内部 SHAKE。

Artix-7、Vivado 2025.2、100 MHz OOC post-route 为 14,811 LUT、
10,850 FF、1 RAMB36、0 DSP、WNS +0.788 ns。这一点比 banked
message-window 更接近最终原始数据语义，但只覆盖 WOTS+ randomized-F；
两 lane 共享一个 ADRS template/step index，但 lane 1 的 chain address
已在硬件内由 lane 0 加一派生，chain 2/3 逐步 oracle 通过。
尚未验证任意 chain pair 的微码寻址和完整并行 OTS。因此仍不能与 Unified HBS Architecture 整机 PPA
直接计算优越性。机器可读证据见
`manifests/experiments/randomized_f_p2_u2_raw_v0.1.0.json`。
