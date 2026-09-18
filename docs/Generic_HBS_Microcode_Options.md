# 通用 HBS 微码架构候选方案

## 状态与目标

> 2026-09-18 更新：本文推荐的“宏指令 + Recipe 描述符”混合方案已经
> 实现。最终 RTL、程序映射、验证和 PPA 见
> [Generic_HBS_Macrocode_Implementation.md](Generic_HBS_Macrocode_Implementation.md)。

本文以下内容保留为实施前的架构选项记录。当时产品 RTL 是“静态
水平微码调度 + SLH-DSA-128f 专用 materializer + 两条等价 U2
Keccak lane”。微码能改变任务顺序、循环、坐标和 lane 分配，但 Hash
输入构造、地址格式、结果路由以及 FORS/WOTS/XMSS 语义仍由 RTL
状态硬编码。

后续目标是：保留两条完全等价的 Hash lane，将新 HBS 算法的增加尽量
收敛为“重新编译微码与描述符”，而不是增加算法专用 FSM。

## 方案 A：细粒度 Recipe 微码

方案 A 把当前 `S_PREP_*`、`S_COMMIT` 和算法专用数据拼接逻辑下沉为
Recipe 微码。算法层微码负责调度，Recipe 微码负责定义单个任务。

```text
算法层水平微码
    ↓
Recipe 微码
├─ HASH_BEGIN
├─ APPEND / APPEND_ADDR
├─ CHAIN / HASH_END
├─ STORE / EMIT
└─ EVENT
    ↓
通用 composer + 两条等价 Hash lane
```

建议的 Recipe 微操作包括：

- `HASH_BEGIN`：选择 Hash 模式、domain、padding 和输出长度；
- `APPEND`：从消息、密钥、寄存器、node store 或 endpoint store 追加数据；
- `APPEND_ADDR`：按可编程布局生成地址字段；
- `CHAIN`：设置迭代次数、运行时终点和 capture 位置；
- `HASH_END`：结束 context 并等待结果；
- `STORE`：把结果写入通用寄存器或本地存储；
- `EMIT`：把指定结果写入签名输出流；
- `EVENT`：产生或消费记分牌事件。

此外增加小型标量 ALU，支持 `MOV/ADD/SUB/AND/OR/SHIFT/EXTRACT/CMP/BRANCH`，
以微码实现 WOTS digit、checksum、tree index 和 leaf index 处理。

优点：

- 可编程性最强，输入拼接、地址格式和结果路由都可重编译；
- RTL 可以只保留通用 fetch/feed/wait/writeback 状态；
- 能适配非标准输入布局或新的 HBS 组合。

代价：

- 微码和译码器较大，预计需要 1～3 RAMB36；
- 如果逐个 128-bit beat 解释微码，可能产生 5%～15% 周期开销；
- 编译器和验证状态空间明显增大；
- 容易退化成一个面积不小、效率不高的专用 RISC 处理器。

方案 A 必须使用 `APPEND source, offset, length` 一类批量操作，不应使微码
逐字节、逐 beat 或逐 Keccak round 控制数据通路。

## 方案 B：通用 `HASH/CHAIN/TREE` 宏指令

方案 B 不保留文章中带有 FORS/WOTS/XMSS 语义的 11 类 task，而是按
Hash 计算图抽象为三种通用拓扑。

### `HASH`

执行一次任意长度 Hash，描述符包含 input segments、domain、地址布局、
输出长度和 destination。它覆盖文章的 task0、task1、task5 和 task8。

### `CHAIN`

执行连续一元 Hash 链，描述符包含 instances、seed recipe、step recipe、
max steps、runtime stop、capture step 和 destination。它覆盖 task2、
task3、task6 和 task7。

### `TREE`

执行通用二叉树归约，描述符包含 leaf count、height、leaf recipe、
parent recipe、selected leaf、auth capture、root destination 和 traversal mode。
它覆盖 task4、task9 和 task10。`leaf_recipe` 可以调用 `HASH` 或 `CHAIN`。

