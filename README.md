# mHBS 项目包

固定单 Hash lane，保留 `PIPELINE=P`、`UNROLL=U`。包含当前有效 RTL、统一 Verilator 测试平台、Python 模型和独立 C 参考、向量生成与共同核综合入口。根目录 `SOURCE.json` 保留最初导出包的来源；后续实测源码校验分别保存在 `docs/manifests/experiments/` 和对应运行目录中。

支持 SHAKE 与 SHA2 两个编译后端，算法配置名保持一致。SHAKE 支持 SLH-DSA 的 `slh_128f/192f/256f/128s/192s/256s`；SHA2 支持 `slh_128f/128s`。两后端均实现 `xmss_h10/h16/h20`、`lms_h10/h15/h20` 的 Keygen、Sign、Verify。Sign 包含完整认证路径重算；h20 完整树生成及仿真默认关闭。

| 后端 | XMSS（n=32、w=16） | LMS（m=32、LMOTS w=4） | SLH |
|---|---|---|---|
| `shake`（默认） | h10/16/20，OID=0x10/0x11/0x12 | h10/15/20，LMS=0x10/0x11/0x12，LMOTS=0x0B | SHAKE256，六参数 |
| `sha2` | h10/16/20，OID=1/2/3 | h10/15/20，LMS=6/7/8，LMOTS=3 | SHA2-128f/s，SHA256＋HMAC／MGF1 |

XMSS/LMS 每叶均为67条链、每链最多15步。XMSS 按 RFC 8391/SP 800-208，LMS 按 RFC 8554/9858，SLH SHA2 按 FIPS 205。旧 omega 名称和实验 ROM 码已停用。后端通过软件 `--hash shake|sha2`、Shell `HASH_BACKEND=shake|sha2` 选择；RTL 单宏 `MHBS_SHA2` 定义时选择 SHA2，未定义时保持 SHAKE。一个综合设计只包含所选后端，运行时不切换。

`rtl/hash/shake-recipe.sv` 与 `rtl/hash/sha2-recipe.sv` 都提供相同的 `module recipe` 接口，宏保证互斥；后者使用 `rtl/hash/sha256.sv` 的单压缩通道。profile 描述符 bit5 标记后端，低5位保持参数码；RTL 拒绝后端不匹配的镜像，SHA2 同时拒绝 SLH192/256。外部节点／消息／输出握手与签名格式保持不变。

## 文件

```text
rtl/                 当前生产 RTL 与导出的共同核
model/               算法解释器、镜像编码、独立验证器与默认输入
tb/tb.sv             统一测试平台
tb/vectors/          SHAKE 镜像、输入和期望输出；sha2/ 保存 SHA2 向量
model/vectors.py     从软件模型生成全部镜像与向量
scripts/simulate.sh  Verilator 编译、仿真入口
scripts/synthesize.sh / synth.tcl
                     Vivado 综合入口
scripts/clock.xdc     时钟约束
sources.txt          完整 RTL 源码清单
SOURCE.json          最初导出包的原始提交及 SHA-256（历史清单）
VALIDATION.json      独立重生成、仿真与综合验证结果
LICENSE              MIT 许可证
```

包可整体移动。仿真与综合脚本可从任意目录调用；生成向量前先进入包根目录。软件模型与默认输入均在包内，无需原仓库、历史实验、测试归档或参考 RTL；独立 C 参考首次构建后保存在 build/reference_native。仿真编译产物和完整日志写入 `build/`。

## 独立生成向量

需要 Python 3.10 或更新版本。SLH 模型只使用标准库；XMSS/LMS 向量还使用 GCC、Git 和 OpenSSL 开发库，首次构建下载固定提交的独立 C 参考，无需 pip 依赖。即使删除整个 `tb/vectors/`，也能从 `model/default_jobs.json` 的种子、消息和 q 重新生成：

