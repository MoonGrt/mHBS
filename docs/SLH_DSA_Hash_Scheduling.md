# SLH-DSA Hash 粒度 K×U 调度模型

## 范围与计时合同

`model/slh_dsa_schedule.py` 为 FIPS 205
SLH-DSA-SHAKE-128f 的 Keygen、Sign、Verify 建立完整 Hash 任务 DAG。
每个任务是一整个 SHAKE 调用；多 block `T_l` 的 permutation 不能拆到
不同 lane。只有所有数据依赖完成后，任务才能进入任意一条等价 lane。

- `K`：完全等价的 Hash lane 数量；
- `U`：每周期执行的 Keccak-f[1600] 轮数；
- permutation 延迟：`ceil(24/U)`；
- 默认 SHAKE wrapper 开销：每次调用 3 cycles；
- 默认微码发射宽度：1 task/cycle；
- Sign 输出按 FIPS 205 固定顺序，以 8 bytes/cycle 串行化。

3-cycle wrapper 参数来自当前 U2 单 block lane 的 12-cycle permutation 加
start/pad/done 控制开销。模型同时允许将该参数设为 0，以显示纯
permutation 下界。该模型尚不包含布局布线、Scratchpad bank conflict、
有限任务队列和模板生成器结构冲突，因此结果是**带真实算法依赖的 Hash
服务理论值**，不是完整 RTL 实测值。

## 算法正确性 Gate

任务图不是按总数合成的虚拟工作量。它由 FIPS 205 的 WOTS chain、FORS
子树、XMSS 认证路径和层间 root 依赖生成，并用独立参考实现复核。

| Operation | Hash tasks | Permutations | 分类 |
|---|---:|---:|---|
| Keygen | 4,495 | 4,527 | PRF 280、F 4,200、H 7、T_l 8 |
| Sign | 104,937 | 105,641 | PRF_msg 1、H_msg 1、PRF 8,272、F 94,257、H 2,230、T_l 176 |
| Verify | 6,441 | 6,533 | H_msg 1、F 6,153、H 264、T_l 23 |

同时验证：

- NIST ACVP Keygen tc31 的 SK/PK 完全一致；
- deterministic SigGen tc137 的签名 SHA256、`R` 和 Verify 结果一致；
- Sign 的 1,068 个 16-byte 输出块均对应唯一 Hash 生产任务；
- 输出映射连续覆盖 17,088 bytes，无重叠、无空洞；
- 调度结果逐任务检查 `dependency.finish <= task.start`。

## K×U 理论调度结果

### 纯 Hash 口径（不考虑 RTL）

对已编译的151条 Sign微码按原有阻塞顺序回放，仅计算
`permutations×ceil(24/U)`：

- 41,888条 pair指令同时使用lane 0/1；
- 其余19,192个composer请求只使用lane 0；
- 1,969个TreeHash parent使用lane 1，但与composer阶段串行；
- lane 0执行61,784次permutation，lane 1执行43,857次；
- U2 Hash-only makespan为765,036 cycles，平均lane利用率82.852%。

完整DAG重排后，不改变105,641次permutation和任何依赖：

| K×U | Keygen | Sign | Verify |
|---|---:|---:|---:|
| K1×U1 | 108,648 | 2,535,386 | 156,792 |
| K1×U2 | 54,324 | 1,267,694 | 78,396 |
| K2×U1 | 54,337 | 1,267,730 | 80,746 |
| K2×U2 | **27,169** | **633,866** | **40,378** |
| K4×U2 | 13,599 | 316,952 | 21,356 |

因此现有151条微码的Hash级固定调度比K2×U2 DAG调度多
131,170 cycles（Hash makespan口径为131,172），约20.69%。差距来自
只对auth-subtree WOTS pkgen做相邻chain配对，而FORS、selected WOTS、
recovery chain和TreeHash parent没有进入统一ready-task调度。

### 带每次 SHAKE 3-cycle 协议开销的扩展口径

以下结果使用单发射微码口、每 Hash 3-cycle wrapper、critical-path 优先级：

| K×U | Keygen | Sign | Verify | Sign lane utilization |
|---|---:|---:|---:|---:|
| K1×U1 | 122,133 | 2,850,197 | 176,115 | 100.000% |
| K1×U2 | 67,809 | 1,582,505 | 97,719 | 100.000% |
| K2×U1 | 61,081 | 1,425,128 | 90,562 | 99.998% |
| K2×U2 | 33,913 | **791,274** | 50,194 | 99.997% |
| K4×U2 | 16,974 | 395,658 | 26,408 | 99.993% |

K2×U2、wrapper=0 时，Sign 为 633,866 cycles：Hash 完成为 633,864，
最后一个 16-byte 签名块再占 2 cycles。它只比旧的无依赖
`ceil(105641/2)×12 = 633,852` 下界多 14 cycles，证明 DAG 中存在足够的
合法并行度；默认 791,274 与它的差值主要是 104,937 次调用各 3 cycles
的 wrapper 开销，而不是算法依赖。

