# mHBS 有类型微指令与单棵树宏架构

默认实现采用 `hbs_micro64` ABI 4。同一固定 K1U1 RTL 通过镜像运行六种 SLH-DSA SHAKE 参数的 Keygen、Sign 和 Verify。生产源码由 `sources.txt` 指定。

```text
top：同步程序 ROM、descriptor、启动控制、固定 Job、消息输入
  ├─ signature：Sign 签名缓存，可编译关闭
  └─ common：通用Job/ROM启动边界
    └─ executor：专用上下文、节点存储和流式 I/O
      ├─ TREE：完整单棵 HT/FORS 树；固定父子握手复用 CHAIN
      ├─ CHAIN：一条 WOTS 链的 PRF、连续 F 与截取
      ├─ 普通 HASH/WAIT：一次 Hash，允许有限元数据重叠
      └─ 一个 recipe → shake_context → 每拍一轮 Keccak
```

## 软硬件分工

image 准备消息摘要、DIGITS 和 TARGET，控制 FORS 的 GROUP 循环、根列表压缩、超树 LAYER 推进和最终 ROOT_COMPARE。阻塞 TREE 宏完成当前一棵树的叶生成、WOTS 链遍历、栈合并、认证路径及签名节点流；不跨 GROUP 或 LAYER，不包含完整 Job。没有 template、运行时调用栈或操作系统接口。

HT ROOT/SIGN 遍历叶和链，复用 LIST 存放当前叶的 WOTS 端点，再按栈式次序合并。FORS SIGN 成对生成叶，直接计算首父节点后合并。VERIFY 消费签名节点并恢复真实根；HT SIGN 的 TOP_SHORTCUT 仅在最后一层有效，输出相同签名并返回调用方提供的 V3 公钥根，不把它标作实际计算根。

保留单链 CHAIN 和普通 HASH/WAIT。ABI 4 的三种比较镜像分别使用 TREE、显式树＋CHAIN、全显式树和链；同一 RTL/仿真二进制仅替换 image。编译期 helper 不是硬件宏，显式版本仍产生有界循环和分支。

## 有类型控制与取指

ABI 4 没有 scalar[] 寄存器堆、任意字段搬运、宽整数 ALU 或任意地址 load/store。LAYER、64 位 TREE 地址、LEAF、GROUP、CURSOR、CHAIN、STEP/DIGIT、LEVEL、INDEX/PATH、FORS_BASE 和归约索引使用独立寄存器及受限连线。普通指令的范围检查在更新前完成，越界不静默回卷。

程序为 512×64 位同步 ROM，descriptor 为 32×64 位异步 ROM，PC 与三个入口均为 9 位。单条预取缓冲在分支、结束及复位时清除。TREE 运行时冻结 image，通过固定父子握手调用 CHAIN；子链不推进 PC、不退休，整条 TREE 只退休一次。新 RTL 拒绝 ABI 1/2/3。编码与权限见 [ABI](ABI.md) 和[指令表](ISA.md)。

## Hash 与快照

固定一个物理 Hash lane、UNROLL=1。L0/L1 是逻辑槽，普通 HASH 的有效 mask 必须为 1 或 2；每项请求最多执行一次完整 Hash。普通 HASH 锁存请求上下文，等待期间只允许白名单元数据更新及直接分支；节点访问、摘要变换、I/O 和下一次发射必须在 WAIT 后执行。

TREE 在首次 Hash、I/O 或工作区修改前锁存完整 64 位地址、profile、TARGET、flags，并检查全部所需 recipe。HT 检查 7…10；FORS SIGN 检查 4…6，VERIFY 检查 5/6。检查形状、domain、arity、输出长度、块数容量及保留位，子链使用已验证的紧凑快照。TREE 内部请求由固定控制器授权，lane 和 sponge 不包含链或树遍历状态。

CHAIN 在处理器侧控制一条链。中间 F 使用 sponge 保留摘要反馈，按 n 构造输入，不增加整节点反馈寄存器。响应消费与下一次合法 F 请求可在同一边沿发生；每次请求仍有独立握手和完整 Hash。最终摘要保留至提交结束，普通 HASH 不自动续接。

## 存储和返回边界

