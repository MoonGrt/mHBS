# μHBS SLH-DSA 优化执行计划

> 版本：v1.0，2026-09-16
> 对象：独立、无 runtime、无需软件逐步喂任务的 μHBS SLH-DSA-SHAKE-128f Sign RTL
> 原则：先消除确定的周期瓶颈，再提高 Hash 并行度，最后压面积和闭合时序。

> 当前执行状态：Wave 1、Wave 2 功能 Gate 已通过；Wave 3 已完成连续
> 源字 request 重叠和单项 128-bit lane-local Hash 反馈缓存。NIST ACVP
> tc137 实测为 6,002,014 cycles，较 14,333,951-cycle 基线累计减少
> 58.127%。732,201 个后续 component 全部预取命中；反馈缓存命中
> 187,612 次，将 Scratchpad 读取从 630,294 降至 442,682（−29.766%）。
> Hash/permutation、component 和签名结果计数不变；写入仍为 205,939。
> 当前 post-route 为 34,874 LUT / 23,903 FF / 7 RAMB36 / 0 DSP、
> WNS -1.489 ns；相对原基线 LUT×cycles 改善 57.032%，timing-aware
> LUT×time 改善 52.560%。Wave 3 因未达 35% 读及 25% 写的退出门槛仍为
> 部分完成；100 MHz 时序留到数据路稳定后闭合。

> 2026-09-17 水平微码双-lane 分支更新：新的独立 Sign 顶层已生成
> tc137 完整 17,088-byte 签名，实测 704,060 cycles / 105,641
> permutations，两 lane 平均利用率 90.94%。`xc7a200tffg1156-3`
> OOC post-route 为 36,898 LUT / 15,809 FF / 13 RAMB18 / 0 DSP，
> post-route phys-opt 后 WNS +0.035 ns。Wave 4 的功能和性能 Gate 已通过；
> Wave 5 面积目标、微码到 materializer 直连以及产品 ROM top 仍未完成。

## 1. 已接受基线

所有优化均与同一个已验证基线比较，不允许混用估算值、旧架构结果或不完整轨迹。

| 指标 | 当前基线 |
|---|---:|
| 完整 Sign 周期 | 14,333,951 cycles |
| LUT / FF | 33,985 / 23,269 |
| RAMB36 / DSP | 7 / 0 |
| 100 MHz WNS | -0.406 ns |
| 路由后估计频率 | 96.10 MHz |
| 路由后估计延迟 | 149.16 ms |
| retired 微指令 | 221,811 |
| SHAKE 调用 / permutation | 104,937 / 105,641 |
| component 数 | 835,169 |
| Scratchpad 读 / 写 | 630,294 / 205,939 |

功能基线是 17,088-byte NIST ACVP tc137 签名逐字节一致。任何不能保持该结果的优化均不得进入下一阶段。

当前周期分布：

| 类别 | 周期 | 占比 |
|---|---:|---:|
| byte-serial emit | 6,689,794 | 46.671% |
| component request/wait/product/validate | 3,340,676 | 23.306% |
| Scratchpad source read | 1,260,588 | 8.794% |
| SHAKE block send + digest wait | 1,648,192 | 11.499% |
| layout lookup/product/validate/start | 411,872 | 2.873% |
| digest write回 | 205,939 | 1.437% |
| idle/其他 | 776,890 | 5.420% |

Microsequencer 的 FETCH+RUN 仅为 443,622 cycles（3.095%）；P1/U2 的理想 Keccak 活跃时间为 1,267,692 cycles（8.844%）。因此近期不优化 FETCH，也不通过加入更复杂 runtime 解决问题。

## 2. 不可退让的实现边界

