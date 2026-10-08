# 当前项目的构建与验证

## 环境与入口

在仓库根目录运行。仿真依赖 Python 3.12、GNU Make、Icarus Verilog、Verilator 和 C++ 编译器，不需要 Vivado。综合使用 Vivado 2025.2、xc7a200tffg1156-3。

```bash
make smoke TAG=my_smoke
make verify TAG=my_full
```

`smoke` 执行合同检查、lint、12 组软件参考、17 项单元、12 组 Keygen/Sign 和六参数正常 Verify，校验当前选定版本与 KU 原始归档。结果写入 `build/smoke_<tag>.json`。

`verify` 执行完整验收：上述模型/单元/正常执行，加 66 项扩展、12 组共同核提取等价、24 组统计关闭、2 项统计关闭扩展、12 项故障退出及 130 项 Verify。与 `current_core.json` 选定的六参数基线逐项比较输出、周期和 Hash/置换次数。

模型、单元证据必须先于源码快照生成；Makefile 保证顺序。源码或测试修改后须换新 TAG。

| 入口 | 内容 |
|---|---|
| `make contract-test lint` | 接口、源闭包、工具与快照合同、RTL lint |
| `make compile-microcode` | 六参数模型、独立参考及 f 参数 ACVP KAT，生成镜像与向量 |
| `make rtl-unit-test` | 启动、共享存储、sequencer、SHAKE、配方、padding、路由与地址检查 |
| `make rtl-test TAG=...` | 单元与 12 组正常 RTL |
| `make rtl-verification TAG=...` | 已有正常结果上的扩展、共同核、统计关闭、故障和 Verify |
| `python3 scripts/verify_v42_current.py <tag>` | 核验已有完整证据 |
| `make reproduce-v42` | 核验 current_core 指向的完整原始归档 |
| `make reproduce-ku` | 核验最新 KU 归档和报告哈希 |

单点使用独立标签：`make rtl-profile-test TAG=probe PROFILE=slh_192f OPERATION=sign`。单点结果不能替代完整验收。

## 检查范围

扩展覆盖 Keygen 根传入 Sign、lane 交换、消息停顿、复位/重放、1/7/8/9/81/82/83/87 字节消息和尾拍噪声。Verify 覆盖有效签名、节点/消息/根篡改、输入等待、复位、lane 交换、统计关闭和故障。

集成 scoreboard 检查共享列表初始化、FORS/WOTS 切换和读取值、父节点输入稳定性及左右顺序，以及 ROUTE 消费值与原暂存值逐拍一致。存储源代码中的固定银行断言检查写地址奇偶。

17 项单元包括一个启动协议和 16 个核心检查；独立根存储已无生产实例，其两个测试随模块删除。仍保留被当前验证使用的冻结参考 RTL。

## 证据与面积

运行输出在 `build/v4.2/external_job_message/<tag>/`，包括源码快照、输入哈希、仿真日志、正常/扩展/共同核/Verify 结果。生成过程会更新工作门禁；封存候选独立保存。

完整功能验收后可运行：

```bash
make synth-core TAG=my_full
make synth-common TAG=my_full
make route-common TAG=my_full
```

共同核综合为 10 ns、8 线程、PROFILE_ENABLE=0；面积包括 LUTRAM。完整顶层流程另检查十二个外壳的 ROM 初始化及共同核结构指纹。布线频率仅覆盖 OOC 核内时序，外部接口需要系统级签核。

历史采用版本见 [面积报告](v4.2/LUT21k.md)。归档快照包含验收时完整源码；当前树删除了无实例的独立根存储，七个保留 RTL 的内容与归档一致。面积仍引用该冻结网表，本次清理不声明重新测量 PPA。

[KU 最新报告](v4.2/KU_Sign_ATP_150_110_67_48.md)列出历史 L2 共同核与实验性 L1/L3/L4 综合面积；历史周期和频率不构成新源码的功能或时序验收。历史转换入口和旧实验驱动已删除，旧版本可从 Git 恢复。

## 历史 K/P/U 流水实验

以下流水接口与命令仅对应历史冻结源码，当前生产源码不再提供 P 配置；当前入口见文末 L/U 验证。

参数 `LANES/PIPELINE/UNROLL` 分别为 K/P/U，默认 K2P1U2。每 lane 的 P 个流水级各包含 U 轮，共用普通 sponge 与交错链任务；每个上下文的链反馈遵守数据依赖。WOTS 和 FORS 每批最多 K×P 个任务；K1U1、P>1 sign 的 WOTS 完成直接写回，capture 与 FORS 节点仍按原索引消费。仅新增内部 batch 接口，外部接口不变。

`make lup-unit-test` 验证轮级等价与链交错；`make lup-atp LUP_TAG=<新标签>` 执行 128f sign 的 L2U1P1～P4 仿真、共同核综合和 ATP 报告。频率统一假定 150 MHz，不布线。P>1 的其他参数集/操作未作本轮端到端验收。历史 K 标签只用于冻结证据，当前命名统一使用 L。

