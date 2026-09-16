# μHBS Architecture v0.1

## 外部边界

μHBS 是单 Job、自主运行的微码引擎，不是 task runtime。外部只有初始化、整幅镜像装载、一条 Job 提交、数据流和完成/错误状态。

本项目 RTL 只保留μHBS原生 Microsequencer、composer、Hash lane、
Scratchpad 和 TreeHash 路径；外部项目的固定算法 FSM 不进入本项目 RTL。

```text
Program/Layout RAM --(idle-only load)--> Microsequencer
                                         | PC + loop/call stack
One Job Descriptor --> Job Latch --------+--> AGU --> Composer --> Hash lanes
                                                        |             |
Output Stream <--- Emit/TreeHash/Scratchpad <------------+-------------+
```

`BUSY` 期间不接受 task、Hash descriptor 或主机生成的 ADRS。lane 分配由静态指令的 `lane_mask` 完成；冲突只导致确定性 stall。

## 参数化边界

- `P ∈ {1,2}`：Hash lane 数。
- `U ∈ {1,2}`：每周期 Keccak round 数，论文主点为 P2/U2。
- Loop Stack 6 层，Call Stack 4 层。
- 指令固定 64 bit，程序镜像默认 512 words（4 KiB）。
- Scratchpad 和 TreeHash 深度由综合参数固定，程序 manifest 声明使用上限。

JSON 源微码由离线 assembler/verifier 导出为 64-bit `$readmemh`
镜像；当前 LMS/XMSS/SLH-DSA 共 7 幅镜像均在 512-word 上限内。
Program store 既支持 IDLE 期写入，也支持综合/仿真时的固定
`PROGRAM_INIT_FILE`。已用实际 LMOTS 导出镜像完成控制回放：
1 条 Job 展开 1,073 个 Hash 请求、1 个 `EMIT` 请求和
2,215 条动态指令。该测试的 Hash/data service 仅作内部应答，
因此它证明“权威镜像可被 RTL 控制器执行”，不证明完整 LMOTS
密码数据路已完成。

Layout 表已有独立的 128-bit descriptor store，支持 IDLE-only
配置、BUSY 镜像锁定、未初始化/越界/版本错误 fail-closed；
新增 `micro_hbs_descriptor_shake_composer` 已将 descriptor lookup、
多 rate-block SHAKE256 和 1--32-byte 写回连成同一 `HASH_LAYOUT` 路径。
输入模式 2 由静态 192-bit component words 组合 literal、zero、32-bit
register、最多两个寄存器的仿射 Scratchpad 段与两段 XOR，并能在组件
中间跨 rate block 续传。离线 `model/layout_lowering.py` 已把 XMSS Sign
JSON layout 0--7/9--10 降低为 10 个 layout/91 个组件；PRF randomizer
和 H_msg 已在真实 RTL 从同一 Job 连续执行。layout 0--7 还已直接
执行 1,024 个 WOTS+/L-tree leaf，接入 `TREEHASH_MIN`、root 写回和
EMIT，得到 oracle-equal h=10 root/auth。该 Keygen 顶层已从一条 Job
锁存 `SK.seed`/`PK.seed`，并在 sequencer 启动前由 RTL 自主写入 8 个
64-bit Scratchpad word；消息由无 DMA 的 payload-only stream 搬入；其余 expression/context 与
TreeHash layout-8 pipeline temp 尚未全部降低。
数据路径也有独立 128-bit descriptor store，静态绑定
LOAD/STORE/XOR/EMIT 的物理 word 地址、长度和末 word byte mask。

离线 `model/data_lowering.py` 已冻结逻辑槽到物理字的映射：
`physical_word = logical_slot * ceil(logical_slot_bytes/8)`。它能确定性
生成 Scratchpad 初始化镜像、v1 descriptor，以及为现有 XMSS
`R5+R7 -> R6+R3` move 生成 v2 多寄存器 binding side table，并在生成前
证明无重叠和边界。当前 RTL data engine 已执行 v1/v2；独立 v2
切片在单 Job 中快照 R0--R7，通过 binding-table 计算两寄存器 affine
地址并完成 STORE→EMIT。同一 data engine 现已与通用 XMSS
WOTS/TreeHash 顶层合并；EMIT 通过可配置 descriptor base 与 STORE
命名空间隔离。

