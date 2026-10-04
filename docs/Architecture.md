# mHBS 当前生产架构

生产源码以 `manifests/v42_sources.txt` 为准；`manifests/unified_sources.txt` 是内容相同的兼容清单。当前支持 SLH-DSA SHAKE 128f、192f、256f、128s、192s、256s 的 Keygen/Sign，以及外部节点输入的 Verify，唯一顶层为 `mhbs_top`。验证入口见 [Verification.md](Verification.md)，端口协议见 [Job_Interface.md](Job_Interface.md)。

## 执行路径

```text
mhbs_top：三组镜像 ROM、启动控制、固定 Job 参数、外部消息
  ├─ mhbs_signature_store：Sign 完整签名缓存，完成后同步节点读回（可编译关闭）
  └─ mhbs_hbs：宏操作调度、树归约、消息缓冲、结果输出
      ├─ mhbs_program_sequencer：RUN / LOOP → 单个待完成宏指令
      ├─ mhbs_value_store：68 项共享存储，分时保存 FORS 根与 WOTS 链端点
      └─ 两个 mhbs_recipe_lane：Hash 输入构造与局部链反馈
          └─ mhbs_compact_shake_context_lane：统一 SHAKE 状态、吸收与流水控制
              └─ P×U 个 mhbs_keccak：每级 U 轮，默认 P1U2
```

五类宏操作为 HASH、CHAIN、TREE、TRANSFORM、EMIT。Sequencer 等待当前宏操作完成后才提交下一条；双 lane 并行位于宏操作内部。逻辑 lane 0 支持完整 recipe 集，逻辑 lane 1 主要执行链计算；`SWAP_PHYSICAL_LANES` 可交换物理位置，逻辑能力不变。

核使用 256 位节点存储，由 descriptor 中的 profile 编码选择有效的 16/24/32 字节。FORS 根与 WOTS 链端点共享深度为 68 的存储；树栈和认证路径各为 16 个节点。消息缓冲上限为 87 字节。

## 镜像与启动

物理格式为 `slh64_v4.2`、布局修订 3，沿用 ABI 4 宏语义：

| 镜像 | 逻辑容量 | 用途 |
|---|---:|---|
| program | 16 × 64 bit | RUN / LOOP 等控制指令 |
| template | 16 × 64 bit | 宏指令模板 |
| descriptor | 32 × 64 bit，双读 | 参数集、入口、输出长度及 recipe |

三组独立数组通过 `$readmemh` 初始化，共 512 字节逻辑容量。每个参数集的一组镜像同时包含 Keygen 和 Sign 入口；Job 与消息不放在程序镜像中。软件 `model/slh64_external.py` 负责镜像边界和字段检查，程序地址及 PC 为 4 位；保留头部原有 5 位入口字段，软件拒绝入口大于 15 或超出 16 条的程序。硬件按可信、不可变镜像执行，不做完整镜像扫描。

顶层同步复位后依次读取 header 与 profile，释放执行核，再提交一次 Job。Boot 计数为两拍；它不等于从复位释放到 Job 开始的全部控制开销。操作完成或失败后顶层停机，下次操作需要再次复位。

## 共同核综合

`scripts/v42_common_partition.py` 从顶层标记区域提取启动控制和执行核，生成构建用的 `mhbs_common`。Job、消息和 ROM 数据成为该区域输入，内部连接保持不变。共同区域综合一次，十二个 Keygen/Sign 参数外壳分别链接同一网表；验收检查内部结构指纹、ROM 初始化映射以及提取前后的完整 RTL 输出和周期一致性。

支持共同核 post-synth 流程，以及十二个 Keygen/Sign 参数外壳分别进行的布局布线。`route-common` 完成布线和验收，`freeze-common` 封存已验收的结果。频率口径为 OOC 核内寄存器间路径，核内同步控制参与检查，外部输入/输出路径排除。0 ns 外部输入假设下的端口 hold 违例单独保留，接口尚未时序签核。资源或频率结论绑定实际测量的源码快照，最新结果见 [最新 K/U 实验报告](v4.2/KU_Sign_ATP_150_110_67_48.md)。

## L2U2P1 数据通路裁剪

默认生产配置为 `LANES=2, UNROLL=2, PIPELINE=1`，任务数组、掩码及输出控制按双通道构建；保留物理 lane 交换验证。配方形状和长度解码受各 lane 的 `RECIPE_MASK` 静态约束，链专用 lane 不构建流式输入路径。SLH 普通链复用 sponge 保留的摘要，普通链和 compact chain 共用 sponge capture 寄存器；请求字段仍保持到响应握手，不增加流水级。旧 masked 配方仅在模块参数允许它时保留跨中间哈希的值寄存器，不进入生产网表。

统计开关沿 top/common/core/lane 传递，生产综合关闭，仿真保留。综合阶段检查实际网表，禁止统计寄存器和被替代的重复值/capture 寄存器残留。


## Verify 复用路径

