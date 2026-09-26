# μHBS 当前微码 ABI 3：token、template、descriptor

本文描述**当前仓库**的三算法实现，而不是后续讨论过的 ABI 4 或 v4.1 方案。编码的可执行定义是 [`model/unified_hbs.py`](../model/unified_hbs.py) 和 [`model/static_task_microcode.py`](../model/static_task_microcode.py)；RTL 对应 [`uhbs_static_task_sequencer.sv`](../rtl/sequencer/uhbs_static_task_sequencer.sv)、[`uhbs_hbs.sv`](../rtl/top/uhbs_hbs.sv) 和 [`uhbs_recipe_lane.sv`](../rtl/hash_lane/uhbs_recipe_lane.sv)。本文的位号从最低位 0 开始，`[高:低]` 两端均包含。

## 1. 三层各做什么

```text
token ROM ──选择模板、给坐标、展开 RUN/LOOP──┐
                                         ├─→ 48 位宏命令 ─→ 宏执行器 ─→ Hash lane / 节点存储 / 输出
template ROM ──五类宏操作、描述符编号、路由、标志──┘              ↑
                                                           │
descriptor ROM ──Hash 配方、Chain/Tree 参数、输出来源等──────────┘
```

三者分别是 **128 位 token**、**128 位 template**、**64 位 descriptor**。token 规定宏操作的次序和循环，template 规定每次发出的宏命令，descriptor 规定宏操作的具体配方及结果去向。宏执行器只识别五类指令：`HASH=1`、`CHAIN=2`、`TREE=3`、`TRANSFORM=4`、`EMIT=5`。链的每一步和树的每个节点由宏内部的硬件循环执行，**不需要为每个 Hash 写一条 token**。

当前镜像只存放不可变的程序与配方。种子、随机量、identifier、索引 `q` 和消息由三个算法顶层的固定参数及消息接口进入 `uhbs_hbs`；**Job 和消息不在 token ROM 中**。Keygen 和 Sign 分别从 descriptor 0 指定的入口运行；顶层控制先执行 Keygen，再接收消息并执行 Sign。当前 XMSS/LMS 还有外部索引提交保护接口。

`scripts/compile_unified_hbs.py` 先用软件模型和向量核对结果，再生成 `rtl/microcode/uhbs_{slh,xmss,lms}_{tokens,templates,descriptors}.mem`，RTL 用 `$readmemh` 初始化。软件画像统一编译，但现有三个顶层**分别静态综合**：例如 `N=16/32`、recipe mask、ROM 有效深度和 lane 数可以不同。因此 ABI 相同不等于三算法当前面积相同，也不等于仅替换 ROM 就能在三份已综合网表之间切换算法。

| 镜像 | token 有效字数 | template 有效字数 | descriptor 存储字数 | Keygen 入口 | Sign 入口 | `n` | 树高配置 |
|---|---:|---:|---:|---:|---:|---:|---:|
| SLH-DSA-128f | 14 | 11 | 128 | 0 | 3 | 16 | Hypertree 子树高 3；FORS 树高 6 |
| XMSS，w=4 | 10 | 8 | 128 | 0 | 3 | 32 | 10 |
| LMS-SHAKE256/256 研究 profile，w=4 | 10 | 8 | 128 | 0 | 3 | 32 | 10 |

表中的 descriptor 大部分字为零，只有被引用的地址承载记录。软件编译器检查镜像的 descriptor 类型引用和程序终止；RTL 运行时也做类型及部分边界检查，但**不能把所有软件校验都理解为 RTL 启动时的完整镜像扫描**。

## 2. Token：程序顺序、坐标和循环

每个 token 128 位，`[127:126]` 给出类型：`00 SINGLE`、`01 RUN`、`10 LOOP`、`11 HALT`。

### SINGLE / RUN

| 位 | 含义 |
|---|---|
| `[125:120]` | template 地址，6 位 |
| `[119:96]`、`[95:72]` | 两个命令槽的初始 24 位坐标 `coord0/coord1` |
| `[71:66]` | 本 token 的发射次数减 1；SINGLE 必须为 0，RUN 必须非 0 |
| `[65:42]`、`[41:18]` | RUN 每次发射给两槽坐标加的 `stride0/stride1` |
| `[17:0]` | 保留，必须为 0 |