AGU 已实现静态 descriptor 所需的
`base + base_reg + index * stride` 地址形式，并对完整
`[address, address + span)` 访问区间做 Scratchpad 边界检查。
可变步长使用 16-cycle shift/add，不使用算法 ID，也不引入 DSP
乘法器或 runtime 调度。AGU 已与 data descriptor、LOAD/STORE/XOR
和 EMIT 组成可执行数据切片；固定优先级 `data > EMIT > TreeHash`
仲裁器每次只保留一个 outstanding transaction，不存在 task queue。

Microsequencer 已能对 LOAD 响应执行可选的 R0--R7
写回，并将 `TREE_PUSH` 指令发送到独立内部通道。
Scratchpad 数据面已分别验证有界的 word-serial
STORE/XOR 和带末字节 `keep` 的 EMIT 流，两者都在任何写/输出
前完成整段范围检查。这些是微码内部执行器，不是外部
task ingress。

`micro_hbs_tree_push_slice` 已把一条 Job、循环微码、
4 个 Scratchpad 叶节点、真实 `TREEHASH_MIN` 和 SHAKE256 parent
串起，自主产生 h=2 root 和两层认证节点。该切片的
TreeHash 高度和节点宽度仍是综合参数，parent layout 仅为
`SHAKE(left || right)`；它证明控制连通，不替代 LMS/XMSS/SLH-DSA
标准 parent composer 的完整集成。

`micro_hbs_xmss_tree_push_slice` 进一步用 RFC 8391
XMSS-SHAKE256/n=32 randomized H 取代上述测试 parent；RTL 从
TreeHash `(parent_height,start_leaf)` 自主导出 ADRS treeHeight/treeIndex，
4 leaves/3 parents 的 root 和 auth path 与独立 Python oracle 一致。
`micro_hbs_xmss_wots_tree_slice` 已补上此前预装叶的边界：每条
layout `0x0200` 请求在 RTL 内自主执行完整 base-16 WOTS+ 公钥生成和
L-tree 压缩（每叶 67 PRF_keygen、1,005 randomized-F step、66 randomized-H
parent，共 3,346 SHAKE），结果写入同一个 4-word 叶缓冲，随后由
`TREE_PUSH` 立即消费。h=1 两叶测试由一条 Job、两个 `HASH_LAYOUT` 和
两个 `TREE_PUSH` 得到 oracle-equal root/auth，BUSY 期间无 task/Hash
输入。同一路径现已以 h=10 执行 1,024 leaf/1,023 parent，
用 57,204,676 cycles 得到 oracle-equal root 和全部 10 层 auth path。
它仍是串行 U2，layout `0x0200` 仍为融合 WOTS+ leaf capability，
还不是通用 descriptor composer 或 P2/OTS-wide 性能点。

与此对照，`micro_hbs_xmss_generic_leaf_slice` 用 JSON-lowered layout
0--7 和 descriptor-v2 STORE 替换融合 leaf，执行未截断的 93-word
Keygen 镜像。一条 Job 完成 3,426,304 次 `HASH_LAYOUT`、1,024
leaf、1,023 parent、root 写回及 4-word EMIT，root 与 10 层 auth
均与 RFC 8391 oracle 一致，时序流水版实测 675,417,082 cycles（含 8-word Job seed
自主装载的 17-cycle admission 开销）。该结果
证明通用控制/数据路可完成整树，也显示字节串行 composer
与 37,044,232 次 sequencer 执行期 Scratchpad 交易带来 11.81× 周期开销。
再加 Job admission 的 8 次 seed 写入，物理 Scratchpad 交易总数为
37,044,240。