## 历史 K1P1U1～K1P4U1 ATP 优化验证

本轮结果见 [ATP 优化报告](v4.2/KPU_ATP_Optimization.md)，证据保存在 `manifests/experiments/kpu_atp_opt_20261007/`。最终候选为 `c4b_shared_sponge_write`；仅验收 128f sign 的四组性能，不将节点宽度单元测试视为其他参数集/操作的端到端验收。

四组逐字节软件参考、统计关闭、停顿与复位重放、共同核等价、两项异常退出及 16 项相关单元组通过；Hash/置换次数保持 104937/105641。默认 K2P1U2 与 K2P4U1 周期回归通过，14 项 Python 流程契约测试与 17 项原有基础单元回归通过。链单元增加按 tag 读取已完成摘要/capture 的保留与复用检查；共享状态覆盖普通多块吸收、链反馈及三种节点宽度填充边界。连续调度候选另通过五组显式槽位释放测试，但因 ATP 增加撤回，相关接口不进入最终源码。综合关闭统计，并审计私有 sponge 状态寄存器移除。

统一底层后的 `scripts/verify_lup_pipeline.py` 从 compact lane 的 batch 端口验证 P2～P4 和 U2P2 的随机置换、固定返回延迟和交错链；P1 使用普通 sponge/recipe 入口。链向量包含 capture 禁用、未命中、首/中/末位置及 tag 复用。`scripts/verify_kpu_chain_format.py --out <独立目录>` 对照冻结的旧链适配器，检查三种节点宽度、反馈块、同拍完成/新请求、capture 读回和控制周期。测试接线适配器不进入生产源码清单。

第二轮结果见 [统一 Keccak 与 ATP 优化](v4.2/KPU_ATP_Unified_Optimization.md)。`scripts/verify_kpu_round_decode.py --out <独立目录>` 以冻结轮函数检查零值、全一、随机状态及所有有效/无效轮号；会记录是否启用了固定级译码。该译码候选未保留，最终版本走原译码。集成签名检查新增尾批和连续输出覆盖计数。

## XMSS/LMS 扩展验证

原 SLH 流程继续覆盖六种参数集。新算法使用 `scripts/stateful_vectors.py` 生成四参数镜像和向量：冻结 `67a1cd75` 模型给出根和签名字节，新冷启动模型比较输出并统计完整树重算；`model/reference/stateful_shake.py` 独立使用 hashlib 验证，不执行微码。

```bash
python3 scripts/stateful_vectors.py
python3 scripts/run_stateful.py --lanes 1
python3 scripts/run_stateful.py --lanes 2
python3 scripts/verify_stateful_edges.py
python3 scripts/verify_stateful_lms_padding.py
python3 scripts/verify_stateful_masked_chain.py
python3 -m unittest tests.test_stateful
```

运行时 Job/ROM 集成 bench 执行真实共同核，逐字节检查 Keygen/Sign、Verify 结果、Hash/置换统计及混合长度缓存读回。边界覆盖 q=0/1/1023、超界索引、7/8/9/81/82/83/87 字节消息、签名/消息/根篡改、输入等待、截断后复位、运行中复位重放、lane 错误、统计关闭、lane 交换、非二次幂 L3 及默认 U2 配置。

实测数据及独立综合快照保存在 `manifests/experiments/stateful_20261008/`；报告见 [Stateful_XMSS_LMS.md](v4.2/Stateful_XMSS_LMS.md)。本轮只做综合，不布线，150 MHz 是估算假设。

## 当前 L/U、P=1 验证

`make lu-freeze LU_TAG=<新标签>` 冻结源码；`make lu-matrix` 对 14 个合法 L/U 配置执行 128f Sign 字节检查与 10 ns OOC 综合；`make lu-regress` 对五个代表配置执行十参数三操作；`make lu-protocol` 检查统计开关、物理交换、输入停顿、复位重放、错误清空及 Verify 篡改拒绝。全部使用 Verilator，每项编译 2 线程，综合全局最多 6 个任务、每项 4 线程。

`verify_lu_equivalence.py` 对照冻结 `9dbcac8f` 的四组 P1 配置，逐拍检查接口、地址、输出、统计和完成时刻。`mhbs_lu_check.svh` 检查未接受请求稳定性、奇偶 bank 写回和 FORS 槽位范围；recipe 单元通过冻结轮函数检查 U 轮组合结果，通过独立 SHAKE 向量检查 capture 和填充边界。

历史流水测试移至 `tb/reference/pipeline_history`；旧矩阵入口明确拒绝当前源码。历史报告及冻结源码不改写。新证据集中在 `manifests/experiments/lu_p1_20261012`。
