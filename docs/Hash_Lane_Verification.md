# Hash lane verification v0.1.0

## 已实现边界

- `micro_hbs_keccak_f1600`: Keccak-f[1600] 24 轮迭代 lane，综合参数 `UNROLL=1/2`；
- `micro_hbs_shake256_single_block`: 0--135 byte 单最终块、32-byte 输出，用于 rate-wide 快路原型；
- `micro_hbs_shake256_stream`: 内部多块吸收接口，非最终块必须为完整 136-byte rate，最后块必须为 0--135 byte。

stream 接口是 composer 到 hash lane 的内部接口，不是 top-level host 接口。它不会改变“一条 Job、BUSY 期间软件零任务输入”的系统契约。

## 验证点

| 测试 | Oracle / 期望 | 结果 |
|---|---|---|
| Keccak-f[1600] 零状态 | canonical 25-lane permutation result | U1/U2 均逐 lane 一致 |
| permutation latency | 24 rounds | U1=24、U2=12 active cycles |
| SHAKE256 empty / `abc` | Python `hashlib.shake_256`, 32 bytes | 一致 |
| SHAKE256 135 bytes | rate 末字节同时承载 suffix/final bit | 一致 |
| SHAKE256 136 bytes | 1 full block + empty final block | 一致 |
| SHAKE256 200 bytes | 1 full block + 64-byte final block | 一致 |
| 非最终短块 | fail-closed contract | 拒绝，且不产生 digest |
| 3-step feedback chain | `hashlib.shake_256` 递归 oracle | 1 Job、3 Hash、结果一致 |
| 任务接受后修改外部 input bus | Job latch contract | 不影响结果 |
| 不支持的 layout 99 | 执行期 fail-closed | `error_code=0x0101` |
| TreeHash h=3 | Python SHAKE256 tree oracle | root + 3 auth nodes 一致 |
| TreeHash h=10 | Python SHAKE256 tree oracle | root + 10 auth nodes 一致，1,023 次父 Hash |
| warm TreeHash auth provider | target 5/21，单次 start | 各 10/10 cache hit、0 recompute；2-cycle 输出背压不丢节点 |
| randomized F | RFC 8391 oracle，`pub_seed=40..5f` | 输出一致，3 次 SHAKE |
| randomized H | RFC 8391 oracle，同上 | 输出一致，4 次 SHAKE |
| base-w/checksum | XMSS KAT message digest | 67 digits 一致，chain sum=495 |
| SLH-DSA digit unpack | ACVP tc137 digest | 33 个 6-bit FORS index 全部一致，跨字节/消费边界通过 |
| layout expression | FORS subtree/address arithmetic | 32-bit engine 结果一致；BUSY image write、非法/未配置/溢出 token 均拒绝 |
| Scratchpad-backed randomized-F chain | RFC 8391 oracle，动态 bound=3 | 1 Job、3 layout 请求、9 SHAKE、结果一致 |
| static P2/U2 batch | 7 个 SHAKE256 KAT | even masks `11/11`、odd `11/01`；输入接受后外部 bus mutation 不影响结果 |
| windowed P2/U2 slice | 7 个 SHAKE256 KAT + invalid mask | 1 Job 自主发射 2 pairs；BUSY write 拒绝；`10` 在 bank/lane 前拒绝 |
| raw-Job randomized-F P2/U2 | RFC 8391 chain 2/3 WOTS+ oracle | lane 1 相邻地址硬件派生；`11/01`；9/9 与 9/0 SHAKE；中间/最终 node 一致 |
| BUSY 期间 Scratchpad host port | 自主性契约 | 不暴露 ready；host control writes=0 |
| 动态 bound 地址越界 | fail-closed contract | `error_code=0x0201`，不挂起 |

命令：

```bash
make rtl-keccak-test rtl-shake-test rtl-shake-stream-test \
     rtl-shake-chain-test rtl-treehash-test rtl-treehash-h10-test \
     rtl-treehash-cache-test rtl-treehash-auth-provider-test \
     rtl-treehash-warm-cache-test rtl-treehash-warm-auth-test \
     rtl-randomized-hash-test rtl-base-w-test \
     rtl-digit-unpack-test rtl-layout-expr-test rtl-static-p2-test \
     rtl-windowed-p2-test \
     rtl-randomized-f-p2-test \
     rtl-randomized-chain-test rtl-slh-dsa-full-test
```