```bash
python3 -m model.vectors                # SHAKE 十个非 h20 参数三操作
python3 -m model.vectors --hash sha2     # SHA2 六个非 h20 参数三操作
python3 -m model.vectors --profile slh_128f
python3 -m model.vectors --output build/new_vectors --workers 2
python3 -m model.vectors --profile lms_h10 --q 1 --message-hex 010203
python3 -m model.vectors --profile xmss_h16 --message-length 9
python3 -m model.vectors --profile lms_h10 --q 1 --message-hex 010203 --output build/custom_vectors
VECTORS_DIR=build/custom_vectors bash scripts/simulate.sh lms_h10 verify 4 1
HASH_BACKEND=sha2 bash scripts/simulate.sh xmss_h10 verify 4 1
```

每次为所选参数生成 Keygen/Sign/Verify 三组八文件向量，以及 `generation.json` 中的 Hash/置换次数、根和文件 SHA-256。默认输入复现随包提供的向量。生成过程计算完整公钥根与签名；随后使用独立验证器验证签名并统计 Verify 工作量，不从已有向量或历史结果复制期望输出。s 参数和 XMSS/LMS 的完整树计算耗时较长。

`--job inputs.json` 接收输入覆盖：单参数时可直接提供 `secret_seed`、`secret_prf`、`public_seed`、`randomizer`、`identifier`、`message` 的十六进制字串及整数 `q`；多参数可按参数名组织对象。缺省字段来自包内默认输入。节点字段须恰好 n 字节，identifier 为 16 字节，消息为 1～87 字节，q 为 0～2^h−1；SLH 的 q/identifier 必须为零。软件默认重算 XMSS/LMS 认证路径，与当前 RTL 一致。

软件接口为 `model.executor.Job/Machine`、`model.mHBS.compile_image`；参数／镜像携带 `hash_backend`，入口缺省值为 `shake`。SHA2 默认向量目录为 `tb/vectors/sha2`，不覆盖 SHAKE 向量。`mHBS.py` 默认生成 Job 外部输入的 16/16/32 字镜像；独立验证器位于 `model/reference/slh_dsa.py` 和 `model/reference/stateful_shake.py`。在包根目录运行 `python3 -m model.vectors` 生成向量。

## 仿真

已验证工具：Verilator 5.008、Bash；编译使用系统 C++ 编译器和 make，每次最多 2 个编译线程。默认配置为 P1U2、统计开启。

```bash
bash scripts/simulate.sh
bash scripts/simulate.sh slh_128f sign 4 1
bash scripts/simulate.sh xmss_h10 verify 4 1
bash scripts/simulate.sh --smoke 4 1
bash scripts/simulate.sh --all 4 1
SIM_SYNTHESIS=1 bash scripts/simulate.sh slh_128f sign 4 1
```

`--smoke` 执行所选后端非 h20 参数 Verify 加上 128f Keygen/Sign；`--all` 执行非 h20 参数的完整三操作，SHAKE为30项、SHA2为18项。h20 Verify仅在显式单点指定并已有向量时运行。后台完整验收仅运行非 h20 参数，h20 只要求配置、ROM、位宽和 elaboration 检查。XMSS/LMS 的 Keygen/Sign 计算完整树，运行较久。运行时读取所选向量，不必为每种算法重新编译；P/U、统计配置或源码变化时重新编译。

测试逐字节检查公钥/签名、Verify 结果、Hash/置换次数以及签名缓存读回，并输出计算/总周期。出现不匹配即返回非零状态。支持附加 `+STALL=1`、`+REPLAYS=2`、`+INTERRUPT=1`；例如：

```bash
bash scripts/simulate.sh lms_h10 verify 4 1 +STALL=1 +REPLAYS=2 +INTERRUPT=1
```

`P` 范围为 1～24，`U>0`，要求 `P×U` 整除 24。U1 支持 P1/2/3/4/6/8/12/24，U2 支持 P1/2/3/4/6/12。P1 为标量单任务；P>1 可交错执行 P 个独立链上下文。每级组合展开 U 轮。SHAKE 执行24轮 Keccak；SHA2 执行64轮 SHA256，最后一轮循环越过63的部分同时旁路工作状态与调度窗口，feed-forward 单独寄存。整个核只有一个 recipe 前端，流水级不复制配方格式化器。