RUN 的第 `i` 次发射坐标为 `coord + loop_bias + i×stride`，`i=0…repeat_minus_one`。SINGLE 只发射一次且 stride 必须为零。坐标的现有布局为 `layer[23:19] | group[18:13] | height[12:10] | item[9:4] | variant[3:0]`；**当前宏执行 RTL 实际取用 layer 和 group**，其余低位保留了坐标表达能力，但不能仅凭这些低位推断当前硬件支持新算法语义。

### LOOP / HALT

| LOOP 位 | 含义 |
|---|---|
| `[125:114]` | 后跳 token 数减 1，编码支持 1…4096 |
| `[113:108]` | `loop_repeats`，1…63，表示初次执行之后的**额外**重复次数 |
| `[107:84]`、`[83:60]` | 每次回跳累加给两个坐标槽的 `delta0/delta1` |
| `[59:0]` | 保留，必须为 0 |

执行到 LOOP 时回跳 `back_count` 个 token；每次重复增加坐标偏置。循环栈最多两层。SLH Sign 中 `loop_repeats=20`、`delta0=1<<19`，使同一段宏命令依次作用于 hypertree 的第 0～20 层；随后另有一条第 21 层的 TREE token。`HALT` 只允许 `[127:126]=11`，其余 126 位全零；它要等尚未完成的事件结束才结束入口。

## 3. Template：一次宏命令如何发出

template 是 128 位的水平任务字。当前编译器的每个模板只在**命令槽 0**放一条宏命令；槽 1 保留为零。虽然模板保留两个槽和事件 scoreboard，本版 `uhbs_hbs` 不接收第二条宏命令。**这与宏内部可以同时调用两个 Hash lane 是两回事。**

| 位 | 当前含义 |
|---|---|
| `[127:124]` | template 操作码 `OP_ISSUE=1` |
| `[123:116]` | 等待事件 mask：入口首条为 0，后续为 `0x01` |
| `[115:108]` | 消费事件 mask：入口首条为 0，后续为 `0x01` |
| `[107]`、`[106]` | 槽 0 有效为 1、槽 1 有效为 0 |
| `[105:103]`、`[102:100]` | 两槽完成事件编号；当前使用事件 0 |
| `[99:52]`、`[51:4]` | 两条 48 位命令；token 分别覆盖其中的坐标 `[75:52]`、`[27:4]` |
| `[3]`、`[2]` | 两槽完成事件跟踪；当前槽 0 为 1、槽 1 为 0 |
| `[1:0]` | 保留，当前为 0 |

单条 48 位宏命令的格式：

| 命令位 | 含义 |
|---|---|
| `[47:44]` | 五类宏操作之一 |
| `[43:36]` | 主 descriptor 地址，8 位 |
| `[35:28]` | ROUTE descriptor 地址，8 位；0 表示不路由 |
| `[27:24]` | flags：bit0 `CAPTURE`、bit1 `AUTH`、bit2 `SIGN_ONLY`、bit3 `EXTERNAL_ROOT` |
| `[23:0]` | token 注入的坐标 |

事件 0 表示**整条宏命令全部执行完成**，包括它展开的所有链步或树节点。下一个模板等待该事件，所以宏命令顺序由镜像决定；同一宏内部的两个 Hash lane 可以并行处理相邻链。这里的 lane 是 Hash 计算 lane，不是两个独立宏命令发射槽。

## 4. Descriptor：通用记录格式

每条 descriptor 为 64 位，`[63:60]` 是 kind。地址是**类型化引用**，例如 TREE 指向 CHAIN 和父节点 HASH，CHAIN 再指向 seed/step/reduce/leaf HASH。未列出的位为零或当前未使用，不能视为任意扩展字段。

