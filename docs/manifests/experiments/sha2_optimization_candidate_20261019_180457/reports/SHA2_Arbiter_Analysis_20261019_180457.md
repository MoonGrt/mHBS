# SHA2 轮询仲裁候选2

候选1使用共享64位／128位固定窗口消除了大部分逐字节格式化逻辑。候选2继续处理P12U1的`need_block→标签选择→长度／掩码控制`路径：以游标后的资格掩码、最低有效位选择和one-hot编码替换动态环形索引扫描，保留原轮询顺序和寄存边界。只修改sha2-recipe.sv的仲裁与声明位置，不改变格式化数据路径。

候选2recipe SHA256：`ef7948df9d287c1d5b400e20cd5b10f551c30272d1f6753e5e046444bb9820d0`。

完整Sign：{'pending': 0, 'running': 0, 'passed': 9, 'failed': 0}；逐点周期核对：{'required': 9, 'checked': 9, 'cycle_equal': True, 'workload_equal': True, 'complete': True, 'comparison_run': '/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/sha2_optimization/candidate_20261019_175821'}。

| 配置 | 候选1 Slice | 候选2 Slice | 面积变化 % | 候选1路径 ns | 候选2路径 ns | 候选2WNS ns | 状态 |
|---|---:|---:|---:|---:|---:|---:|---|
| P1U1 | 4,876.250 | 4,821.125 | -1.130 | 7.712 | 7.712 | 2.311 | passed |
| P4U1 | 8,324.725 | 8,774.725 | 5.406 | 7.927 | 8.031 | 1.928 | passed |
| P12U1 | 13,803.525 | 14,449.750 | 4.682 | 10.935 | 10.178 | -0.219 | passed |

面积均为同配置common，等效Slice = LUT/4 + FF/8 + 232.4×BRAM36 + 102.4×DSP。报告固定100MHz假定ATP；综合路径只是低频诊断，尚无本轮布局布线结论。

本候选重新验证实际生产RTL仲裁：P1/2/3/4/6/8/12全部合法游标与请求掩码穷举，P24为边界和固定种子随机测试，共306,754组，检查valid、标签及one-hot选择。它是两态组合等价检查，未覆盖不可达游标或X传播。另有P4U1/P12U1/P4U2共36组批配方及P4U1三目标完整Sign通过；局部P12批测试使用4个同时活动标签，全核P12 Sign按真实上下文调度另外测量。

候选1的764项配方、9项鲁棒性、4条ACVP签名及3个SYNTHESIS Sign证据仍归属候选1的源码，本轮未重跑这些集合，不把其结果改记到候选2。两候选的SHA256、SHAKE和executor源码相同；既有双后端长回归继续后台运行，h20完整Keygen／Sign未启动。

逐算法周期、原始基线ATP以及候选1的逐点对照见[测量报告](SHA2_Optimization_20261019_180457.md)。

候选1完整验证见[候选1分析](../../sha2_optimization_candidate_20261019_175821/reports/SHA2_Formatter_Analysis_20261019_175821.md)。


最终取舍：撤回候选2，保留全部冻结证据，工作区恢复候选1。详见[阶段记录](SHA2_Optimization_Stages.md)及FINAL_SELECTION.json。