默认 K2×U2 理论值相对当前 3,241,107-cycle RTL 为 4.096×，但在模板
生成、有限队列、存储端口和 RTL 时序加入模型前，不把它称为 RTL speedup。

critical-path 策略需要最多暂存约 3,088 bytes 的提前完成签名结果。更简单
的 FIFO/程序顺序策略为 791,286 cycles，只慢 12 cycles，并把该值降到
96 bytes；因此 K2×U2 的首版 RTL 应采用 FIFO 静态顺序，而不是实现复杂的
全局 priority queue。报告中的 `maximum_ready_depth=7502` 是离线 DAG 在
同一时刻可选的任务数，不是建议的硬件 FIFO 深度；这些任务由嵌套微码循环
按需生成。

## 现有微码使用频次

### Keygen

现有程序为 12 words，动态执行 9,275 条：

| Opcode | 次数 | 占比 |
|---|---:|---:|
| HASH | 4,488 | 48.388% |
| LOOP_END | 4,488 | 48.388% |
| LOOP_BEGIN | 289 | 3.116% |
| TREE_PUSH | 8 | 0.086% |
| OUTPUT/HALT | 2 | 0.022% |

### Sign

现有程序为 151 words，动态执行 135,417 条：

| Opcode | 次数 | 占比 |
|---|---:|---:|
| HASH | 61,080 | 45.105% |
| LOOP_END | 56,906 | 42.023% |
| LOOP_BEGIN | 4,740 | 3.500% |
| DATA_LOAD | 4,155 | 3.068% |
| SET_REG | 3,826 | 2.825% |
| TREE_PUSH | 2,178 | 1.608% |
| OUTPUT | 1,068 | 0.789% |
| 其他 | 1,464 | 1.081% |

61,080 次 `HASH` 发出 102,968 个 composer Hash；2,178 次
`TREE_PUSH` 产生 1,969 个 parent Hash。动态指令中 42.0% 是显式
`LOOP_END`，说明继续保留逐 Hash 阻塞指令和显式循环尾会浪费控制周期。

### Verify

独立 Verify 程序为38 words，实际使用8种opcode，tc137动态执行18,036条：

| Opcode | 静态条数 | 动态次数 |
|---|---:|---:|
| DATA_LOAD | 15 | 2,732 |
| HASH | 7 | 6,441 |
| LOOP_BEGIN | 6 | 849 |
| LOOP_END | 6 | 7,209 |
| SET_REG | 1 | 770 |
| DATA_MOVE | 1 | 33 |
| OUTPUT | 1 | 1 |
| HALT | 1 | 1 |

程序直接按循环索引读取签名切片，重建的root与ACVP tc137的PK.root一致；
逐Hash输入、输出及顺序与独立FIPS 205参考实现完全一致。单bit签名突变会
重建出不同root。Verify共执行6,441个Hash、6,533次permutation；现有程序
全部固定在lane 0，U2纯Hash周期为78,396，而统一K2×U2 DAG调度为40,378。

## 面向统一 Keygen/Sign/Verify 的微码设置

保持现有64-bit、12-op通用ISA和component/layout descriptor机制。
不将`FORS`、`XMSS`、`WOTS`、签名分段或固定TreeHash流程编码为
算法专用微指令。算法流程应继续由通用`HASH`、`DATA_LOAD/DATA_MOVE`、
`LOOP_BEGIN/LOOP_END`、`TREE_PUSH`、`OUTPUT`和同步/控制指令组合得到。

对微码的优化限定在不破坏这一可编程边界的范围内：

- 编译器重排通用Hash/Tree指令，但不引入算法专用opcode；
- 将重复的layout、地址和循环参数放入可配置descriptor；
- 通过现有循环/CALL结构压缩程序，而不把整个算法阶段固化为任务；
- 两条Hash lane保持等价，lane-local feedback是通用数据路径能力；
- 调度、输出位置和lane mask由微码/描述符决定，不由RTL固定算法。

已归档的8类宏指令尝试及其Hash周期下界记录见
`docs/Microcode_Optimization_Model.md`。

对于 K2×U2：

- 1 task/cycle 的微码发射宽度足够；最短 Hash 服务仍为15 cycles；
- 建议 request FIFO 深度4，completion/tag槽位4；
- 两条 lane 各保留一个16-byte feedback context；
- signature reorder 至少覆盖一个双-lane完成对；
- TreeHash节点栈与auth capture独立于通用Scratchpad。

完整逐任务分配可用以下命令生成：

```bash
python3 scripts/simulate_slh_dsa_hash_schedule.py \
  --config 2x2 \
  --json-out build/slh_dsa_schedule.json \
  --trace-dir build/schedules
```

`build/schedules/*.jsonl.gz` 的每行包含任务、依赖、具体 lane、开始/结束
cycle及签名偏移。冻结的汇总结果位于
`manifests/experiments/slh_dsa_hash_schedule_v0.1.0.json`。

另一份不使用算法DAG、只从现有12-op微码执行轨迹提取依赖的
通用Hash粒度实验见`docs/Microcode_Hash_Grain_Optimization.md`。
