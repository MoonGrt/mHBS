# P12U1 / P4U1 / P1U1 Sign 优化证据

最终候选为 `20261014_113650`，基线为 `20261014_110400`。完整结论见 [报告](../../../report/ATP_Focus_P12_P4_P1_20261014.md)。

- `SOURCE.json`、`BASELINE_SOURCE.json`：两份冻结源码、工具版本及逐文件SHA-256。
- `VALIDATION.json`、`SOURCE_AUDIT.json`：最终70组补充验证、四种宏视图审计及日志校验。
- `MEASUREMENTS.json`：归档时的三点九项面积、周期、Hash/置换数、假定150MHz ATP和逐阶段结果。
- `EXPERIMENTS.json`：各独立实验的标签和运行目录；不是按配置选择不同RTL。
- `evidence.tar.gz`：基线/最终完整源码与向量，三点综合报告和日志、实际网表诊断裁剪审计、最终验证日志，以及未选候选RTL和结果快照。
- `CHECKPOINTS.json`：基线/最终综合检查点的本地路径和校验；较大的DCP保留在对应build目录。
- `final_rtl.patch`：相对于提交 `ace6310` 的最终RTL差异。
- `SHA256.json`：归档文件的SHA-256。报告生成器为 `scripts/report_atp_focus.py`，复现参数见 `EXPERIMENTS.json`。

最终候选和基线均已完成。旧 `onehot_phase` 候选的P12综合在归档时超时，仅跳过分析并保持后台运行；其面积没有用于最终结论。归档为当时证据快照，后台任务完成后会补齐报告的逐阶段表。

面积为完整运行时common共同核，不含外部ROM和签名缓存；ATP按150MHz假定频率计算。本轮没有布线STA测量，不能据此声明150MHz已闭合。XMSS/LMS h20完整Keygen、Sign未恢复。
