# μHBS Micro-ISA v0.1

## 固定编码

每条指令 64 bit：

```text
63          56 55          48 47          40 39          32 31           0
+--------------+--------------+--------------+--------------+-------------+
| opcode (8)   | flags (8)    | rd (8)       | rs (8)       | imm (32)    |
+--------------+--------------+--------------+--------------+-------------+
```

所有保留位必须为零。只实现 R0–R7 八个公开控制/计数寄存器，不构成通用寄存器文件；密码字节保存在有边界的 Scratchpad。

| Opcode | Code | 语义 |
|---|---:|---|
| NOP | 0x00 | 无副作用 |
| MOVI | 0x01 | `R[rd] = imm` |
| ADDI | 0x02 | `R[rd] = R[rs] + sext(imm)`，溢出报错 |
| HASH_LAYOUT | 0x03 | 由 layout `imm[15:0]` 组合并发往 `lane_mask=flags[1:0]`；同时锁存 `R[rs]` 的值供 layout 做地址/索引绑定，`rd` 是受 layout 解释的目标槽 |
| LOOP_SETUP | 0x04 | 默认压入 `{counter=R[rs], bound=imm, body_pc=pc+1}`；`flags[0]=1` 时从受界 `Scratchpad[R[rd]]` 读取 8-bit bound，`imm` 是 bound=0 时的镜像内 exit PC |
| LOOP_END | 0x05 | 计数递增并回跳；结束时弹栈 |
| CALL | 0x06 | 压入返回地址并跳 `imm` |
| RET | 0x07 | 弹出返回地址 |
| LOAD | 0x08 | 按 `imm` 选择静态 load/post-process descriptor；支持将 Job 数据或 Scratchpad 数据载入受界寄存器/槽位 |
| STORE | 0x09 | 按 `imm` 选择静态 move descriptor，在有界 Scratchpad 槽位间复制 |
| XOR | 0x0a | 按 `imm` 选择静态 XOR descriptor，对两个等长字节串异或并写入受界目标 |
| TREE_PUSH | 0x0b | 节点入栈并执行等高 reduce |
| EMIT | 0x0c | `imm[31:16]` 选择静态输出 descriptor；物理起点为 descriptor base + `rd+imm[15:0]`，`flags[0]=1` 时再加 `R[rs]` |
| HALT | 0x0d | 成功结束 Job |
| FAIL | 0x0e | 以 `imm` 错误码终止 |
| WAIT | 0x0f | 等待 `lane_mask` 完成 |
| BARRIER | 0x10 | 等待全部已发射 lane 完成 |
| JUMP | 0x11 | 跳到镜像内直接地址 `imm` |

`HASH_LAYOUT` 的 lane mask 必须是 `01/10/11`；为保持单 lane 源程序简洁，assembler 仅在源指令完全省略 `flags` 时默认编码为 `01`。显式 `flags=0` 不会被改写，并由静态 verifier 拒绝。

当前 RTL Microsequencer 已为 `LOAD/STORE/XOR/EMIT` 实现统一的内部请求/响应控制、背压、错误传播和可选的受界寄存器写回；`TREE_PUSH` 也已有独立内部请求/响应通道。128-bit data descriptor、串行 AGU、Scratchpad `LOAD/STORE/XOR`、`EMIT` 输出流和固定优先级 Scratchpad 仲裁已在同一条 Job 数据切片中连通。进一步的组合切片已让 data、EMIT 和 TreeHash 共享同一个单端口 Scratchpad，完成 49 次可归属交易。离线 lowering 已统一 logical slot 与 64-bit word；RTL v2 切片已消费 multi-register binding side table。`HASH_LAYOUT` 的组件模式现可解释 JSON lowering 后的 literal/zero/register、双寄存器 affine memory 与 XOR；XMSS layout 0--7 已用该通路完成整棵 h=10 Keygen 树、自主 root 写回和 EMIT，layout 9--10 已执行 Sign PRF/H_msg。layout `0x0200` 融合 capability 现保留为 57,204,676-cycle 对照点；地址时序流水后的通用路径为 675,417,082 cycles（含 Job seed 自主装载），说明下一步需要 rate-wide/banked 组件输入。expression/context、layout-8 pipeline temp 和 OTS-wide P2/U2 尚未完成。

`HASH_LAYOUT`、`TREE_PUSH` 等操作的展开语义由版本化 layout manifest 定义；不得依据算法 ID 进入隐藏 sub-FSM。

为覆盖宽树地址与认证路径左右次序，layout manifest 允许受限、无副作用的
整数表达式（寄存器/内存/TreeHash context 上的加、减、乘、移位、按位运算）
以及 `ordered_pair`。这些表达式只构造当前一次 Hash 的 ADRS 与输入顺序，
不得发起 Hash、循环或隐式任务。小树 layout 可声明
`restart_on_complete`，每次完成后显式释放 TreeHash context，供 FORS/XMSS
认证子树复用；每个内部 Hash 仍进入有序 trace。

Layout composer 的通用能力包括固定宽度 word-array 编码、有界存储引用、
等长字节串 XOR 和有界的 hash pipeline 临时值。这些能力由 layout
显式描述，不引入 XMSS 专用 opcode；每个 pipeline 内部 Hash 仍单独记入 trace
和工作量计数。

当前 RTL layout `0x0100` 将 `R[rs]` 绑定到 32-byte address 的 word 6，
从 Scratchpad 的 `rd..rd+3` 读取并写回 randomized-F node。它是版本化
layout capability，而不是 XMSS task opcode；非法 layout、lane mask 或
Scratchpad 地址均 fail closed。

WOTS 共用后处理以静态 load descriptor 表达 `base_w + checksum`，输出每个
digit 到受界 Scratchpad 槽位。动态循环只能从这些槽位读取公开的、
8-bit 上界；Job 不包含由软件计算的 chain length。

## 静态 verifier

装载前必须证明：opcode/flags 合法、全部直接跳转在镜像内、loop/call 深度不超过 6/4、公开 loop bound 不超过 manifest、layout capability 与 lane/input 模式一致、Scratchpad 范围有界、所有可达正常路径以 HALT 结束。Job 执行期间由硬件重复检查 PC、栈和地址边界。
