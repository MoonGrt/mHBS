# C3基础 P1／SHA 时序与ATP优化

更新时间：2026-10-22T15:33:20+08:00。

唯一基线为上一轮冻结C3：21项完整Sign、7点100MHz common诊断、36组正常/综合视图验证全部通过。本轮逐文件、日志和报告SHA核对后复用这些实测基线，不重新解释为旧B0或旧omega工作量。C3的指定频率路由继续后台，物理结果单列；负WNS不外推Fmax。

候选默认18项完整Sign与六点100MHz诊断：SHAKE/SHA2的P1U1、P1U2，SHA2的P4U1、P4U2。目标U1=150MHz，U2=100MHz；可选P12诊断仅作兼容补充，不阻塞六目标点路由门禁。最终路由需要独立命令、36组source-bound功能验证和目标点Sign/诊断全通过，最多两候选各六点；不搜索或自动降频。

器件xc7a200tffg1156-3，Vivado2025.2，common OOC、默认时序驱动、SYNTHESIS统计裁剪，每工具两线程。全机顶层Vivado最多12，wrapper/实际进程去重，SYNTH_DESIGN_PARENT内部worker不算独立job；旧任务保留。等效Slice=LUT/4+FF/8+232.4×BRAM36+102.4×DSP；100MHz面积和路径仅为诊断。

## SHAKE common诊断面积

| 候选 | 配置 | LUT | FF | BRAM36 | 等效Slice | 相对C3% | 路径ns | 状态 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| C3基线 | P1U1 | 18,063.000 | 6,229.000 | 0.000 | 5,294.375 | 0.000 | 6.245 | passed |
| C3基线 | P1U2 | 20,368.000 | 6,212.000 | 0.000 | 5,868.500 | 0.000 | 6.712 | passed |
| D1_stream_mode_randomizer_lookaheadK | P1U1 | 17,555.000 | 6,225.000 | 0.000 | 5,166.875 | -2.408 | 6.867 | passed |
| D1_stream_mode_randomizer_lookaheadK | P1U2 | 19,652.000 | 6,230.000 | 0.000 | 5,691.750 | -3.012 | 6.651 | passed |
| D2_stream_words_preparedH_shared_output_static_scheduler | P1U1 | 18,051.000 | 6,236.000 | 0.000 | 5,292.250 | -0.040 | 5.829 | passed |
| D2_stream_words_preparedH_shared_output_static_scheduler | P1U2 | 20,004.000 | 6,215.000 | 0.000 | 5,777.875 | -1.544 | 5.485 | passed |

## SHA2 common诊断面积

| 候选 | 配置 | LUT | FF | BRAM36 | 等效Slice | 相对C3% | 路径ns | 状态 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| C3基线 | P1U1 | 14,764.000 | 7,332.000 | 0.000 | 4,607.500 | 0.000 | 6.552 | passed |
| C3基线 | P1U2 | 16,205.000 | 7,344.000 | 0.000 | 4,969.250 | 0.000 | 9.340 | passed |
| C3基线 | P4U1 | 24,507.000 | 12,733.000 | 0.000 | 7,718.375 | 0.000 | 7.187 | passed |
| C3基线 | P4U2 | 28,267.000 | 12,701.000 | 0.000 | 8,654.375 | 0.000 | 9.530 | passed |
| C3基线 | P12U1 | 45,850.000 | 27,529.000 | 0.000 | 14,903.625 | 0.000 | 12.630 | passed |
| D1_stream_mode_randomizer_lookaheadK | P1U1 | 14,878.000 | 7,601.000 | 0.500 | 4,785.825 | 3.870 | 6.303 | passed |
| D1_stream_mode_randomizer_lookaheadK | P1U2 | 15,863.000 | 7,639.000 | 0.500 | 5,036.825 | 1.360 | 9.394 | passed |
| D1_stream_mode_randomizer_lookaheadK | P4U1 | 25,472.000 | 13,113.000 | 0.000 | 8,007.125 | 3.741 | 8.077 | passed |
| D1_stream_mode_randomizer_lookaheadK | P4U2 | 27,464.000 | 13,205.000 | 0.000 | 8,516.625 | -1.592 | 8.741 | passed |
| D2_stream_words_preparedH_shared_output_static_scheduler | P1U1 | 15,913.000 | 7,347.000 | 0.000 | 4,896.625 | 6.275 | 5.874 | passed |
| D2_stream_words_preparedH_shared_output_static_scheduler | P1U2 | 16,193.000 | 7,355.000 | 0.500 | 5,083.825 | 2.306 | 9.753 | passed |
| D2_stream_words_preparedH_shared_output_static_scheduler | P4U1 | 25,308.000 | 12,712.000 | 0.000 | 7,916.000 | 2.560 | 6.806 | passed |
| D2_stream_words_preparedH_shared_output_static_scheduler | P4U2 | 27,248.000 | 12,838.000 | 0.000 | 8,416.750 | -2.746 | 8.726 | passed |

