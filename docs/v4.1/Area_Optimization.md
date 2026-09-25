# μHBS v4.1：面积优先优化

## 范围与验收口径

基线为 `u2_readselect_route`：32,257 LUT、14,133 FF、2,312 LUTRAM、
0 BRAM/DSP，等效面积 **9,830.875 Slice**，post-route **100 MHz**。
七点各自的 Sign 周期允许增加不超过 5%。最终取舍同时检查实测频率与七点最差 ATP 比例。
论文门槛和旧三点 V3 上限保持不变；未达标时仅称为优化候选。

保持 U2、双 Hash lane、五类宏指令、ABI 4 逻辑编码和三个独立 ROM。
每份镜像使用同一物理布局。输入仍只有 `clk/rst`；索引策略仍为 `fixed_q_no_guard`。
本轮没有引入 BRAM、完整树缓存、通用处理器或按算法选择的完整流程 FSM。

## 1. 吸收和长消息格式器 :codex-annotation{index="1"}

首先试验直接向 1,600 位状态逐拍吸收 64 位数据，删除原 128 位暂存。
功能通过，但整机等效面积由综合基线 9,843.875 增至 9,886.375 Slice，
综合 WNS 由 +2.115 降为 +0.776 ns，因此撤回。暂存器数量减少并不保证整机面积下降。

保留原 128 位吸收接口，改为先选择当前状态中的 128 位片段，
与输入共享一组 XOR，再写回目标状态字。新 Hash 的首块清零语义、
多块 Hash 的完整状态保留、短 Hash 的 1,088 位快速装载及链内直接反馈均保留。
该改动相对仅压缩 template 的候选减少 42.875 Slice，执行周期不变。

面积优先组合进一步将长消息/列表格式器从 64 位缩至 32 位，
每四拍组成 128 位输入；136 字节块的最后一个输入只需两拍有效数据。
短 Hash 和链反馈仍使用原快速路径。对 24 字节节点、LMS 两字节偏移、
消息尾部、跨块 SHAKE 填充均显式处理。七点 Sign 增量最大为 2.702%，
Keygen 增量另列，不能把 Keygen 成本隐藏到 Sign 加速中。

## 2. 单宏发射和完成事件 :codex-annotation{index="2"}

执行器本来一次只接受一条宏命令；裁剪未使用的第二条命令坐标、步长和循环偏移寄存器，
以及多事件 scoreboard，保留一个完成事件。兼容端口中未使用的第二宏输出固定为零，
综合后不形成第二宏调度器。两条 Hash lane 的内部并行调度不变。

program 仍支持 SINGLE、RUN、两级 LOOP 和 HALT；宏模板仍决定五类操作。
入口在收窄为 6 位 PC 前检查完整字段，拒绝数据区入口、非零事件编号、
第二宏字段和超范围 LOOP 回跳。软件先校验一条宏完成后才发射下一条的镜像约束。
独立综合候选减少 61 Slice，Keygen/Sign 周期不变。

## 3. 固定宽度物理镜像 :codex-annotation{index="3"}

逻辑 `.mem` 和 ABI 4 地址不变。INIT 生成器将 template 打包，物理 ROM 读取后以连线展开。
七点始终采用相同的打包规则，硬件不依据某个镜像的零值裁剪。

| ROM | 逻辑容量 | 保留的物理容量 | 端口 |
|---|---:|---:|---:|
| program | 64×128 | 64×128 | 1 |
| template | 64×128 | 64×64 | 1 |
| descriptor | 128×64 | 128×64 | 2，复制存储 |

| template 逻辑位 | 物理位 | 内容 |
|---|---|---|
| 127:124 | 63:60 | opcode |
| 123:116 | 59:52 | wait mask |
| 115:108 | 51:44 | consume mask |
| 107 | 43 | 首条命令有效 |
| 105:103 | 42:40 | event 编号，当前执行合同仅允许 0 |
| 99:76 | 39:16 | 首条命令字段 |
| 3 | 15 | track |
| 固定为零 | 14:0 | 保留；物理非法值触发非法逻辑 opcode |

第二宏字段和模板坐标必须为零；坐标由 program 提供。无法无损表示的模板在软件打包时拒绝。
template 的局部资源从 128 LUT 降至 67 LUT（64 LUTRAM＋3 LUT 检查），
整机 LUTRAM 从 2,312 降至 2,248。读取拍数不变。

descriptor 曾试作固定 64×64 存储，将高逻辑地址映射到未用低地址槽。
两个端口的映射和非法地址门控使局部 LUT 从 256 增至 282，故撤回。
`model/physical_image.py` 保留该实验的打包器和软件门禁，用于复现淘汰结果；
生产 `rom_initialization.py` 只压缩 template，descriptor 仍按原地址直接存储。

## 4. 综合筛选结果

以下均为 post-synth，100 MHz 仅用于归一化 ATP，不能从 WNS 宣称实现频率。
LUTRAM 已包含在 LUT 内。全部候选 BRAM/DSP 均为零。

| 候选 | LUT | FF | LUTRAM | 等效 Slice | WNS/ns | Sign 周期 |
|---|---:|---:|---:|---:|---:|---|
| u2_readselect（原综合基线） | 32,312 | 14,127 | 2,312 | 9,843.875 | +2.115 | 基线 |
| u2_direct64（撤回） | 32,611 | 13,869 | 2,312 | 9,886.375 | +0.776 | 部分增加 |
| u2_singlemacro | 32,136 | 13,991 | 2,312 | 9,782.875 | +1.908 | 不变 |
| u2_template64 | 32,251 | 14,127 | 2,248 | 9,828.625 | +2.115 | 不变 |
| u2_template64_absorbpair | 32,077 | 14,132 | 2,248 | 9,785.750 | +2.115 | 不变 |
| u2_area_balanced（前三项组合，64 位格式器） | 31,976 | 13,996 | 2,248 | 9,743.500 | +1.909 | 不变 |
| u2_area_stream32（组合＋32 位格式器） | 30,568 | 13,856 | 2,248 | 9,374.000 | +1.902 | 最大 +2.702% |