- μHBS 不引用 HashFlow/SLH-Flow 的源码、RTL、构建产物或运行结果。
- 不引入 DMA、通用任务图 runtime、动态 work stealing 或软件逐 Hash 调度。
- 算法控制仍来自静态微码和 descriptor；优化只能改变执行数据路和静态 lowering。
- 每项优化必须能独立开关和消融，保留基线结果与源码哈希。
- 每次先通过局部单元测试，再跑完整 tc137 周期仿真；完整功能失败时不启动 Vivado。
- 周期结论只使用完整 RTL 实测值；估算值必须显式标为 projection。
- 论文比较同时报告 cycles、路由后频率、真实延迟、LUT/FF/BRAM/DSP 和 ATP，不用单一指标替代完整 PPA。

## 3. 执行波次与依赖

### Wave 0：冻结测量合同

状态：基线已具备，先补齐自动化门禁。

任务：

1. 固定 tc137 输入、签名摘要、周期分类器和 PPA 报告解析器。
2. 每次完整运行输出同一份 CSV/JSON：总周期、各状态周期、component 数、Scratchpad 流量、lane 利用率和响应停顿。
3. 在 manifest 中记录 RTL、微码、descriptor、testbench、Vivado report 和 routed DCP 哈希。
4. 将 14,333,951 cycles 设为回归上限；未声明的周期回退直接失败。

退出条件：同一 revision 连续两次完整仿真结果一致，报告可由脚本重建。

### Wave 1：rate-wide composer（最高优先级）

目标是把当前 1 byte/cycle 的 `S_EMIT_BYTE` 改为最多 64 bit/cycle，同时保留通用 `HASH` 语义。

实现内容：

1. 新增 64-bit masked append 数据路，支持任意 byte offset、1--8 byte 有效长度及 1088-bit SHAKE rate 边界拆分。
2. 静态 lowering 为每个 component 生成 gather plan；`PK.seed`、ADRS 和 node 等固定片段一次装入，链中间值优先在 lane 内反馈。
3. literal、zero、register、Scratchpad、XOR/select 均走同一 append 接口，不为 SLH-DSA 添加专用算法 FSM。
4. 对跨 component、跨 64-bit word、跨 rate block 和 backpressure 分别建立单元测试。

验收门槛：

- tc137 签名逐字节一致，Hash 调用和 permutation 数不变；
- emit 周期从 6,689,794 降至不高于 2,000,000；
- 完整 Sign 首个门槛不高于 9,500,000 cycles，目标接近 8,480,381-cycle projection；
- 初步综合 LUT 增幅不高于 15%，DSP 仍为 0；若超限，先压缩 barrel/mask 网络再继续。

### Wave 2：component 双缓冲与预取

状态：功能 Gate 已通过。active/prefetched 两项缓冲复用原有四个地址
乘法器；732,201 / 732,201 后续 component 命中，bubble=0，
component 控制由 3,340,676 降至 1,144,073 cycles（−65.753%），
完整周期相对 Wave 1 下降 24.961%。component-only 中间 post-route 为
34,367 LUT / 23,684 FF / 7 RAMB36 / 0 DSP、WNS −0.847 ns。

该阶段在当前 component emit/Keccak 时，完成下一个 component 的 REQ/WAIT/PRODUCT；不改变 descriptor 的 fail-closed 校验。

实现内容：

1. 建立两项静态 descriptor buffer：active 与 prefetched。
2. 将地址 product、bounds/版本检查提前，但只有通过校验后才能提交数据。
3. 对 layout 切换、最后一个 component、异常 descriptor 和取消路径加入定向测试。
4. profiler 新增 prefetch hit、bubble、validation stall 三类计数。

验收门槛：

- component 控制周期至少减少 50%，即不高于 1,670,338；
- 与 Wave 1 相比总周期继续下降至少 10%；
- 不因预取增加可观察的错误读写，fault/cancel 后下一 Job 可恢复；
- 若 prefetch hit 低于 80%，先修正调度，不进入双 lane。

### Wave 3：减少 Scratchpad 往返

状态：部分实施。连续源字的下一次 request 已与当前 64-bit 字发射重叠；
另增加一条 128-bit 写透反馈缓存，在 Hash digest 到达时原子保留前两个
64-bit 字，后续 `SCRATCH`/`SELECT_SCRATCH` component 在 validation 阶段命中后
直接发射。外部 writer 提交时整条失效，因此不会形成非受界通用 cache。