```text
文章 task0/1/5/8  → HASH
文章 task2/3/6/7  → CHAIN
文章 task4/9/10   → TREE
```

除三种 Hash 宏指令外，仅保留 `MOVE/EXTRACT`、`LOOP/BRANCH`、`STORE`、
`EMIT`、`WAIT/HALT` 等少量非 Hash 指令。

优点：

- 微码很小，一条 `CHAIN` 或 `TREE` 可以运行数百至数千次 Hash；
- 控制开销不进入每个 append beat，更容易保持当前性能；
- SLH-DSA、XMSS 和 LMS 可以复用同一组迭代器；
- 编译器、边界检查和形式验证较容易。

代价：

- `CHAIN` 和 `TREE` 内部仍需要固定的通用迭代 FSM；
- 对非树/非链的新计算拓扑适应性低于方案 A；
- 如果描述符不充分可编程，可能只是把文章的 11 类 task 压缩成
  3 类新的固定 task。

## 方案比较

| 对比项 | 方案 A：细粒度 Recipe 微码 | 方案 B：`HASH/CHAIN/TREE` |
|---|---|---|
| 微码粒度 | APPEND/ADDR/HASH/STORE | 完整 Hash/链/树 |
| 固定 RTL | 通用 composer、lane、store | 另有通用 chain/tree 迭代器 |
| 算法灵活性 | 最高 | 高，但限于 Hash/链/树拓扑 |
| 微码大小 | 数百至数千条 | 数十至数百条 |
| 预计 ROM | 1～3 RAMB36 | 通常不超过 1 RAMB36 |
| 控制周期开销 | 预计 5%～15% | 预计 0%～3% |
| 双 lane 调度 | 微码显式安排 | 宏引擎内部安排 |
| 预计新增逻辑 | 1.5k～3.5k LUT | 1k～2k LUT |
| 编译器复杂度 | 高 | 中等 |
| 验证难度 | 高 | 较低 |
| 新拓扑扩展 | 较容易 | 可能需要修改 RTL |
| 与文章的区别 | 最大，接近通用微码处理器 | 明显，但仍是宏任务加速器 |

## 推荐：宏指令 + Recipe 描述符的混合架构

推荐以方案 B 为执行主体，吸收方案 A 的可编程输入和结果路由：

```text
算法层水平微码
├─ HASH / CHAIN / TREE
├─ ALU / BRANCH / LOOP
└─ STORE / EMIT
        ↓
可编程 Recipe 描述符
├─ input segment 列表
├─ 地址字段布局
├─ domain / padding
├─ capture 规则
└─ 结果路由
        ↓
通用 HASH/CHAIN/TREE 执行器
        ↓
两条等价 U2 Hash lane
```

这一架构不让微码逐 beat 控制 composer，同时也不把 FORS/WOTS/XMSS
输入格式固化为 RTL task。目标是使不同 HBS 算法只改变算法微码和
Recipe 描述符。

预期设计点：

| 指标 | 目标 |
|---|---:|
| 面积 | 23k～25k LUT |
| 微码/descriptor ROM | 约 1 RAMB36 |
| SLH-DSA-128f Sign | 760k～790k cycles |
| Hash lane | 两条完全等价 U2 lane |

## 架构验收标准

1. RTL 中不再存在 `FORS_LEAF`、`WOTS_TL`、`XMSS_PARENT` 等算法专用执行状态。
2. 同一份 RTL 仅更换微码和描述符即可执行至少两种算法/参数集。
3. `n/h/d/k/a/w/len`、地址布局和结果路由不在顶层 RTL 硬编码。
4. 两条 lane 可物理交换，任意 Recipe 都能在任一 lane 上运行。
5. 添加已有 Hash/链/树拓扑的新算法时，不需要增加新 RTL task FSM。
6. 微码及描述符编译器对 ROM 边界、地址溢出、非法数据源和事件冲突进行静态检查。