`micro_hbs_data_tree_slice` 则在同一微程序内先执行 descriptor-driven
STORE，再执行 4 次 TREE_PUSH 和 EMIT，三类 client 通过同一
Scratchpad 仲裁器分别产生 32/16/1 次交易。该切片的叶节点
仍由 IDLE 期预装，所以它是数据路径与标准 parent 的联合证据，
不是完整 XMSS Keygen/Sign。

FIPS 205 SHAKE profile 的 parent 与 XMSS randomized H 不同：
`micro_hbs_slh_dsa_tree_parent` 对 n=16 执行一次
`SHAKE256(PK.seed || ADRS || left || right, 16)`，完整输入为 80 bytes，
不使用 XMSS prefix/key/bitmask。左右顺序、完整 ADRS 敏感性、响应背压、
错误清零以及一次 parent 恰好一次 Keccak permutation 均已独立验证。

LMS 的 parent 路径使用受界 SHA-256 lane。当前 lane 支持
0--119 byte、最多两个 512-bit block；RFC 8554 parent 严格组合
`I[16] || u32(r) || 0x8383 || left[32] || right[32]` 共 86 byte。独立
向量已验证大端字段、左右顺序、padding、背压和越界拒绝，
但该 parent 尚未接入 LMS 的完整 TreeHash/Job replay。

TreeHash 的 transaction cleanup 已显式化。部分树发生 Scratchpad 或
parent fault，或收到 cancel 时，控制器会取消工作状态并排空最多一个
已接受的旧响应，只有完成隔离后才重新 ready；随后无需全局 reset 即可
启动新树并得到正确 root/auth。该性质不等同于掉电安全或物理清零。

版本化 tree descriptor 编码 tree height、node bytes、parent layout 和
storage mode。独立集成切片在同一 elaboration 通过 descriptor ID 选择
h=2/h=3 MIN，仅用一次 coarse start 产生精确 root/auth。当前该切片
只支持 32-byte MIN；SUBTREE/FULL 在 cache 未连接时返回明确错误，
不会退化为静默 MIN 或要求软件逐层喂入。

## 允许的控制状态

PC、公开参数寄存器、loop/call stack、lane busy/done、bank hazard、TreeHash stack、错误寄存器。禁止 descriptor graph、object-valid scoreboard、动态 ready queue、work stealing 和多 Job 依赖状态。

## 数据路径策略

通用 layout composer 处理域分离、ADRS、变长消息和节点拼接；capability 为 `OTS_RATE_WIDE` 的 layout 使用 1088-bit 单周期快路。选择条件来自已验证 layout，不来自硬编码算法 ID。

TreeHash 支持 FULL_CACHE、SUBTREE_CACHE、TREEHASH_MIN。三种模式必须复用相同 root/auth-path 语义，分别记录峰值 bytes、RAM 访问和 cycles。

当前 h=10 cache-store RTL 的 FULL_CACHE 为 2,047 nodes / 14 RAMB36；
upper-only SUBTREE_CACHE(h≥4) 为 127 nodes / 4 RAMB36。被动旁路缓存不改变
TreeHash 的 1,023 次 parent Hash 或完成时序；缓存辅助 Sign 尚未接入，
因此当前只形成存储 capability，不形成 BRAM–latency Pareto 结论。
工作量模型显示该 upper-only 点的低四级 auth miss 仍需重建 15 个 WOTS
叶。新增 warm-active 结构将当前 16-leaf 子树 h0--h3 的
30 nodes 放入 LUTRAM，h4 根仍只在上层区保存一次；总容量为
157 nodes / 5,024 B，post-route 仍为 4 RAMB36，另用 1,244 LUT/
691 FF，100 MHz WNS +0.556 ns。外部只给一次 target leaf，窗口
base 在 RTL 内部对齐推导。跨窗口会清除低层 valid 但保留上层区。
认证路径 provider 已能从一条 `start + target_leaf` 自主生成全部
`(height, sibling_start_leaf)` 查询：FULL 命中直接输出，SUBTREE miss 则由
内部 recompute 请求补齐。它不暴露逐层地址输入；当前 h=3 集成测试得到
FULL 3/0 hit/miss、SUBTREE 1/2 hit/miss，二者 auth path 均与 SHAKE oracle
一致。provider 与 warm cache 的直接组合回归已在 target=5 和 21
上仅用一次 start 完成各 10 层查询，均为 10/10 hit、0 recompute，
并通过 2-cycle auth 输出背压。该 provider/cache 尚未与真实
WOTS/TreeHash 重算数据路组成完整
Sign replay。