| kind | 编码 | 字段 |
|---|---:|---|
| `HASH` | 1 | shape `[59:56]`；domain `[55:48]`；arity `[47:40]`；输出字节 `[37:32]`；最大 SHAKE rate 块数 `[28:24]` |
| `SEGMENT` | 2 | source `[59:56]`；长度 `[55:48]`；32 位常量 `[31:0]` |
| `CHAIN` | 4 | seed 配方地址 `[59:52]`；step 配方 `[51:44]`；reduce 配方 `[43:36]`；leaf 配方 `[35:28]`；链条数 `[27:20]`；每条最大步数 `[19:15]`；归约模式 `[13:12]` |
| `TREE` | 5 | CHAIN 地址 `[59:52]`；parent HASH 地址 `[51:44]`；高度 `[43:40]`；target 模式 `[37:36]`；indexing 模式 `[33:32]`；建缓存 bit31；读缓存 bit30；完整缓存 bit29 |
| `ROUTE` | 6 | 值槽 `[57:56]`；同时输出 bit55；解析 digest bit54；按 group 存根 bit53 |
| `TRANSFORM` | 8 | 操作 `[59:56]`；输入值槽 `[49:48]`；移位 `[43:40]` |
| `EMIT` | 9 | 首个 SEGMENT 地址 `[59:52]`；连续 SEGMENT 数 `[51:48]` |
| `IMAGE` | 10 / A | ABI 版本 `[59:56]`；Keygen 入口 `[55:47]`；Sign 入口 `[46:38]`；Keygen 输出字节 `[35:18]`；Sign 输出字节 `[17:0]` |
| `PROFILE` | 11 / B | stateful bit59；节点字节数 `n` `[55:48]`；树高 `[43:40]`；消息长度上限 `[31:24]` |

descriptor 0 必须是 `IMAGE` 且版本为 **3**；descriptor 1 是 `PROFILE`。当前 `HASH` 的输出长度由镜像指定（SLH 消息摘要为 34 字节，其余常见输出为 `n`）；`blocks` 是输入的容量上界，执行器还负责 SHAKE256 的 136 字节 rate、域分隔和多块吸收，不是每个块单独输出一个结果。

`ROUTE` 可把宏结果写入 0～3 号值槽、立即输出、解析 SLH 消息摘要得到树号与叶号，或按 group 将 FORS 根写入根列表。`TRANSFORM` 操作 1 将 `n` 字节消息摘要拆成 base-16 数字并追加 3 个校验和数字；操作 2 用指定移位从树号取当前层叶号并更新树号。`EMIT` 依次读取 SEGMENT，输出种子、根、随机量、identifier、索引或常量等字段。`SEGMENT` source 编码：0 `SECRET`、1 `PRF`、2 `PUBLIC`、3 `ROOT`、4 `RANDOM`、5 `IDENTIFIER`、6 `INDEX`、7 `CONSTANT`。多字节索引和常量输出采用大端字节顺序。

### Hash shape 如何替代“按算法写死的 Hash”

`HASH.shape` 选择**输入字节的构造方式**。同一个 SHAKE256/Keccak 引擎可处理三族配方，差别发生在送入海绵前的拼接和附加 Hash：

| shape 编码 | 名称 | 主要用途 / 输入结构概览 |
|---:|---|---|
| 1、2 | `ADDRESS_SEED`、`ADDRESS_VALUE` | SLH：public seed + 32 字节地址 + secret seed，或 + 1/2 个节点值 |
| 3、4 | `MESSAGE_PRF`、`MESSAGE_DIGEST` | SLH：消息随机化；随机量 + public seed + 根 + 消息的摘要 |
| 5、6 | `INDEX_PRF`、`ROOT_MESSAGE` | XMSS：由索引导出随机量；把随机量、根、索引和消息送入消息摘要 |
| 7、8 | `MASKED_SEED`、`MASKED_VALUE` | XMSS：seed Hash；带 key/mask 派生的 1/2 输入链步和父节点 Hash |
| 9、10、11 | `PREFIX_SEED`、`PREFIX_VALUE`、`PREFIX_MESSAGE` | LMS：identifier、叶号、链号/步号或消息域分隔前缀 |
| 12、13 | `ADDRESS_LIST`、`PREFIX_LIST` | 分别压缩 SLH 根/链端点列表、LMS LMOTS 链端点列表 |
| 14、15 | `PREFIX_LEAF`、`PREFIX_PARENT` | LMS：LMOTS 公钥到 Merkle 叶节点；两子节点到父节点 |

