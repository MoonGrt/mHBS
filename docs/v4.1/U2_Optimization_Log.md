# v4.1 U2 优化记录

## 固定条件

U2、双 lane、ABI 4、三个独立分布式 ROM。当前索引策略为
`fixed_q_no_guard`，所有参数点使用同一个通用处理器；禁止使用镜像常量裁剪。
本记录描述候选，不表示性能验收完成。数值表以
[论文对比报告](Unified_HBS_Paper_Comparison.md)及候选 manifest 为准。

## 软件与接口

先通过无 guard 软件门禁，再修改 RTL。历史 `Machine` 默认仍为 guarded，
自运行模型显式选择固定 q。生产源码列表已排除 guard；processor/core/top
删除提交接口及 next_q。保留 q 范围检查、认证路径有效性与索引匹配、错误停机和复位重放。

## 已测结构变化

| 候选 | 变化 | 结论 |
|---|---|---|
| u2_guard_baseline | 本轮开始时的 U2 完整基线 | 12,313 等效 Slice |
| u2_no_guard | 仅移除 guard | 净减少 16 Slice；四个有状态 Sign 各减少 4 周期 |
| u2_storage | 合法对齐窗口、64 位输出选择、端点 128+8、FORS 专用根存储 | 七点周期不变；11,456.5 Slice |
| u2_hierarchy | 保留模块层次，含旧 ROM 地址组合依赖 | 时序不合格，未选用 |
| u2_stream_fixed | recipe 预译码、共享流式字选择、两个 descriptor 端口、显式使用已锁存树描述符 | 10,514.75 Slice；综合 WNS +0.331 ns |
| u2_timing | 综合前施加 10 ns 约束，Default 综合策略 | 10,926.875 Slice；综合 WNS +1.062 ns；布线候选 |
| u2_descpipe | 宏描述符后加一级寄存 | 每个宏多一拍；面积几乎不变、综合时序变差，单独不优选 |
| u2_feedback | 链反馈复用短 Hash 格式器 | 10,635.75 Slice；综合 WNS +1.314 ns；布线候选 |
| u2_wordmux | 显式单热字选择 | 比 u2_feedback 多 437 LUT，时序变差，撤回 |
| u2_statemux | 去掉 1,600 位 RUN 数据掩码，使用寄存器使能和共享加载选择 | 比 u2_wordmux 减少 758 LUT；保留为独立候选 |

以上全部为 post-synth 数字，WNS 约束为 10 ns，不能换算成已验收频率。
`u2_hierarchy` 的长路径涉及 ROM 输出选择再次影响 ROM 地址；后续已经改为
使用 `saved_descriptor` 产生树操作地址。该失败候选及原始证据保留。

显式 LUT6 实现 Keccak 的尝试在局部综合中比原版多 279 LUT，已撤回。
其源码快照在 `build/v4.1/u2_lut/`；未作为生产实现或性能结果。

## 当前后续候选

- `u2_state_shared`：从状态选择候选中撤回单热字选择，综合为 10,405.75 Slice、WNS +1.314 ns，七点周期与 u2_feedback 一致。
- `u2_stream64`：仅长消息和列表的流式格式器改为每拍 64 位，两拍拼成一个
  原 128 位吸收输入；短 Hash 快速装载与 SLH 链内反馈保持。
  完整仿真测得 Sign 增量：SLH 三点分别 6,352 / 12,491 / 32,600 周期，
  XMSS 两点各 15 周期，LMS 两点各 8 周期。LMS Keygen 增量分别
  230,400 / 115,712 周期。整机综合为 32,188 LUT、14,120 FF、9,812 等效 Slice，归一化最差比例降至 1.48683；
  仍需布线验收。

对 Keccak capacity 字段显式使用同步清零的局部候选仅减少 2 LUT，
未获得有意义的面积收益，已撤回；`u2_capacity` 快照与局部结果保留。

## 恢复后的启动校验优化