该缓存命中 187,612 次，完整周期由 6,283,432 降至 6,002,014
（−281,418，−4.479%）；Scratchpad 源读由 630,294 降至 442,682
（−29.766%），源读状态由 940,516 降至 659,098 cycles（−29.922%），
写入仍为 205,939。post-route 为 34,874 LUT / 23,903 FF / 7 RAMB36 /
0 DSP、WNS −1.489 ns；约 87.04 MHz / 68.96 ms。相对前一点，
LUT×cycles 改善 3.160%、路由后延迟改善 1.327%，timing-aware LUT×time
因布局拥塞微退 0.036%。该点不增加 BRAM 且真实延迟改善，因此保留；
但尚未达到本 Wave 的读/写退出条件。

消融中已拒绝两个时序更差的实现：两项全相联、逐地址失效版本为
6,095,470 cycles / 34,817 LUT / WNS −2.560 ns；两项整体失效版本为
6,095,472 cycles / 34,646 LUT / WNS −3.406 ns。两者的动态命中比较均进入
Scratchpad BRAM enable 路径。当前单项版只在 component validation 比较一次并锁存
结果，第二字不再动态查询，因此作为 Wave 3 的保留点。

目标是减少 630,294 次读和 205,939 次写引起的数据搬运，而不是扩展 Scratchpad 容量。

实现内容：

1. 添加 banked 64-bit rate buffer，并合并连续、对齐的读取。
2. WOTS/FORS/XMSS 链中间值在 hash lane 内反馈；仅跨阶段存活的数据写回 Scratchpad。
3. 对固定 `PK.seed`、ADRS 模板和 parent 输入提供受界缓存，禁止形成通用对象 cache/runtime。
4. 对 RAW/WAR、bank conflict、rate 边界和 lane backpressure 建立断言。

验收门槛：

- Scratchpad source-read 等待周期至少下降 50%；
- 动态读请求至少下降 35%，写请求至少下降 25%；
- BRAM 不超过 8 RAMB36，除非能给出明确的 latency--BRAM Pareto 点；
- 每增加 1 RAMB36 必须报告带来的 cycles 和 ATP 变化。

### Wave 4：统一双 Hash lane 服务

只有 Wave 1--3 已把供数瓶颈压下后才启用第二 lane。TreeHash parent 与 composer 请求进入同一个静态 P2/U2 队列，两条 lane 均可执行 WOTS、FORS、XMSS leaf/parent；不加入动态 runtime。

实现内容：

1. 统一请求/响应格式和固定仲裁，保留 Job 内确定性顺序。
2. 为两 lane 提供独立 rate/state buffer，共享只读 seed/ADRS 数据。
3. TreeHash parent、composer 和 chain feedback 使用标签化但有界的返回路径。
4. profiler 报告每 lane active/stall、队列空/满、TreeHash 等待和乱序禁止断言。

验收门槛：

- 完整 P2/U2 tc137 replay 通过；
- 在可并行的 Hash 区间获得至少 1.6x 吞吐提升；
- 两 lane 平均有效利用率不低于 60%，目标高于 70%；
- 若利用率低于 60%，不接受“增加第二 lane”作为最终优化，返回 Wave 2/3 修复供数。

633,852 cycles 仅是按 105,641 次 permutation、双 lane、每次 12 cycles 得到的理想 Hash 下界，不是完整 Sign 的目标周期。最终总周期还必须包含 composer、TreeHash、存储和输出控制。

当前实验进展：两条等价 U2 lane 已完成新的端到端 Sign 数据路径。tc137
完整 17,088-byte 签名逐字一致，周期 704,060，保持 105,641 次 Keccak
permutation；两 lane 平均有效利用率 90.94%，所以 Wave 4 的功能、周期和
利用率门槛已通过。独立的压缩 sequencer 仍保持 189 个 64-bit token 与
33 个模板，展开等价于 5,817 个水平调度字；当前端到端 materializer 先由
静态 phase/counter 驱动，尚未直接消费压缩 token 的 context index。详见
`docs/Horizontal_Microcode_Architecture.md`。

