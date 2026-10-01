# 各参数集操作周期

当前 K2U2 实现，单位为时钟周期。统一统计复位释放至操作完成的**总周期**，包含启动及结束开销，无外部输入等待；Sign/Verify 使用仓库的 1 字节消息测试向量。签名和消息内容变化可能改变 Verify 周期。

| SLH-SHAKE 参数集 | Keygen | Sign | Verify |
|---|---:|---:|---:|
| 128f | 29,867 | 729,988 | 84,040 |
| 128s | 1,909,787 | 15,317,511 | 29,323 |
| 192f | 43,659 | 1,249,496 | 118,019 |
| 192s | 2,792,475 | 29,016,923 | 42,553 |
| 256f | 115,771 | 2,579,241 | 123,463 |
| 256s | 1,851,931 | 27,069,762 | 62,966 |

Keygen/Sign 的核内计算周期为表中数值减 5；Verify 使用现有 testbench 的总周期计数。

数据来自当前已验收版本 `lut21k_20261002_v1_route_alias` 的 [Keygen/Sign 仿真](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/lut21k_20261002_v1_route_alias/simulation.json)及 [Verify 仿真](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/lut21k_20261002_v1_route_alias/verify/results.json)。已通过面积与完整回归验收。