独立 `pipeline` 模块已删除。SHAKE P1 使用 `recipe.scalar_execution` 标量路径：单 Keccak 状态、固定块格式化、链反馈和流式吸收，不实例化上下文引擎。P>1 的固定块与上下文调度位于 `recipe.scheduled_execution.fixed_context`，真正的 Keccak 各级状态由 `scheduled_execution.stages` 保存。最新面积和实测周期见 [P1 标量对照](docs/manifests/experiments/p1_scalar_20261014/reports/P1_Scalar_20261014.md)；此前全部 P/U 使用上下文引擎的历史测量见 [Recipe 合并对照](docs/manifests/experiments/recipe_integration_20261014/reports/Recipe_Integration_Matrix_20261014.md)。

2026-10-13 优化：XMSS/LMS 的完整端点批次直接写入单端口端点存储；无需输出捕获的批次在最后一个响应到达时推进。直接写回与批后读取共用上下文读端口。Verify、仅签名链及单槽捕获尾批保留原消费顺序。

```bash
bash scripts/benchmark_targets.sh 12 1  # 128f Sign、XMSS/LMS h10 Keygen
python3 scripts/check_keccak.py        # 64 项 LUT 真值表 + 两种映射各 816 项逐轮对照
python3 scripts/report_atp.py          # 从归档证据重建 Markdown / JSON
```

SHA2 的 `hash_count` 统计完整 SHA256 调用（HMAC 内外层、MGF1 各次分别计数），`permutation_count` 统计实际64字节压缩块次数。SHAKE 仍统计完整 SHAKE 与 Keccak 置换。两种算法工作量不同，不能直接沿用 SHAKE 的 Hash 计数或 ATP 基线。

SHA2 的 SLH 地址哈希与 XMSS 的 KEY/MASK 公共种子 PRF 共用一个首块中间态缓存，分别保存 `PK.seed || zero padding` 和 `toByte(3,32) || PK.seed`，所有合法 P/U 均适用。冷启动由现有压缩通道计算一次，后续从第二块续算；算法或相关种子变化时重建，复位时失效。秘密种子的 INDEX/PRFkeygen 不使用该缓存。向量 `meta.mem` 保留算法的逻辑块数，快仿日志 `logical_permutations` 对应这一数值；日志 `permutations` 和 RTL 统计端口均为缓存后的实际压缩次数，仿真严格检查两者。

SHA2 的固定格式块直接写入现有512位输入寄存器，列表和变长消息继续使用128位流式路径；压缩返回时可提前预约下一描述符。P1U1、SLH128f Sign 的同33字节KAT实测 Remaining 从1,030,190降至410,621，总周期从7,953,600降至7,334,031，完整签名及缓存保持一致。三点面积、周期和假定同频ATP，以及候选取舍见 [SHA2 Remaining 优化](docs/manifests/experiments/sha2_remaining_optimization_20261023_162334/reports/SHA2_Remaining_Optimization_20261023_162334.md)。本轮只做100MHz诊断综合，实际布线频率尚未重新验收。

后续链反馈版本G复用原块寄存器作为模板，从已寄存的压缩输出直接启动下一步，连续SLH/LMS链不再返回格式器。相同KAT的P1U1 Remaining进一步降到127,895，总周期7,051,305，Hash占98.19%。P1面积增加1.20%；多槽反馈命中较少，并有面积/同频ATP代价，具体见 [SHA2 链反馈对照](docs/manifests/experiments/sha2_chain_replay_20261023_165540/reports/SHA2_Chain_Replay_20261023_165540.md)。所有P/U共用同一运行时条件和通用回退路径，未新增P/U专用开关；频率仍需实际布线验收。

最新C候选精简逐槽描述符和初始CV写入，并把同一缓存银行用于XMSS公共PRF。相对G，P4U1/P12U1 common等效Slice下降7.93%/4.04%，P1U1增加1.09%；XMSS h10 Sign三点实测周期下降约32%，假定150MHz的辅助ATP下降31.54%～37.62%。SLH/LMS周期不变，其ATP随面积变化；P1的两项ATP增加1.09%。冷填充竞争失败候选及修复、完整签名/计数对照、独立C参考和三点100MHz诊断综合见 [本轮SHA2 ATP报告](docs/manifests/experiments/sha2_atp_round_20261023_172538/reports/SHA2_ATP_Round_20261023_172538.md)。本轮没有重新布局布线，尚未验证150MHz闭合。