### Wave 5：面积合并

在周期路径稳定后压缩面积，避免过早共享导致吞吐优化无法定位。

任务：

1. 重新生成层级利用率，确认 composer、TreeHash adapter 和两 Hash lane 的真实独占/共享面积。
2. 共享 parent 输入包装、AGU、只读 seed/ADRS 存储和重复的 1600-bit 状态外围逻辑。
3. 压缩 composer 的非 Keccak mux、mask、bounds 和 descriptor decode；对大 mux 做结构化分级。
4. 保留 P1/U2 与 P2/U2 两个可综合配置，形成周期--面积 Pareto。

阶段目标：总 LUT 先降至 30k 以下，进而争取 27k 以下；24,184 LUT 文章点作为对照目标而非预设结论。每次面积减少都必须保持此前周期收益。

### Wave 6：时序闭合

旧架构基线 WNS 为 -0.406 ns。新水平双-lane Sign 顶层在
`xc7a200tffg1156-3` 上的 OOC post-route WNS 为 +0.035 ns，TNS 为 0，
且 tc137 周期未回退，因此该器件上的内部 100 MHz Gate 已通过。
当前不再通过盲目增加每 component 固定周期来换时序。

任务：

1. 以 post-route critical path 为准，依次处理高扇出、宽 mux、mask/gather 和跨层级控制。
2. 只在能被数据预取隐藏的位置加 pipeline；每一级都要同时报告新增 cycles。
3. 使用寄存器复制、局部译码、分级选择和 floorplan 约束，最后再考虑接口寄存。
4. 至少跑两个实现 seed，报告最佳值和离散程度，避免单 seed 结论。

退出条件：100 MHz post-route WNS >= 0，tc137 实测周期不回退，DSP 为 0。
当前状态：`xc7a200tffg1156-3` OOC 内部时序已满足；板卡顶层需要在
设置 `HD.CLK_SRC` 和实际 IO 约束后再做最终 signoff。另外仍需要第二个
implementation seed 来完成离散性报告。

### Wave 7：静态 ROM 顶层与接口收敛

性能开发期间保留当前 configurable top 作为验证壳；并行建立产品顶层。产品顶层用 ROM/`$readmemh` 固化微码、layout、component、data/tree/bitfield descriptor，删除所有 `*_cfg_*` 端口。

产品接口只保留：时钟/复位、粗粒度 Job start/status、密钥和消息输入流、签名输出流及必要 fault 状态。软件不输入微指令、descriptor 或逐步任务。

验收门槛：

- 产品 top 的端口表中不存在 `*_cfg_*`；
- 从干净目录可独立 elaboration、仿真、综合，不访问 HashFlow/SLH-Flow；
- 静态 ROM 镜像哈希写入 manifest，非法/缺失镜像 fail closed；
- configurable top 与产品 top 对同一 tc137 产生完全相同签名和周期分类；
- ROM 推断后的 BRAM、LUT 和时序单独报告，不沿用验证壳 PPA。

## 4. 并行执行策略

允许并行的是独立工作流，不允许多个任务同时改同一 composer 主状态机或复用同一构建目录。

| Track | 内容 | 可与谁并行 | 依赖 |
|---|---|---|---|
| A | Wave 1--3 composer/存储数据路 | B、C | A 内部严格顺序 |
| B | 静态 ROM 产品 wrapper 与接口测试 | A、C | 不改 active composer |
| C | profiler、manifest、回归和报告解析 | A、B、D | 只读 DUT 或独立 TB |
| D | 候选点 Vivado 综合/实现 | B、C | 对应候选 RTL 已冻结 |
| E | 双 lane 服务 | B、C | Wave 1--3 通过后开始 |

运行规则：

