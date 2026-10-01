# 共同核 LUT 前台优化结果

已按用户要求完成当前候选后停止，不再继续优化。按用户选择，当前采用 `lut21k_20261002_v1_route_alias`：21,043 LUT、7,932 FF。已完成完整验收并应用到生产 RTL；等效 Slice 为本轮已验收版本中的最低值。

## 当前采用结果

- **21,043 LUT、7,932 FF、1,112 LUTRAM、6252.250 等效 Slice**；BRAM/DSP 均为零。
- 相对本轮起点：LUT 减少 **1**，FF 减少 **391**，等效 Slice 减少 **49.125**。
- 相对上一采用版本（21,037 LUT / 8,325 FF）：LUT 增加 **6**，FF 减少 **393**，等效 Slice 减少 **47.625**。
- 尚未达到总 LUT <21,000，至少还需减少 **44 LUT**。本轮已停止。
- K2U2、六参数 Keygen/Sign/Verify、接口、Program16 镜像、输出、计算周期及 Hash／置换次数保持一致。template 继续使用文件加载。

## 面积对比

| 候选 | LUT（含 LUTRAM） | FF | LUTRAM | 等效 Slice | 验收结论 |
|---|---:|---:|---:|---:|---|
| 固定写银行基线 | 21044 | 8323 | 1112 | 6301.375 | 完整验收，起点 |
| 固定银行＋尾区拆分 | 21139 | 8318 | 1116 | 6324.500 | 初步通过，面积增加，拒绝 |
| 固定银行＋SHAKE 选择简化 | 21042 | 8324 | 1112 | 6301.000 | 初步通过，未完整验收、未应用 |
| 固定银行＋尾区＋SHAKE 选择简化 | 21139 | 8321 | 1116 | 6324.875 | 初步通过，面积增加，拒绝 |
| 结果暂存改为来源选择（当前） | 21043 | 7932 | 1112 | 6252.250 | 完整验收，按用户选择应用 |
| 取消 Keccak 轮层级限制 | 23078 | 8325 | 1112 | 6810.125 | 初步通过，面积增加，拒绝 |
| SHAKE 各字局部吸收 | 21087 | 8326 | 1112 | 6312.500 | 初步通过，面积增加，拒绝 |
| SHAKE 同步清零 | 21037 | 8325 | 1112 | 6299.875 | 完整验收，保留为对照 |

所有候选使用 Vivado 2025.2、xc7a200tffg1156-3、10 ns 共同核综合约束、8 线程、PROFILE_ENABLE=0。全部 BRAM/DSP 为零。等效 Slice = LUT/4 + FF/8，非实际占用 Slice；本轮未测新布线频率。

同步清零版本仍是本轮 LUT 最低的已验收版本；用户选择结果暂存版本作为当前实现，以使用更低的 FF 数量和等效 Slice。两版本证据分别保留，不混用面积数据。

## 最终改动与完整验证

保留固定写银行基线，将 392 位 `route_value` 暂存改为 2 位来源选择，在原 ROUTE 周期直接读取稳定的 result、node、saved value 或 emit 寄存器。状态转换和消费周期不变；节点值补零、Hmsg 高位解析及输出顺序不变。SHAKE 恢复该候选综合时的原实现，Keccak 层级继续保留。

- 合同检查与 lint 通过。新增结果路由 scoreboard，在原锁存边沿冻结期望值，逐拍核对 ROUTE 消费值；复位/异常时清除检查上下文。
- 路由检查在 240 份完整执行日志中通过，覆盖 lane 交换、反压、重复执行及 Verify。单元测试继续覆盖 Hmsg 高位、六参数端序、目标槽隔离和节点补零。
- 12 组软件参考证据核对、19 项单元、12 组正常执行、66 项扩展、12 组共同核拆分等价全部通过。
- 24 组统计关闭、2 项统计关闭扩展、12 项故障退出和 130 项 Verify 全部通过。
- 正常、扩展、Verify 与冻结基线逐项比较，输出、周期、Hash／置换次数和 Verify 结果一致。
- 应用前确认主工作区 RTL／测试未被并发修改，镜像和向量哈希未变；应用后八份生产 RTL 哈希与验收报告一致。

## 原始证据

- [分层面积](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/lut21k_20261002_v1_route_alias/synthesis/core_hierarchical.rpt)
- [资源报告](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/lut21k_20261002_v1_route_alias/synthesis/core_utilization.rpt)
- [完整回归审计](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/lut21k_20261002_v1_route_alias/verification.json)及[基线比较](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/lut21k_20261002_v1_route_alias/full_comparison.json)
- [源码补丁](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/lut21k_20261002_v1_route_alias/incremental.patch)、[源码快照](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/lut21k_20261002_v1_route_alias/source_snapshot.tar.gz)、[证据哈希](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/lut21k_20261002_v1_route_alias/evidence_sha256.json)
- [逐项实验与日志](../../manifests/experiments/lut21k_foreground_20261002_v1/STATUS.md)

上述源码、原始综合报告、DCP、测试日志和哈希均保存在 manifests，删除 build 后仍可审计。旧队列保持停止；本轮未启动后台调度器、未提交、未推送；选定版本的完整验收完成后保持停止。