例如 `MASKED_VALUE` 的一次逻辑调用内部会先派生 key 和 `arity` 个 mask，再做最终 Hash，所以一个“链步”可包含多次实际 Hash/Keccak 置换。Hash/置换计数须按底层调用统计，不能只数 token 或宏指令。字节拼接、地址构造及填充的精确定义以 `Machine.hash_recipe()` 与 `uhbs_recipe_lane` 为准。

## 5. 同一套 CHAIN 如何实现 FORS、WOTS+、XMSS、LMOTS

CHAIN descriptor 定义一个**链条生成器**：

```text
对 item = 0 … count-1：
    x = HASH(seed_recipe, 地址/叶号/item)
    重复最多 steps 次：x = HASH(step_recipe, 地址/叶号/item/步号, x)
    按 CAPTURE 或 SIGN_ONLY 在消息数字 digit[item] 处输出链值
    保存末端 x
按 mode 归约所有末端；如有 leaf_recipe，再 Hash 成树叶
```

消息数字不是硬编码在 CHAIN 里。`TRANSFORM` 先把摘要变成数字，CHAIN 宏读取当前数字。当前三个 profile 都是 base 16：对 `n=32` 得到 **64 个消息数字 + 3 个校验和数字 = 67 条链**；每条最多 15 步。SLH-128f 的 WOTS+ 为 **32 + 3 = 35 条链**。`SIGN_ONLY` 用于 XMSS/LMS 签名：每条链只计算到对应数字并输出该值，不做后续端点归约。TREE Keygen 则运行到链末端，形成叶节点；若对目标叶设置 `CAPTURE`，既输出中间签名链值，又继续算到端点以维持完整树计算。双 Hash lane 可并行执行相邻 item，但仍受相同 CHAIN descriptor 控制。

| 归约模式 | 含义 | 当前使用 |
|---:|---|---|
| 0 | 不归约，单条链末端直接成为叶值 | SLH FORS |
| 1 | 将全部链末端按顺序拼成一个列表，调用 `reduce_recipe` Hash；可再调用 `leaf_recipe` | SLH WOTS+、LMS LMOTS |
| 2 | 相邻末端两两 Hash，奇数末端提升到下一层，直到只剩一个；可再调用 `leaf_recipe` | XMSS WOTS+ 的 L-tree |

当前实际配置如下；`D#` 是 descriptor 地址：

| 用途 | CHAIN | seed / step / reduce / leaf | count / steps / mode | 结果 |
|---|---:|---|---|---|
| SLH FORS 单叶 | D16 | D4 / D5 / 无 / 无 | 1 / 1 / 0 | 地址绑定的 FORS 叶 |
| SLH WOTS+ 公钥 | D17 | D7 / D8 / D9 / 无 | 35 / 15 / 1 | 35 个端点经 `ADDRESS_LIST` 压成叶 |
| XMSS WOTS+ 公钥 | D16 | D4 / D5 / D6 / 无 | 67 / 15 / 2 | 67 端点经带掩码的 L-tree 压成叶 |
| LMS LMOTS 公钥 | D16 | D3 / D4 / D5 / D6 | 67 / 15 / 1 | 67 端点经 `PREFIX_LIST` 压缩，再经 `PREFIX_LEAF` 得到叶 |

这正是“同一种 CHAIN 支持多种链”的关键：**迭代控制相同，seed/step 配方、链数、最大步数、归约方法以及可选叶 Hash 由 descriptor 组合**。FORS 与 WOTS/LMOTS 的地址、域分隔也分别由 Hash shape 和坐标决定。

## 6. 同一套 TREE 如何实现多种树

TREE descriptor 把一个 CHAIN 生成器当作**叶生成器**，再按树高 `h` 生成 `2^h` 个叶子，用同一套栈归约控制将相邻节点送入 `parent` Hash，逐层得到根；`AUTH` 标志使它按目标叶号输出每层的兄弟节点。概念上：

