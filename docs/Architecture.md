# μHBS RTL Architecture

## 正式顶层

当前唯一完整综合顶层是：

```text
rtl/top/micro_hbs_slh_dsa_top.sv
```

它实现独立、无 DMA、无软件逐步 task 输入的
SLH-DSA-SHAKE-128f deterministic Sign。外部只在空闲期装载程序与
layout/component 镜像，然后提交一条 Job 和 payload-only 消息流；执行期间
FORS index、WOTS+ chain length、ADRS、树遍历与输出顺序均由 RTL 和微码产生。

```text
idle-only program/layout load
             |
single Job -> Job stream loader -> Microsequencer
                                      |
                     +----------------+----------------+
                     |                |                |
                    AGU        Layout composer     TreeHash
                     |                |                |
                     +---------- Scratchpad -----------+
                                      |
                                  SHAKE lane
                                      |
                              signature output stream
```

`rtl/top/micro_hbs_slh_dsa_job_stream_loader.sv` 只负责原子 Job admission、
固定字段锁存和消息写入；算法控制位于微码和通用执行器，不由 loader 内的
算法 FSM 实现。

## 正式综合闭包

完整 top 的 RTL 分为以下稳定模块：

- `sequencer/`：程序存储、PC、loop/call stack 和微指令发射；
- `composer/`：layout/component 表、输入拼装、base-w/checksum 与表达式；
- `agu/`、`memory/`：仿射地址生成、descriptor、Scratchpad 和数据操作；
- `hash_lane/`：Keccak-f[1600] 与 SHAKE256 stream；
- `treehash/`：动态最小栈、FIPS 205 parent 与微码适配器；
- `output/`：签名字节流输出；
- `top/`：Job loader 和唯一完整顶层。

综合源文件的权威清单是 Makefile 中的 `SLH_DSA_RTL`。Vivado 入口为
`experiments/synth_slh_dsa_top.tcl`；仿真入口为
`tb/integration/tb_micro_hbs_slh_dsa_top.sv`。

## 保留的跨算法基础模块

以下 RTL 不属于当前 SLH-DSA 综合闭包，但不是阶段性测试设计，因此保留：

- `micro_hbs_sha256_bounded` 与 `micro_hbs_lms_tree_parent`：LMS parent；
- `micro_hbs_randomized_hash`、`micro_hbs_xmss_tree_parent` 与
  `micro_hbs_xmss_tree_parent_context`：XMSS randomized-H parent；
- `micro_hbs_state_manager`：LMS/XMSS 状态索引的持久化握手边界。

LMS/XMSS 的完整算法目前仍以模型和微码验证为主；这些基础模块不能被描述为
完整 LMS/XMSS RTL top。

## 已删除的历史原型

早期开发曾为每个增量能力建立独立 `*_slice` 顶层，包括 control、data、
descriptor SHAKE、TreeHash、XMSS leaf/tree、静态或窗口化 P2 等。它们用于
证明局部接口或采集阶段性 PPA，不是最终架构的一部分。相关 stub、被否决的
W288 表达式实现、旧 cache/arbiter/TreeHash 变体以及对应 testbench、综合脚本
和 manifest 已删除，避免把局部实验误认为可交付设计；需要时可从 Git commit
`eb325ce` 恢复。

## 实现边界

- 当前 top 为 P1/U2；`UNROLL=2`，但只有一条有效 SHAKE lane。
- rate-wide composer、component 链式预取、连续源字请求重叠和受界
  lane-local Hash 反馈缓存后，完整签名实测 6,002,014 cycles（旧基线
  14,333,951 cycles），输出 17,088 bytes，
  与 NIST ACVP tc137 一致。
- 反馈缓存以 128-bit 寄存器保留最近一次 Hash 的前两个输出字，
  命中时绕过 Scratchpad；读请求从 630,294 降至 442,682，不新增 BRAM。
- 当前 post-route 为 34,874 LUT / 23,903 FF / 7 RAMB36 / 0 DSP、
  WNS −1.489 ns；约 87.04 MHz / 68.96 ms，尚未闭合 100 MHz。
- 当前固定程序容量 256 words，实际 Sign 程序 144 words；动态执行并不存储
  221,811 条展开指令。

## 独立性

μHBS 源码不依赖 HashFlow 或 SLH-Flow。`make check-standalone` 会将项目复制到
独立临时目录并运行验证；完整算法运行不需要外部 runtime 或逐 Hash 软件调度。