实测比较和剩余瓶颈见 [ATP 优化报告](docs/manifests/experiments/atp_optimization_20261013/reports/ATP_Optimization_20261013.md)。基线与候选源码、面积/时序报告及测试日志随文档归档。

2026-10-14 聚焦 P12U1、P4U1、P1U1 的 SLH-DSA 128f、XMSS h10、LMS h10 Sign，见 [三点优化报告](docs/manifests/experiments/atp_focus_20261014/reports/ATP_Focus_P12_P4_P1_20261014.md)。结果包含同一候选的 common 面积、九项实测周期、150MHz 假定 ATP、单点回退及逐阶段取舍。可用以下命令冻结源码并只测这三个配置：

```bash
python3 scripts/run_pu_sign_matrix.py --launch --configs P12U1 P4U1 P1U1 --vivado-workers 3 --sim-workers 3
```

后续配方冗余清理与 L-tree/LMS 控制空拍优化见 [配方冗余与 ATP 对照](docs/manifests/experiments/recipe_redundancy_20261014/reports/Recipe_Redundancy_ATP_20261014.md)，包含同源码面积、周期、失败候选及精简 mask 回归。`python3 scripts/check_recipes.py --recipe-mask 0x101e` 可独立检查关闭 LMS 列表配方后的 SLH 128 位列表窗口。

P4U1 的统一固定块执行、滚动链补发、并行 L-tree、128 位流式生产及 FORS 四叶归约见 [P4U1 联合优化报告](docs/manifests/experiments/p4_joint_20261013/reports/P4U1_Redundancy_Performance_ATP_20261013.md)。以下入口检查独立字节配方、标签回收与完整回归，并导出逐状态周期分解：

```bash
python3 scripts/check_recipes.py
python3 scripts/check_pipeline.py     # recipe 内部上下文、标签与捕获测试
python3 scripts/check_recipes.py --hash sha2
python3 scripts/check_pipeline.py --hash sha2 --pipeline 12 --unroll 1  # 当前局部bench覆盖低4标签
python3 scripts/check_sha2_prefix_cache.py --pipeline 12 --unroll 1  # 全槽冷填充、换种子、复位与捕获
python3 scripts/check_sha256.py --all  # 全部合法 P/U 的压缩、尾轮、停顿与复位
python3 scripts/check_statistics.py   # 实际置换事件驱动的 64 位统计进位
scripts/validate_p4.sh build/p4_validation
python3 scripts/profile_p4.py --output build/p4_profile
```

仿真默认使用通用布尔表达式；`KECCAK_LUT6=1` 可直接仿真 FPGA LUT 的 INIT 表，运行较慢，编译目录另加 `_lut6`。逐轮检查覆盖两条实现路径。

## 综合

```bash
bash scripts/synthesize.sh          # P1U2
bash scripts/synthesize.sh 4 1      # P4U1
HASH_BACKEND=sha2 bash scripts/synthesize.sh 4 1
```

Vivado 2025.2，器件 `xc7a200tffg1156-3`，2 线程，约束 6.666667 ns。综合顶层为 `common`，通过 `SYNTHESIS` 宏裁剪统计；检查周期及 Hash/置换计数寄存器已裁剪。终端仅显示阶段结果，完整日志和分层面积、总面积、综合时序报告默认位于 `build/synth/PxUy_generic/`。本入口只综合、不布局布线；综合约束不是实测频率。

SHA2 输出目录另加 `_sha2`；仿真与综合的源码身份、缓存和结果均记录后端。双后端验收入口 `scripts/run_hash_backends.py --launch --gate <通过的局部验证JSON>` 冻结两版源码，在后台运行完整非 h20 回归以及两后端 P1U1/P4U1/P12U1 的100 MHz共同核综合；不自动布线。

SHA2 formatter采用共享64位／128位固定窗口，已完成P1U1/P4U1/P12U1三点common综合及九项目标Sign；后续并行轮询仲裁尝试因P4/P12面积与固定频率ATP回退而撤回，最终保留候选1：见[实测结果](docs/manifests/experiments/sha2_optimization_candidate_20261019_175821/reports/SHA2_Optimization_20261019_175821.md)、[资源与关键路径归因](docs/manifests/experiments/sha2_optimization_candidate_20261019_175821/reports/SHA2_Formatter_Analysis_20261019_175821.md)和[候选阶段记录](docs/manifests/experiments/sha2_optimization_candidate_20261019_175821/reports/SHA2_Optimization_Stages.md)。ATP使用100MHz假设频率；综合路径时延不作为布线频率。