| 候选 | LUT | FF | 等效 Slice | 综合 WNS（10 ns） | Boot | Keygen/Sign |
|---|---:|---:|---:|---:|---:|---|
| u2_stream64 | 32,188 | 14,120 | 9,812 | +0.504 ns | 259 | 比较基线 |
| u2_bootpipe_resume1 | 32,207 | 14,123 | 9,817.125 | +0.754 ns | 260 | 与基线一致 |
| u2_bootall | 32,181 | 14,120 | 9,810.25 | +1.618 ns | 262 | 与基线一致 |

`u2_bootpipe_resume1` 寄存消息读取标志及 program 校验结果，原消息控制到
program ROM 校验的长路径消失，但 descriptor 校验仍成为最差路径。
`u2_bootall` 继续寄存 template/descriptor 校验，并在扫描末尾排空流水。
其整机综合耗时 247 秒；最差路径移至 endpoint 地址选择、读存储与流式数据装载。
综合时序仅用于筛选，不能作为最终频率。两候选均保留独立源码与综合记录。

`u2_bootall` 已通过七点全输出/计数、q=0/5/1023、消息边界、lane 交换、
复位中断/重放、12 项有状态故障、七组镜像驱动执行检查及物理 ROM INIT 映射。
新增 Icarus 排空测试检查三个 ROM 的最后一字。测试自身曾在初始复位阶段
过早采样错误信号；修正为复位释放后等待错误，生产 RTL 不受该测试修正影响。
归档快照中的初版排空测试应使用当前 `tb_mhbs_boot_drain.sv` 修正后重跑；
实际通过证据在 `unit/ee34210019bfac8c/`，记录独立测试源码哈希。

吸收数据选择网络的局部候选已撤回：Default/rebuilt 同设置下，recipe lane
从 12,420 LUT 增至 12,530 LUT，FF 均为 3,375，WNS 从 +1.945 到 +1.946 ns。
源码、局部综合报告与拒绝理由已归档在
`manifests/experiments/unified_hbs_v4.1/screening/absorb_shared/`，不进入整机综合。
去掉 Keccak 两轮间 `keep_hierarchy` 的独立试验为 12,815 LUT、3,375 FF、
WNS +1.945 ns，比同设置基线多 395 LUT，亦淘汰；证据在 `screening/keccak_flat/`。

`u2_readselect` 将端点读取模式与每次宏内部状态跳转一起寄存，覆盖常量转移及
Hash/输出的动态返回状态，不改变宏语义或执行时序。七点及边界周期保持不变。
局部控制综合因 Hash lane 为黑盒，其最差路径为其他控制路径，不能代表整机收益；
局部面积 10,630→10,877 LUT、5,873→5,904 FF，WNS +3.427→+3.060 ns。
整机综合实测 32,312 LUT、14,127 FF、9,843.875 Slice、WNS +2.115 ns。
相对 `u2_bootall` 多 33.625 Slice（0.34%），目标最差路径从 8.341 缩短至 7.844 ns。
保留为时序候选，与较小的 `u2_bootall` 比较布线后的 ATP。
完整功能矩阵及来源复核已通过：

```bash
python3 scripts/reproduce_autonomous.py --allow-incomplete --functional-tag u2_readselect
```

该命令核对当前候选的 Icarus、七点/边界/消息、lane 交换、复位重放、12 项故障、
宏轨迹与物理 ROM 映射证据。无最终 manifest 时仍输出 `performance acceptance: INCOMPLETE`。

暂停前中断的任务不作为有效布线结果；重跑使用独立候选/日志。
新布线流程在 route_design 前保存 post_place.dcp，便于恢复有效检查点。

## ROM 优化边界与实现后检查

