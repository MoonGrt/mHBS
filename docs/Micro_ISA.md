# μHBS Micro-ISA v0.2

## 固定编码

每条指令 64 bit：

```text
63          56 55          48 47          40 39          32 31           0
+--------------+--------------+--------------+--------------+-------------+
| opcode (8)   | flags (8)    | rd (8)       | rs (8)       | imm (32)    |
+--------------+--------------+--------------+--------------+-------------+
```

只实现 R0–R7 八个控制/计数寄存器；密码数据保存在有界 Scratchpad。
保留位和指令专用 `flags` 组合必须通过静态校验。

| Opcode | Code | 语义 |
|---|---:|---|
| `SET_REG` | `0x01` | `R[rd] = imm` |
| `ADD_IMM` | `0x02` | `R[rd] = R[rs] + sext(imm)`，溢出报错 |
| `HASH` | `0x03` | 按 `imm` 选择 layout descriptor 组织输入并发送至 `flags[1:0]` 选择的等价 Hash lane |
| `LOOP_BEGIN` | `0x04` | 建立有界循环；边界为 `imm` 或受界 Scratchpad 动态值 |
| `LOOP_END` | `0x05` | 计数递增并回跳，结束时弹出循环栈 |
| `CALL` | `0x06` | 压入返回地址并跳转至 `imm` |
| `RETURN` | `0x07` | 弹出子程序返回地址 |
| `DATA_LOAD` | `0x08` | 执行静态 load/parse/transform descriptor，将 Job 或 Scratchpad 数据载入寄存器/槽位 |
| `DATA_MOVE` | `0x09` | 按 move descriptor 在有界 Scratchpad 槽位间复制数据 |
| `TREE_PUSH` | `0x0b` | 将节点压入参数化 Merkle 栈，并执行已就绪的等高父节点 Hash |
| `OUTPUT` | `0x0c` | 按输出 descriptor 将 Scratchpad 片段追加到 Job 结果流 |
| `HALT` | `0x0d` | 在循环栈和调用栈平衡时成功结束 Job |

`0x00`、`0x0a`、`0x0e`–`0x11` 是从 v0.1 删除后保留的编码空洞；解码器必须将其视为非法
opcode，不得重解释旧镜像。被删除的指令为 `NOP`、`XOR`、`FAIL`、
`WAIT`、`BARRIER`和`JUMP`，原因是九个已编译的 Keygen/Sign/Verify 程序均不使用。

Layout 内部仍允许等长数据 XOR，这是 Hash 输入表达式，不是 `XOR`微指令。

## 参数化语义

`HASH`、`DATA_LOAD`、`DATA_MOVE`、`TREE_PUSH`和`OUTPUT`的展开语义由版本化
descriptor manifest 定义。硬件不得根据 SLH-DSA、XMSS、LMS、FORS 或 WOTS
等算法 ID 进入隐藏 sub-FSM。

`HASH` lane mask 必须是 `01/10/11`。assembler 仅在源指令省略 `flags`时
默认为 `01`；显式 `flags=0` 会被静态 verifier 拒绝。`flags[2]` 是双 lane
配对操作的有界写延迟契约。

## 静态 verifier

装载前必须证明：opcode/flags 合法，loop/call 深度不超过 6/4，直接目标在
镜像内，layout/load/move descriptor 存在，且所有可达正常路径能达到
`HALT`。Job 执行期间硬件再次检查 PC、栈、寄存器和地址边界。

## 灵活性边界

当前 ISA 是“可编程 HBS 算法编排器”，不是通用 CPU：

- 九个 SLH-DSA/XMSS/LMS Keygen、Sign、Verify 镜像只使用这 12 条指令，不含算法命名 opcode。
- 算法差异由微码流程和 descriptor 数据表达，因此可更换参数集、树形和签名输出顺序。
- 当前没有条件比较/分支；适合公开有界、数据无关的 HBS 控制流，不适合任意控制程序。
- `HASH`和`TREE_PUSH`目前是阻塞退休；Python 的多 lane issue-window 调度收益尚未成为 RTL 执行语义。优先应用硬件 scoreboard 隐式处理依赖，只在真正需要显式同步时再定义新指令。
- Verify 微码当前输出重建 root，接受/拒绝比较在外部完成；XMSS/LMS 的持久化状态事务也在 ISA 之外。

因此，v0.2 已达到最初的“灵活微码 HBS”核心意图：同一小型指令集可编排多算法和三种操作，而不是把每种 HBS 任务固定为硬件宏操作。但它尚未实现非阻塞多 lane 调度和完全自治的 Verify/状态提交。
