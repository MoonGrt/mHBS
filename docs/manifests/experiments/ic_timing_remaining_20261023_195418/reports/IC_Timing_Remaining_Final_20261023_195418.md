# i/c 时序与 Remaining 最终取舍

组装：2026-10-23T20:24:01.926736+08:00；P1U1 common，100MHz，xc7a200tffg1156-3。

选择：i=`i_software`，c=`c_control_pipeline`；采用状态：是。实际采用状态来自参数或 DECISION.json，脚本不读取生产 RTL。

本轮动态汇总 5 个候选、10 个后端验证组。缺失/未完成条目：0。基线：`ablation_route_20261023_190751`。

## SHAKE 面积与100MHz布线

等效Slice = LUT/4 + FF/8 +232.4×BRAM +102.4×DSP；综合和布线面积分别列出。

| 配置 | 综合LUT | FF | 等效Slice | 布线LUT | FF | 等效Slice | WNS ns | WHS ns | 完整路由 | DRC错误 | 100MHz接受 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline_i | 16,319 | 5,845 | 4,810.375 | 16,381 | 5,845 | 4,825.875 | -2.949 | 0.119 | 是 | 0 | 否 |
| baseline_c | 20,099 | 6,324 | 5,815.250 | 20,269 | 6,334 | 5,859.000 | -2.997 | 0.130 | 是 | 0 | 否 |
| baseline_t | 17,624 | 6,198 | 5,180.750 | 17,562 | 6,203 | 5,165.875 | 0.244 | 0.096 | 是 | 0 | 是 |
| c_control_pipeline（选择） | 20,309 | 6,465 | 5,885.375 | 20,268 | 6,465 | 5,875.125 | 0.149 | 0.116 | 是 | 0 | 是 |
| c_selective_pipeline | 20,760 | 6,515 | 6,004.375 | 20,785 | 6,515 | 6,010.625 | 0.102 | 0.131 | 是 | 0 | 是 |
| i_prefetch | 16,921 | 5,922 | 4,970.500 | 17,128 | 5,922 | 5,022.250 | -4.789 | 0.106 | 是 | 0 | 否 |
| i_software（选择） | 16,367 | 5,884 | 4,827.250 | 16,353 | 5,883 | 4,823.625 | 0.012 | 0.122 | 是 | 0 | 是 |
| i_timing_v3 | 16,640 | 5,888 | 4,896.000 | 16,536 | 5,887 | 4,869.875 | 0.043 | 0.150 | 是 | 0 | 是 |

## SHA2 面积与100MHz布线

等效Slice = LUT/4 + FF/8 +232.4×BRAM +102.4×DSP；综合和布线面积分别列出。

| 配置 | 综合LUT | FF | 等效Slice | 布线LUT | FF | 等效Slice | WNS ns | WHS ns | 完整路由 | DRC错误 | 100MHz接受 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline_i | 17,992 | 9,333 | 5,664.625 | 17,881 | 9,333 | 5,636.875 | -3.176 | 0.110 | 是 | 0 | 否 |
| baseline_c | 20,503 | 9,533 | 6,317.375 | 20,323 | 9,540 | 6,273.250 | -2.776 | 0.120 | 是 | 0 | 否 |
| baseline_t | 18,059 | 9,462 | 5,697.500 | 17,948 | 9,459 | 5,669.375 | 0.178 | 0.096 | 是 | 0 | 是 |
| c_control_pipeline（选择） | 20,549 | 9,713 | 6,351.375 | 20,446 | 9,713 | 6,325.625 | 0.057 | 0.096 | 是 | 0 | 是 |
| c_selective_pipeline | 21,418 | 9,687 | 6,565.375 | 21,277 | 9,687 | 6,530.125 | 0.149 | 0.096 | 是 | 0 | 是 |
| i_prefetch | 18,662 | 9,421 | 5,843.125 | 18,551 | 9,421 | 5,815.375 | -4.498 | 0.113 | 是 | 0 | 否 |
| i_software（选择） | 17,874 | 9,387 | 5,641.875 | 17,778 | 9,386 | 5,617.750 | 0.012 | 0.122 | 是 | 0 | 是 |
| i_timing_v3 | 18,296 | 9,384 | 5,747.000 | 18,124 | 9,383 | 5,703.875 | 0.113 | 0.106 | 是 | 0 | 是 |

