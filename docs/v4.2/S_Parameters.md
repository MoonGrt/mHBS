# 六种 SLH-SHAKE 参数支持

六参数扩展基线 `s_parameters_20260930_v1` 同时支持 128f/192f/256f/128s/192s/256s 的 Keygen、Sign 和外部节点 Verify。基线共同核 **6405.875 等效 Slice**，较 Program16 的 6312.500 增加 **93.375（1.48%）**。后续先完成[长期结果暂存裁剪](Value_Narrowing.md)，再由已验收的 `parent_right_20260930_v1` 将当前面积降至 **21,071 LUT、6308.250 等效 Slice**，详见[20.9k LUT 实验](LUT20900.md)。这些版本均只测综合面积，未测新频率；102.040816 MHz 属于扩展之前的历史 RTL。

## 实现与接口

K2U2、256 位节点输出、64 位外部消息和 256 位 Verify 节点接口不变。新增 descriptor[1] 编码 4/5/6 分别代表 128s/192s/256s，原 f 编码 0/1/2 不变。离线模型拒绝其余编码。切换参数集需同时指定对应三份镜像与 Job 参数，Verify 继续复用 sign 镜像。

FORS 的目标、叶游标、节点索引拓宽为 14 位；FORS 目标提取覆盖 a=6/8/9/12/14。摘要树索引增加 s 的 7 字节布局；128s/192s 的 XMSS 叶索引按两字节大端读取并保留低 9 位，256s 保留低 8 位。软件执行模型同步修复原先只读取一字节叶索引的 f 特化逻辑。没有新增流水级或计算 lane。

树栈和认证路径各 16×256 位、共享列表 68×256 位、最大摘要 49 字节均保持原容量。program/template/descriptor 仍为 **16/16/32 条**；六种参数均使用 14 条程序、11 条模板、30 条 descriptor（含头部/profile）。各参数镜像属于替换配置，不在核内同时存储六份 ROM。

| 参数 | n 字节 | 总树高 h | 层数 d | XMSS 高度 h′ | FORS 高度 a | FORS 数 k | 摘要 m 字节 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 128s | 16 | 63 | 7 | 9 | 12 | 14 | 30 |
| 192s | 24 | 63 | 7 | 9 | 14 | 17 | 39 |
| 256s | 32 | 64 | 8 | 8 | 14 | 22 | 47 |

参数依据 [FIPS 205 表 2](https://nvlpubs.nist.gov/nistpubs/fips/nist.fips.205.pdf#page=53)，仓库保留标准 PDF。

## 综合面积

器件 `xc7a200tffg1156-3`，K2U2，`PROFILE_ENABLE=0`。等效 Slice 按 LUT/4 + FF/8 计算；BRAM/DSP 均为零，不是物理占用 Slice 数。

| 共同核 | Program16（仅 f） | 六参数扩展基线 | 差值 |
|---|---:|---:|---:|
| LUT | 20857 | 21224 | +367 |
| FF | 8786 | 8799 | +13 |
| LUTRAM（包含于 LUT） | 1112 | 1112 | +0 |
| 等效 Slice | 6312.500 | 6405.875 | +93.375 |

本次仅共同核综合，没有十二个外壳的综合面积及布线频率。统计/目标冗余寄存器审计通过。`current_core.json` 现指向后续面积优化 `parent_right_20260930_v1`；本页保留扩展基线证据。历史完整外壳的 `final.json`/`routed_final.json` 保留 Program16，不代表当前源码。

## 验证与周期

通过 12 组软件执行模型与独立 FIPS 205 参考对照、15 组 RTL 单元、12 组正常 Keygen/Sign、66 项扩展、12 组共同核等价、24 组统计关闭、2 项统计关闭扩展、12 项故障退出、130 项 Verify。新增摘要解析单元覆盖六种参数所有 FORS group 的零值、全一最大索引及随机摘要，检查树/叶索引字节序、掩码和跨字节提取。完整 s 签名执行遍历到 14 位 FORS 叶索引边界。

f 向量保持原 ACVP KAT。s 向量使用 f KAT 中的确定性种子/消息，重新按 s 参数生成公钥和签名，并由独立参考模型验证；**不是新增 s ACVP KAT 认证**。

| 参数 | Keygen 计算周期 | Sign 计算周期 | Verify 正常周期（含启动，无等待） |
|---|---:|---:|---:|
| slh_128f | 29862 | 729983 | 84040 |
| slh_192f | 43654 | 1249491 | 118019 |
| slh_256f | 115766 | 2579236 | 123463 |
| slh_128s | 1909782 | 15317506 | 29323 |
| slh_192s | 2792470 | 29016918 | 42553 |
| slh_256s | 1851926 | 27069757 | 62966 |

与 Program16 比较，原 f 六组输出字节、启动/计算/总周期、Hash/置换次数全部一致，62 项非故障 Verify 的结果、节点数、Hash/置换数及无等待周期一致。s 延迟增加来自更深树的额外计算，不能按原 f 周期估算性能。

## 使用与证据

```bash
make verify TAG=<fresh_tag>
make synth-core TAG=<fresh_tag>
# 单点探测使用另一独立标签：
make rtl-profile-test TAG=<probe_tag> PROFILE=slh_128s OPERATION=sign
```

- [分层面积](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/s_parameters_20260930_v1/synthesis/core_hierarchical.rpt)
- [完整功能审计](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/s_parameters_20260930_v1/verification.json)
- [f 兼容性](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/s_parameters_20260930_v1/f_compatibility.json)
- [机器可读汇总](../../manifests/experiments/unified_hbs_v4.2/external_job_message/s_parameters.json)

源码快照 SHA-256：`f6effb489fa18a1c86479ee1ffd9fadbf4ac0abffdb506ea9d6b99e151521dcf`。候选保留独立快照、增量补丁、镜像、参考向量、完整日志与综合网表。本轮未提交、未推送。
