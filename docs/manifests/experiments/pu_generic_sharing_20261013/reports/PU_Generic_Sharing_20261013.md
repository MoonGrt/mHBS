# 通用 P/U 执行、统计宏与资源复用（2026-10-13）

更新时间：2026-10-14T10:38:30+08:00。验收：未通过。

删除 P4U1 独占分支，所有合法 P/U 使用统一固定引擎、滚动链、并行 L-tree、128位流式生产和 FORS 四叶微组。P1 复用原迭代 Keccak 状态。统计直接用 SYNTHESIS 宏裁剪，统计端口保持64位并在综合时置零。

端点RAM容量保持136×256位：0～66链端点/FORS根，67保护槽，68～87树栈，88～107认证路径，108～111保留，112～135 FORS暂存。认证与树栈同拍写冲突增加一拍，签名缓存与XMSS的三个同时存活银行保持独立。

冻结候选及矩阵：[矩阵报告](/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/docs/manifests/experiments/pu_sign_matrix_20261013_203826/reports/PU_Sign_Matrix_20261013_203826.md)；[源码清单](/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/pu_sign_matrix/20261013_203826/SOURCE.json)。

面积使用每个P/U的common；外部ROM、完整签名缓存和板级I/O不计入。矩阵ATP按U1=150MHz、U2=110MHz假定计算。布线结果另列，不能把假定频率当作闭合频率。

| 算法 | 基线最佳 | 基线 ATP Slice·ms | 候选最佳 | 候选 ATP Slice·ms | 变化 |
|---|---|---:|---|---:|---:|
| slh_128f | P12U1 | 37301.109654 | P12U1 | 30816.216963 | -17.39% |
| xmss_h10 | P4U1 | 1406294.883875 | P24U1 | 746238.732360 | -46.94% |
| lms_h10 | P24U1 | 344979.115635 | P24U1 | 309247.967535 | -10.36% |

矩阵未全部完成时，上表候选排名为暂定值；最终验收要求其余已测配置通过、三个已测配置中的最佳ATP均不回退且至少一个降低；异常配置继续后台运行，其结果未完成时不参与面积与ATP排名。

| 检查 | 状态 | 日志 |
|---|---|---|
| full32 | passed | [full32.log](/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/pu_generic/20261013_201408/audit/full32.log) |
| standard_models | passed | [standard_models.log](/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/pu_generic/20261013_201408/audit/standard_models.log) |
| compatibility | passed | [compatibility.log](/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/pu_generic/20261013_201408/audit/compatibility.log) |
| extended | passed | [extended.log](/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/pu_generic/20261013_201408/audit/extended.log) |
| route/baseline/P12U1 | passed | [route_baseline_P12U1.log](/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/pu_generic/20261013_201408/audit/route_baseline_P12U1.log) |
| route/baseline/P24U1 | failed | [route_baseline_P24U1.log](/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/pu_generic/20261013_201408/audit/route_baseline_P24U1.log) |
| route/baseline/P4U1 | passed | [route_baseline_P4U1.log](/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/pu_generic/20261013_201408/audit/route_baseline_P4U1.log) |
| route/candidate/P12U1 | passed | [route_candidate_P12U1.log](/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/pu_generic/20261013_201408/audit/route_candidate_P12U1.log) |
| route/candidate/P24U1 | failed | [route_candidate_P24U1.log](/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/pu_generic/20261013_201408/audit/route_candidate_P24U1.log) |

完整回归为十个非h20配置的三操作加两个h20 Verify，共32项；h20完整Keygen、Sign继续停止。其他合法P/U逐项执行三算法Verify和459项独立配方。扩展回归覆盖乱序标签、捕获、停顿、复位、异常、截断、篡改、消息和填充边界及q边界。

综合采用xc7a200tffg1156-3、同工具、OOC、通用Keccak、6.666667ns约束和默认时序驱动优化，最多12个Vivado、每个2线程。旧/新胜出配置从冻结综合检查点布线；先6.666667ns，未闭合时按测得违例放宽，固定布线以0.1ns精度扫描setup和hold。未新增false-path或multicycle。OOC时钟模型结论不扩展到板级top。

| 来源/P/U | 布线等效Slice | 闭合周期 ns | STA MHz | WNS/WHS ns |
|---|---:|---:|---:|---|
| baseline/P12U1 | 16245.125 | 11.867 | 84.267 | 0.068/0.116 |
| baseline/P4U1 | 9678.875 | 12.467 | 80.212 | 0.019/0.108 |
| candidate/P12U1 | 15888.750 | 12.567 | 79.573 | 0.062/0.138 |

| 算法 | 基线布线ATP Slice·ms | 候选布线ATP Slice·ms | 变化 |
|---|---:|---:|---:|
| slh_128f | 65930.103340 | 57508.285733 | -12.77% |

P4U1逐步对照：

| 阶段 | LUT | FF | 等效Slice | SLH Sign周期 | XMSS Sign周期 | LMS Sign周期 |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 33889 | 10797 | 9821.875 | 728037 | 21476982 | 7340300 |
| macro | 34543 | 10807 | 9986.625 | 728037 | 21476982 | 7340300 |
| generic | 33049 | 10911 | 9626.125 | 727476 | 21476982 | 7340300 |
| shared_workspace | 33277 | 10912 | 9683.250 | 727562 | 21476982 | 7340300 |

工作区复用这一独立步骤在P4U1增加57.125等效Slice及86个SLH周期；最终组合相对当前标准基线面积下降1.41%，三个已测最佳ATP下降。复用并非在所有点上单独降低面积，表中保留实测代价。

[逐步JSON](/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/pu_generic/20261013_201408/steps.json)、[周期分解](/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/pu_generic/20261013_201408/profile/profile.json)、[证据清单](/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/pu_generic/20261013_201408/EVIDENCE.json)。

待解决：route/baseline/P24U1

待解决：route/candidate/P24U1