## 相同33字节KAT的 i 周期组成

通过的本核结果保持 Hash 优先、Transfer=0、Remaining 为补集，并通过总和与签名/cache/Hash/物理块断言；未完成或失败项不作通过声明。SLotH使用原报告口径，其Hash另含部分引擎装载和链控制，不能把两方Hash差直接解释为算法工作量差。

| 后端 | 实现 | 状态 | 总周期 | Hash | Transfer | Remaining | Hash数 | 物理块 |
|---|---|---|---|---|---|---|---|---|
| shake | SLotH | 原报告 | 4,943,102 | 2,641,069 | 265,156 | 2,036,877 | — | — |
| shake | i baseline | passed | 5,827,283 | 2,536,104 | 0 | 3,291,179 | 104,967 | 105,671 |
| shake | i_prefetch | passed | 4,428,640 | 2,536,104 | 0 | 1,892,536 | 104,967 | 105,671 |
| shake | i_software | passed | 3,756,587 | 2,536,104 | 0 | 1,220,483 | 104,967 | 105,671 |
| sha2 | SLotH | 原报告 | 9,163,945 | 7,134,844 | 244,167 | 1,784,934 | — | — |
| sha2 | i baseline | passed | 10,633,293 | 6,923,410 | 0 | 3,709,883 | 104,925 | 106,514 |
| sha2 | i_prefetch | passed | 9,235,241 | 6,923,410 | 0 | 2,311,831 | 104,925 | 106,514 |
| sha2 | i_software | passed | 8,564,082 | 6,923,410 | 0 | 1,640,672 | 104,925 | 106,514 |

shake：所选i的KAT/工作量与基线匹配=是；Remaining−SLotH=-816,394；低于SLotH=是。

sha2：所选i的KAT/工作量与基线匹配=是；Remaining−SLotH=-144,262；低于SLotH=是。

诊断工具失败与DUT结果分开：第一次 `profiles/i_prefetch` 的编译失败来自该Verilator版本处理跨层枚举引用时的内部错误（EnumItemRef），不是DUT功能不通过。只修诊断wrapper：解析冻结RTL枚举并生成localparam，STATE_ENUMS.json记录源校验与映射。后续各profiling是否通过以表格及原始result.json为准，旧失败日志在运行目录保留。

## 三个目标的默认回归 Sign

这是默认向量的实测周期，实际消息长度由各冻结包 job.mem读取；与上表33字节KAT分开。ATP100单位为等效Slice·秒。旧未闭合基线仅进行同频“面积×周期”假设比较，该列不代表基线实际达到100MHz。