## slh_128f 完整Sign

| 候选 | 后端／配置 | 周期 | C3周期 | 变化% | 假设时间ms | 假设ATP | ATP变化% | 实际MHz | 布线ATP | 状态 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| D1_stream_mode_randomizer_lookaheadK | shake/P1U1 | 2,619,846.000 | 2,619,846.000 | 0.000 | 17.466 | 90,242.779 | -2.408 | 149.993 | 90,932.851 | passed |
| D1_stream_mode_randomizer_lookaheadK | shake/P1U2 | 1,352,154.000 | 1,352,154.000 | 0.000 | 13.522 | 76,961.225 | -3.012 | 100.000 | 76,290.219 | passed |
| D1_stream_mode_randomizer_lookaheadK | sha2/P1U1 | 15,077,862.000 | 15,077,862.000 | 0.000 | 100.519 | 481,066.726 | 3.870 | — | — | passed |
| D1_stream_mode_randomizer_lookaheadK | sha2/P1U2 | 8,312,038.000 | 8,312,038.000 | 0.000 | 83.120 | 418,662.808 | 1.360 | 100.000 | 417,260.152 | passed |
| D1_stream_mode_randomizer_lookaheadK | sha2/P4U1 | 4,216,672.000 | 4,216,672.000 | 0.000 | 28.111 | 225,089.465 | 3.741 | — | — | passed |
| D1_stream_mode_randomizer_lookaheadK | sha2/P4U2 | 2,357,216.000 | 2,357,216.000 | 0.000 | 23.572 | 200,755.247 | -1.592 | — | — | passed |
| D2_stream_words_preparedH_shared_output_static_scheduler | shake/P1U1 | 2,619,846.000 | 2,619,846.000 | 0.000 | 17.466 | 92,432.533 | -0.040 | 149.993 | 91,199.216 | passed |
| D2_stream_words_preparedH_shared_output_static_scheduler | shake/P1U2 | 1,352,154.000 | 1,352,154.000 | 0.000 | 13.522 | 78,125.768 | -1.544 | 100.000 | 77,873.929 | passed |
| D2_stream_words_preparedH_shared_output_static_scheduler | sha2/P1U1 | 15,077,862.000 | 15,077,862.000 | 0.000 | 100.519 | 492,204.240 | 6.275 | — | — | passed |
| D2_stream_words_preparedH_shared_output_static_scheduler | sha2/P1U2 | 8,312,038.000 | 8,312,038.000 | 0.000 | 83.120 | 422,569.466 | 2.306 | 100.000 | 419,317.381 | passed |
| D2_stream_words_preparedH_shared_output_static_scheduler | sha2/P4U1 | 4,216,672.000 | 4,216,672.000 | 0.000 | 28.111 | 222,527.837 | 2.560 | — | — | passed |
| D2_stream_words_preparedH_shared_output_static_scheduler | sha2/P4U2 | 2,357,216.000 | 2,357,216.000 | 0.000 | 23.572 | 198,400.978 | -2.746 | — | — | passed |

## xmss_h10 完整Sign

