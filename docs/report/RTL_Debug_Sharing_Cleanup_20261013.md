# RTL 调试裁剪、签名缓存宏与互斥资源复用（2026-10-13）

更新时间：2026-10-13T22:40:54.875538+08:00。冻结源码校验：True。

本轮基线是提交 `09ee1b72` 的标准算法通用实现，对照上一矩阵 20261013_203826；历史报告保持原口径。

定义 `MHBS_SIGNATURE_STORE` 才实例化 top 的 Sign 缓存，未定义时缓存读回接口返回零，签名输出流继续有效。宏按是否定义判断，`-DMHBS_SIGNATURE_STORE=0` 仍表示开启。`synth_top.tcl <profile> 0/1` 负责转换为宏不存在/存在；脚本默认1，延续之前含缓存的面积口径。

`SYNTHESIS` 下 error_code、cycles、boot/keygen/sign_cycles、hash_count、permutation_count 及内部统计接口、寄存器、更新逻辑一起删除。调试更新和断言使用独立 always 块，功能 always 中没有 SYNTHESIS 条件。功能性 error/abort、存储读回长度、有效标记和错误中止保留，它们参与协议和数据正确性。

| 共用项 | 实现及存活期约束 |
|---|---|
| 控制标记 | 归约寄存器、滚动active/批次done标记的合并均已撤回；实测新增选择逻辑抵消FF收益。原有互斥调度继续共用一套状态机。 |
| 宽度与策略 | 缩窄计数器的候选比保留原宽度的候选面积更大，故撤回；endpoint_count保留8位，非法ROM计数检测继续有效。公共计数策略复用尝试同样撤回。 |
| 现有宽存储 | 三算法共用单 Hash lane、136×256工作区和可选签名缓存；本轮容量不变。 |
| 保留的同时存活数据 | 树栈与认证路径、XMSS key/digest/captured、Verify二元输入、Sign缓存与树工作区分别同时存活，继续占不同位置。 |

