# K2U2 特化与单变量实验

**结论：先前两个组合候选均因综合面积增加而未采纳；补充单变量实验确认，仅显式展开双 lane 不增加面积，综合网表结构也一致；单独特化 U2 轮对计数器同样没有面积收益。生产 RTL 保持原样。** 当前仍使用 `prune_k2u2_20260927_v1`，共同核为 6206 等效 Slice，六组最低已测核内频率为 104.166667 MHz。

## 同口径综合比较

| 方案 | LUT | FF | LUTRAM | 等效 Slice | 相对基线 | 处理 |
|---|---:|---:|---:|---:|---:|---|
| 当前基线 | 20,154 | 9,340 | 1,456 | 6,206.000 | — | 保留 |
| 显式双 lane／固定双轮 | 22,158 | 9,343 | 1,456 | 6,707.375 | +8.08% | 面积不合格 |
| 固定双轮＋独立链反馈 | 26,371 | 9,348 | 1,456 | 7,761.250 | +25.06% | 面积不合格 |

BRAM、DSP 均为零。等效 Slice 采用 LUT/4 + FF/8。两个候选均在面积门槛处停止，未构建六组参数外壳、未布局布线，**不声明候选频率**。基线频率只代表原有实现的 OOC 核内时序，外部接口未签核。

## 实际实现与验证

- 两个候选均实现显式双 lane、显式偶/奇 Keccak 轮、0～11 轮对计数及固定轮常量译码；每次 permutation 保持 12 个计算周期。清除了 sponge 中未调用的重复函数，保留静态位映射 generate。
- 候选一允许双轮内部跨层次优化；候选二在此基础上使用独立链反馈路径。两者均保留接口、lane 交换及仿真统计，生产综合关闭统计。
- 每个候选通过 792 项组合等价检查：对照冻结自 b4816c0 的单轮实现，覆盖全部 12 个轮对、零值、全一和 64 个确定性随机状态。
- 每个候选通过 6 组软件模型、13 项单元门禁、6 组正常执行、33 项扩展场景、6 组共同核等价、12 组统计关闭对照、2 项统计关闭扩展以及 6 项故障退出；六组操作周期与基线完全一致。
- 层次资源报告显示，候选一的主要 LUT 增量位于 lane1 sponge（5516 → 7479），候选二进一步增加两个 sponge 的组合逻辑。此前同时改变了 lane 展开、双轮结构、轮计数、常量译码和层次约束，不能把 +8.08% 归因于删除 generate。补充实验已单独排除纯 lane 展开的面积影响；其余因素尚未全部隔离。

## 补充实验：仅显式展开双 lane

候选 `k2u2_lanes_only_20260927_v1` 从生产提交 `b4816c0` 独立建立。唯一生产 RTL 修改是将 `mhbs_hbs` 中的两个 recipe lane 手工展开为 `lane0`、`lane1`；参数、端口连接、配方掩码及 lane 交换均等价。保留 roots 包装、原 Keccak generate、轮计数、常量译码和 `keep_hierarchy`，其余生产 RTL 逐字节一致。测试仅同步层次引用，综合驱动增加 `--core-only` 便于独立测量。

| 指标 | 基线 | 仅 lane 展开 | 差值 |
|---|---:|---:|---:|
| LUT | 20,154 | 20,154 | 0 |
| FF | 9,340 | 9,340 | 0 |
| LUTRAM | 1,456 | 1,456 | 0 |
| 等效 Slice | 6,206 | 6,206 | 0 |
| lane0 sponge LUT | 7,216 | 7,216 | 0 |
| lane1 sponge LUT | 5,516 | 5,516 | 0 |

对完整 EDIF 进一步比较：仅归一化时间戳、两个 lane 实例名、内部网络名以及无序项排列后，全部 cell 定义、端口、实例属性和网络引脚连接的结构摘要完全相同。两者均有 31 个 cell 定义、30,273 个实例定义、59,025 个网络定义（包含层次定义，并非展开后的物理单元数）。这支持“等价 generate 与手工例化产生同一逻辑结构”，不能从参数可配置本身推断硬件冗余。

