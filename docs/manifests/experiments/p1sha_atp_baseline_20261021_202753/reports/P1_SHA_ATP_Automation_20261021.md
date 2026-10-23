# P1／SHA 后台测量与最终路由协调

更新时间：2026-10-21T21:49:47+08:00；阶段：`complete`；PID：2604577。

C3/C4的六个目标点（SHAKE/SHA2 P1U1、P1U2，SHA2 P4U1、P4U2）完成18项完整Sign、六点100MHz诊断、36组正常/综合视图功能验证后自动启动最终路由。P12U1附加诊断不阻塞。U1固定150MHz、U2固定100MHz，不降频、不搜索、不加时序例外。

对C3/C4计算四个P1配置三算法假定ATP比的几何均值，以及四点诊断路径比的几何均值；二者均被另一候选支配的候选不重复布线，存在取舍时保留两者，各自六点。C2作为归因中间候选额外检查；若其两项P1指标均支配已选候选，就替换被支配者，仍最多两份源码/十二点路由。这是选择实验范围的规则，不是最终Fmax或ATP结论；最终按实际STA和布线ATP评估。

| 候选 | 就绪 | 尚待项 | 失败项 |
|---|---|---:|---:|
| candidate_20261021_203456 | True | 0 | 0 |
| candidate_20261021_203556 | True | 0 | 0 |
| candidate_20261021_204522 | True | 0 | 0 |

| 候选 | P1假定ATP几何均值比 | P1诊断路径几何均值比 | 选中 |
|---|---:|---:|---|
| C2_P1_feedback_sha2_list_fetch | 0.984770 | 0.936739 | False |
| C3_P1_list_fetch_small_K_table | 0.982920 | 0.912567 | True |
| C4_P1_list_fetch_small_K_plain_add_final_flag | 0.990942 | 0.973880 | False |

[candidate_20261021_203556最终物理报告](docs/manifests/experiments/p1sha_atp_candidate_20261021_203556/reports/P1_SHA_Fixed_Targets_20261021_203556.md)；状态：`{"passed": 2, "target_not_met": 4}`。

长任务保留后台。全机跨进程预约包含Vivado wrapper与实际进程并去重，最多12个、每进程2线程。所有冻结源码、逐项证据和控制器升级记录保留；原矩阵进程不终止。