## 尚未证明

目前已证明 microsequencer–动态循环–单端口 Scratchpad–layout composer–randomized F–SHAKE lane–写回的最小端到端连接，并单独验证 randomized H、base-w/checksum、32-bit layout expression、静态 digest unpack 和 static P2/U2 capability。3 步链从一条 Job 自主展开，读取 36 个、写入 12 个 64-bit word，并完成 9 次内部 SHAKE。2026-09-18后，完整SLH-DSA-128f Sign也已改为29-token静态水平微码路径，tc137及5组非tc137消息全部通过；Keygen/Verify、XMSS/LMS仍属后续扩展。

该功能切片的 `START` 到 `DONE` 为 260 cycles，而 9 次 U2 Keccak
permutation 的理想 active-round 下界是 108 cycles。差额来自 SHAKE 状态
握手、48 次串行 Scratchpad 访问、微指令 fetch/loop 和写回；该结果明确
说明当前单端口适配器只用于正确性集成，不能用来主张相对论文的性能收益。
机器可读证据见 `manifests/experiments/randomized_chain_slice_v0.1.0.json`。

P2/U2 raw-Job 切片进一步去掉了外部预组 SHAKE 消息。两条
lane 以共享 step index 并行运行三步，各完成 9 次 SHAKE；
Job 窗口内每条 lane 记录 150 active / 26 idle cycles。`01` 尾批中
lane 1 为 0 active / 176 idle cycles。Artix-7 100 MHz post-route 为
14,811 LUT、10,850 FF、1 RAMB36、0 DSP、WNS +0.788 ns。lane 1
的 chain address 由 lane 0 的 word 5 加一派生，chain 2/3 的三步
中间值均通过；它未包含任意 chain pair 的微码寻址和完整 OTS，
因此仍是工程切片。

## Composer 宽度决策

288-bit 通用 postfix expression engine 的 OOC post-route 为 10,929 LUT、
6,307 FF、WNS −7.749 ns；32-bit ADRS/index engine 为 993 LUT、922 FF、
WNS +0.253 ns。故全宽通用 barrel shifter 被拒绝，摘要 digit 改用静态
MSB-first wiring，后者被综合为空网表（0 LUT/0 FF）。详细证据见
`docs/Layout_Expression_Tradeoff.md`。

## Static P2/U2 capability

固定 even/odd lane 映射在 4-hash even batch 中以 34 cycles 完成，窗口吞吐
相对同延迟单 lane 为 2×；3-hash odd batch 使用 `11/01` mask，同指标为
1.5×。但 5-entry 宽 batch 的 post-route 为 41,633 LUT、15,757 FF、
WNS +0.033 ns，其中 batch control/宽存储占 24,420 LUT、9,345 FF。
因此只保留静态 lane 分配，消息改由 microsequencer 与 banked composer
在硬件内部按小窗口生成。见 `docs/Static_P2_Tradeoff.md`。

## U1/U2 局部 PPA 消融

Artix-7 `xc7a200tffg1156-2`、Vivado 2025.2、100 MHz、out-of-context post-route：

| 点 | LUT | FF | BRAM/DSP | WNS | permutation active cycles |
|---|---:|---:|---:|---:|---:|
| U1 | 4,689 | 3,213 | 0 / 0 | +1.692 ns | 24 |
| U2 | 7,071 | 3,211 | 0 / 0 | +0.389 ns | 12 |

U2/U1 的 LUT 为 1.508×，LUT×cycle 为 0.754×，即固定 100 MHz 下局部 LUT–置换周期积改善约 24.6%。按对照论文的 7-series equivalent-slice 公式（此点 BRAM/DSP 为零），equivalent-slice×cycle 为 0.689×。

该 OOC 流程的 1,600-bit state ports 没有顶层 partition pin 位置，clock source 也没有顶层位置；因此 WNS 仅用于确认两点在相同局部流程下通过 100 MHz，不解读为整机 Fmax。机器可读结果见 `manifests/experiments/keccak_u1_u2_v0.1.0.json`。