2026-10-22 的 SHA2 I 候选已覆盖当前 RTL：请求先登记再分配，每槽单独译码和写回，首个列表地址及地址字段分别提前登记；SHA256 预存 H/K/W 的 carry-save 对，并把 Sigma(E) 后接到共享加法树。保留单 Hash lane、P 个上下文和原接口。I 相对 G2 的690项真实 RAM 配方及432个满槽请求逐项周期、输出与计数一致；原语全部30个合法 P/U 的普通和综合视图均通过独立向量验证。

本轮硬目标为 U1≥150MHz、U2≥100MHz，14点使用同一冻结源码运行42项完整Sign、100MHz诊断和实际布线。U1使用6.666ns约束，实际周期验收容差为零；完整路由、setup/hold和DRC均通过才算达标。新候选频率、面积及ATP仍待测量，不沿用旧候选通过点，进度见[I候选报告](docs/manifests/experiments/sha2_timing_g_candidate_20261022_120553/reports/SHA2_Timing_G_20261022_120553.md)。


后续又完成五组SHA2面积／时序候选（共45项Sign、15次common综合），均未降低三个算法在本轮三点中的最佳固定100MHz假设ATP，因此当前RTL仍保留上述固定窗口版本。候选的面积／路径取舍、未采用原因及完整证据见[五候选对照](docs/manifests/experiments/sha2_optimization_candidate_20261019_184135/reports/SHA2_Five_Candidate_Review_20261019.md)。

2026-10-19 SHAKE 时序候选及其固定目标布线保留为历史证据，见[时序架构对照](docs/manifests/experiments/shake_timing_optimization_candidate_20261019_213301/reports/SHAKE_Timing_Architecture_20261019.md)与[固定目标报告](docs/manifests/experiments/timing_targets_20261019_213925/reports/Timing_Targets_20261019_213925.md)。

2026-10-20 从冻结 C2 继续优化的结果已完成：[C2 后续对照](docs/manifests/experiments/c2_timing_optimization_20261020_100009/reports/C2_Timing_Progress_20261020.md)。其中 R5 是唯一让 P12U1／P4U1 均通过 130 MHz 布线的候选；R1 在 P4U1 同频率下的面积与 ATP 更低，保留为对照。两者均未通过 150 MHz，不能把失败 WNS 外推为已验证频率。

以冻结 R5 为基线的四版候选已经完成：S1 删除无效端点字选择、拆分响应队列并维护树目标的当前层坐标；S2 提前登记相邻 RAM 地址与认证判断；S3 使用直接登记阶段的 recipe 状态编码；S4 并行选择预先配对的主／邻地址。S4 的 common 实际布线闭合频率为 P12U1 139.9972 MHz、P4U1 149.9925 MHz，成为本轮两配置的共同基线；P12U1 的 150 MHz 尝试仍差0.063 ns。完整历史对照见[R5 后续报告](docs/manifests/experiments/r5_timing_optimization_20261020_110128/reports/R5_Timing_Progress_20261020.md)。

从 S4 出发的 T1／T2／T3 已完成比较，剩余两项 T3 布线按用户要求停止。T2 将完成结果先写入既有 bitmap/count，再推进批次，周期增幅最高约0.183%；它的 P12U1 和 P4U1 均在实际6.667 ns（149.9925 MHz）约束下通过布线 STA，160 MHz 尝试未通过。T2 的 P12U1 三项布线 ATP 比 S4 各自最佳降低约6.5%～6.6%，P4U1 则增加约2.0%～2.1%；同一份 RTL 选择 T2。历史证据见[S4 后续报告](docs/manifests/experiments/s4_timing_optimization_20261020_115725/reports/S4_Timing_Progress_20261020.md)。