Verify 使用同一 sign 镜像：PRF_msg 宏读取外部 R；TREE 宏读取 FORS/WOTS 签名节点并恢复叶节点，随后输入认证路径，复用父节点 Hash；其余 H_msg、FORS 根压缩、WOTS checksum、层切换和结果路由沿用原流程。顶层树的 EXTERNAL_ROOT 快捷路径在 Verify 下关闭，最终必须计算并比较真实根。没有第二套 Keccak、配方 lane 或整签名缓存。

WOTS 按两个链一组输入，复用普通单次 Hash 请求执行 digit 到 14 的后缀链；digit=15 直接存端点。这样保持现有 compact chain 语义和 Hash lane 源码不变，Verify 每步有控制调度开销。所有节点长度与地址来自受信任镜像；签名字节流拆分位于外部。

当前输出采用 256 位节点拍：`out_valid` 有效时接收 `out_data` 的低 `out_bytes` 个字节（16/24/32），`done` 标记整项结束；无输出反压、out_keep 或 out_last。测试端仍逐字节检查完整 SK/PK/签名和精确总长度。原 64 位输出波形及周期属于历史版本。

Sign 顶层默认同时将输出写入 1558 × 256 bit 签名缓存，完整保存后可随机或顺序读回；
`SIGNATURE_STORE_ENABLE=0` 可关闭。缓存位于共同核提取区域之外，Keygen/Verify 不实例化。
缓存单独综合实测为 484 LUT（含 172 LUTRAM）、293 FF、11 RAMB36E1 + 1 RAMB18E1；当前尚未重新测量带缓存
整机的布线面积和频率，历史共同核资源与时序结论不等同于新增缓存后的完整顶层。
接口见 [Job_Interface.md](Job_Interface.md)，验证与资源证据见
[完整签名缓存报告](report/Signature_Storage.md)。

共享列表存储按阶段复用：FORS 根压缩完成后才允许 WOTS 端点覆盖。FORS 叶节点直接进入树计算，不写入共享列表；根按地址奇偶进入对应写端口，保留双链同时写入能力。独立 mhbs_root_store 及其闲置测试已删除。

六种 SHAKE 参数共用同一 L2U2P1 核。descriptor[1] 编码 0/1/2 为 128f/192f/256f，4/5/6 为 128s/192s/256s，3/7 非法，软件镜像检查拒绝。FORS 目标、叶游标和节点索引为 14 位；XMSS 叶地址保持 10 位（s 最大需要 9 位）。树栈/认证路径各 16 项、共享列表 68 项、摘要暂存 49 字节及 ROM 容量均不扩大。s 摘要使用 7 字节树索引，128s/192s 的叶索引按大端两字节解码；256s 使用一字节。

## K/P/U 流水实验

参数 `LANES/PIPELINE/UNROLL` 分别对应 K/P/U，新配置统一写作 KxPxUx，默认 K2P1U2；历史 L 与 K 含义相同。每 lane 的 P 个流水级各包含 U 轮，普通 sponge 与交错链共用 Keccak；每个上下文的链反馈遵守数据依赖。WOTS 和 FORS 每批最多 K×P 个任务，FORS 按序送入树栈。外部接口不变。

`make lup-unit-test` 验证轮级等价与链交错；`make lup-atp LUP_TAG=<新标签>` 执行 128f sign 的 L2U1P1～P4 仿真、共同核综合和 ATP 报告。频率统一假定 150 MHz，不布线。P>1 的其他参数集/操作未作本轮端到端验收。历史 L/U/P 标签及实验路径保持不变，新报告统一使用 KxPxUx。

K1P1U1～K1P4U1 的 ATP 优化见 [报告](v4.2/KPU_ATP_Optimization.md)。链模块保留单份结果/capture，并向控制器提供按 tag 读口；K1、U1、P>1 签名的 WOTS 完成后按链索引直接写端点，capture 按序输出。普通 sponge 在 K1、U1、P>1 时复用流水末级状态，仅在初始化、吸收和链反馈时通过内部写口修改它。连续补任务候选因 ATP 增加撤回，当前仍保留批次边界。

统一 Keccak 实现：`mhbs_compact_shake_context_lane` 内直接展开 P 个级、每级 U 个 `mhbs_keccak`，级间状态、轮号、tag、有效位和循环反馈均在此模块管理；不再实例化独立 `mhbs_keccak_pipeline`。P1 使用唯一状态寄存器及组合轮末完成判断，保持原周期；P>1 保留普通 sponge 与交错链共享流水和末级状态复用。轮函数仅保留 `mhbs_keccak` 一份实现。第二轮测量见 [统一结构与 ATP 报告](v4.2/KPU_ATP_Unified_Optimization.md)。

第二轮最终保留 capture 有效位及 WOTS 批次控制优化：capture 仅在实际捕获时写入，未有效时读口返回零；K1U1、P>1 sign 路径跳过无效尾槽，capture 可连续逐节点输出，整批消费后直接准备下一批。仍无跨批连续补任务。U1 遍次计数/固定级轮常量译码候选因最低 ATP 增加撤回。
