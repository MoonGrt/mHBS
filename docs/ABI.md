# 默认镜像 ABI：`hbs_micro64` 3

默认顶层 `top` 执行有类型 HBS 微指令和阻塞单链宏。ABI 3 与 ABI 2、ABI 1 的标量指令、v4.2 的宏镜像均不兼容。`model/microcode.py` 定义编码与操作数权限，编译器为 `model/mHBS.py`，逐指令软件模型为 `model/executor.py`。完整语义见 [Micro_ISA.md](Micro_ISA.md)。

## 镜像布局

| 文件 | 容量 | 读取方式 |
|---|---|---|
| `program.mem` | 512×64 位，4096 字节 | 一拍同步读，9 位地址 |
| `descriptor.mem` | 32×64 位，256 字节 | 异步单读，5 位地址 |

每行一个 16 位十六进制字。实际指令区之后填零；零指令非法，不能进入填充区。没有 template 文件，Job 和消息不放入程序镜像。

| Descriptor | 内容 |
|---|---|
| 0 | magic `0x48425350` 位于 `[63:32]`；ABI=3 位于 `[31:27]`；Keygen/Sign/Verify 入口分别为 `[26:18]`/`[17:9]`/`[8:0]` |
| 1 | SLH profile 编码：0/1/2/4/5/6 |
| 2…11 | 单次 Hash 配方：shape、domain、arity、输出字节数、最大 rate 块数 |
| 12 | 实际指令数，1…512 |
| 13 | Keygen 输出字节数 `[31:0]`，Sign 输出字节数 `[63:32]` |
| 14 | 由低到高八个字节：n、hp、d、k、a、m、h、WOTS 链数 |
| 15…31 | 零填充 |

## 执行模型

64 位指令容器仍为 `opcode[63:56] | d[55:48] | a[47:40] | b[39:32] | imm[31:0]`。这些位是各 opcode 私有的枚举、节点对象、受限索引、立即数或直接分支目标；它们不编码通用寄存器。

上下文由独立的 HBS 字段组成。TREE 保留完整 64 位，只允许摘要装载、固定层推进和 ADRS 读取。计数器、链步、层级与归约索引各有独立宽度和更新权限；没有任意字段之间的搬运、整数 ALU 或通用移位器。树循环、链号推进和是否继续合并由 image 的直接分支决定；单条 WOTS 链内循环可由 CHAIN 宏执行。

节点为 256 位，低 n 字节有效。LIST/STACK/AUTH 深度为 68/16/16，只能通过相应空间允许的具名索引或合法立即索引访问。Job 常量只读，节点不参与整数运算。

生产配置固定 K1U1（一个物理 Hash lane、每周期一轮 Keccak）。L0/L1 保留为逻辑上下文及结果槽；HASH 有效 mask 必须为 1 或 2，mask 0/3 原子故障。每条 HASH 执行一次密码学 Hash，并须以 WAIT 提交；硬件不自动拆分双槽请求。等待期间仅允许权限表列出的上下文更新、地址更新与直接分支；节点访问、摘要变换、I/O 和结束须位于 WAIT 后。HASH 锁存 recipe、mask 和地址，数据源保持稳定；未参与 lane 的结果保持不变。多块 SHAKE 吸收仍属于一次 Hash。

PARSE/TARGET 使用独立的 49 字节 H_msg 暂存；WOTS digits/checksum 是有界数据变换。上述变换与地址更新均不能发射 Hash。

## 可信边界与兼容性

assembler、VM 与 RTL 使用同一操作数权限定义。生成器检查容量、保留字段、入口、跳转、对象与索引权限、profile、配方及 HASH/WAIT 控制流。RTL 在指令生效前检查编码与动态范围；故障指令不得提交上下文或节点修改。计数器允许规定的终止值，但禁止继续递增后静默回卷。RTL 不扫描整幅镜像。

Job 的 secret/prf/public/random 种子端口须在整项操作期间保持不变；公共顶层使用参数满足此约定。HASH 锁存 recipe、mask 和地址，RTL 冻结节点与消息输入；它不额外复制这些 Job 种子。

LIST/STACK/AUTH 不由复位清零。合法 image 必须先写后读，不能依赖 VM 初始化存储为零的便利行为。完整 descriptor 配方保留位、profile 一致性、整幅程序控制流和输出次序属于离线验证边界；RTL 不重复整镜像扫描。VM 在 END 额外检查输出字节数和 Verify 输入是否恰好耗尽；RTL 的 END 不执行整项输出/输入长度核算，集成与顶层测试检查这些算法约定。

外部消息、Verify 节点、输出与签名缓存协议保持兼容，见 [Job_Interface.md](Job_Interface.md)。镜像参数仍为 `PROGRAM_INIT_FILE` 和 `DESCRIPTOR_INIT_FILE`。新 RTL 拒绝 ABI 1/2，不提供历史镜像兼容执行模式。

本分支仅提供ABI3工具和执行器，不携带源仓库的ABI1/2或v4.2 legacy实现。源节点说明中的历史工具、旧归档和旧提交仅作为源项目历史语境；本次移植的原始材料与校验保存在 `docs/manifests/experiments/image_chain_import_20261021/`。

## ABI 3 单链宏

新增 opcode36 CHAIN，`d` 为 FULL(0)/CAP_FULL(1)/CAP_PREFIX(2)/SUFFIX(3)，`a` 为现有 lane 选择器，`b` 为 CURSOR(0)/LEAF(1)，`imm=0`。有效 mask 必须单选，链号为 CHAIN+slot；输入范围先检查再截断。配方 7/8 固定为 WOTS PRF/F，宏启动前同时校验并锁存。descriptor 布局与容量不变，没有新的 template 或宏描述符表。

宏负责一次 PRF 加至多 15 次 F，或从输入节点执行后缀链；CAP 模式截取 digit 节点。宏阻塞 image，内部每个 lane 请求仍只执行一次 Hash。它不递增链号、不访问 LIST/STACK/AUTH、不输出节点，也不执行树归约。宏自行等待和提交，后面不加 WAIT。普通 HASH/WAIT 的一请求一 Hash 及有限重叠语义保持。

成功只提交选中 L、必要的对应 CAP 和 STEP 终值；架构 ADRS、链号及树上下文保持。截取先进入私有 RAM shadow，全部计算成功后才提交。非法参数/配方在首个 Hash 前拒绝，途中错误不修改架构节点或 STEP；已执行物理 Hash/置换允许计数。复位取消宏及 shadow 有效位。SUFFIX digit15 不启动 Hash，CAP_PREFIX digit0 仍执行一次 PRF。完整规则见[指令表](Micro_ISA.md)。

ABI 2 的 `a9b4e0e2` 与第三轮独立归档作为此次迁移基线；旧源码在其 source_snapshot 中可复核，不覆盖 ABI 1 历史工具与任何封存证据。