随后以冻结 T2 为基线测量返回控制预取、平坦写回选择、sponge 容量复用、响应队首预计算与滚动槽回收五项组合，见[T2 面积与延迟对照](docs/manifests/experiments/t2_atp_optimization_20261020_135654/reports/T2_ATP_Progress_20261020.md)。该轮U5候选的P12U1/P4U1等效综合Slice为15,957.875/9,577.500，比T2减少0.71%/4.42%；诊断路径为5.259/4.680 ns，周期增幅0.061%～0.214%。U4保留为P12固定频率ATP对照。`python3 scripts/run_t2_atp_optimization.py --launch-candidate --label <候选名>` 默认仅执行六项完整 Sign 和两项100 MHz common诊断综合；`python3 scripts/validate_t2_atp_candidate.py --run-root <运行目录>` 运行补充验证，`python3 scripts/report_t2_atp_optimization.py` 更新对照。候选未进行布局布线，100 MHz ATP 为假设频率下的辅助指标，不代表实际频率提高。实现保持通用 P/U、单 Hash lane 与原数据接口，P1仍用标量路径；h20完整树继续停止。

最新工作区保留U5后续的V8候选，见[八候选实测对照](docs/manifests/experiments/u5_atp_optimization_20261020_145923/reports/U5_ATP_Progress_20261020.md)及[架构取舍](docs/manifests/experiments/u5_atp_optimization_20261020_152253/reports/U5_ATP_Architecture_20261020.md)。同口径100 MHz common综合：P12U1为15,749.375等效Slice、P4U1为9,559.500，比U5减少1.306565%/0.187940%；周期完全不变。P12诊断路径5.259→5.190 ns，P4为4.680→5.198 ns回退。V2保留为P4固定频率ATP更优对照。全部48项Sign、608组补充验证通过；没有重新布线，实际频率与布线ATP未知。`python3 scripts/run_u5_atp_optimization.py --launch-candidate --label <候选名>`默认只运行六Sign和两项100 MHz综合，`python3 scripts/report_u5_atp_optimization.py`刷新源码绑定汇总。

`scripts/run_shake_timing_optimization.py --launch-baseline` 冻结当前源码，后台运行两配置六项 Sign 和100 MHz诊断综合；后续用 `--launch-candidate --baseline-run <基线目录>` 冻结候选，显式增加 `--route --route-mhz 150` 才运行布线。`scripts/report_shake_timing_optimization.py --watch` 更新本轮对照。综合路径延迟不换算为实测频率。

C2 后续实验使用 `scripts/run_c2_timing_optimization.py --launch-candidate --label <候选名>`，强制核验冻结 C2 的源码和实测工作量；诊断完成后显式执行 `--route-existing <运行目录> --route-mhz 150 130`，只为该冻结候选追加布线。`scripts/report_c2_timing_optimization.py --watch` 汇总结果。每个 Vivado 两线程、最多十二个进程，异常长任务保留后台运行。

R5 后续实验使用 `scripts/run_r5_timing_optimization.py --launch-candidate --label <候选名>` 和 `scripts/report_r5_timing_optimization.py --watch`。该入口严格绑定 R5 的源码、六项 Sign、两项诊断及 130／150 MHz 布线证据；`--route-existing <运行目录> --route-mhz <明确目标>` 仅为已通过验证的同一冻结候选追加布线，默认测量仍只做诊断综合。

S4 后续实验使用 `scripts/run_s4_timing_optimization.py --launch-candidate --label <候选名>` 和 `scripts/report_s4_timing_optimization.py --watch`，先执行六项 Sign与两项100 MHz诊断。显式 `--route-existing <运行目录> --route-mhz <目标>` 为同一冻结候选追加布线；实际STA闭合与名义目标精确匹配分开记录，ATP按实际周期计算。每个P/U与自身最高已验证的S4频率比较，不从失败WNS外推Fmax。

SHAKE 综合默认使用通用 Keccak 表达式，报告位于 `build/synth/PxUy_generic/`。`KECCAK_LUT6=1 bash scripts/synthesize.sh 12 1` 可比较 Xilinx 专用映射：定义 `MHBS_XILINX_LUT6`，将旋转后的三个 Theta XOR 与 Chi 合并为一个六输入 LUT，INIT 为 `64'h6666966996696666`，报告位于 `build/synth/PxUy/`。本轮两个配置的通用映射均优于显式 LUT6 映射，因此通用映射为默认。未定义该宏时，RTL 可继续由其他工具读取。

