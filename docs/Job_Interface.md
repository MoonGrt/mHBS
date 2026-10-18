# mHBS 微程序核 Job 与流接口

唯一生产顶层为 `rtl/top/top.sv`。支持六组SLH-DSA SHAKE及XMSS h10/h16/h20、LMS h10/h15/h20，每次复位执行一次Keygen、Sign或Verify。

## 配置

`OPERATION=0/1/2` 分别选择 Keygen/Sign/Verify。`SECRET_SEED`、`SECRET_PRF`、`PUBLIC_SEED`、`RANDOMIZER`、`PUBLIC_ROOT` 为五个 256 位综合参数，分别使用低 128/192/256 位；首字节位于低 8 位。默认值来自 128f 测试向量。切换参数集须同时使用对应镜像和 Job 参数。Sign/Verify 的公钥根由调用方提供。Verify 只使用 PUBLIC_SEED、PUBLIC_ROOT；同一组微程序镜像包含独立的 Keygen、Sign 和 Verify 入口。

ROM 路径使用 `PROGRAM_INIT_FILE` 和 `DESCRIPTOR_INIT_FILE` 参数指定；程序为 512×64 位同步读，descriptor 为 32×64 位异步单读。没有 template 镜像。顶层没有运行时 Job 写入、start 或输出背压端口。

## 端口协议

| 端口 | 语义 |
|---|---|
| `clk` / `rst` | 时钟；高有效同步复位，至少覆盖一个上升沿 |
| `message_length[6:0]` | Keygen 为 0；SLH Sign/Verify为1～87，stateful为0～87，在内部 Job 接受时锁存 |
| `message_data[63:0]` | 低字节先传，尾拍多余字节忽略 |
| `message_valid` / `message_ready` | 上升沿两者同时为 1 时接收一拍；等待 ready 时保持 valid 和 data |
| `out_valid` / `out_data[255:0]` | 每个有效拍直接输出一个完整节点，无 out_ready；接收方必须及时接收 |
| `out_bytes[5:0]` | 有效低位字节数（16/24/32），按低字节到高字节拼接；未用高位忽略 |
| `result_kind[1:0]` | 0为Keygen（SLH SK\|\|PK、stateful root）；1为签名payload；2为Verify |
| `busy` | 复位时置 1，完成或错误时清零 |
| `done` | 整项结果输出结束后保持为 1，直到复位；不再提供 out_last/out_keep |
| `keygen_done` | Keygen 完成单周期脉冲 |
| `error` / `error_code[15:0]` | 错误状态保持到复位，错误操作不产生 done |
| `boot_cycles` | header/profile 读取计数，正常为 2 |
| `keygen_cycles` / `sign_cycles` | 完成时锁存对应操作周期，未执行的操作为 0；包含消息等待 |
| `hash_count` / `permutation_count` | 当前操作的 Hash / Keccak 置换次数 |

在复位释放前设置好 message_length。Sign 可将长度保持到首次 message_ready，再开始发送消息；Keygen 保持 0 即可。消息没有 last/keep 输入，接收长度只由锁存的 message_length 决定。Keygen、消息接收结束、完成和错误停机阶段，message_ready 均为 0。

同步复位可以中断运行；重新释放复位后从头执行。顶层不自动将 Keygen 根接入随后一次 Sign，也不在完成后自动接受下一项任务。

错误码 `0x3002` 表示操作或消息长度非法，`0x3006` 表示指令、对象边界或 HASH/WAIT 执行错误，`0x3007` 表示 Hash lane 错误，`0x3101` 表示启动时 header magic/ABI 错误。镜像的全面合法性检查由软件生成阶段完成。

ABI 4 的 TREE 在宏内流式输出和接收节点，不增加端口。预检失败没有 Hash 或 I/O；运行中故障则停止整项 Job，可能已有部分签名输出或工作区更新。调用方须丢弃本次全部结果，并复位重放；done 不产生，签名缓存作废。输入停顿不构成执行故障，签名根不匹配通过 verify_pass=0 返回。

验证命令及验收边界见 [Verification.md](Verification.md)。

## 完整签名缓存与读回

`SIGNATURE_STORE_ENABLE=1`（默认）且 `OPERATION=1` 时，顶层自动保存全部签名输出。
缓存位于共同核之外，不改变原输出流、计算周期或微码。Keygen、Verify 或显式关闭该参数时，
缓存不实例化，下面所有输出恒为零。新增输入不用时接零。

