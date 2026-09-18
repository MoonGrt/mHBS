# 静态水平微码与等价双 Hash lane

## 2026-09-18 产品微码实现

当前生产 top 已不再由22状态算法FSM决定任务顺序。静态微码ROM通过
`micro_hbs_static_task_sequencer` 发出两个48-bit lane command，任务
materializer只执行当前recipe、结果写回和流输出。产品镜像为29个
128-bit token和13个128-bit template，展开为5,811个水平任务字。

该镜像按SLH-DSA-128f参数结构编译，不含消息、密钥或tc137实际
Hash时长。WOTS链长、FORS选中叶和最终XMSS层的选中路径均由
RTL在运行时解析。旧189-token镜像仅保留为tc137 Hash调度投影，
不再作为产品控制镜像。

| 指标 | 实测 |
|---|---:|
| tc137完整签名周期 | **757,448** |
| Hash context / Keccak permutation | **10,680 / 105,641** |
| post-synth | **22,923 LUT / 8,319 FF / 0 BRAM / 0 DSP** |
| post-route | **22,647 LUT / 8,315 FF / 0 BRAM / 0 DSP** |
| post-route 100 MHz | **WNS +0.422 ns / TNS 0** |
| post-route Equivalent Slice | **6,701.13** |

同一ROM已通过1、8、31、64和87-byte消息的完整签名对比；两条
物理lane互换后tc137的结果、周期和计数不变。

## 历史：tc137 Hash调度投影

SLH-DSA-SHAKE-128f Sign 的现有完整微码执行轨迹可拆成 6,105 个通用
Hash context，并静态调度到两条完全等价的 U2 Keccak lane。调度保持
105,641 次 permutation 和 tc137 签名摘要不变。

这不是把 SLH-DSA 控制写死进 RTL。RTL 只理解四类存储 token：

- `SINGLE`：发射一个水平模板；
- `RUN`：按两个 context 步长重复同一模板；
- `LOOP`：回放一段 token，并给有效 lane 的 context 编号加固定偏移；
- `HALT`：等待记分牌清空并结束。

FORS、XMSS、WOTS 等含义仍由离线编译器、context 表和模板决定。两条
Hash lane 接口与能力完全相同；RTL 中没有 TreeHash 专用 lane。

## tc137 编译结果

| 项目 | 数值 |
|---|---:|
| Hash context | 6,105 |
| 原始 128-bit 水平字 | 5,817 |
| 第一级 `RUN` 后 token | 2,812（含 HALT） |
| `RUN` + 外层 `LOOP` 后 token | **189（含 HALT）** |
| 水平模板 | **33 × 128 bit** |
| token 镜像 | 1,512 bytes |
| 模板镜像 | 528 bytes |
| 合计 | **2,040 bytes** |
| 相对原始水平程序 | **2.19%** |

压缩器会将 token 展开回全部 5,817 个 128-bit 字并逐位比较；不一致时
编译失败。RTL 也已加载实际 189-token/33-template 镜像并逐条重放全部
5,816 个 `ISSUE` 字。带 event wait/consume/track 的字不会被 `RUN` 合并。

## Hash-only 调度投影

| 指标 | 数值 |
|---|---:|
| U2 Hash active makespan | 667,416 cycles |
| 含直接 lane 边界 | 673,187 cycles |
| lane utilization | 94.97% |
| 最大同时存活 event | 1 |

以上仍是压缩 token 执行器的 Hash 服务投影，不能把 673,187 直接当作
端到端周期。完整签名 RTL 的实测见下一节。

## 完整 Sign RTL

`micro_hbs_horizontal_slh_dsa_sign_top` 已接入两条完全等价的 U2 lane、
多 block SHAKE context、本地树值存储和完整签名 RAM。tc137 的 2,136 个
64-bit 输出字全部逐字比对通过：

