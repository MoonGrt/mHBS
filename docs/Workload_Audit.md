# B0 工作量与可比性审计

版本：v0.1.0；输入摘要：`970775289fa4071f3c27e1bc83f4a7e620727eb037ebbd4b50c0f11841b8da0c`

下表中的“最大满载 permutation”按论文 P=2/U=2、每 lane 每个 Keccak-p[1600] permutation 12 cycles 推得：`floor(cycles × 2 / 12)`。它只是报告周期能够容纳的计算容量上界，不是论文实际 Hash 或 permutation 计数。

| Family | Profile | Op | Cycles | 最大满载 permutation | 可比性 |
|---|---|---:|---:|---:|---|
| SPHINCS+ | n=128 fast | Keygen | 23,688 | 3,948 | NON_STRICT：final/draft 语义未核 |
| SPHINCS+ | n=128 fast | Sign | 537,636 | 89,606 | NON_STRICT：final/draft 语义未核 |
| SPHINCS+ | n=192 fast | Keygen | 34,687 | 5,781 | NON_STRICT：final/draft 语义未核 |
| SPHINCS+ | n=192 fast | Sign | 926,398 | 154,399 | NON_STRICT：final/draft 语义未核 |
| SPHINCS+ | n=256 fast | Keygen | 91,510 | 15,251 | NON_STRICT：final/draft 语义未核 |
| SPHINCS+ | n=256 fast | Sign | 1,929,154 | 321,525 | NON_STRICT：final/draft 语义未核 |
| LMS | h=10,w=2,SHAKE256 | Keygen | 3,808,440 | 634,740 | NON_STRICT：非 RFC 8554 SHA-256 点 |
| LMS | h=10,w=2,SHAKE256 | Sign mean | 3,572 | 595 | NON_STRICT：非 RFC 8554 SHA-256 点 |
| LMS | h=10,w=4,SHAKE256 | Keygen | 5,843,438 | 973,906 | NON_STRICT：非 RFC 8554 SHA-256 点 |
| LMS | h=10,w=4,SHAKE256 | Sign mean | 5,429 | 904 | NON_STRICT：非 RFC 8554 SHA-256 点 |
| XMSS | h=10,lg(w)=2,len=133 | Keygen | 7,829,494 | 1,304,915 | NON_STRICT：未注册研究 profile |
| XMSS | h=10,lg(w)=2,len=133 | Sign mean | 7,334 | 1,222 | NON_STRICT：未注册研究 profile |
| XMSS | h=10,lg(w)=4,len=67 | Keygen | 15,682,342 | 2,613,723 | NON_STRICT：结构匹配、trace 未核 |
| XMSS | h=10,lg(w)=4,len=67 | Sign mean | 14,549 | 2,424 | NON_STRICT：结构匹配、trace 未核 |

## 结论

当前 14 个 B0 数据点均未获准与最终 FIPS/RFC 实现计算 speedup。尤其是 README 中“SLH-DSA-128f 约 104,937 次 Hash”的示意数大于论文 128f Sign 在理想双 lane 下可容纳的 89,606 个单-permutation Hash；这说明两者的 Hash 定义、可消除调用或工作量边界至少有一项不同，不能直接相除。

## 最终 FIPS 205 SHAKE-128f Keygen 实测工作量

独立 oracle 与 NIST ACVP keyGen tc31 一致时，顶层高度 3 的 XMSS tree
包含 4,495 次 SHAKE 调用、4,527 次 Keccak permutation：280 PRF、4,200
F、8 次 `T_len` 和 7 次 H。`T_len` 的 608-byte 输入各需要 5 次
permutation，其余调用各需要 1 次。

在理想 P2/U2、每个 lane 每 12 cycles 完成一次 permutation 且无任何
开销的假设下，下界为 `ceil(4527/2)×12 = 27,168 cycles`。该下界已是
论文 SPHINCS+ SHAKE-128f Keygen 报告值 23,688 cycles 的 1.147×，所以
paper draft 与最终 FIPS 205 的工作量或计时边界必有未对齐项；该点继续
保持 `NON_STRICT`，不得计算 speedup。

## 最终 FIPS 205 SHAKE-128f Sign 实测工作量

NIST ACVP deterministic SigGen group/case `16/137` 的完整模型与微码均为：

```text
SHAKE calls             104,937
Keccak permutations     105,641
P=2/U=2 ideal floor     ceil(105641 / 2) × 12 = 633,852 cycles
signature               17,088 bytes
microprogram            144 words / 1,152 bytes
dynamic instructions    221,811
```

论文 draft SPHINCS+ SHAKE-128f Sign 报告 537,636 cycles。最终 FIPS 205
微码的纯置换下界已为该值的 1.179×；因此两者在 Hash 调用定义、草案语义
或计时边界厘清前，该项不得计算 speedup。

解除 `NON_STRICT` 需要获得或重建 B1 的逐 Hash trace，分别统计：

- PRF/消息摘要、OTS、FORS、Merkle/XMSS 和 root compression 的调用数；
- 每次调用的输入长度、吸收 block、挤出 block和 permutation 数；
- 跨阶段 forwarding 是否删除调用；
- Keygen/Sign 计时是否包含树预计算、缓存读取和签名输出。

自动复核命令：`python3 experiments/audit_workload.py`。
