# 进一步冗余裁剪与整节点输出

本文为上一轮裁剪记录。当前已进一步合并 FORS/WOTS 存储，面积为 **6310.750 等效 Slice**，见 [最新合并报告](Shared_List_Store.md)。

当前保留 `redundancy_output_latched_20260927_v1`：**6370.250 等效 Slice**，较本轮基线 6675 减少 **304.750（4.57%）**。统计关闭；仅综合，未测布线频率。

## 单独候选

| 候选 | 改动 | LUT | FF | LUTRAM | 等效 Slice | 相对父版本 | 处理 |
|---|---|---:|---:|---:|---:|---:|---|
| `redundancy_capture_20260927_v1` | 顶层 capture 去重 | 21986 | 8837 | 1456 | 6601.125 | -73.875 | 保留 |
| `redundancy_list_20260927_v1` | SLH 对齐单读口列表 | 21451 | 8883 | 1454 | 6473.125 | -128.000 | 保留 |
| `redundancy_depth9_20260927_v1` | stack/auth_path 深度 16→9 | 21451 | 8883 | 1454 | 6473.125 | +0.000 | 撤回 |
| `redundancy_output_20260927_v1` | 直接 256 位节点输出 | 21800 | 8797 | 1454 | 6549.625 | +76.500 | 撤回 |
| `redundancy_output_latched_20260927_v1` | 共享暂存 256 位节点输出 | 21079 | 8804 | 1454 | 6370.250 | -102.875 | 保留 |

- capture 直接取 sponge 保留值，移除顶层两路重复暂存；输出消费完毕后才允许下一批请求。
- SLH 节点和前缀按 8 字节对齐，每拍 64 位列表输入只访问一个节点。裁除生产配方不需要的跨节点窗口，并选择单读口存储；旧双读口默认配置仍用于兼容单元测试。
- 数组深度 9 与深度 16 的综合资源完全相同，故保留原深度 16。当前三种 f 参数最多访问前 9 项，不声称全部逻辑容量被使用。
- 最终输出复用原有 emit_value 暂存，一拍传输完整节点，取消 64 位拆分、偏移计数、累计字节计数与末拍比较；verify 输入继续共用该 256 位暂存。直接组合输出虽进一步缩短周期，但整核综合面积增加，故撤回。
- 顶层接口已改变：out_data[255:0]、out_bytes[5:0]、out_valid；低字节在先，未用高位忽略，done 定界。移除 out_keep/out_last，且不支持输出反压。接收端须同步调整；不提供旧 64 位适配器。完整签名字节顺序及 SK/PK 格式不变。
- 原硬件输出长度比较及 0x3005 退出被移除；当前离线验证的镜像决定输出序列，测试平台仍检查精确字节数和所有输出字节。

## 周期

| 参数 | Keygen 原→新 | Sign 原→新 | Verify 正常周期 |
|---|---:|---:|---:|
| slh_128f | 29868 → 29862 | 731050 → 729983 | 84040（含启动，与原版本一致） |
| slh_192f | 43666 → 43654 | 1252461 → 1249491 | 118019（含启动，与原版本一致） |
| slh_256f | 115784 → 115766 | 2583908 → 2579236 | 123463（含启动，与原版本一致） |

前三个候选的六组周期完全不变。整节点输出后，Keygen 节省节点数×(n/8−1) 拍；Sign 节省节点数×(n/8−1)−(min(n/8,3)−1) 拍：R 的原串行输出有最多 3 拍与 sequencer 的 FETCH/LOAD/ISSUE 重叠，新输出仍占 1 拍，不能重复计为收益。

## 验证与边界

- 每个候选独立通过合约/lint、存储与 SHAKE 等单元测试、6 组正常执行和 65 项 Verify 检查。列表候选新增单读口存储测试，覆盖所有地址、正反读取及单侧写入。
- 最终版本额外通过 33 项扩展、6 组共同核等价、12 组统计关闭、2 项关闭统计的停顿/复位重放及 6 项故障退出，verify_v42_current.py 完整审计通过。
- 与上轮面积优化版本的 62 个非故障 Verify 用例逐项比较：节点数、结果、Hash/置换次数及扣除输入等待后的周期完全一致。
- 六组 keygen/sign 输出与旧版逐字节一致、Hash/置换次数不变，周期减少量由独立输出长度公式核验；直接顶层与共同核、统计开/关之间逐周期一致。
- 实际网表确认顶层 capture、输出偏移和累计输出计数寄存器消失；emit_value 仍为一份 256 位共享暂存。Keccak 和 sponge RTL 未修改。
- 未运行布局布线，旧 104.166667 MHz 只属于历史无 Verify 版本，不作为当前频率。未提交或推送。

## 复现与证据

```bash
make verify TAG=<fresh_tag>
python3 scripts/v42_external_synth.py <fresh_tag> --core-only
```

- [redundancy_capture_20260927_v1](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/redundancy_capture_20260927_v1/result.json)：源码快照、增量补丁、完整日志、功能结果、资源报告与 SHA-256。
- [redundancy_list_20260927_v1](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/redundancy_list_20260927_v1/result.json)：源码快照、增量补丁、完整日志、功能结果、资源报告与 SHA-256。
- [redundancy_depth9_20260927_v1](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/redundancy_depth9_20260927_v1/result.json)：源码快照、增量补丁、完整日志、功能结果、资源报告与 SHA-256。
- [redundancy_output_20260927_v1](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/redundancy_output_20260927_v1/result.json)：源码快照、增量补丁、完整日志、功能结果、资源报告与 SHA-256。
- [redundancy_output_latched_20260927_v1](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/redundancy_output_latched_20260927_v1/result.json)：源码快照、增量补丁、完整日志、功能结果、资源报告与 SHA-256。

当前分层报告：[core_hierarchical.rpt](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/redundancy_output_latched_20260927_v1/synthesis/core_hierarchical.rpt)。