| 指标 | 实测 |
|---|---:|
| 完整签名周期 | **704,060** |
| Keccak permutation | **105,641** |
| 物理 lane context | 10,680 |
| lane 0 active | 658,982 cycles |
| lane 1 active | 621,622 cycles |
| 双 lane 平均有效利用率 | **90.94%** |
| 相对 633,852 Hash 下界的端到端开销 | **11.08%** |

FORS secret/auth path、FORS roots、全部 22 层 XMSS、WOTS 签名字和认证路径
均由新顶层生成；没有实例化旧 `micro_hbs_slh_dsa_top`。树节点、FORS roots
和 WOTS endpoints 保存在小型 parity-banked LUTRAM 中，17,088-byte 签名
保存在三路 banked BRAM 中。

需要区分两层控制：189-token/33-template 压缩执行器已经能完整重放 Hash
调度；当前通过 tc137 的端到端 materializer 使用静态 phase/counter 控制来
生成相同类别的 lane context。把 materializer 的 phase 控制改为直接消费
189-token context index，仍是后续的“通用微码路径”工作，不能把两者写成
已经连接。

### `xc7a200tffg1156-3` 完整 Sign PPA

相同 RTL、U2 展开和 10.000 ns 约束的 out-of-context post-route 结果如下：

| 层级 | LUT | FF | RAMB18 | DSP |
|---|---:|---:|---:|---:|
| 顶层控制/包装 | 6,083 | 4,792 | 1 | 0 |
| Hash lane 0 | 12,846 | 5,293 | 0 | 0 |
| Hash lane 1 | 13,928 | 5,154 | 0 | 0 |
| node store | 1,415 | 0 | 0 | 0 |
| root store | 526 | 0 | 0 | 0 |
| endpoint store | 826 | 0 | 0 | 0 |
| signature RAM | 1,291 | 570 | 12 | 0 |
| 总计 | **36,898** | **15,809** | **13** | **0** |

13 RAMB18 等价于 6.5 RAMB36。初次路由 WNS 为 -0.035 ns；post-route
`AggressiveExplore` 将一个关键路径 LUT 变换后，最终 WNS 为 **+0.035 ns**、
TNS 为 0，无未路由 net，约等于 **100.35 MHz**。在 100 MHz 下完整
Sign 延迟为 **7.0406 ms**，`LUT × cycles` 为 25,978,405,880。

该数字是 OOC 内部时序结果；报告仍提示顶层时钟端口没有
`HD.CLK_SRC`，所以接入具体板卡后还需要跑一次完整 top-level signoff。
当前 LUT 仍高于 24,184-LUT 文章对照点，因此 Wave 5 面积合并不能标记完成。

## 256-token 双 lane 核心 PPA

器件为 `xc7k325tffg900-2`，post-route，目标 100 MHz：

| 层级 | LUT | FF | RAMB36 | DSP |
|---|---:|---:|---:|---:|
| lane 0 | 8,689 | 4,729 | 0 | 0 |
| lane 1 | 8,697 | 4,729 | 0 | 0 |
| token sequencer | 1,872 | 107 | 1 | 0 |
| 合计 | **19,255** | **9,565** | **1** | **0** |

WNS 为 **+1.193 ns**。模板表占 104 个 LUTRAM；token 镜像映射为一个
256×64 RAMB36。未压缩 6,144×128 控制 ROM 的对照核心为
19,086 LUT / 9,518 FF / 32 RAMB36 / WNS +1.453 ns。压缩使控制 BRAM
从 32 降到 1，代价是 169 LUT、47 FF 和 0.260 ns WNS。

## 尚未完成

1. 让端到端 context materializer 直接接受 189-token 执行器的 context index；
2. 将 token、模板、context 表改为 `$readmemh` 静态 ROM，并移除配置端口；
3. 将 PRF_msg/H_msg 的消息流扩展到 87 bytes 以上；
4. 对不同消息、Keygen/Verify 以及 XMSS/LMS 重新编译和验证调度镜像。
5. 合并重复的 lane 外围与宽控制网，将完整 Sign 面积压到 30k LUT 以下。