通过 6 组模型、12 项单元门禁、6 组正常执行、33 项扩展、6 组共同核对照、12 组关闭统计对照、2 项关闭统计扩展及 6 项故障退出；六组输出 SHA-256 和计算周期均与基线相同。综合统计关闭，冗余计数寄存器审计通过。

本候选用于隔离综合面积影响，未布局布线，不声明新的频率；未替换生产实现。

证据：[结果](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/k2u2_lanes_only_20260927_v1/result.json)、[范围检查](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/k2u2_lanes_only_20260927_v1/experiment/scope_audit.json)、[网表结构检查](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/k2u2_lanes_only_20260927_v1/experiment/netlist_equivalence.json)、[修改补丁](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/k2u2_lanes_only_20260927_v1/implementation.patch)。

复测：在候选快照运行模型、单元及完整回归后，执行 `python3 scripts/v42_external_synth.py <新标签> --core-only`。范围检查脚本需要本地保留基线 Git 提交；网表检查脚本接受基线和候选 EDIF 路径。

## 补充实验：仅 U2 轮对计数器特化

候选 `k2u2_pair_counter_20260927_v1` 也从 `b4816c0` 独立建立，未叠加 lane 展开。只将 sponge 的步进 2 轮索引改为 0～11 轮对索引，并将完成判断改成 `pair_index == 11`；保留原两个 Keccak 实例、常量译码和层次约束，保留 `round_index={pair_index,1'b0}` 供原数据路径和测试观察。其余生产 RTL 逐字节一致。

结果仍为 **20,154 LUT、9,340 FF、1,456 LUTRAM、6206 等效 Slice**；两个 lane 及 sponge 的分层资源数也与基线相同。完整功能回归项目与上一项一致，六组输出和计算周期不变，统计关闭审计通过。

基线 EDIF 中已不存在 `round_index_reg[0]`，仅保留 `[1]`～`[4]`；候选改为 `pair_index_reg[0]`～`[3]`，两者实际都使用 4 位计数寄存器。因此源码由 5 位改为 4 位并未减少 FF，完成判断改写也未带来本次综合面积收益。此结论基于实际资源测量，不把资源数相同视为该候选的网表结构等价证明。

本项也止于综合诊断，未测布局布线频率、未替换生产实现。两项单变量实验排除了 lane 展开和单独轮对计数改写的面积增量；此前组合候选的增加仍需进一步隔离双轮常量译码及跨层次映射，不能归因于 generate 本身，也不能据此认为所有特化空间都已耗尽。

证据：[结果](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/k2u2_pair_counter_20260927_v1/result.json)、[范围检查](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/k2u2_pair_counter_20260927_v1/experiment/scope_audit.json)、[计数寄存器名称](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/k2u2_pair_counter_20260927_v1/experiment/counter_registers.json)、[修改补丁](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/k2u2_pair_counter_20260927_v1/implementation.patch)。复测使用同样的 `--core-only` 流程。

## 归档与复查

实验实现仅保存在独立工作目录和归档中，未覆盖生产 RTL，也未提交或推送。归档包含源码快照、实现差异、新测试源码、全部功能回归、核心综合网表与资源报告、面积门槛结果及逐文件 SHA-256。

- 候选一：[k2u2_fixed_20260927_v2](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/k2u2_fixed_20260927_v2/result.json)；[实现差异](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/k2u2_fixed_20260927_v2/implementation.patch)。
- 候选二：[k2u2_feedback_20260927_v2](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/k2u2_feedback_20260927_v2/result.json)；[实现差异](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/k2u2_feedback_20260927_v2/implementation.patch)。

机器可读汇总：[k2u2_specialization.json](../../manifests/experiments/unified_hbs_v4.2/external_job_message/k2u2_specialization.json)。当前有效 PPA：[Current_PPA.md](Current_PPA.md)。

复测时解包相应源码快照，先运行单元与完整 RTL 回归，再执行 `python3 scripts/v42_external_synth.py <新标签> --max-core-slices 6206`。终端仅输出阶段摘要，完整 Vivado 输出写入候选目录的 `synth.log`。
