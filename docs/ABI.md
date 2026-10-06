# mHBS 当前 ABI：`slh64_v4.2`（布局修订 3）

本文描述**当前生产 RTL**。工程版本为 v4.2，五类宏操作延续 **ABI 4 逻辑语义**，三份物理镜像采用 `slh64_v4.2` 的**布局修订 3**。物理镜像没有运行时 ABI 版本字；格式标识和修订号由构建元数据及离线工具管理。历史布局不能直接交给当前 RTL 使用。本文位号从最低位 0 开始，`[高:低]` 包含两端。

编码与校验的依据是 [`model/slh64_external.py`](../model/slh64_external.py) 和 [`model/slh64.py`](../model/slh64.py)，宏执行语义见 [`model/unified_hbs.py`](../model/unified_hbs.py)。RTL 对应 [`mhbs_top.sv`](../rtl/top/mhbs_top.sv)、[`mhbs_program_sequencer.sv`](../rtl/sequencer/mhbs_program_sequencer.sv) 和 [`mhbs_hbs.sv`](../rtl/top/mhbs_hbs.sv)。

## 架构与运行接口

```text
program（顺序、RUN/LOOP、坐标） ─┐
template（宏、引用、标志）       ├─→ 单条 48 位宏命令 → mhbs_hbs → Hash lane／节点存储／结果流
descriptor（配方、参数、路由）  ─┘                         ↑
Job 参数、message_length、消息流 ──────────────────────────┘
```

- 生产核支持 **SLH-DSA-128f、192f、256f、128s、192s、256s**。每个参数点有一组三份镜像，同一执行核支持六者。新增实验 SHAKE256 XMSS/LMS omega2/4，支持外部索引 q；不实现树缓存或索引 guard。
- 五类宏操作为 `HASH=1`、`CHAIN=2`、`TREE=3`、`TRANSFORM=4`、`EMIT=5`。镜像决定执行顺序、循环、配方和结果路由。FSM 执行宏内部链步、树归约、存储访问与 Hash lane 调度。任一时刻只发射一条宏命令，宏内部可在唯一 Hash lane 的 P 个上下文间交错执行。
- `mhbs_top` 内有三个独立、由 `$readmemh` 初始化的分布式 ROM 数组；生产 RTL 没有显式 ROM 模块或 `mhbs_processor`。固定一个 Hash lane，默认 P1U2；`PIPELINE`、`UNROLL` 是硬件参数，**不是镜像字段**。
- Job 和消息不占 program 地址。五个 256 位 Job 参数从顶层进入，按 profile 只取低 `n` 字节。Sign 的 `PUBLIC_ROOT` 由调用方配置，例如使用独立 Keygen 输出。
- 镜像的完整格式和引用检查在离线工具中完成。RTL **不扫描或全面校验镜像**；非法镜像不属于硬件运行契约。顶层仍检查消息长度，执行器仍处理运行故障。

完整端口协议见 [Job_Interface.md](Job_Interface.md)。`OPERATION=0/1/2` 选择 Keygen/Sign/Verify；消息为 64 位 valid/ready 输入，输出为 256 位节点拍及 `out_bytes`，Verify 使用 256 位节点 valid/ready 输入。每次同步复位后执行一次操作。

## 三份独立镜像

| 文件 | 固定容量 | 内容 |
|---|---:|---|
| `program.mem` | 16 × 64 位 | SINGLE、RUN、LOOP、HALT 指令 |
| `template.mem` | 16 × 64 位 | 一条宏命令的操作、引用和标志 |
| `descriptor.mem` | 32 × 64 位、双读 | 参数、Hash 配方、链/树和结果路由 |

每行一个由 **16 个十六进制字符**表示的 64 位字。三者始终独立。共同执行逻辑按通用 ROM/Job 接口综合，随后替换镜像 INIT；直接将某份实际镜像用于整机综合并允许常量传播，不能据此声称不同 profile 具有共同面积。构建边界见 [`v42_common_partition.py`](../scripts/v42_common_partition.py)。

### Program：纯指令、双入口

Program 的 **16 字全是指令区**，没有 Job、消息或操作控制字。每组镜像同时含 Keygen 和 Sign 程序，入口由 descriptor 0 指定；当前生成镜像的入口为 **0/3**，不是 RTL 硬编码。两段程序各以 HALT 结束，其余填零。离线工具拒绝非法入口或跳入填充区。

| 位 | SINGLE / RUN：`[63:62]` 为 0 / 1 |
|---|---|
| `[61:58]` | template 地址 |
| `[57:47]` | 紧凑坐标：`layer[10:6]`、`group[5:0]` |
| `[46:41]` | 发射次数减 1；SINGLE 为 0 |
| `[40:30]` | 每次 RUN 发射后的紧凑坐标增量 |
| `[29:0]` | 保留，离线要求为零 |