- 每个仿真/编译任务最多使用 8 核；Make 使用 `-j8`，Verilator 构建使用 8 个 build jobs。
- Vivado Tcl 显式设置 `set_param general.maxThreads 8`；工具或许可证实际少用线程时如实记录。
- 每个 Vivado 候选使用独立目录，例如 `build/vivado/<revision>-<variant>/`，禁止共享 `.Xil`、run 或 report 目录。
- 默认最多同时运行一个完整 Vivado implementation；仅当可用内存、许可证和磁盘空间满足时并行两个。每个任务仍最多 8 核。
- 同一阶段可并行跑单元仿真、完整 tc137 仿真和已冻结候选的综合，但只有功能回归通过的结果可进入论文表格。
- 长任务每 60 秒以内提供一次状态；保存命令、起止时间、峰值内存和退出码。

建议的构建约定：

```text
SIM_JOBS=8
VIVADO_THREADS=8
BUILD_TAG=<git-short-sha>-<variant>
```

后续需将这些变量接入 Makefile/Tcl，而不是由每次运行临时修改共享脚本。

## 5. 每项优化的统一验证流水

每个候选按以下顺序执行，前一 Gate 未通过不得消耗完整 P&R 时间：

1. lint/elaboration；
2. 受影响模块定向单元测试；
3. Python/reference regression；
4. 完整 tc137 签名与周期 profiler；
5. 独立性扫描；
6. out-of-context synthesis 快速面积/时序筛选；
7. 通过筛选后执行完整 post-route；
8. 更新 manifest、消融表和结论。

每次报告必须包含：

- revision、variant、微码/descriptor/ROM 哈希；
- exact signature pass/fail；
- cycles 与分状态差值；
- LUT、FF、RAMB36、DSP、WNS、关键周期；
- `LUT × cycles`、`LUT × routed latency` 两种 ATP；
- 相比 14,333,951-cycle 基线的提升与置信边界；
- 与文章比较时的参数、工作负载和技术节点可比性说明。

## 6. Go/No-Go 与回退

- Wave 1 若不能在 LUT 增幅 <=15% 下达到 9.5M cycles，停止堆叠功能，重做 gather/mask 结构。
- Wave 2 若 component 控制仍占总周期 15% 以上，先引入静态预解码微操作；不得用 runtime 队列掩盖问题。
- Wave 3 若 BRAM 增加但 latency/ATP 无改善，回退该缓存点。
- Wave 4 若双 lane 利用率低于 60%，回退为单 lane，并优化供数与 TreeHash 并行窗口。
- 任一优化若改变 tc137 输出、Hash/permutation 计数或 fault 语义，立即回退到上一个通过 manifest 的点。
- 时序优化若每新增一级 pipeline 带来的周期损失超过频率收益，则不接受该点。

## 7. 最终完成定义

以下项目全部满足，才可声称“μHBS 已完成可论文评估的独立 SLH-DSA RTL”：

1. 产品 top 独立运行完整 SLH-DSA-SHAKE-128f Sign，tc137 17,088-byte 签名一致。
2. 微码和 descriptor 由片上静态 ROM 提供，外部不存在逐任务/逐 Hash `cfg` 输入。
3. 100 MHz post-route WNS >= 0，报告完整 cycles、真实 latency、LUT/FF/BRAM/DSP。
4. P1/U2、P2/U2、固定控制器 B1 及关键优化消融使用同一数据路和同一工作负载。
5. 完整 profiler 能解释至少 99% 的周期，并给出 lane 利用率与 Scratchpad 流量。
6. 与参考文章只在参数和测量口径对齐后比较 ATP；未对齐项明确标注，不宣称虚假优势。
7. 清除 HashFlow/SLH-Flow 依赖后，干净环境仍能完成仿真和综合。

执行顺序固定为：**rate-wide composer → component 预取 → Scratchpad/反馈 → 双 lane → 面积合并 → 时序闭合**。静态 ROM 产品 wrapper、profiler 和报告工具作为独立 Track 并行推进。