layout 数据路采用拆分实现：32-bit postfix engine 仅处理 ADRS/index，
FORS/base-w digit 由 MSB-first 静态 wiring 解包，宽节点顺序由独立
ordered-pair mux 处理。288-bit 通用表达式栈已经 PPA 实测淘汰。

P=2 使用综合期固定的 even/odd lane 映射和 `11/01` 尾掩码，不使用动态
ready queue。宽整批输入锁存也已由 PPA 实测淘汰；最终消息由硬件内部
microsequencer 与 banked composer 以 pair window 生成，外部仍只有一条
Job，不暴露逐 Hash/task 接口。
当前窗口化垂直切片已将 512-word Microsequencer、两个 64-bit
message bank 和两条 U2 lane 连通，post-route 为 20,204 LUT/
11,294 FF/3 RAMB36/WNS +0.368 ns。它的 IDLE 预载内容仍是完整
SHAKE 消息，每 pair 需 18 个 bank read，因此只是数据路分解证据；
最终路径必须从 raw Job 数据和内部 node 组合，并为 OTS 保留
单周期 rate-wide 能力。

新的 `micro_hbs_randomized_f_p2_slice` 已向这一边界前进一步：
Job 只锁存 public seed、ADRS template、两个 32-byte node 和一个
公开 chain bound，两条 lane 在内部生成 key/mask/core 的 SHAKE
预映像并在同一 lane 内反馈。微程序静态发出 `11/01`，
`R[index]` 在硬件内绑定 ADRS word 6，lane 1 的 ADRS word 5 由
lane 0 的 chain address 加一派生；BUSY 期间没有消息、task
或 Hash 入口。该切片已以 14,811 LUT、10,850 FF、1 RAMB36、
WNS +0.788 ns 通过 100 MHz post-route。它目前只是 RFC 8391
WOTS+ randomized-F 热点，两 lane 仅覆盖由一个 template 派生的
相邻 chain pair，不能代替完整 OTS/Sign 回放或 OTS rate-wide 证据。

当前首个 Scratchpad-backed layout `0x0100` 是通用 randomized-F
能力切片：固定槽 0--3 保存 public seed，4--7 保存 32-byte address
模板，`HASH_LAYOUT.rd` 选择 node 的起始槽，`HASH_LAYOUT.rs` 的寄存器值
绑定到 address word 6。适配器自行完成 12 个 64-bit 读取、3 次 SHAKE、
4 个 64-bit 写回；主机在 `BUSY` 时不能访问 Scratchpad。该布局证明了
sequencer、动态循环、Scratchpad、composer 和真实 Keccak 的连通性，但其
串行单端口搬运不是最终 banked/OTS-wide 数据路。

## 已实现的状态索引边界

`micro_hbs_state_manager` 将原子持久化作为外部服务边界：它输出 `persist_req_valid/persist_next_index`，仅在 `persist_ack` 后使 `release_valid` 有效。cancel 或 soft-reset 不会撤销持久化请求，而是在确认后将已预留索引计为 burned。掉电安全仍依赖未集成的原子 NVM 实现，不属于当前已通过边界。

## 工程解耦验证

`make check-standalone` 将 μHBS 单独复制到不存在 HashFlow 的临时工作树并执行 `ci-core`。`make check-parallel-isolation` 则把两个项目各自复制到不同临时目录后并发运行；当前结果为 μHBS `ci-core` 通过、HashFlow 81 项 Python 测试通过，两者无共享输出目录。该可选并行检查不是 μHBS `make ci` 的依赖。
