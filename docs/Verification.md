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
