# SHA2 优化候选阶段与最终取舍

最终保留候选1：工作区全部RTL及sources.txt已与候选1冻结清单逐字节核验一致。候选2已完整测量后撤回，冻结源码、验证和综合证据全部保留。

| 阶段 | 状态 | 验证与测量 | 记录 |
|---|---|---|---|
| 原始基线 | 已完成 | 9/9 Sign、3/3 common综合；逐字节动态formatter | [基线](../../sha2_optimization_baseline_20261019_174711/reports/SHA2_Optimization_20261019_174711.md) |
| 候选1 | **retained** | 9/9 Sign、3/3 common综合；共享64/128位固定窗口，九项假设100MHz ATP全部改善 | [测量](../../sha2_optimization_candidate_20261019_175821/reports/SHA2_Optimization_20261019_175821.md)／[归因](../../sha2_optimization_candidate_20261019_175821/reports/SHA2_Formatter_Analysis_20261019_175821.md) |
| 候选2 | **discarded** | 9/9 Sign、3/3 common综合；并行轮询仲裁，全部周期与候选1严格一致 | [测量](../../sha2_optimization_candidate_20261019_180457/reports/SHA2_Optimization_20261019_180457.md)／[归因](../../sha2_optimization_candidate_20261019_180457/reports/SHA2_Arbiter_Analysis_20261019_180457.md) |

| 配置 | 候选1 Slice | 候选2 Slice | 候选2面积／假设ATP变化 | 候选1综合路径 | 候选2综合路径 |
|---|---:|---:|---:|---:|---:|
| P1U1 | 4,876.250 | 4,821.125 | -1.130% | 7.712ns | 7.712ns |
| P4U1 | 8,324.725 | 8,774.725 | +5.406% | 7.927ns | 8.031ns |
| P12U1 | 13,803.525 | 14,449.750 | +4.682% | 10.935ns | 10.178ns |

候选2的P1面积略降，但P4面积上升5.406%、综合路径变长1.312%；P12面积上升4.682%。P12综合路径有所改善，但不能据此假定布线频率更高并抵消固定频率ATP回退。因此保留九项原始基线对比均改善的候选1。

面积统一取common：等效Slice = LUT/4 + FF/8 + 232.4×BRAM36 + 102.4×DSP。两个候选均在100MHz、OOC、默认时序驱动设置下综合，未启动布局布线。固定100MHz ATP为假设频率指标，面积×周期×综合路径为诊断指标。

候选1 recipe SHA256：`798454974b2eb7ce98cafba2838e54f4f0961b8cfb9f2546c19216ac14874f81`。候选2 recipe SHA256：`ef7948df9d287c1d5b400e20cd5b10f551c30272d1f6753e5e046444bb9820d0`。当前源码绑定与未舍入比较保存于本实验目录的FINAL_SELECTION.json。

候选1的ACVP／鲁棒性证据保持原源码归属，候选2另有实际RTL仲裁等价和批配方验证。此前双后端大树回归继续后台运行，不能据本轮九项测量宣称全部大树回归完成。h20完整Keygen／Sign未启动。