| 候选 | 后端／配置 | 周期 | C3周期 | 变化% | 假设时间ms | 假设ATP | ATP变化% | 实际MHz | 布线ATP | 状态 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| D1_stream_mode_randomizer_lookaheadK | shake/P1U1 | 86,567,075.000 | 86,567,075.000 | 0.000 | 577.114 | 2,981,875.038 | -2.408 | 149.993 | 3,004,676.982 | passed |
| D1_stream_mode_randomizer_lookaheadK | shake/P1U2 | 45,385,295.000 | 45,385,295.000 | 0.000 | 453.853 | 2,583,217.528 | -3.012 | 100.000 | 2,560,695.076 | passed |
| D1_stream_mode_randomizer_lookaheadK | sha2/P1U1 | 497,855,675.000 | 497,855,675.000 | 0.000 | 3,319.038 | 15,884,334.239 | 3.870 | — | — | passed |
| D1_stream_mode_randomizer_lookaheadK | sha2/P1U2 | 273,817,819.000 | 273,817,819.000 | 0.000 | 2,738.178 | 13,791,724.362 | 1.360 | 100.000 | 13,745,517.605 | passed |
| D1_stream_mode_randomizer_lookaheadK | sha2/P4U1 | 130,829,618.000 | 130,829,618.000 | 0.000 | 872.197 | 6,983,794.034 | 3.741 | — | — | passed |
| D1_stream_mode_randomizer_lookaheadK | sha2/P4U2 | 72,787,666.000 | 72,787,666.000 | 0.000 | 727.877 | 6,199,052.559 | -1.592 | — | — | passed |
| D2_stream_words_preparedH_shared_output_static_scheduler | shake/P1U1 | 86,567,075.000 | 86,567,075.000 | 0.000 | 577.114 | 3,054,230.684 | -0.040 | 149.993 | 3,013,478.408 | passed |
| D2_stream_words_preparedH_shared_output_static_scheduler | shake/P1U2 | 45,385,295.000 | 45,385,295.000 | 0.000 | 453.853 | 2,622,305.613 | -1.544 | 100.000 | 2,613,852.602 | passed |
| D2_stream_words_preparedH_shared_output_static_scheduler | sha2/P1U1 | 497,855,675.000 | 497,855,675.000 | 0.000 | 3,319.038 | 16,252,083.631 | 6.275 | — | — | passed |
| D2_stream_words_preparedH_shared_output_static_scheduler | sha2/P1U2 | 273,817,819.000 | 273,817,819.000 | 0.000 | 2,738.178 | 13,920,418.737 | 2.306 | 100.000 | 13,813,287.515 | passed |
| D2_stream_words_preparedH_shared_output_static_scheduler | sha2/P4U1 | 130,829,618.000 | 130,829,618.000 | 0.000 | 872.197 | 6,904,315.041 | 2.560 | — | — | passed |
| D2_stream_words_preparedH_shared_output_static_scheduler | sha2/P4U2 | 72,787,666.000 | 72,787,666.000 | 0.000 | 727.877 | 6,126,355.878 | -2.746 | — | — | passed |

## lms_h10 完整Sign

| 候选 | 后端／配置 | 周期 | C3周期 | 变化% | 假设时间ms | 假设ATP | ATP变化% | 实际MHz | 布线ATP | 状态 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| D1_stream_mode_randomizer_lookaheadK | shake/P1U1 | 28,524,614.000 | 28,524,614.000 | 0.000 | 190.164 | 982,554.100 | -2.408 | 149.993 | 990,067.541 | passed |
| D1_stream_mode_randomizer_lookaheadK | shake/P1U2 | 15,123,590.000 | 15,123,590.000 | 0.000 | 151.236 | 860,796.934 | -3.012 | 100.000 | 853,291.852 | passed |
| D1_stream_mode_randomizer_lookaheadK | sha2/P1U1 | 81,162,706.000 | 81,162,706.000 | 0.000 | 541.085 | 2,589,536.716 | 3.870 | — | — | passed |
| D1_stream_mode_randomizer_lookaheadK | sha2/P1U2 | 44,805,522.000 | 44,805,522.000 | 0.000 | 448.055 | 2,256,775.733 | 1.360 | 100.000 | 2,249,214.802 | passed |
| D1_stream_mode_randomizer_lookaheadK | sha2/P4U1 | 22,945,096.000 | 22,945,096.000 | 0.000 | 152.967 | 1,224,828.345 | 3.741 | — | — | passed |
| D1_stream_mode_randomizer_lookaheadK | sha2/P4U2 | 12,812,616.000 | 12,812,616.000 | 0.000 | 128.126 | 1,091,202.457 | -1.592 | — | — | passed |
| D2_stream_words_preparedH_shared_output_static_scheduler | shake/P1U1 | 28,524,614.000 | 28,524,614.000 | 0.000 | 190.164 | 1,006,395.923 | -0.040 | 149.993 | 992,967.689 | passed |
| D2_stream_words_preparedH_shared_output_static_scheduler | shake/P1U2 | 15,123,590.000 | 15,123,590.000 | 0.000 | 151.236 | 873,822.126 | -1.544 | 100.000 | 871,005.357 | passed |
| D2_stream_words_preparedH_shared_output_static_scheduler | sha2/P1U1 | 81,162,706.000 | 81,162,706.000 | 0.000 | 541.085 | 2,649,488.902 | 6.275 | — | — | passed |
| D2_stream_words_preparedH_shared_output_static_scheduler | sha2/P1U2 | 44,805,522.000 | 44,805,522.000 | 0.000 | 448.055 | 2,277,834.329 | 2.306 | 100.000 | 2,260,304.168 | passed |
| D2_stream_words_preparedH_shared_output_static_scheduler | sha2/P4U1 | 22,945,096.000 | 22,945,096.000 | 0.000 | 152.967 | 1,210,889.200 | 2.560 | — | — | passed |
| D2_stream_words_preparedH_shared_output_static_scheduler | sha2/P4U2 | 12,812,616.000 | 12,812,616.000 | 0.000 | 128.126 | 1,078,405.857 | -2.746 | — | — | passed |