所有 sources.txt 中 RTL 使用统一4空格缩进、100列目标宽度和长表达式换行。`scripts/format_rtl.sh` 可复现格式；工具为 [Verible](https://github.com/chipsalliance/verible) v0.0-4296-g0f262651。清理退休 omega2 分支及未使用配方信号，保留 FSM 编号和测试观察层级。

源码和四种宏组合 lint/预处理审计通过：综合视图没有诊断标识符，任一 always 内均没有 SYNTHESIS 开关。Vivado 对实际综合网表继续核对诊断端口和寄存器。

## 面积

器件 xc7a200tffg1156-3，Vivado 2025.2，OOC，通用 Keccak，6.666667ns，默认时序驱动，每个 Vivado 2线程；没有新增时序例外。等效 Slice=LUT/4+FF/8+232.4×BRAM36+102.4×DSP。common 排除ROM、签名缓存和板级I/O；top 包含固定128f Sign ROM及按宏选择的缓存。

| 口径 | LUT | FF | BRAM36 | 等效Slice | 相同P/U上轮Slice | 变化 | 状态 |
|---|---:|---:|---:|---:|---:|---:|---|
| common/P4U1 | 33873.0 | 10903.0 | 0.0 | 9831.125 | 9683.25 | +1.527% | passed |
| common/P12U1 | 51042.0 | 24438.0 | 0.0 | 15815.25 | 16049.5 | -1.460% | passed |
| common/P24U1 | 78602.0 | 44654.0 | 0.0 | 25232.25 | 25311.375 | -0.313% | passed |
| top/signature0 | 25554.0 | 10622.0 | 0.0 | 7716.25 |  |  | passed |
| top/signature1 | 28448.0 | 10919.0 | 11.5 | 11149.475 |  |  | passed |

排名仅覆盖本轮已测 common 的配置；未测/未完成面积不借用上一轮值。U1=150MHz、U2=110MHz 是比较用假定频率；本轮尚无布线 STA，因此不作布线 ATP 结论。

| 算法 | 修改前已测最佳 | 最终候选已测最佳 | ATP变化 |
|---|---|---|---:|
| slh_128f | P12U1 | P12U1 | -1.460% |
| xmss_h10 | P24U1 | P24U1 | -0.313% |
| lms_h10 | P24U1 | P24U1 | -0.313% |

## 复用取舍

相同P/U、相同工具设置的隔离实验保留在独立冻结目录。减少声明位数会增加选择逻辑，按实际综合面积决定是否保留；最终候选的三个目标最佳ATP须与本轮之前标准矩阵比较。

| 变体 | P/U | LUT | FF | 等效Slice | 状态 |
|---|---|---:|---:|---:|---|
| consolidated_flags_separate | P12U1 | 52173.0 | 24428.0 | 16096.75 | passed |
| narrow_flags | P12U1 | 51758.0 | 24394.0 | 15988.75 | passed |
| narrow_flags_separate | P12U1 | 52044.0 | 24424.0 | 16064.0 | passed |
| narrow_flags_separate | P24U1 | 80242.0 | 44630.0 | 25639.25 | passed |
| narrow_shared | P12U1 | 51354.0 | 24385.0 | 15886.625 | passed |
| per_slot_policy | P12U1 | 52038.0 | 24419.0 | 16061.875 | passed |
| separate_both | P12U1 | 51042.0 | 24438.0 | 15815.25 | passed |
| separate_both | P24U1 | 78602.0 | 44654.0 | 25232.25 | passed |
| separate_both | P4U1 | 33873.0 | 10903.0 | 9831.125 | passed |
| separate_reduction | P12U1 | 51084.0 | 24425.0 | 15824.125 | passed |
| widths_only_separate | P12U1 | 51785.0 | 24444.0 | 16001.75 | passed |

最终选定 `separate_both`：保留签名宏、完整诊断裁剪、独立调试块、无用逻辑清理与格式整理；新增存储/状态合并和缩窄尝试按实测撤回。此前已有的单lane、上下文、工作区复用保持有效。

## slh_128f Sign

| P/U | 周期 | 时间ms | ATP Slice·ms | 已测排名 | 与上轮周期/工作量 |
|---|---:|---:|---:|---:|---|
| P12U1 | 288011 | 1.920073 | 30366.439785 | 1 | 一致 |
| P1U1 | 2578767 | 17.191780 |  |  | 一致 |
| P24U1 | 209884 | 1.399227 | 35305.637060 | 2 | 一致 |
| P3U1 | 957922 | 6.386147 |  |  | 一致 |
| P4U1 | 727562 | 4.850413 | 47685.019782 | 3 | 一致 |

## xmss_h10 Sign

| P/U | 周期 | 时间ms | ATP Slice·ms | 已测排名 | 与上轮周期/工作量 |
|---|---:|---:|---:|---:|---|
| P12U1 | 8010195 | 53.401300 | 844554.909825 | 2 | 一致 |
| P1U1 | 82737051 | 551.580340 |  |  | 一致 |
| P24U1 | 4422352 | 29.482347 | 743905.941680 | 1 | 一致 |
| P3U1 | 28772869 | 191.819127 |  |  | 一致 |
| P4U1 | 21476982 | 143.179880 | 1407619.297765 | 3 | 一致 |

## lms_h10 Sign

| P/U | 周期 | 时间ms | ATP Slice·ms | 已测排名 | 与上轮周期/工作量 |
|---|---:|---:|---:|---:|---|
| P12U1 | 3004177 | 20.027847 | 316745.401995 | 2 | 一致 |
| P1U1 | 27042419 | 180.282793 |  |  | 一致 |
| P24U1 | 1832662 | 12.217747 | 308281.238330 | 1 | 一致 |
| P3U1 | 9705079 | 64.700527 |  |  | 一致 |
| P4U1 | 7340300 | 48.935333 | 481089.378917 | 3 | 一致 |

## 验证与证据

本轮完整 Sign 已完成 15 项，包括普通与综合宏视图；六组 SLH 与六组 XMSS/LMS 的两种宏视图 Verify 已完成 24 项。
补充验证包括：四种 top 宏组合的完整128f Sign及缓存逐字节读回；459项配方、12项流水 family/地址检查；64位计数进位；两种宏视图下非法状态、q越界、非法配置和在途故障的功能中止。

- 冻结源码及校验：[SOURCE.json](/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/rtl_cleanup_20261013/FINAL_SOURCE.json)。
- 完整 Sign/Verify 日志：[validation](/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/rtl_cleanup_20261013/variants/separate_both/validation)。
- 源码裁剪审计：[source_audit.json](/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/rtl_cleanup_20261013/source_audit.json)。
- 补充验证：[VALIDATION.json](/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/rtl_cleanup_20261013/variants/separate_both/validation/FINAL_VALIDATION.json)。
- 综合任务和日志：[synthesis_tasks.json](/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/rtl_cleanup_20261013/synthesis_tasks.json)。

XMSS/LMS h20 完整 Keygen/Sign 保持停止。上一轮异常 P3U2 和旧赢家布线继续后台运行，其结果属于归档源码，不混入本轮候选面积。综合耗时异常时仅暂缓分析，不终止进程。