节点存储为 128×256 bit、异步单读单写 RAM。LIST[68]、STACK[16]、AUTH[16] 和固定节点对象映射到互不重叠的分区；V2、V3 和 RIGHT 保留独立寄存器。私有字 123 保存 CHAIN 截取值，没有第二 RAM 端口、整树缓存或新增完整签名缓冲。独立 H_msg 为 49 字节，DIGITS 保留消息与校验和快照。

普通 TREE 成功返回 L0 根，保留 LAYER、TREE64、LEAF、GROUP、TARGET、V0…V3、H_msg 和全局 DIGITS；工作元数据及 ADRS 清零，MASK=L0。临时节点失效后读零。FORS 保留 LIST 中此前各树的根；HT 可覆盖 LIST。STACK/AUTH 是树工作区。独立 CHAIN 继续保留原子 L/CAP/STEP 提交语义；TREE 内子链与工作区不提供整树回滚。

消息使用专用 16×64 bit RAM，仅消息握手写入，Hash 按锁存长度屏蔽旧尾部。它不向 image 提供字节寻址。SHAKE 直接按 64 bit rate 字吸收，固定短 Hash 为 25 周期，多块后续 rate 块增加一周期。单端口节点 RAM 的 Hash 与处理器访问互斥，SYNTHESIS 模式另验真实端口。

## 流接口与故障

TREE SIGN 内部输出 WOTS CAP 或 FORS secret，再按高度输出 AUTH；输出无 ready，按有效脉冲发送。VERIFY 仅在需要节点时拉高 verify_ready，允许任意输入停顿且每节点准确消费一次。顶层端口与签名缓存协议见 [Job_Interface](Job_Interface.md)。

预检失败没有 Hash、I/O 或工作区修改。TREE 中途故障采用整 Job 终止：工作区和部分输出可能已改变，停止后续请求与 I/O，不产生 done，签名缓存作废；调用方丢弃本 Job 的全部结果并复位重放。签名不匹配由最终 ROOT_COMPARE 返回 verify_pass=0，不作为执行故障。

Job 种子与消息在协议要求的期间保持稳定。控制快照不复制全部密钥。每次复位执行一个 Job，复位取消在途工作。签名缓存位于共同核之外，可编译关闭；正常功能验收保留顶层完整读回。

## 验证与测量

每个物理 Hash 必须归属普通 HASH、独立 CHAIN 或合法 TREE 实例，记录树实例、叶号、链号、阶段、步号及高度。同一 image 的 VM/RTL 有序 trace 一致，调度不同的 image 按完整输入/结果多重集和工作次数比较。TREE busy 包含子链，不能重复相加。

共同核提取保留通用 Job/ROM 端口，六参数共用同一核。本仓库移植只执行100MHz共同核综合，没有启动布线；本轮结果见[移植报告](manifests/experiments/image_chain_tree_import_20261021/reports/Import.md)，验证命令见[验证指南](Verification.md)。源项目曾对128f执行布线并据此选择该固定提交；这些历史频率不能作为本仓库新测频率。

TREE 优化版将准备和推进操作合到同一有效状态，并让非目标 FORS 叶对的 PRF0→PRF1→F0→F1 在响应消费的同一边沿接受下一请求。旧响应继续使用 group 快照，下一请求使用独立的 recipe、地址和逻辑槽选择；目标叶对保留原截取路径。RAM 同拍仅写一个旧结果并读一个新输入，没有增加读写端口。完整消融属于源项目历史记录；本轮只复现既定最终实现。

合法节点宽度仍为 16/24/32 字节，数据通路按 64 位字数保存 TREE 的宽度快照，再补三个零位还原字节数。普通宽度连线同样固定字节数低三位。配置检查继续比较完整原始 n 值，17/25/33 等非法值不能通过舍入被接受；此约束不改变任何合法 Hash 输入或节点截断。

TREE 发射时同时锁存完整配置的合法性结果，首个预检状态检查该结果，再依次检查配方。非法配置仍在首次 Hash、I/O 或工作区写入前终止；合法路径不增加状态或周期。这将宽配置判断与普通指令的节点 RAM 写使能路径分开。该源版本曾按源项目的实际布线 ATP 选定；本轮不进行新的候选取舍。
