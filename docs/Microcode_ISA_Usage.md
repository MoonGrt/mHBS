# μHBS 微指令使用清单

> 当前架构为 12-op 通用 Micro-ISA v0.2。8 类算法宏指令尝试仅作为已归档对照，未进入 ISA 或 RTL。

## 编译覆盖

下表是重新编译后的静态 64-bit 指令数，不是动态执行次数。

| 算法 | 操作 | words | opcode种类 | 静态组成 |
|---|---|---:|---:|---|
| SLH-DSA | Keygen | 12 | 6 | HASH 3, LOOP_BEGIN 3, LOOP_END 3, TREE_PUSH 1, OUTPUT 1, HALT 1 |
| SLH-DSA | Sign | 151 | 12 | DATA_LOAD 30, HASH 29, LOOP_BEGIN 19, LOOP_END 19, SET_REG 14, OUTPUT 12, DATA_MOVE 11, TREE_PUSH 7, CALL 5, ADD_IMM 2, RETURN 2, HALT 1 |
| SLH-DSA | Verify | 38 | 8 | DATA_LOAD 15, HASH 7, LOOP_BEGIN 6, LOOP_END 6, SET_REG 1, DATA_MOVE 1, OUTPUT 1, HALT 1 |
| XMSS | Keygen | 93 | 8 | HASH 32, SET_REG 31, LOOP_BEGIN 11, LOOP_END 11, DATA_MOVE 5, TREE_PUSH 1, OUTPUT 1, HALT 1 |
| XMSS | Sign | 114 | 10 | HASH 38, SET_REG 31, LOOP_BEGIN 15, LOOP_END 15, DATA_MOVE 5, OUTPUT 4, DATA_LOAD 3, ADD_IMM 1, TREE_PUSH 1, HALT 1 |
| XMSS | Verify | 177 | 8 | DATA_LOAD 82, HASH 36, SET_REG 32, LOOP_BEGIN 10, LOOP_END 10, DATA_MOVE 5, OUTPUT 1, HALT 1 |
| LMS | Keygen | 13 | 6 | HASH 4, LOOP_BEGIN 3, LOOP_END 3, TREE_PUSH 1, OUTPUT 1, HALT 1 |
| LMS | Sign | 35 | 8 | HASH 7, DATA_LOAD 7, LOOP_BEGIN 6, LOOP_END 6, OUTPUT 6, SET_REG 1, TREE_PUSH 1, HALT 1 |
| LMS | Verify | 24 | 8 | DATA_LOAD 9, HASH 5, LOOP_BEGIN 3, LOOP_END 3, SET_REG 1, ADD_IMM 1, OUTPUT 1, HALT 1 |

## 指令含义与使用算法

| 指令 | 含义 | 当前使用操作 |
|---|---|---|
| `SET_REG` | 将立即数写入控制寄存器 | SLH-DSA Sign/Verify；XMSS Keygen/Sign/Verify；LMS Sign/Verify |
| `ADD_IMM` | 寄存器加有符号立即数 | SLH-DSA Sign；XMSS Sign；LMS Verify |
| `HASH` | 按 layout descriptor 组织输入并调用等价 Hash lane | 全部 9 种操作 |
| `LOOP_BEGIN` | 建立静态或 Scratchpad 边界的有界循环 | 全部 9 种操作 |
| `LOOP_END` | 递增循环计数并回跳/退出 | 全部 9 种操作 |
| `CALL` | 调用微码子程序 | SLH-DSA Sign |
| `RETURN` | 从微码子程序返回 | SLH-DSA Sign |
| `DATA_LOAD` | 执行 load/parse/transform descriptor | SLH-DSA Sign/Verify；XMSS Sign/Verify；LMS Sign/Verify |
| `DATA_MOVE` | 按 descriptor 复制 Scratchpad 值 | SLH-DSA Sign/Verify；XMSS Keygen/Sign/Verify |
| `TREE_PUSH` | 通用 Merkle 栈入栈及等高归约 | SLH-DSA Keygen/Sign；XMSS Keygen/Sign；LMS Keygen/Sign |
| `OUTPUT` | 将 Scratchpad 片段按程序顺序追加至结果流 | 全部 9 种操作 |
| `HALT` | 成功结束 Job | 全部 9 种操作 |

## 删除项

v0.1 中从未被九个生产微码镜像使用的 `NOP`、`XOR`、`FAIL`、`WAIT`、
`BARRIER`和`JUMP`已删除。其数值编码保留为非法空洞，保证旧镜像 fail-closed。

## 结论

12 条微指令可编译全部 SLH-DSA/XMSS/LMS Keygen、Sign、Verify，且没有算法命名 opcode，因此保留了“灵活微码 HBS”的核心区别。

但当前灵活性是有边界的：控制流只支持有界循环和子程序，非阻塞双 lane 调度仍只在 Python Hash 粒度模型中，Verify 根比较和有状态签名的持久化事务仍属于外部管理。

机器可读的 12×9 使用矩阵位于
`manifests/experiments/microcode_isa_usage_v0.2.0.json`。
