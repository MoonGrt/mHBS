# 当前共同核面积

当前采用 `lut21k_20261002_v1_route_alias`，按用户选择保留较低的 FF 数量和等效 Slice。

| LUT（含 LUTRAM） | FF | LUTRAM | BRAM | DSP | 等效 Slice |
|---:|---:|---:|---:|---:|---:|
| **21,043** | **7,932** | 1,112 | 0 | 0 | **6252.250** |

Vivado 2025.2、xc7a200tffg1156-3、10 ns、8 线程、K2U2、PROFILE_ENABLE=0。等效 Slice = LUT/4 + FF/8，不是实际占用 Slice。本版本未测新布线频率。

## 实现与验收

固定写银行；将 392 位结果暂存改为 2 位来源选择，在原 ROUTE 周期消费稳定的来源寄存器。接口、六参数 Keygen/Sign/Verify、输出、计算周期和 Hash/置换次数不变。template 保持文件加载。

封存时通过 19 项单元、12 组正常执行、66 项扩展、12 组共同核等价、统计关闭及故障退出、130 项 Verify。结果路由 scoreboard 在 240 份执行日志中通过。

清理后删除了没有生产实例的独立根存储及其两个单元测试，保留七个 RTL 模块内容不变；当前单元入口为 17 项。面积数据继续绑定下面的原始快照，不宣称本次清理重新测量面积。

目标 LUT <21,000 尚差 44 LUT，优化已停止。旧候选报告已清理，历史结果可从 Git 恢复。

## 原始证据

- [分层面积](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/lut21k_20261002_v1_route_alias/synthesis/core_hierarchical.rpt)
- [资源报告](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/lut21k_20261002_v1_route_alias/synthesis/core_utilization.rpt)
- [完整回归审计](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/lut21k_20261002_v1_route_alias/verification.json)
- [基线比较](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/lut21k_20261002_v1_route_alias/full_comparison.json)
- [源码快照](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/lut21k_20261002_v1_route_alias/source_snapshot.tar.gz)
- [证据哈希](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/lut21k_20261002_v1_route_alias/evidence_sha256.json)

全部原始报告、DCP、源码和日志保存在 manifests，删除 build 后仍可核验：`make reproduce-v42`。
