# 通用微码驱动的Hash粒度调度实验

## 范围

本实验保持现有64-bit、12-op通用ISA和所有已编译微码不变，
不引入`TREE_CONFIG`、`SIG_CONFIG`或任何FORS/XMSS/WOTS专用
opcode，也不修改RTL。

与已归档的8类宏指令方案不同，本模型不由Python预先生成算法
DAG。依赖直接来自现有微码的实际执行轨迹：

1. `HASH`根据layout descriptor读取Job、Scratchpad和寄存器；
2. 解释器为每个Scratchpad/寄存器值记录生产者Hash tag；
3. 动态循环边界亦传播控制依赖；
4. `TREE_PUSH`内部的parent Hash通过左/右子节点值传播tag；
5. 调度器只看Hash request、tag和两条等价lane，不知道算法阶段。

## 优化方案

保留微码原始动态指令流，在Hash服务入口加入通用的有界
request window：

- 微码指令最快每周期释放一个Hash request；
- request在其所有生产者tag完成后变为ready；
- ready request按FIFO选择，无全局critical-path priority queue；
- 16-entry通用issue window，4-entry物理request FIFO；
- 两条K2×U2 Hash lane完全等价，不保留composer/tree固定lane。

这是Hash粒度模型；静态words、动态微指令数和Hash工作量均未减少。

## 结果

纯Hash口径，`permutations×ceil(24/U)`，wrapper=0：

| 操作 | 静态words | 动态微指令 | 现有固定映射 | 通用FIFO window=16 | 降低 | lane利用率 |
|---|---:|---:|---:|---:|---:|---:|
| Keygen | 12 | 9,275 | 54,324 | **27,263** | 49.814% | 99.630% |
| Sign | 151 | 135,417 | 765,036 | **633,900** | 17.141% | 99.991% |
| Verify | 38 | 18,036 | 78,396 | **40,740** | 48.033% | 96.215% |

Sign的16-entry FIFO结果比同一轨迹的256-entry critical window下界
`633,864 cycles`只多36 cycles。因此不需要将整个算法编译成固定
硬件任务，小型通用scoreboard/window就能暴露几乎全部Hash并行度。

若为每次Hash加3-cycle wrapper，window=16的Keygen/Sign/Verify结果分别为
34,017 / 791,308 / 50,646 cycles。

## 正确性与限制

- Keygen、Sign、Verify微码输出与ACVP/参考结果一致。
- 轨迹完整覆盖115,873次Hash，数量和permutation数与解释器计数器一致。
- 所有依赖均指向更早的Hash，调度后逐任务检查
  `dependency.finish <= task.start`。
- 模型使用完整动态轨迹回放，虽然限制了每周期的指令释放速率，
  但没有模拟微码前端因未完成Hash数据而暂停解码的全部时序。
  因此它是通用微码调度上界，不是可直接代替RTL仿真的周期值。
- 未包含非Hash指令周期、Scratchpad端口冲突、composer、签名输出和布线时序。
- 单个T_l最多可有36个逻辑生产者；未来RTL应用组完成计数器或
  存储器scoreboard压缩，而不是在每个request中存储36个tag。

机器可读结果位于
`manifests/experiments/slh_dsa_microcode_hash_schedule_v0.1.0.json`。