两个组合候选的完整综合均耗时 171 秒。面积优先组合相对原综合基线下降 4.773%。
组合收益以整机报告为准，不能直接相加各独立候选的收益。

**最终保留 `u2_area_balanced_route`，工作树 RTL 与其快照一致。**
32 位格式器通过功能和周期上限检查，但其原布线尝试经过 3,432 秒仍处于严重拥塞修复，
最后记录的中间 WNS 为 −3.198 ns，未获得合格布线证据，因此停止并撤回工作树中的该改动。
它的 **9,374 Slice 仅为综合面积**；没有可验收频率或 post-route ATP，不能据此声称优于保留方案。
源代码保存在 `candidates/u2_area_stream32/source_snapshot.tar.gz`，未完成布线记录保存在
`screening/stream32_route_incomplete/`。其他有效改动继续保留。

| Profile | 基线 Sign | 32 位候选 Sign | 增量 | 基线 Keygen | 32 位候选 Keygen |
|---|---:|---:|---:|---:|---:|
| slh_128f | 730,773 | 744,359 | +1.859% | 29,864 | 30,480 |
| slh_192f | 1,252,185 | 1,278,926 | +2.136% | 43,662 | 44,878 |
| slh_256f | 2,583,685 | 2,653,503 | +2.702% | 115,780 | 119,892 |
| xmss_omega2 | 5,599 | 5,631 | +0.572% | 16,898,048 | 16,898,048 |
| xmss_omega4 | 11,172 | 11,204 | +0.286% | 24,844,288 | 24,844,288 |
| lms_omega2 | 3,363 | 3,380 | +0.506% | 4,871,203 | 5,364,771 |
| lms_omega4 | 4,423 | 4,440 | +0.384% | 7,917,603 | 8,165,411 |

Boot 均为 262 拍。两个组合候选的 Hash/置换次数和逐字节输出与向量一致。
布线结果及最终候选选择以同目录 `Unified_HBS_Paper_Comparison.md` 的实测表为准。

### 已完成的布线与冻结

`u2_area_balanced_route`：32,000 LUT、13,996 FF、2,248 LUTRAM、0 BRAM/DSP，
**9,749.5 Slice、100 MHz**。七点周期与基线相同，面积及最差 ATP 比例降低 **0.828%**。
setup 裕量 0.132 ns，hold 裕量 0.090 ns；完整布线、脉宽及覆盖检查通过。
布线工具会话耗时 807 秒。

七份 INIT 检查点的共同硬件哈希为
`61062ecc1ac3463f9bc90a15e4e0551148f3a0d9b68ff08c399021ee26759aa8`。
单元、连接、布局、布线与资源一致，全部 INIT 与逻辑镜像逐字对应。
结构文本以无损 gzip 保存；哈希按解压后的字节计算。

冻结脚本先前调用 `list_property`，在 Vivado 的层次单元上触发隔离逻辑处理而失败；
改为显式属性查询，从原有效 DCP 重跑后通过。失败记录保存在
`screening/freeze_query_failed/`；实际使用的检查脚本封存在候选的 `frozen/flow.tcl`，
复现冻结阶段时使用该文件替换源码快照内的早期检查脚本。

另试验将 100 MHz 候选的布局/布线复用于 32 位格式器。Vivado 检测到单元匹配
71.14%、网络匹配 70.57%，低于其 80%/75% 复用门槛，自动退出增量模式。
该尝试在继续重新布局前停止，不计为完成布线；记录在 `screening/incremental_placement/`。

同一 32 位布局检查点还尝试了 10.2 ns 目标和 Default 路由策略，但仍出现持续拥塞，
在原路由继续运行时停止该附加对照。其检查点、命令及日志保存于
`screening/stream32_relaxed_incomplete/`，不报告该未完成尝试的最终频率或 ATP。

## 5. 验证与复现

新增软件门禁先检查七点完整输出、Hash/置换计数、镜像往返和八类错误，
封存在 `software/area_v1/software_gate.json`，之后才修改调度与 ROM RTL。
沿用独立算法模型及既有 KAT、缓存和树检查。

Icarus 增加 135/136/137 字节填充、多块吸收、非法事件、次级宏字段、
入口截断与 LOOP 回跳溢出检查。Verilator 检查七点全流程、q 边界、消息边界、
交换 lane、复位中断/重放、停机及执行前/输出中故障。
物理 ROM 检查使用 Vivado RAM 原语仿真模型，对七份镜像的全部地址与双 descriptor 端口逐字比对。

```bash
make area-software-test
make rtl-test
make rtl-verification
python3 scripts/reproduce_autonomous.py --allow-incomplete --functional-tag u2_area_stream32
python3 scripts/reproduce_autonomous.py --allow-incomplete --functional-tag u2_area_balanced_route
python3 scripts/select_area_candidate.py u2_area_balanced_route
```

候选分别保留源码快照、哈希、完整仿真引用、综合 DCP 与原始报告。
局部筛选证据位于 `screening/packed_roms/` 和 `screening/area_lanes/`。
`synth_autonomous_snapshot.py <新 tag>` 从已捕获且逐项校验的快照综合，允许工作树继续变化。
复现时必须使用该候选快照，不能把后续源码的周期与历史面积混用。

布线冻结后仅修改 ROM INIT，不再次优化、布局或布线；核验七份检查点的共同结构、资源及 INIT。
NON_STRICT 限制、固定输入、缓存策略和无 guard 语义见对比报告。
