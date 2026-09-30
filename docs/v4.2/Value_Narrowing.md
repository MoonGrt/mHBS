# 长期结果暂存裁剪候选

候选 `value_narrow_20260930_v1`；基线 `s_parameters_20260930_v1`：共同核 6405.875 等效 Slice、21224 LUT、8799 FF、1112 LUTRAM。器件及综合配置沿用基线，K2U2、`PROFILE_ENABLE=0`。

本候选已通过面积与完整回归验收，保留该修改。共同核 **6362.250 等效 Slice**，较基线减少 **43.625（0.68%）**。本页保留该阶段记录；`current_core.json` 现指向后续的 `parent_right_20260930_v1`，面积 **6308.250 等效 Slice**，见[20.9k LUT 实验](LUT20900.md)。均未布局布线或测新频率。

| 共同核资源 | 基线 | 当前 | 差值 |
|---|---:|---:|---:|
| LUT | 21224 | 21158 | -66 |
| FF | 8799 | 8582 | -217 |
| LUTRAM（包含于 LUT） | 1112 | 1112 | 0 |
| 等效 Slice | 6405.875 | 6362.250 | -43.625 |

BRAM/DSP 均为零；等效 Slice 按 LUT/4 + FF/8 计算，并非物理占用 Slice 数。

## 修改范围

- 四个长期 `value` 槽缩至 256 位，FORS 槽另存 64 位尾部。六种参数的 FORS 摘要最多占 40 字节；按整字节保留，避免字节内位序转换丢失末组索引。
- Hmsg 的 `result[0]` 和 `route_value` 保持 392 位，树/叶索引在原 ROUTE 周期从完整摘要解析。
- 根节点反馈显式补零至 392 位。路由写入 FORS 槽时同步写尾部，其他槽及禁止写入的路由不改变尾部；不增加复位数据通路或计算状态。
- 综合网表确认长期数据位由 1296 位降至 1088 位：四槽各 256 位，加 64 位 FORS 尾部，共减少 208 位。其余优化使总 FF 减少 217 位；`result[0]`/`route_value` 的 RTL 声明仍为 392 位，综合各裁掉 4 位无用高位，完整有效树/叶索引未丢失。
- 父节点左右输入寄存、Keccak、compact chain、微码、存储深度及外部接口均未改动。左右输入裁剪留待独立候选。

## 综合前检查

`tb_mhbs_s_parameters` 增加真实时钟路由检查：六种参数的零值、全一、随机及 392 位逐位激励，覆盖 256/320 位边界、全部 FORS group、完整树/叶解析、槽位隔离、禁止写入、复位后覆盖、根反馈补零及原状态延迟。

综合前通过接口合同/lint、15 组单元、12 组正常 keygen/sign 和 6 组正常 verify。正常执行的输出、周期、Hash/置换次数与冻结基线逐项比较，结果见 `pre_synth_checks.json`。

综合后通过完整源绑定审计：12 组正常执行、66 项扩展、12 组共同核等价、24 组统计关闭、2 项统计关闭扩展、12 项异常退出、130 项 verify；复核已有 12 组软件参考证据与当前模型/向量一致。正常与扩展 Keygen/Sign 的输出、周期、Hash/置换次数，以及全部 Verify 结果、周期、节点数和覆盖统计均与基线一致。硬件统计裁剪审计通过。综合时序仅为估算，未生成新的布局布线频率。

## 任务与恢复

工作目录：`build/v4.2/external_job_message/value_narrow_20260930_v1/`。

- `source_snapshot.tar.gz`、`inputs.json`：密封源码及校验值。
- `incremental.patch`、`experiment.json`：修改补丁、基线和阶段记录。
- `progress/`：检查、仿真及综合驱动日志。
- `synth.log`：Vivado 完整日志。
- `synthesis/core_hierarchical.rpt`：分层面积报告。

本次按约定在提交后台综合后停止，用户通知完成后才检查面积、运行完整回归并验收。后续父节点输入裁剪的独立结果见[20.9k LUT 实验](LUT20900.md)；全程未提交、未推送。

正式证据位于 `manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/value_narrow_20260930_v1/`：

- [分层面积](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/value_narrow_20260930_v1/synthesis/core_hierarchical.rpt)
- [面积与寄存器对比](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/value_narrow_20260930_v1/area_comparison.json)
- [完整回归审计](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/value_narrow_20260930_v1/verification.json)
- [周期表](Cycles.md)
