# 当前项目的构建与验证

## 固定单 lane

生产 RTL 只有 `core.lane` 一个实例；`LANES`、`SWAP_PHYSICAL_LANES` 和仿真命令行的 lane/swap 选项均已删除。默认 P1U2，P/U 参数继续保留。历史多 lane 驱动在当前源码上报错；复现旧实验应使用对应冻结源码，不能把旧 L2 周期当作当前单 lane 基线。

当前裁剪验收使用提交 `9dbcac8f` 的冻结实现，并明确固定其 LANES=1。逐周期比较 Job/消息/Verify 握手、输出、完成、错误、周期和 Hash/置换计数。冻结模块只进入测试，不在生产源码清单中。

```bash
make contract-test lint
python3 scripts/verify_v42_units.py
make single-lane-regression
```

`verify_single_lane.py` 检查 P1U1 下六种 SLH 与四种 XMSS/LMS 的 Keygen/Sign/Verify，共 30 组，输出逐字节比较软件向量。`verify_single_lane_edges.py` 检查 P1～P4/U1～U2、统计关闭、P4 普通 stateful 请求、停顿、复位重放、截断、异常退出、q 边界、消息边界和签名篡改。二者完整日志写入 `manifests/experiments/single_lane_20261008/`，编译输出写入 `build/single_lane_20261008/`。

## 工具与常规流程

在仓库根目录运行。依赖 Python、GNU Make、Icarus Verilog、Verilator 和 C++ 编译器；综合使用 Vivado 2025.2、xc7a200tffg1156-3。

```bash
make smoke TAG=my_smoke
make verify TAG=my_full
```

`smoke` 检查合同、lint、模型、单元、12 组 SLH Keygen/Sign、六参数正常 Verify 和封存证据。历史参考只比较输出和 Hash/置换次数，当前周期由冻结单 lane 对照验收。

`verify` 追加 SLH 消息/复位扩展、共同核提取等价、统计关闭、异常退出和完整 Verify 测试。单 lane Verify 删除了物理交换与双链不对称专项，保留零步/最大步、左右认证节点、节点延迟、污染后复位等检查，共 118 项。

| 入口 | 内容 |
|---|---|
| `make contract-test lint` | 接口、无 lane 参数、源闭包、快照合同、RTL lint |
| `make compile-microcode` | 六参数模型、独立参考和 f 参数 ACVP KAT，生成镜像与向量 |
| `make rtl-unit-test` | 启动、单写相邻双读存储、sequencer、配方、padding、路由和地址检查 |
| `make rtl-profile-test TAG=probe PROFILE=slh_192f OPERATION=sign` | 单点 SLH 仿真 |
| `make rtl-verification TAG=...` | 已有正常结果上的扩展、共同核、统计关闭、故障和 Verify |
| `python3 scripts/verify_v42_current.py <tag>` | 核验已有完整 SLH 证据 |
| `python3 scripts/run_stateful.py --p 1 --u 1` | 固定单 lane 的四参数 XMSS/LMS 三操作 |
| `make pu-unit-test` | 独立 SHAKE 向量、三节点宽度、交错链和 capture |
| `make reproduce-v42 reproduce-ku` | 只读核验历史封存证据 |

单元 scoreboard 检查共享列表初始化、FORS/WOTS 切换、父节点输入稳定性/左右顺序和 ROUTE 消费值。存储单元覆盖 68/136 项、奇偶写入、127/128 边界和奇数尾节点归约。

常规 SLH 流程输出在 `build/v4.2/external_job_message/<tag>/`，包括源码快照、哈希、日志和结果。源码或测试修改后使用新的 TAG；模型和单元证据应先于快照生成。

## 共同核测量

```bash
make pu-atp PU_TAG=my_pu
```

该入口只测单 lane 的 P1～P4/U1～U2、128f sign：冻结源码，逐字节对照软件向量，再综合共同核。约束 6.666667 ns，PROFILE_ENABLE=0，不布线；检查网表中统计寄存器已裁剪。LUT 包含 LUTRAM，不重复计数。150 MHz 如用于时间/ATP，是假定值，不是实测频率。

默认 P1U2 的既有流程也可使用 `make synth-core TAG=...`；其约束为 10 ns，不能与 6.666667 ns 实验混作同约束对照。`synth-common`/`route-common` 另含十二个 SLH 外壳；OOC 核内频率与外部接口时序签核仍需区分。本轮不执行布线。

当前测量、候选差异及验收明细见 [单 lane 优化报告](report/Single_Lane_Optimization.md)。历史 K/U、K/P/U 和 XMSS/LMS 扩展报告保持原始数据，不代表当前源码。

## XMSS/LMS 软件参考

`stateful_vectors.py` 对照冻结 `67a1cd75` 模型和独立 hashlib 签名验证器；当前冷启动模型包含完整认证路径重算。原始向量保留于 `manifests/experiments/stateful_20261008/vectors/`，当前单 lane 测试结果写入独立目录。索引由外部持久化管理，复位不表示允许重复使用索引。

## XMSS/LMS 链上下文验证

`scripts/stateful_pipeline_experiment.py` 使用 Verilator，实验目录为 `manifests/experiments/stateful_pipeline_20261012`。`baseline` 冻结 `01486e3f` 的生产 RTL；`candidate2` 冻结新增三算法族链上下文的 RTL。`matrix` 对 P1/P4/P12 × U1/U2 的四参数三操作逐字节比对向量，`regression` 比较 SLH 输出与周期，`edges` 检查索引、节点篡改、停顿、复位、异常清空及统计关闭，`partition` 逐周期比较完整 top 与提取共同核。

`units` 对 11 个 P>1 配置运行 `tb_mhbs_stateful_pipeline`，每点 72 个独立 hashlib 向量；检查最高 tag、链索引 132、零步/最大步、子步骤、capture、反馈冲突、尾批、背压和槽位复用，且每级轮输出对照冻结轮函数。P1 的两个配置通过普通路径完整操作验证。集成观察器记录实际同时在途上下文数，P>1 的新算法操作必须出现多上下文交错并完成排空。

后续面积实验由 `scripts/stateful_pipeline_area.py` 驱动，证据保存于 `manifests/experiments/stateful_pipeline_area_20261012/`。冻结 `5d53fa6e`，使用 Verilator 对全部 13 种 P/U 逐周期比较；P>1 比较批量请求、置换块、响应和有效读数据，P1 比较普通 sponge 的握手、计数和多块填充结果。另以六种上下文深度检查混合算法的乱序返回，并断言确实发生了初值接受/置换返回同拍以及 XMSS key 返回。

正常矩阵仍包含六配置 × 四参数 × 三操作的 72 组；补充六种 SLH 三操作、统计关闭、q 边界、停顿、复位、异常退出与共同核等价。P4U2 仅跳过综合，功能验证保留；P12U2 不新增综合。四个面积点为 P1U1/P1U2/P4U1/P12U1。各候选的源码、父版本差异、生成的测试平台、日志和保留决定见 [面积优化报告](report/Stateful_Pipeline_Area_Optimization.md)。本轮不运行 Icarus，不布局布线。

`synth` 仅综合共同核，最多 6 个 Vivado、每任务 4 线程，约束 6.666667 ns，检查统计寄存器裁剪。完整结果和验收范围以 [本轮报告](report/Stateful_Pipeline_20261012.md) 为准。