```text
for leaf_index in 0 .. 2^h-1:
    leaf = CHAIN(chain_id, leaf_index)   # 内部也可能完成链端点归约
    push/merge(leaf, parent_recipe)
    若该节点是目标路径的兄弟节点，保存到 auth_path[level]
最后得到 root；按 ROUTE 存值、存 FORS 根或输出
```

`target` 模式 0 取当前 `scalar_leaf`；模式 1 从 SLH 消息摘要按 `group` 提取 FORS 目标索引；模式 2 取当前 stateful `q`。`indexing` 模式 0 使用普通 `0…2^h-1` 叶序号；模式 1 使用 SLH FORS 的 `group×2^h+leaf_index` 地址；模式 2 使用 LMS 的 `2^h+leaf_index` 叶地址，并在父节点层使用 LMS 二叉堆式编号。`parent` HASH descriptor 决定 SLH 地址型、XMSS 带掩码型或 LMS 前缀型父节点 Hash。软件模型允许 1～10 层；生产 RTL 当前拒绝 TREE 的 `full_cache` 位 29。

| 用途 | TREE | CHAIN / parent | 高度 | target / indexing | 缓存行为 |
|---|---:|---|---:|---|---|
| SLH FORS 的 33 棵树 | D20 | D16 / D6 | 6，64 叶/棵 | 消息摘要 / FORS group 地址 | 不跨操作保留整树；将 33 个根按 group 存入根列表 |
| SLH hypertree 子树 | D21 | D17 / D10 | 3，8 叶/棵 | 当前层叶号 / 普通 | 按 layer 坐标重复；Sign 输出 WOTS+ 值与认证路径 |
| XMSS Keygen | D20 | D16 / D7 | 10，1024 叶 | `q` / 普通 | 计算全树，保存**该 q 的认证路径**和根 |
| XMSS Sign | D21 | D16 / D7 | 10 | `q` / 普通 | `lookup=1`，读已存认证路径，不重算全树 |
| LMS Keygen | D20 | D16 / D7 | 10，1024 叶 | `q` / LMS 编号 | 计算全树，保存**该 q 的认证路径**和根 |
| LMS Sign | D21 | D16 / D7 | 10 | `q` / LMS 编号 | `lookup=1`，读已存认证路径，不重算全树 |

因此 XMSS/LMS Sign 周期显著低于 Keygen：Keygen 做完整 1024 叶计算，Sign 主要生成目标叶的链签名，再读取 Keygen 为固定 `q` 保存的 10 个认证节点。**这不是完整树缓存**；换用另一 `q` 必须重建其认证路径。软件 `full_cache=True` 可做验证实验，但生产 RTL 明确拒绝该位。当前版本的 stateful 签名还要通过索引 guard 的保留/提交检查。

SLH 的 FORS 通过 `RUN` 把一条 TREE D20 展开成 33 棵树：每次 `group` 坐标增加 1，D20 以对应组的 6 位目标索引选择签名叶；`CAPTURE|AUTH` 输出该叶秘密值和 6 个认证节点，`ROUTE.group` 保存这棵树的根。随后 D11 的 `ADDRESS_LIST` Hash 读取 33 个根形成 FORS 公钥。Hypertree 则由 D21、`TRANSFORM` 和 LOOP 共同驱动层号与当前叶号：重复每层的 WOTS+ 链、子树归约、认证路径输出；末层的 `EXTERNAL_ROOT` 使用已有公共根作为结果，跳过目标路径上不必要的重算。这些变化发生在同一 TREE/CHAIN 执行器内，没有三套按算法展开的树状态机。

## 7. 三份程序的实际宏序列

下面按**展开后的逻辑流程**列出入口；括号内为主 descriptor 和重要 flags，省略 route 的常规值槽写入。