`check_rom_boundary.tcl` 在相同 post-synth 检查点上测试两种 INIT：
解除整个 processor 的 DONT_TOUCH，保护 ROM 原语和输出网络，再执行 opt_design。
`u2_timing` 的两个逻辑/连接序列化结果一致；相关输出保存在
`build/v4.1/u2_timing_boundary/`。后续 route 使用这一边界。
`u2_readselect` 再次通过同项检查，结构哈希为
`952d7a3f0e2bff38b569ceea4add82fa1fd6b6b72bb8d96f4c8e20b18d265dbb`；
证据已归档至 `manifests/experiments/unified_hbs_v4.1/boundary/490f8059275c0015/`。
最终仍须对七个实际镜像检查单元、连接、位置、布线和 INIT 映射。

## 验证与复现

- Icarus：存储边界、根读写、recipe、复位、非法镜像；四个有状态参数点均检查 q=1024。
- Verilator：七点全输出/计数、q=0/5/1023、消息尾拍、交换 lane、复位中断/重放。
- 故障矩阵：四个有状态点各检查缓存不匹配、执行前失败和输出中失败，共 12 项。
- `verify_physical_rom.py`：七份镜像与物理 ROM 初始化映射。
- `reproduce_autonomous.py --allow-incomplete`：核对软件门禁、镜像及所有已归档候选
  的快照哈希、仿真来源、面积与 ATP；不存在 final.json 时明确返回性能未完成。

候选存放于 `manifests/experiments/unified_hbs_v4.1/candidates/`。
同名候选不得覆盖不同源码；复测新版本应使用新的 `TAG`。

```bash
make test
make rtl-test
make rtl-verification
make synth-common TAG=<新候选标识>
make route-common TAG=<同一候选标识>  # 写入 <候选标识>_route
make freeze-common TAG=<同一候选标识>
python3 scripts/archive_autonomous_candidate.py <候选标识>
python3 scripts/report_autonomous_optimization.py --tag <候选标识>
python3 scripts/reproduce_autonomous.py --allow-incomplete
```

最终验收还要求七点 ATP 达标、旧三点 V3 不退化、共同频率及七份冻结检查点证明。
目前不得把综合通过或功能通过标记为性能通过。

## 面积优先：单宏调度、template 压缩和长消息格式器

以 `u2_readselect_route` 的 9,830.875 Slice、100 MHz 为布线基线，
增加七点分别不超过 5% 的 Sign 周期约束。软件镜像往返、单宏事件合同和七点 KAT
先通过，随后修改 RTL。完整分项记录见 [面积优先优化](Area_Optimization.md)。

- 单宏/单事件裁剪保留 RUN、两级 LOOP 和五类宏；宏内部双 Hash lane 仍并行。
- template 物理存储改为 64×64，逻辑 ABI 4 模板仍为 128 位；descriptor 保持 128×64 双读。
- 直接 64 位吸收候选整机面积反增，撤回；descriptor 压缩也因译码开销撤回。
- 保留共享 128 位吸收 XOR；面积候选将长消息格式器缩至 32 位，保留短 Hash/链反馈。
- `u2_area_balanced` 综合为 9,743.5 Slice，周期不变；`u2_area_stream32` 为 9,374 Slice，
  七点 Sign 增量最大 2.702%，两者各保留独立快照与综合证据。

两个组合候选均通过完整功能矩阵，来源复核命令为：

```bash
python3 scripts/reproduce_autonomous.py --allow-incomplete --functional-tag u2_area_balanced
python3 scripts/reproduce_autonomous.py --allow-incomplete --functional-tag u2_area_stream32
```

历史 V3/V4 复现核验同时通过。后续布线与 INIT 冻结结果以对比报告为准；
没有七点全部达标及最终证据时，不建立 `final.json`。

本轮最终保留 `u2_area_balanced_route`：9,749.5 Slice、100 MHz，七点周期不变，
面积和最差 ATP 比例较 `u2_readselect_route` 改善 0.828%。完整功能、时序/覆盖、
七份仅 INIT 不同的检查点和来源审计均通过。32 位格式器的布线持续拥塞，
3,432 秒后停止且未取得验收频率；保留综合和未完成布线证据，工作树恢复 64 位格式器。
增量布局复用因匹配率不足停止；10.2 ns 布线对照亦明确记录为未完成。