共同核面积包含控制器、算法数据存储与 Hash lane，ROM 和完整签名缓存由外部提供。生产 `top` 内含这些 ROM，并可启用完整签名缓存，面积口径不同。

`scripts/implement_p4.tcl` 对冻结源码运行同设置的 P4U1 OOC 综合、布局布线和 STA。首次约束为 6.666667 ns；失败后按实测路径延迟放宽并重新实现，最终在固定布线上按 0.1 ns 检查 setup/hold 闭合。它不增加时序例外，保存完整报告及检查点。两个 Tcl 参数依次为含 `sources.txt` 的源码根目录和独立输出目录；输出目录中的源码校验可防止复用过期综合检查点。

## 顶层与接口

- `rtl/top/top.sv`／`top`：生产顶层，Job 参数在综合/实例化时配置，含 program/template/descriptor ROM 和可选签名缓存。默认 ROM 路径为包内 128f Sign 镜像。
- `rtl/top/common.sv`／`common`：从生产顶层执行区域导出，Job/ROM 为运行时端口，供统一测试与共同核面积综合使用。
- 其余模块：`keccak`、`sha256`、`recipe`、`executor`、`sequencer`、`value`、`signature`；两份后端 recipe 文件宏互斥。`sources.txt`、实例引用、仿真和综合入口已统一使用这些名称。

两个入口每次复位执行一项操作，完成/错误状态保持至复位。`rst` 高有效、同步；切换 Job 或镜像后重新复位。生产顶层 `OPERATION=0/1/2` 对应 Keygen/Sign/Verify；共同核使用 `job_operation`。秘密种子、PRF 种子、公种子、R 随机量、公钥根分别通过生产顶层参数或共同核 `job_*` 端口提供，使用节点低 128/192/256 位。

| 端口 | 用法 |
|---|---|
| `message_length[6:0]` | Keygen 为 0；Sign/Verify 为 1～87，在接受 Job 时锁存 |
| `message_valid/ready`、`message_data[63:0]` | 上升沿 valid/ready 同为 1 时接收；等待时保持数据；低字节在先，尾拍多余字节忽略 |
| `verify_valid/ready`、`verify_data[255:0]` | 同样握手，每拍一个低位 n 字节节点；不足节点时等待 |
| `out_valid`、`out_data[255:0]`、`out_bytes[5:0]` | 每有效拍输出低位 4/16/24/32 字节，低字节在先，无输出背压 |
| `done`、`error`（仿真另有 `error_code`） | 操作完成/执行错误；Verify 根不匹配不属于执行错误 |
| `verify_pass` | Verify 完成且 error=0 时判断签名是否通过 |
| `SYNTHESIS` 宏 | 定义时裁剪诊断端口与寄存器，包括 `error_code` 和64位统计；仿真默认不定义 |

Verify 使用节点接口，由外部拆分签名并校验总长度。SLH 顺序为 R、各 FORS 树的秘密节点和认证路径、各层 WOTS 签名与认证路径。XMSS/LMS 顺序为 R、67 个链节点、h 个认证节点，路径从叶到根；q 和 LMS 类型字段不作为节点输入。公钥根由调用方提供。

XMSS/LMS 的 `KEY_INDEX`／`job_index` 为 q（0～2^h−1），LMS 的 `IDENTIFIER`／`job_identifier` 为 16 字节 I。q 由外部持久化管理，每次签名只能使用一次；复位不恢复可用索引。

编译时定义 `MHBS_SIGNATURE_STORE` 宏，生产顶层保存完整 Sign 输出；未定义时不实例化签名缓存，其读回接口返回零。该宏独立于 `SYNTHESIS`。`signature_valid=1` 后按节点索引发起 `signature_read_enable/address`，下一同步读响应使用 `signature_read_valid/data/bytes`；将各项低位有效字节拼接即可恢复签名。

## 向量格式

每个 `tb/vectors/<profile>/<operation>/` 目录包含八个文本文件：