| 实现/后端 | 参数 | 旧消息B | 消息B | 旧周期 | 周期 | 周期变化% | Hash数 | 物理块 | 输入/工作量一致 | 实际ATP100 | 同频面积×周期变化% |
|---|---|---|---|---|---|---|---|---|---|---|---|
| i/shake | slh_128f | 1 | 1 | 5,825,429 | 3,755,264 | -35.537 | 104,937 | 105,641 | 是 | 181.140 | -35.567 |
| i/shake | xmss_h10 | 1 | 1 | 119,396,316 | 97,607,160 | -18.249 | 3,431,815 | 3,431,815 | 是 | 4,708.203 | -18.288 |
| i/shake | lms_h10 | 1 | 1 | 59,188,121 | 38,332,555 | -35.236 | 1,101,392 | 1,116,752 | 是 | 1,849.019 | -35.266 |
| i/sha2 | slh_128f | 1 | 1 | 10,633,206 | 8,563,450 | -19.465 | 104,925 | 106,513 | 是 | 481.073 | -19.738 |
| i/sha2 | xmss_h10 | 1 | 1 | 357,993,035 | 336,203,065 | -6.087 | 3,431,950 | 4,736,133 | 是 | 18,887.048 | -6.405 |
| i/sha2 | lms_h10 | 1 | 1 | 110,688,810 | 89,834,036 | -18.841 | 1,101,347 | 1,136,162 | 是 | 5,046.652 | -19.116 |
| c/shake | slh_128f | 1 | 1 | 2,958,730 | 3,090,926 | 4.468 | 104,937 | 105,641 | 是 | 181.596 | 4.756 |
| c/shake | xmss_h10 | 1 | 1 | 86,678,790 | 86,719,788 | 0.047 | 3,431,815 | 3,431,815 | 是 | 5,094.896 | 0.323 |
| c/shake | lms_h10 | 1 | 1 | 28,639,398 | 28,684,490 | 0.157 | 1,101,392 | 1,116,752 | 是 | 1,685.250 | 0.433 |
| c/sha2 | slh_128f | 1 | 1 | 7,390,104 | 7,522,300 | 1.789 | 104,925 | 106,513 | 是 | 475.832 | 2.639 |
| c/sha2 | xmss_h10 | 1 | 1 | 323,215,019 | 323,256,017 | 0.013 | 3,431,950 | 4,736,133 | 是 | 20,447.963 | 0.848 |
| c/sha2 | lms_h10 | 1 | 1 | 74,993,335 | 75,038,427 | 0.060 | 1,101,347 | 1,136,162 | 是 | 4,746.649 | 0.896 |

## 验证与拒绝路径

验证组按当前队列动态列出。通过只按完整SUMMARY记录；待完成不标为通过。h20仅Verify，完整Keygen/Sign保持停止。

| 验证组 | 完成 | 通过 | 已通过操作 | 应有操作 | 已通过测试 | 应有测试 | SYNTHESIS Sign | 源码未变 | h20 Verify |
|---|---|---|---|---|---|---|---|---|---|
| c_control_pipeline/shake | 是 | 是 | 20 | 20 | 4 | 4 | passed | 是 | xmss_h20/verify:passed,lms_h20/verify:passed |
| c_control_pipeline/sha2 | 是 | 是 | 16 | 16 | 2 | 2 | passed | 是 | xmss_h20/verify:passed,lms_h20/verify:passed |
| c_selective_pipeline/shake | 是 | 是 | 20 | 20 | 4 | 4 | passed | 是 | xmss_h20/verify:passed,lms_h20/verify:passed |
| c_selective_pipeline/sha2 | 是 | 是 | 16 | 16 | 2 | 2 | passed | 是 | xmss_h20/verify:passed,lms_h20/verify:passed |
| i_prefetch/shake | 是 | 是 | 20 | 20 | 4 | 4 | passed | 是 | xmss_h20/verify:passed,lms_h20/verify:passed |
| i_prefetch/sha2 | 是 | 是 | 16 | 16 | 2 | 2 | passed | 是 | xmss_h20/verify:passed,lms_h20/verify:passed |
| i_software/shake | 是 | 是 | 20 | 20 | 4 | 4 | passed | 是 | xmss_h20/verify:passed,lms_h20/verify:passed |
| i_software/sha2 | 是 | 是 | 16 | 16 | 2 | 2 | passed | 是 | xmss_h20/verify:passed,lms_h20/verify:passed |
| i_timing_v3/shake | 是 | 是 | 20 | 20 | 4 | 4 | passed | 是 | xmss_h20/verify:passed,lms_h20/verify:passed |
| i_timing_v3/sha2 | 是 | 是 | 16 | 16 | 2 | 2 | passed | 是 | xmss_h20/verify:passed,lms_h20/verify:passed |

定向控制、FORS慢操作数、快慢分支交替、RAM107/108及拒绝后无部分写入的摘要在JSON的directed_validation中；每项附候选RTL哈希匹配结果，匹配未知时不宣称该测试覆盖所选候选。

- `/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/ic_timing_staging/c/AUDIT.json`：通过/状态=passed；RTL对应={"i": null, "c": true}。

- `/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/ic_timing_staging/c_v2/AUDIT.json`：通过/状态=passed；RTL对应={"i": null, "c": false}。

- `/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/ic_timing_staging/c_v2/validation/EXISTING_VALIDATION.json`：通过/状态=4；RTL对应={"i": null, "c": false}。

