## state_t 分析与取舍

SLH-DSA、XMSS、LMS 已共用一套主 FSM。算法按 Job 互斥有助于共享临时存储，但状态的驻留拍同时承担 RAM 读地址登记、写冲突处理、请求握手及结果消费。不能仅根据算法名字将这些拍合并。

本轮基线为 `20261014_182411`，独立冻结并重新综合当前接口布局；此前用户已重排 executor 端口声明与 top/common 的命名连接。它与旧矩阵 `20261014_180342` 的源码不同，使用本轮自己的面积作为增量基线。各候选均以自身冻结源码测量，旧矩阵仍保留自己的面积与周期。

当前主状态为7位二进制编码，67个枚举名、最大编号70。综合中 state 的多个物理 FF 来自扇出复制；删除一个枚举名不能据此推算减少一个物理 FF。`hash_return`、`output_return`、`verify_return` 的声明各7位，也已有部分常量位被综合裁剪。

| 返回用途 | 写入 | 消费 | 存活约束 |
|---|---|---|---|
| 固定/流式哈希 | start_hash | HASH_WAIT 收到 lane_valid | 整个 HASH_ISSUE/HASH_WAIT 内保持，包括 P1 的 parent_right |
| 节点输出 | start_output | OUTPUT_CHUNK | 捕获连续输出结束前保留 PIPE_CAPTURE_NEXT 哨兵 |
| Verify 节点接收 | read_verify_node | VERIFY_INPUT 收到 verify_valid | 接收之后才启动下一次哈希 |

三类传输在主 FSM 上按阶段串行执行，返回值在新的传输启动前消费。A 将它们共用为 `continuation`，保留所有主状态编码、状态跃迁、RAM 读写和握手拍。声明由3×7位降为7位；真实面积收益还包括写选择和译码映射，不能按14位寄存器直接换算。父节点右操作数依旧按 `continuation==PARENT_DONE` 选择，活跃哈希期间保持原行为。

B 在 A 上删除 `PIPE_CAPTURE`、`PIPE_ADVANCE`、`SF_REDUCED`、`LT_PIPE_ADVANCE`、`FORS_RIGHT` 五个无功能引用名字，并去掉历史数字空洞。保留62个名字，使用6位编码，其中 `PIPE_CAPTURE_NEXT` 是输出返回哨兵。B 的功能验证通过，但三点面积均高于 A，少一个编码位并没有保证整个 common 更小。

| 候选 | P1U1 Slice | P4U1 Slice | P12U1 Slice | 选择 |
|---|---:|---:|---:|---|
| 当前冻结基线 | 5,207.125 | 9,212.375 | 15,505.000 | 原三返回寄存器 |
| A | 5,169.875 | 9,173.250 | 15,361.000 | 采用：三点均减面积，九项周期相同 |
| B | 5,188.375 | 9,217.125 | 15,457.625 | 撤回：三点均不如 A |

最终恢复 A 的7位原编码、枚举声明和对应测试观察器；只保留共享 continuation 的改动。A、B 各自120/120扩展回归通过，449个冻结文件校验保持一致。源码选择依据 common 的实测结果，没有为了减少 enum 名称而保留面积更大的实现。

用户在测试期间调整了 executor 的诊断输出声明顺序，并给 recipe 的参数例化换行；这两项保留。归档源码与当前排版快照分别保存，正常视图的原始词法校验如实标记不同。独立预处理核对确认综合视图的31,090个词法 token 与实测 A 完全相同；没有以当前源码替换历史冻结 RTL。

保留 P1 的 `LT_SETUP/LT_STORE/LT_NEXT`、奇数 L-tree 尾搬移 `LT_COPY`、FORS 的地址预读 `FORS_LEFT`，以及认证路径与树栈同写口冲突的 `PUSH_STACK`。这些是真实操作所需的拍，本轮均未删减。

## 验证与兼容性

A、B 的三配置九项完整 Sign 均逐字节核对输出和签名缓存，计算周期、总周期、Hash/置换数与本轮基线逐项相等。A 的独立逐拍锁步10/10通过，检查1,411,726拍；B 正常和 SYNTHESIS 两视图共20/20通过，检查2,823,452拍。锁步按状态名称归一化，比较主状态、握手、ROM地址、RAM地址和写数据、活跃哈希与批次参数、父节点右操作数和返回值存活期。这是所跑向量的逐拍核对，未宣称全输入形式证明。

扩展回归覆盖正常/SYNTHESIS 视图、十二参数 Verify、h10 边界 q 的完整 Sign、Keygen、复位重放、停顿、截断、篡改、在途错误、64位统计进位、消息与填充边界、多槽标签、六组 SLH Sign 和 P24U1 最大 FORS 临时工作区。A、B 均120/120通过；P24U1 SLH128f完整Sign为207,206周期，Hash/置换104,937/105,641。两组 h20 仅 Verify，完整 Keygen/Sign 保持停止。

重编码时发现测试台使用数字状态观察。B 将这些观察改为由枚举导出的 STATE_* 整数常量，并让非法状态注入随类型宽度取全1。当前 Verilator 5.008 对直接跨层枚举引用产生 internal fault，改整数常量后10/10正常/SYN lint通过。另一次以工具名字开头的普通注释被当成 pragma，修正注释后通过；两项兼容性失败保留摘要，不混入算法功能回归。B 的观察器随 B 一起撤回；当前 A 保留与其原编码对应的数字观察，profile 的返回寄存器观察更新为 continuation。

## 继续可研究的资源共享

`lt_count/lt_cursor/lt_level` 与 `fors_total/fors_offset/fors_level` 分别用于 XMSS L-tree 和 SLH FORS；可继续按存活期研究共用。WOTS 链端点完成后再进入 L-tree，部分游标也有复用机会。此轮只分析，未把它们与返回状态改动捆绑。

滚动调度的已发出计数与已完成计数同时存活；批次捕获消费仍需要 expected_mask；FORS 组根入栈期间 fors_base 与 leaf_cursor 同时存活。树栈、认证路径、签名缓存及 key/digest/captured 的同时存活数据继续独立。

## 测量与归档口径

面积统一为各 P/U 的 common OOC：xc7a200tffg1156-3、Vivado2025.2、通用 Keccak、SYNTHESIS 裁剪诊断、6.666667ns默认时序驱动、每次2线程。没有新增时序例外或关闭时序优化；本轮没有布线 STA，ATP使用150MHz假定频率。

本目录归档所选冻结 RTL、源码校验、hierarchical/timing/utilization 报告、综合日志、验证与锁步摘要、各候选补丁。每次候选另有自己的运行归档。详细 sim/validation 日志留在 build，不归档明细；不保存 README.md。后台异常综合保持运行，结果生成后补齐报告，不自动改换所选 RTL。
