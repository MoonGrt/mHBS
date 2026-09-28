# Verify 面积优化结果

本文为上一轮历史记录。当前面积与接口见 [进一步优化报告](Redundancy_Optimization.md)。

保留 `verify_area_compare_20260927_v1`，当前共同核 **6675.000 等效 Slice**，相对原 Verify 版本 6768.125 减少 **93.125（1.38%）**。本轮未布局布线，不声明新频率。

## 单变量候选

| 候选 | 改动 | LUT | FF | 等效 Slice | 相对父版本 | 处理 |
|---|---|---:|---:|---:|---:|---|
| `verify_area_input_20260927_v1` | 输入节点复用输出暂存 | 22037 | 9599 | 6709.125 | -59.000 | 保留 |
| `verify_area_feedback_20260927_v1` | 链输入复用结果寄存器 | 22064 | 9353 | 6685.125 | -24.000 | 保留 |
| `verify_area_compare_20260927_v1` | 根比较改成分段比较 | 22025 | 9350 | 6675.000 | -10.125 | 保留 |

各候选均为独立快照，并在前一保留版本上只增加一项 RTL 改动。最终 FF 为 9350，比原 Verify 少 519。实际 EDIF 确认独立 verify_node 消失，task_left 只保留父节点所需的 256 位；LUTRAM 仍为 1456，BRAM/DSP 均为 0。

## 行为与验证

- 输入仍为外部节点 valid/ready；节点接受时刻、Keygen/Sign/Verify 结果和原正常执行周期均保持一致。Keccak、hash lane、compact chain、微码和存储模块源码逐字节不变。
- 每个候选通过 65 项 Verify 测试、原 6 组正常执行、33 项扩展、6 组共同核对照、12 组统计关闭对照、2 项统计关闭扩展和 6 项异常退出；另通过 13 项合约检查、lint 和 12 项 RTL 单元门禁。
- 新增双链步数不对称、单侧及双侧零步覆盖，并逐字节检查零步端点保持；覆盖第二节点延迟、认证路径左右方向、复位前脏节点、节点未用高位、公钥分段错误和公钥未用高位。
- 128f/192f 原正常向量不包含双侧零步；测试用独立软件 verifier 校验的确定性消息变异补齐，256f 正常向量也覆盖该场景。没有通过强制 DUT 内部数据制造覆盖。
- 分段比较候选还对实际 RTL 比较表达式执行 1155 项独立字节级对照，包含每个参数宽度下全部 256 个单比特差异及随机字组，确认活动位比较和未用高位忽略语义。
- 与原 Verify 的 45 个非故障用例逐项比较 accepted、节点数、Hash/置换次数及扣除输入等待后的周期：次数完全一致，周期不增加。原六组 Keygen/Sign 仍逐字节、逐周期匹配 prune 基线。
- 综合显式 PROFILE_ENABLE=0，实际统计寄存器裁剪审计通过。完整 Vivado 日志落盘，终端只显示阶段摘要。

## 证据

- [verify_area_input_20260927_v1](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/verify_area_input_20260927_v1/result.json)：源码快照、增量补丁、完整回归、资源报告、寄存器清单及逐文件 SHA-256。
- [verify_area_feedback_20260927_v1](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/verify_area_feedback_20260927_v1/result.json)：源码快照、增量补丁、完整回归、资源报告、寄存器清单及逐文件 SHA-256。
- [verify_area_compare_20260927_v1](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/verify_area_compare_20260927_v1/result.json)：源码快照、增量补丁、完整回归、资源报告、寄存器清单及逐文件 SHA-256。

机器可读汇总：[verify_area.json](../../manifests/experiments/unified_hbs_v4.2/external_job_message/verify_area.json)。未提交或推送。
