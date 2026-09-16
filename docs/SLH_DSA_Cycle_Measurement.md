# SLH-DSA 完整 RTL 周期测量 v1.0.0

更新：2026-09-16。

## 结论

FIPS 205 `SLH-DSA-SHAKE-128f` deterministic Sign 已在当前 P1/U2
微码 RTL 完整执行：

| 配置 | START-to-DONE | 100 MHz 延迟 | 输出 |
|---|---:|---:|---:|
| P1/U2，无 DMA | 15,167,426 cycles | 151.67426 ms（归一化） | 17,088 bytes |

100 MHz 延迟是按周期数归一化的数字，不是已收敛工作点。
xc7a200t-2 post-route 结果为 34,185 LUT / 23,289 FF / 7 RAMB36 /
0 DSP，100 MHz WNS 为 −1.050 ns；11.050 ns 临界路径对应约
90.50 MHz，在该估算频率上签名延迟约 167.60 ms。

测试加载 assembler 生成的 144-word 微程序，只提交一条
Job 和 message payload。主机不提交 FORS index、WOTS chain length、
TreeHash 决策、task 或 Hash descriptor。输出的 2,136 个 64-bit word
逐字匹配 NIST ACVP group 16 tc137，签名 SHA-256 为
`3f67c5420ba7d1b58c1149e260843dd658f0ff3049326ec246adb4697f8c6419`。

## 硬件计数闭合

```text
retired microinstructions                 221,811
sequencer HASH_LAYOUT requests            102,968
TreeHash internal parent hashes             1,969
total SHAKE calls                         104,937
sequencer absorbed/squeezed blocks        103,672
TreeHash parent permutations                1,969
total Keccak permutations                 105,641
TREE_PUSH requests                           2,178
data requests                                5,542
Scratchpad reads / writes          630,294 / 205,939
retired layout components                 835,169
```

TreeHash parent 在 adapter 内部发射，不经过 sequencer 的
`HASH_LAYOUT` 请求口，因此必须分别计数。两项相加后，
104,937 次 SHAKE 和 105,641 次 permutation 与独立 FIPS 205
模型清单完全一致。

## 与历史数字的区别

`2,034,645 cycles` 是过去把 FETCH/RUN、SHAKE stream 和无阻塞
输出相加得到的分析下界，没有计入完整 composer、AGU、
Scratchpad、TreeHash 和仲裁等待。它不是完整 RTL 实测。

`633,852 cycles` 是理想 P2/U2 置换下界：
`ceil(105641/2) × 12`。它假设两个 lane 始终满载，不包含数据搬运
与控制开销，也不是实测。

本次 15,167,426 cycles 是完整当前 P1/U2 路径的仿真计数，
包含 composer/AGU/Scratchpad/TreeHash/EMIT，但不包含外部输出背压。

## 复现

```bash
make export-slh-dsa-layouts rtl-slh-dsa-full-test
```

预期末行：

```text
PASS no-DMA complete SLH-DSA Sign cycles=15167426 hash=102968+1969 tree=2178 data=5542 inst=221811 scratch=630294/205939 blocks=103672+1969 components=835169
```

机器可读证据见
`manifests/experiments/slh_dsa_digest_parse_v0.1.0.json`。