第 `i` 次发射使用 `coordinate + loop_bias + i × stride`。紧凑坐标展开为逻辑坐标 `[23:13]`，逻辑低 13 位为零。

| 位 | LOOP：`[63:62]=2` |
|---|---|
| `[61:57]` | 后跳指令数减 1 |
| `[56:51]` | 初次执行后额外重复的次数 |
| `[50:40]` | 每次回跳增加的紧凑坐标偏置 |
| `[39:0]` | 保留，离线要求为零 |

LOOP 最多嵌套两层。`HALT` 为 `[63:62]=3` 且其余位为零，在当前宏完成后结束该入口。

### Template：单宏命令

Template 物理字宽为 64 位，但**仅 `[16:0]` 承载编码**，高位须为零。容量为 16 项。

| 位 | 含义 |
|---|---|
| `[2:0]` | 宏操作号 1…5 |
| `[7:3]` | 主 descriptor 物理地址 |
| `[12:8]` | ROUTE descriptor 物理地址；0 表示没有路由 |
| `[13]` | `CAPTURE`：输出目标链值或 FORS 秘密值 |
| `[14]` | `AUTH`：输出认证路径 |
| `[15]` | `EXTERNAL_ROOT`：最终层使用外部公钥根的语义 |
| `[16]` | SIGN_ONLY；SLH 必须为零，XMSS/LMS Sign 链使用 |
| `[63:17]` | 保留，离线要求为零 |

序列器将 template 与 program 坐标展开为 ABI 4 的 48 位宏命令：`op[47:44]`、`descriptor[43:36]`、`route[35:28]`、`flags[27:24]`、`coordinate[23:0]`。物理引用补成 8 位，坐标低 13 位为零。`flags[27:24]` 从高到低为 `EXTERNAL_ROOT`、`SIGN_ONLY`、`AUTH`、`CAPTURE`；当前 SLH 格式禁止 `SIGN_ONLY`。发射和完成是单宏握手，没有第二宏槽或多事件 scoreboard。

### Descriptor：固定物理地址

每项 64 位。历史 ABI 4 的逻辑 descriptor 地址离线压缩为连续物理地址；**kind 不存放在 `[63:60]`**，记录类型由位置决定。地址 30、31 为零填充。模板及 descriptor 内部引用均使用物理地址，由离线工具重映射。

| 物理地址 | 类型 | 历史逻辑地址 |
|---|---|---|
| 0 / 1 | IMAGE / PROFILE | 0 / 1 |
| 2…11 | HASH | 2…11 |
| 12…13 | CHAIN | 16…17 |
| 14…15 | TREE | 20…21 |
| 16…20 | ROUTE | 40…44 |
| 21…22 | TRANSFORM | 48…49 |
| 23 | EMIT | 50 |
| 24…29 | SEGMENT | 64…69 |
| 30…31 | 保留 | — |

| 类型 | 物理字段；其余位按离线格式要求置零 |
|---|---|
| IMAGE，地址 0 | Sign 输出字节 `[17:0]`；Keygen 输出字节 `[35:18]`；Keygen 入口 `[40:36]`；Sign 入口 `[45:41]`；`[63:46]=0` |
| PROFILE，地址 1 | 整个字取 `0/1/2/4/5/6`，分别表示 128f/192f/256f/128s/192s/256s；节点 `n=16/24/32` 字节和树参数由此选择 |
| HASH | shape `[59:56]`；domain `[55:48]`；arity `[47:40]`；输出字节 `[37:32]`；最大 SHAKE rate 块数 `[29:24]`，**6 位** |
| CHAIN | seed/step/reduce/leaf 配方地址位于 `[59:52]`/`[51:44]`/`[43:36]`/`[35:28]`；链数 `[27:20]`；最大步数 `[19:15]`；归约模式 `[13:12]` |
| TREE | CHAIN 地址 `[59:52]`；parent HASH 地址 `[51:44]`；高度 `[43:40]`；target `[37:36]`；indexing `[33:32]`；缓存相关 `[31:29]` 必须为零 |
| ROUTE | 值槽 `[57:56]`；立即输出 bit 55；解析摘要 bit 54；按 group 存 FORS 根 bit 53 |
| TRANSFORM | 操作 `[59:56]`；来源值槽 `[49:48]`；移位 `[43:40]` |
| EMIT | 首个 SEGMENT 地址 `[59:52]`；连续 SEGMENT 数 `[51:48]` |
| SEGMENT | 来源 `[59:56]`；长度 `[55:48]`；32 位常量 `[31:0]` |

