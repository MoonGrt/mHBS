# Control-slice PPA checkpoint v0.1.0

## 结论

该检查点证明 8 个公开寄存器、6 层 loop stack、4 层 call stack、
受界动态 loop-bound 请求和 512×64-bit program store 可在 Artix-7 上完成
post-route，并满足 100 MHz 约束。它不是完整 μHBS，也不是论文性能点。

| 项目 | post-route 结果 |
|---|---:|
| Device | `xc7a200tffg1156-2` |
| Tool | Vivado 2025.2 |
| Slice LUT | 720 |
| Slice Register | 725 |
| RAMB36 | 1 |
| DSP | 0 |
| Clock constraint | 100 MHz |
| WNS | +0.921 ns |

同步 program store 使用 1 个 RAMB36。每条普通指令当前经过 `FETCH -> RUN`，因此该实现以稳定 BRAM 推断换取一个显式 fetch 周期；后续完整 datapath 的 cycle 消融必须把 fetch/prefetch 成本单列。

## 不可用于论文比较的原因

- `micro_hbs_hash_latency_stub` 只是用于控制握手测试的非密码占位模块；
- 尚无 Keccak/SHA-256 datapath、composer、Scratchpad、TreeHash、output 和 RTL state manager；
- 没有消费者的 Job payload 字段会被综合优化，当前结果未覆盖完整 Job latch 面积；
- 工具是 Vivado 2025.2，而论文报告点使用 Vivado 2018.3；
- 因此不能把本结果与论文报告的 24,184 LUT、13,659 FF 或 16.5 BRAM 相除来声称面积优势。

可复现结果见 `manifests/experiments/control_slice_p1_v0.1.0.json`。生成命令：

```bash
make synth-control
python3 experiments/collect_control_ppa.py
```

## 失败设计记录

program RAM 的首版异步读取/复位写法被综合为约 32k 个 FF，说明微码存储编码方式会完全支配控制面 PPA。该版本已由同步 block-RAM store 替代；失败点保留为设计决策证据，不进入最终 PPA 表。