| 算法 | Keygen | Sign |
|---|---|---|
| SLH | `TREE(D21, layer=21)` → `EMIT(D50)` → HALT | `HASH(D2)` → `HASH(D3)` → `TREE(D20, CAPTURE\|AUTH) ×33` → `HASH(D11)` → `TRANSFORM(D48)` → `TREE(D21, CAPTURE\|AUTH)` 与层转换重复至第 20 层 → `TREE(D21, layer=21, CAPTURE\|AUTH\|EXTERNAL_ROOT)` → HALT |
| XMSS | `TREE(D20, cache build)` → `EMIT(D50)` → HALT | `HASH(D2)` → `HASH(D3)` → `TRANSFORM(D48)` → `EMIT(D51)` → `CHAIN(D16, SIGN_ONLY)` → `TREE(D21, lookup+AUTH)` → HALT |
| LMS | `TREE(D20, cache build)` → `EMIT(D50)` → HALT | `HASH(D2)` → `TRANSFORM(D48)` → `EMIT(D51)` → `CHAIN(D16, SIGN_ONLY)` → `EMIT(D52)` → `TREE(D21, lookup+AUTH)` → HALT |

三个 profile 的 Keygen/Sign 输出长度分别为 SLH **96/17,088**、XMSS **196/2,500**、LMS **140/2,508** 字节，由 IMAGE D0 给出并在执行末尾检查。LMS 使用仓库既有的 SHAKE256/256 **研究 profile**，不能把它写成论文中其他 LMS 参数或标准实现的严格等价物。

## 8. 一个具体的编码追踪

XMSS 的 TREE D20 为 `0x51007a2080000000`：最高半字节 `5` 表示 TREE；`chain=0x10` 即 D16，`parent=0x07` 即 D7，`height=0xA` 即 10，`target=2` 取 `q`，`indexing=0` 使用普通叶序号，bit31 为 1 表示 Keygen 保存选定认证路径。Sign 用 D21=`0x51007a2040000000`，主要差别是 bit30 的 `lookup=1`，所以不重新执行 1024 叶树。

XMSS CHAIN D16 为 `0x404050600437a000`：它引用 seed D4、step D5、reduce D6；`count=67`、`steps=15`、`mode=2`。D6 是 `MASKED_VALUE` 且 `arity=2`，被用于 L-tree 相邻节点归约。Sign 的 template P6 发 `CHAIN(D16, SIGN_ONLY)`；Keygen 的 `TREE(D20)` 则通过 D16 生成每个叶。**相同 CHAIN 数据、不同宏入口和 flags，分别得到链签名与树叶公钥。**

## 9. 能改什么、不能只靠换镜像改什么

- token 能调整宏顺序、重复次数和坐标；template 能选择五类宏、descriptor 地址、结果路由与 flags；descriptor 能组合已有 Hash shape、链和树参数。这些选择必须满足软件模型及 RTL 的既有容量和检查。
- 镜像**不能创造新的 Hash shape 或新的宏操作**。例如改变 SHAKE 域分隔、支持新的 Winternitz 数字宽度、新节点宽度或更大链数，需要相应修改模型与 RTL。
- 当前 ROM 容量、`N`、`STATEFUL`、`LANES`、`RECIPE_MASK`、消息长度上限等由顶层综合参数指定；不同算法现有网表会因这些静态参数被裁剪。若追求“同一硬件、只替换镜像”，必须另做固定容量与不按镜像裁剪的综合边界设计，不能由 ABI 3 编码本身保证。
- 地址、类型、token 保留位和输出长度出错会被模型拒绝，或在 RTL 执行相关宏时停机报错；应始终先运行软件验证，再生成 `.mem`。

## 10. 复现与核对

在仓库根目录执行：

```sh
python3 -m unittest tests.test_unified_hbs tests.test_unified_rtl_contract -v
python3 scripts/compile_unified_hbs.py
```

第二条命令会重写三组镜像和向量，并记录结果哈希与 Hash/置换计数到 [`unified_hbs_model_gate.json`](../manifests/experiments/unified_hbs_model_gate.json)。若要做 RTL 验证，`make rtl-unit-test` 使用 Icarus，`make rtl-slh-dsa-test rtl-xmss-test rtl-lms-test` 使用 Verilator。修改编译器、解释器或镜像后，先核对全输出和计数，再比较硬件周期与面积。