引用字段虽沿用 8 位位置，当前物理地址仅低 5 位有效。SLH 镜像的 HASH shape 使用 1 `ADDRESS_SEED`、2 `ADDRESS_VALUE`、3 `MESSAGE_PRF`、4 `MESSAGE_DIGEST`、12 `ADDRESS_LIST`。SHAKE256 rate 为 136 字节；`blocks` 是输入容量上界，不是重复 Hash 次数。新 Hash 清零 1600 位状态，多块输入延续同一状态；短输入可直接装入填充后的吸收块，链步可走局部反馈路径。

SLH CHAIN 只使用单叶模式 0 和端点列表归约模式 1，最多 **67** 条链，每链最多 15 步。TREE 用于 FORS 和 hypertree，`target/indexing` 当前只使用 0/1，禁用有状态树缓存。ROUTE 保存中间值、解析消息摘要或按 FORS group 保存根。TRANSFORM 操作 1 产生 base-16 链数字及校验和，操作 2 更新 hypertree 层叶号。当前 SEGMENT 来源使用 0 `SECRET`、1 `PRF`、2 `PUBLIC`、3 `ROOT`、4 `RANDOM`、7 `CONSTANT`；旧有状态算法专用来源不属于生产镜像。

| 参数点 | `n` | `d` / 子树高 | FORS `k` / 高度 | WOTS+ 链数 | Keygen / Sign 输出字节 |
|---|---:|---:|---:|---:|---:|
| SLH-DSA-128f | 16 | 22 / 3 | 33 / 6 | 35 | 96 / 17,088 |
| SLH-DSA-192f | 24 | 22 / 3 | 33 / 8 | 51 | 144 / 35,664 |
| SLH-DSA-256f | 32 | 17 / 4 | 35 / 9 | 67 | 192 / 49,856 |
| SLH-DSA-128s | 16 | 7 / 9 | 14 / 12 | 35 | 96 / 7,856 |
| SLH-DSA-192s | 24 | 7 / 9 | 17 / 14 | 51 | 144 / 16,224 |
| SLH-DSA-256s | 32 | 8 / 8 | 22 / 14 | 67 | 192 / 29,792 |

六组镜像的 Keygen 都是末层 hypertree `TREE` → `EMIT` → `HALT`；Sign 使用消息随机化/摘要 `HASH`、FORS `TREE` 与根列表 `HASH`、层间 `TRANSFORM`、hypertree `TREE` 和 `LOOP`，最后 `HALT`。参数、循环次数和路由来自镜像，没有按参数点展开的 Keygen/Sign 控制状态机。

## 离线验证

[`ExternalImage.decode()`](../model/slh64_external.py) 检查容量、保留位、入口/HALT、引用、SLH 限制和输出长度；[`ExternalMachine`](../model/slh64_external.py) 使用独立 Job 和消息执行。`model/slh64.py` 的逻辑展开仍由当前镜像生成与参考检查使用。


```sh
make compile-microcode          # 六参数共十二种参数点/操作组合的软件模型与向量门禁
make rtl-unit-test             # Icarus 小型 RTL 单元测试
make rtl-all-profiles TAG=ABI  # Verilator 十二组独立 Keygen/Sign 仿真
make reproduce-v42             # 核验 v4.2 已保存证据
```

当前镜像位于 [`external_job_message/images`](../manifests/experiments/unified_hbs_v4.2/external_job_message/images)，接口与测量边界另见 [`External_Job_Message_Interface.md`](Job_Interface.md)。历史 ABI 3、XMSS/LMS、旧布局和旧 PPA 数据应使用对应封存源码及报告复现，不应按本文的生产 ABI 解读。

## 实验 XMSS/LMS 扩展

编码由 `model/stateful.py` 生成并按规范化镜像严格回读检查。profile 8/9 为 xmss_omega2/4，10/11 为 lms_omega2/4；均 n=32、h=10。新镜像采用可达描述符压缩，地址不沿用上面的 SLH 固定映射；各引用已重定位，segment 连续性保留。原 SLH 编码和镜像不变。

新增生产使用的 shape 为 5 INDEX_PRF、6 ROOT_MESSAGE、7 MASKED_SEED、8 MASKED_VALUE、9 PREFIX_SEED、10 PREFIX_VALUE、11 PREFIX_MESSAGE、13 PREFIX_LIST、14 PREFIX_LEAF、15 PREFIX_PARENT。XMSS mode=2 使用 L-tree，LMS mode=1 压缩端点后计算叶；TREE indexing=2 使用 LMS 堆式地址。omega2 的 TRANSFORM 产生 128+5 个二位数字，omega4 产生 64+3 个四位数字。

TREE 历史缓存位 31/30/29 在新镜像清零，Sign 重建认证树。SEGMENT 5 为 identifier，6 为四字节大端 q；XMSS 的来源 4 是计算所得 R，LMS 来源 4 是外部 RANDOMIZER。混合长度输出和节点 Verify 的边界由 [Job_Interface.md](Job_Interface.md) 定义。四个 profile 使用仓库实验格式，不是 RFC 注册编码。
