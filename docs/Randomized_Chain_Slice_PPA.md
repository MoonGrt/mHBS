# Randomized-F vertical-slice PPA v0.1.0

## 结论

自主 `Microsequencer -> dynamic bound -> Scratchpad -> randomized F ->
SHAKE256/Keccak U2 -> Scratchpad writeback` 垂直切片在 Artix-7 上完成
post-route，并满足 100 MHz。

| 项目 | post-route 结果 |
|---|---:|
| Device | `xc7a200tffg1156-2` |
| Tool | Vivado 2025.2 |
| P/U | P1/U2 |
| Slice LUT | 7,685 |
| Slice Register | 6,039 |
| RAMB36 | 2 |
| DSP | 0 |
| Clock constraint | 100 MHz |
| WNS | +0.568 ns |

两个 RAMB36 分别是 512×64-bit program store 和 32×64-bit
Scratchpad。该切片含真实 SHAKE256 数据路，但只实现一个 randomized-F
layout，不是完整 XMSS/LMS/SLH-DSA。

## 同工具局部诊断

同一器件、工具和 100 MHz OOC 流程下，U2 Keccak primitive 为 7,071
LUT、3,211 FF、WNS +0.389 ns。垂直切片相对它增加 614 LUT 和 2,828
FF，并增加 2 RAMB36；由于跨层综合优化，差值只是局部诊断而不是可加的
模块面积分解。

结果表明：microsequencer、地址绑定与串行 Scratchpad 控制没有造成大的
额外 LUT，但 seed/address/node/key/mask 的宽状态寄存器显著推高 FF，宽
当前重跑 WNS 为 +0.568 ns，与单独 Keccak 点的路由差异不可作加和比较，且仍满足 100 MHz；这种 OOC
布线差异不能当成模块可加的时序结论。进入 P2 仍需优先把
composer 状态映射为 bank/rate buffer，并加入明确的流水边界。

## 性能边界

功能测试的三步链为 260 cycles，内部 9 次 U2 permutation 的 active-round
下界为 108 cycles。当前 2.41× 放大包含 48 次串行 64-bit Scratchpad
访问和控制握手，证明该切片适合正确性集成，不适合作为最终 OTS 性能点。

本结果不可与论文报告的 24,184 LUT 或算法 cycles 相除来声称优越性：
算法范围、P、composer/HIL、存储语义、工具版本和顶层约束均未对齐。OOC
端口与 clock source 缺少顶层位置，因此 WNS 只表示当前局部流程满足约束。

机器可读结果见
`manifests/experiments/randomized_chain_p1u2_v0.1.0.json`。生成命令：

```bash
make synth-randomized-chain
make collect-randomized-chain-ppa
```