- `/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/ic_timing_staging/c_v2/validation/FORS_VALIDATION.json`：通过/状态=是；RTL对应={"i": null, "c": false}。

- `/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/ic_timing_staging/i_rom/AUDIT.json`：通过/状态=passed；RTL对应={"i": null, "c": null}。

- `/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/ic_timing_staging/i_rom/MODEL_VALIDATION.json`：通过/状态=是；RTL对应={"i": null, "c": null}。

- `/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/ic_timing_staging/i_v2/AUDIT.json`：通过/状态=passed；RTL对应={"i": null, "c": null}。

- `/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/ic_timing_staging/i_v2/DIRECTED_VALIDATION.json`：通过/状态=4；RTL对应={"i": true, "c": null}。

- `/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/ic_timing_staging/i_v3/AUDIT.json`：通过/状态=passed；RTL对应={"i": null, "c": null}。

- `/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/ic_timing_staging/i_v3/DIRECTED_VALIDATION.json`：通过/状态=4；RTL对应={"i": false, "c": null}。

- `/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/ic_timing_remaining/20261023_195418/candidates/c_selective_pipeline/source/build/ablation/c/chain_controls/VALIDATION.json`：通过/状态=4；RTL对应=true。

- `/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/ic_timing_remaining/20261023_195418/candidates/i_prefetch/source/build/ablation/i/chain_controls/VALIDATION.json`：通过/状态=4；RTL对应=true。

## ROM、失败候选与适用范围

- i/i_software：观察到 20 组（原有20组）ROM；template/descriptor不变=是；program改变组数=20。
- c/c_control_pipeline：观察到 20 组（原有20组）ROM；template/descriptor不变=是；program改变组数=0。
- i_prefetch/shake：WNS=-4.789ns，WHS=0.106ns，100MHz接受=否。失败/未达标证据保留，不用低频或推算频率替代验收。
- i_prefetch/sha2：WNS=-4.498ns，WHS=0.113ns，100MHz接受=否。失败/未达标证据保留，不用低频或推算频率替代验收。

i的软件逐Hash链/树边界、c的硬件CHAIN＋软件树边界保持；共享Hash后端及标准输出语义不变。所选i可以调整普通ROM程序以搬出不变条件，但每一步Hash仍有独立软件授权。

本报告仅覆盖共同核OOC的受约束内部路径；没有执行极限频率搜索，不宣称板级接口时序。

## 来源与原始日志

- 本轮运行：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/ic_timing_remaining/20261023_195418`；候选冻结包：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/docs/manifests/experiments/ic_timing_remaining_20261023_195418/candidates/<候选>/frozen_rtl.tar.gz` 及 `SOURCE.json`。
- 同口径基线：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/docs/manifests/experiments/ablation_route_20261023_190751`。
- 路由/综合原始日志：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/ic_timing_remaining/20261023_195418/routes/<候选>/<后端>/vivado.log`；分层与时序在对应 synth/route 子目录。
- 完整验证SUMMARY：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/ic_timing_remaining/20261023_195418/validation/<候选>/<后端>/SUMMARY.json`，其 runtime_log_directory 指向原始明细。
- 33字节profiling：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/ic_timing_remaining/20261023_195418/profiles/`；baseline分解：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/ic_timing_staging/profile_baseline/`。
- 归档保留冻结RTL、源码校验、综合/布线分层、时序及工具日志；仿真/验证明细留在运行目录，仅汇总摘要进入归档。
- i_software冻结包的旧image_layout元数据不冒充新程序占用；run/DERIVED_IMAGE_LAYOUT.json及各候选归档中的同名文件另列派生的20组ROM占用。若实际采用，metadata更新由采用步骤负责。
- i_software缺失的model/default_jobs.json以候选归档support/及SUPPORT_SOURCE.json补证；不回写历史immutable tar或SOURCE清单。所有补充元数据来源见JSON supplemental_source_metadata。
- 本脚本只写本次Final Markdown/JSON；不覆盖progress report、不写INDEX或ARTIFACTS，也不读写生产RTL。