| 端口 | 语义 |
|---|---|
| `signature_valid` | `done=1` 且签名缓存无错误时为 1；保持至复位 |
| `signature_length[15:0]` | 已保存的有效字节总数；签名完成后使用 |
| `signature_nodes[10:0]` | 已保存节点数；签名完成后使用 |
| `signature_node_bytes[5:0]` | 每节点有效低位字节数，16/24/32 |
| `signature_read_enable` / `signature_read_address[10:0]` | 同步读请求，地址为节点索引，从 0 开始 |
| `signature_read_valid` / `signature_read_data[255:0]` | 请求采样上升沿之后返回数据及有效标志；可每拍请求一个节点，无响应背压 |
| `signature_error` | 缓存溢出、节点宽度非法/不一致或执行错误；保持至复位 |

只有 `signature_valid=1` 且地址小于 `signature_nodes` 的请求产生读响应；其余请求的
`signature_read_valid=0`。读数据仅在 valid 为 1 时有意义，未使用高位忽略。
按地址递增，将每节点的低 `signature_node_bytes` 字节按低字节在先拼接，SLH得到完整签名，stateful得到待软件组装的payload。
缓存可重复随机读取，读操作不影响 `done` 或原输出。缓存错误不改变原核心 `error`，调用方
须检查 `signature_valid` 和 `signature_error` 后再使用缓存。

存储为 1558 × 256 bit，同一存储覆盖全部六参数，最长签名为 256f 的 49,856 字节。
128/192 位节点在 256 位槽中留空高位，以省去打包逻辑。存储拆为 1024 项 BRAM、512 项 BRAM
和 22 项 LUTRAM 尾区，统一为同步读接口，不复位 RAM 内容；
同步复位清除计数与有效状态，因此运行中复位会丢弃本次签名，旧 RAM 内容不可读回。
本模块用于功能性保存，不提供物理存储擦除。历史共同核的 0 BRAM 面积不包含此顶层缓存。

## 仿真统计与综合裁剪

`PROFILE_ENABLE` 在仿真默认开启，在定义 `SYNTHESIS` 时默认关闭；生产共同核综合也显式设置为 0。关闭后 `boot_cycles`、`keygen_cycles`、`sign_cycles`、`hash_count` 和 `permutation_count` 保留端口但恒为零，内部计数寄存器、基准寄存器及统计加减逻辑裁除。此开关不影响签名/公钥输出、握手、错误处理和完成周期。仿真 testbench 另从实际完成的 permutation 和 hash 事件观察统计，用于检查两种配置行为一致。

## Verify 节点接口

新增 `verify_valid`、`verify_ready`、`verify_data[255:0]` 和 `verify_pass`。仅 `OPERATION=2` 使用。每拍在上升沿 valid 和 ready 同时为 1 时接受一个 n 字节节点，放在 data 低位、低字节在先；高位忽略。等待 ready 时必须保持 valid/data。Keygen/Sign 将新增输入接零即可。

调用方负责将签名拆成节点并检查原始签名长度，依次提供：R；每棵 FORS 树的签名秘密节点和 a 个认证节点；每层 XMSS 的 len 个 WOTS 签名节点和 h′ 个认证节点。认证节点按从叶到根顺序提供。内核根据 Verify 入口的 INPUT 或 TREE 内部节点需求发出 ready，不接收类型标签、字节流帧或中间计算结果。消息继续使用原消息接口，可以先完成消息传输再供应节点。

Verify 不输出 out 数据流。done=1、error=0 时读取 verify_pass：1 为根匹配，0 为签名不匹配；不匹配不是协议或执行故障。done/verify_pass 保持到复位。节点供应不足时等待输入，不把停顿判成无效签名；完成后的额外节点不被接受。完整签名字节流的长度及分帧检查由外部负责。

Verify 的 keygen_cycles、sign_cycles 保持零；仿真可观察共同核 cycles，hash/permutation 统计沿用 PROFILE_ENABLE。生产统计仍关闭。消息范围和每次复位一项操作的约束不变。

## 标准 stateful Job 扩展

新增 `job_index[31:0]`、`job_identifier[127:0]`、`job_lms_c[255:0]` 输入，Job接受时锁存；LMS C取代该算法的randomizer。stateful q范围0≤q<2^h；消息0～87字节，SLH仍为1～87字节。消息及节点仍低字节在先。所有周期、Hash、置换和宏统计扩为64位，关闭PROFILE_ENABLE后为零。

XMSS/LMS Keygen输出32字节root。Sign及签名缓存仅保存payload：32字节R/C、67个32字节链节点、h个32字节认证节点。它不是可直接发送的标准签名字节流。软件先检查原签名类型、长度、q和树高，再经 `model/stateful.py` 拆分Verify节点或组装标准签名、公钥。XMSS标准公钥68字节、LMS56字节。签名长度XMSS h10/h16/h20为2500/2692/2820字节；LMS h10/h15/h20为2508/2668/2828字节。

签名缓存与源模块共用，容量不变；缓存的节点payload可按序读回，再由软件添加标准整数/类型字段。高树Verify为真实高度路径验证；合成兄弟节点不构成完整Keygen/Sign验收。
