# 已归档：SLH-DSA 8类宏指令尝试

> 状态：**ARCHIVED / NOT ADOPTED**
> 决策：不将下述8类宏操作作为μHBS目标ISA，恢复到原有
> 12-op通用微码架构。本文仅保留实验思路和模型数据，不代表
> 当前实现计划。

## 归档原因

该方案能大幅压缩动态控制数并接近Hash调度下界，但
`SIG_CONFIG`、`TREE_CONFIG`等指令把算法任务语义固定到架构中，
会使μHBS趋近Unified_HBS的“固定硬件任务”方式。这与项目目标
“通过可编程微码组合Hash、chain、tree、存储和输出原语”不符。

因此，只保留以下可迁移结论：完整chain的lane-local feedback、
两条等价Hash lane、离线拓扑排序和4-entry发射FIFO。这些应由
通用微指令及描述符表达，而不是新增算法专用宏指令。

## 结论

本次尝试只修改过 Python 编译/调度模型，**未修改 RTL**。对
SLH-DSA-SHAKE-128f，将逐 Hash 微指令改为粗粒度模板，将完整
PRF/F chain 折叠为 lane-local context，并把离线关键路径调度结果
固化为上下文描述符顺序。运行时只需单个顺序发射头和4深度
物理请求FIFO，不需要全局 ready-task priority queue。

| 操作 | 现有静态 words | 优化后 words | 映射模板 | 现有动态指令 | 宏上下文发射 |
|---|---:|---:|---:|---:|---:|
| Keygen | 12 | 8 | 3 | 9,275 | 300 |
| Sign | 151 | 19 | 13 | 135,417 | 10,686 |
| Verify | 38 | 12 | 7 | 18,036 | 1,096 |

`words`是紧凑模板程序大小；“宏上下文发射”是实际运行时生成的
Hash/chain context数，两者不是同一口径。

## 微码结构

优化模型共8种宏操作名称，每个 Keygen/Sign/Verify 程序使用其中7种：

| 宏操作 | 意义 |
|---|---|
| `JOB_CONFIG` | 锁定参数集和Job输入 |
| `SIG_CONFIG` | 配置签名分段及结果路由 |
| `TREE_CONFIG` | 配置FORS/XMSS树和auth capture |
| `CHAIN_ISSUE` | 提交一个完整PRF/F或F-only chain context |
| `HASH_ISSUE` | 提交H、T_l、PRF_msg或H_msg context |
| `WAIT_TAG` | 只在真实的阶段依赖处同步 |
| `OUTPUT_CONFIG` | 配置Keygen/Verify输出 |
| `HALT` | 结束Job |

Sign的13个映射模板和tc137动态上下文数为：

| 模板 | 上下文数 | 模板 | 上下文数 |
|---|---:|---|---:|
| message_randomizer | 1 | message_digest | 1 |
| fors_selected_chain | 33 | fors_auth_chain | 2,079 |
| fors_auth_parent | 1,881 | fors_recovery_h | 198 |
| fors_compress | 1 | xmss_auth_chain | 5,390 |
| xmss_auth_compress | 154 | xmss_auth_parent | 88 |
| xmss_selected_chain | 770 | xmss_recovery_compress | 21 |
| xmss_recovery_h | 63 |  |  |

该结构完整保留104,937次Hash和105,641次Keccak permutation，
不通过删减算法工作量获得优化。

## 映射与执行

- 两条K2×U2 Hash lane完全等价，chain、composer Hash和Tree parent
  使用同一服务和仲裁路径。
- 完整chain在同一lane中保留feedback，不再逐F往返Scratchpad。
- 编译器先在完整Hash DAG上计算critical-path调度，再按
  `(start_cycle, lane, task_id)`生成拓扑合法的描述符流。
- 运行时严格顺序发射：1个logical head、1 context/cycle、FIFO=4。

纯Hash周期（`permutations×ceil(24/U)`，wrapper=0）：

| 操作 | 现有微码固定映射 | 原始顺序+FIFO4 | 编译排序+FIFO4 | 周期降低 | lane利用率 |
|---|---:|---:|---:|---:|---:|
| Keygen | 54,324 | 27,751 | **27,169** | 49.987% | 99.974% |
| Sign | 765,036 | 651,149 | **633,864** | 17.146% | 99.997% |
| Verify | 78,396 | 42,082 | **40,424** | 48.436% | 96.967% |

Sign的`633,864 cycles`仅比无依赖的总工作量下界
`ceil(105641/2)×12 = 633,852`多12 cycles。全局critical ready pool
在tc137上最大为7,502项；将调度顺序移到编译器后，实现同样
makespan，运行时ready pool为0。

若模型为每次Hash增加3-cycle wrapper开销，编译排序结果为
Keygen 33,913、Sign 791,272、Verify 50,252 cycles。这仍不包含
RTL composer、Scratchpad、签名串行输出和布线延迟。

## 正确性与边界

- NIST ACVP tc137签名完全一致，Verify通过。
- Keygen/Sign/Verify的Hash数和permutation数在宏展开后全部一致。
- 每个调度结果均检查依赖完成时间和FIFO上界。
- 当前编译顺序由tc137的实际chain长度导出，属于profile-guided
  模型。已用8个额外1-byte消息验证同一顺序：宏任务拓扑结构全部
  稳定，相对每条消息单独重排的最大代价为84 cycles。这只是小样本；
  冻结为通用静态ROM前仍需要更多消息和其他参数集验证，或改用固定
  最坏chain长度生成顺序。
- 本结果不是完整RTL周期或PPA预测，本轮也不对RTL改动做任何声明。

回退时已删除该尝试的独立模型、执行脚本、测试和实验manifest；
上表数值作为历史探索记录保留。