| 文件 | 内容 |
|---|---|
| `program.mem`、`template.mem`、`descriptor.mem` | 16/16/32 项微码镜像，按 `sources.txt` 中的控制器解码 |
| `job.mem` | 五个种子/根字段、identifier、q、操作、消息长度（共 9 项） |
| `message.mem` | 消息字节 |
| `nodes.mem` | Verify 输入节点；其他操作不使用 |
| `expected.mem` | Keygen/Sign 期望输出字节；Verify 没有输出数据流 |
| `meta.mem` | 输出字节数、Hash 次数、逻辑置换／压缩块数、Verify 节点数、预期 Verify 通过标记；SHA2 SLH 的实际缓存后压缩数由仿真另行核对 |

随包保留默认向量，也可全部由包内软件重新生成。使用新的输入时，运行生成脚本一次即可同步更新镜像、Job、节点和期望结果。

## SHAKE256 六参数标准迁移

`xmss`、`lms` 默认对应各自 h10。旧 `*_omega*` 名称会报告迁移错误，历史报告与向量保留用于复核，不能作为新标准任务的性能基线。内部 ROM 配置码为0x18～0x1D，标准 XMSS/LMS 算法类型码为0x10/0x11/0x12，LM-OTS 类型码为0x0B。

Keygen只输出标准公钥：XMSS为68字节（OID、root、public_seed），LMS为56字节（两个类型码、I、root）。Sign输出标准签名；Verify节点接口由软件先校验完整签名的长度、类型和q，再拆分输入。仿真中的 cycles、启动/Keygen/Sign周期和Hash/置换统计端口均为64位；定义 `SYNTHESIS` 时诊断端口与寄存器一起消失，功能性错误中止仍有效。外部随机输入和q持久化管理仍由调用方负责。

```bash
python3 scripts/build_stateful_reference.py
bash scripts/simulate_fast.sh xmss_h20 keygen  # 完整逐拍RTL，没有周期外推
bash scripts/simulate_fast.sh lms_h20 sign
vivado -mode batch -nolog -nojournal -source scripts/synth_top.tcl -tclargs xmss_h16
```

直接C++驱动入口用于大树完整实测，仍实例化生产common和签名缓存，并检查每个输出字节、缓存读回、实际Hash/置换事件及64位硬件统计。停顿、异常和兼容检查使用原SystemVerilog测试台。

迁移验收、六个top与通用核面积及实测周期见 [SHAKE256标准迁移报告](docs/manifests/experiments/stateful_standard_20261013/reports/Stateful_SHAKE256_Standard_Migration_20261013.md)。报告在全部36项和边界检查完成前保持“执行中”，大树周期不外推。


通用 P/U 重构移除了 P4U1 专用执行分支，固定哈希统一使用上下文引擎，P1 复用迭代 Keccak。树栈和认证路径分别复用端点 RAM 的 68～87、88～107 槽；112～135 槽保存 FORS 批次结果。签名缓存与 XMSS 同时存活的 key/digest/captured 银行保持独立。

综合时间异常时跳过该点的当前分析，让综合继续在后台运行，不终止进程；通过其他已完成配置给出总体结论。后台矩阵及 `synthesize.sh` 默认10分钟后标记分析暂缓，尚未完成的面积与ATP留空，完成后补入报告。矩阵可用 `--synth-defer-seconds`、单点脚本可用 `SYNTH_DEFER_SECONDS` 调整分析等待阈值。

本轮冻结矩阵与后台验收见 [PU_Generic_Sharing_20261013.md](docs/manifests/experiments/pu_generic_sharing_20261013/reports/PU_Generic_Sharing_20261013.md)，P3U2 的当前分析暂缓，综合继续后台运行。XMSS/LMS h20 完整 Keygen、Sign 继续停止。

实验报告统一入口：[实验与测试归档](docs/manifests/experiments/INDEX.md)。每次矩阵测试自动保存冻结 `rtl.tar.gz`、`RTL_SOURCE.json`、每个 P/U 的 `hierarchical.rpt` 和 `timing.rpt`、综合日志及验证结果摘要；省略 `sim`/`validation` 明细日志。独立 common/top 综合也先冻结源码并归档；后台结果由 `python3 scripts/experiment_archive.py --sync --watch` 持续补齐。
