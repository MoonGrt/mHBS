# SLH-DSA 完整 RTL 周期测量 v1.0.0

更新：2026-09-16。

## 结论

FIPS 205 `SLH-DSA-SHAKE-128f` deterministic Sign 已在当前 P1/U2
微码 RTL 完整执行：

| 配置 | START-to-DONE | 100 MHz 延迟 | 输出 |
|---|---:|---:|---:|
| P1/U2，无 DMA，rate-wide + component/source prefetch + Hash feedback | 6,002,014 cycles | 60.02014 ms（归一化） | 17,088 bytes |

100 MHz 延迟是按周期数归一化的数字，不是已收敛工作点。当前
xc7a200t-2 post-route 点为 34,874 LUT / 23,903 FF / 7 RAMB36 /
0 DSP、WNS −1.489 ns。11.489 ns 临界周期对应约 87.04 MHz 和
68.96 ms 估计延迟。相对优化前 33,985 LUT、WNS −0.406 ns 的点，
LUT×cycles 改善 57.032%，timing-aware LUT×time 改善 52.560%；
100 MHz 时序仍需后续闭合。

测试加载 assembler 生成的 144-word 微程序，只提交一条
Job 和 message payload。主机不提交 FORS index、WOTS chain length、
TreeHash 决策、task 或 Hash descriptor。输出的 2,136 个 64-bit word
逐字匹配 NIST ACVP group 16 tc137，签名 SHA-256 为
`3f67c5420ba7d1b58c1149e260843dd658f0ff3049326ec246adb4697f8c6419`。

## 硬件计数闭合

```text
retired microinstructions                 221,811
sequencer HASH requests            102,968
TreeHash internal parent hashes             1,969
total SHAKE calls                         104,937
sequencer absorbed/squeezed blocks        103,672
TreeHash parent permutations                1,969
total Keccak permutations                 105,641
TREE_PUSH requests                           2,178
data requests                                5,542
Scratchpad reads / writes          442,682 / 205,939
lane-local feedback read hits                187,612
all-engine Scratchpad requests               660,588
retired layout components                 835,169
```

TreeHash parent 在 adapter 内部发射，不经过 sequencer 的
`HASH` 请求口，因此必须分别计数。两项相加后，
104,937 次 SHAKE 和 105,641 次 permutation 与独立 FIPS 205
模型清单完全一致。

## RTL 状态驻留分布

完整 testbench 在每个 START-to-DONE 计数周期采样 sequencer 和
composer FSM。下表是互斥的 composer 分类，合计精确为
6,002,014 cycles：

| 类别 | 实测 cycles | 占比 | 含义 |
|---|---:|---:|---|
| 64-bit masked word append | 1,155,945 | 19.259% | 每周期最多向 1,088-bit rate buffer 放入 8 bytes |
| component 控制 | 1,144,073 | 19.061% | 首项 REQ/WAIT/PRODUCT + 每项 VALIDATE；后续 732,201 项全命中预取 |
| Scratchpad 源读 | 659,098 | 10.981% | 442,682 个 response wait；187,612 个前一轮 Hash 输出读取由本地反馈命中消除 |
| SHAKE block 发送+结果等待 | 1,648,197 | 27.461% | block-send 状态与 digest-wait |
| layout 查找/乘法/校验/启动 | 411,872 | 6.862% | 102,968 次 `HASH` × 4 周期 |
| digest 写回 | 205,939 | 3.431% | 写入单端口 Scratchpad |
| composer idle/其他引擎 | 776,890 | 12.944% | 数据操作、TreeHash、微码取指等 |

sequencer 的 `FETCH + RUN` 只有 443,622 cycles（7.391%）。理想
P1/U2 Keccak active-round 总量为 `105641×12 = 1,267,692 cycles`，
占总周期 21.119%。当前总周期为该置换下界的 4.735×，主要差距
已转为 SHAKE 服务等待、Scratchpad 同步读和每 component 校验，不是
微码程序存储或 Keccak 轮数。

优化顺序因此是：

1. 已完成：将 `S_EMIT_BYTE` 改为最多 64-bit/cycle 的 masked word append；
2. 已完成：链式预取下一 component，隐藏后续 732,201 项的
   `REQ/WAIT/PRODUCT`，严格命中率 100%，无 bubble；
3. 部分完成：连续 Scratchpad 源字 request 与当前字发射重叠，
   并用一条 128-bit lane-local feedback 缓存消除 187,612 次读取；
   下一步是成对/banked 读取与 digest 写回消除；
4. 以上闭合后再做 P2，否则第二条 Keccak lane 会大量空闲。

## 与历史数字的区别

`2,034,645 cycles` 是过去把 FETCH/RUN、SHAKE stream 和无阻塞
输出相加得到的分析下界，没有计入完整 composer、AGU、
Scratchpad、TreeHash 和仲裁等待。它不是完整 RTL 实测。

`633,852 cycles` 是理想 P2/U2 置换下界：
`ceil(105641/2) × 12`。它假设两个 lane 始终满载，不包含数据搬运
与控制开销，也不是实测。

本次 6,002,014 cycles 是完整当前 P1/U2 路径的仿真计数，
包含 composer/AGU/Scratchpad/TreeHash/OUTPUT，但不包含外部输出背压。
相对完整基线 14,333,951 cycles，四步优化累计减少 8,331,937 cycles
（58.127%）：rate-wide append 减少 5,533,847，component 预取减少
2,196,603，连续源字请求重叠减少 320,069，Hash 反馈缓存再减少
281,418。Hash、permutation、component 和签名结果计数均未改变；
Scratchpad 读取按设计从 630,294 减至 442,682，写入不变。

## 复现

```bash
make export-slh-dsa-layouts rtl-slh-dsa-full-test
```

预期末行：

```text
PASS no-DMA complete SLH-DSA Sign cycles=6002014 hash=102968+1969 tree=2178 data=5542 inst=221811 scratch=442682/205939 blocks=103672+1969 components=835169
```

在 PASS 行之前会输出 `PROFILE sequencer ...`、`PROFILE composer ...`
等状态驻留计数，用于重复上述分布。

机器可读证据见
`manifests/experiments/slh_dsa_digest_parse_v0.1.0.json`。