## C3基线与候选的指定频率物理证据

| 候选 | 后端／配置 | 目标MHz | 布线Slice | WNS ns | WHS ns | 状态 |
|---|---|---:|---:|---:|---:|---|
| C3基线 | shake/P1U1 | 150.000 | 5,360.750 | -0.010 | 0.116 | target_not_met |
| C3基线 | shake/P1U2 | 100.000 | 5,851.375 | 0.208 | 0.141 | passed |
| C3基线 | sha2/P1U1 | 150.000 | 4,613.375 | -0.083 | 0.109 | target_not_met |
| C3基线 | sha2/P1U2 | 100.000 | 4,985.125 | -0.313 | 0.096 | target_not_met |
| C3基线 | sha2/P4U1 | 150.000 | 7,968.750 | -1.118 | 0.096 | target_not_met |
| C3基线 | sha2/P4U2 | 100.000 | 8,661.250 | 0.008 | 0.096 | passed |
| D1_stream_mode_randomizer_lookaheadK | shake/P1U1 | 150.000 | 5,206.125 | 0.066 | 0.141 | passed |
| D1_stream_mode_randomizer_lookaheadK | shake/P1U2 | 100.000 | 5,642.125 | 0.386 | 0.130 | passed |
| D1_stream_mode_randomizer_lookaheadK | sha2/P1U1 | 150.000 | 4,703.625 | -0.460 | 0.108 | target_not_met |
| D1_stream_mode_randomizer_lookaheadK | sha2/P1U2 | 100.000 | 5,019.950 | 0.063 | 0.130 | passed |
| D1_stream_mode_randomizer_lookaheadK | sha2/P4U1 | 150.000 | 8,145.125 | -0.879 | 0.094 | target_not_met |
| D1_stream_mode_randomizer_lookaheadK | sha2/P4U2 | 100.000 | 8,482.250 | -0.105 | 0.094 | target_not_met |
| D2_stream_words_preparedH_shared_output_static_scheduler | shake/P1U1 | 150.000 | 5,221.375 | 0.020 | 0.111 | passed |
| D2_stream_words_preparedH_shared_output_static_scheduler | shake/P1U2 | 100.000 | 5,759.250 | 0.973 | 0.134 | passed |
| D2_stream_words_preparedH_shared_output_static_scheduler | sha2/P1U1 | 150.000 | 4,904.625 | -0.063 | 0.108 | target_not_met |
| D2_stream_words_preparedH_shared_output_static_scheduler | sha2/P1U2 | 100.000 | 5,044.700 | 0.079 | 0.113 | passed |
| D2_stream_words_preparedH_shared_output_static_scheduler | sha2/P4U1 | 150.000 | 8,067.125 | -0.854 | 0.094 | target_not_met |
| D2_stream_words_preparedH_shared_output_static_scheduler | sha2/P4U2 | 100.000 | 8,384.875 | -0.121 | 0.094 | target_not_met |

基线源码：`d9fa5f48eecf03241200b32b0352641565a62a2ddbcd7dda1c0964e463d14f14`；参考C3源码：`b96cb542044c062f8623ac69cdcf25b6d7bc26a3fa0da1038df099fc70aaa7f1`。

每候选归档冻结RTL/support、控制器、分层与时序、源码SHA及Vivado日志；仿真/验证详细日志留运行目录。不生成CSV或归档README，不执行h20完整Keygen/Sign。
