# μHBS 独立执行与论文验证计划

> 状态：执行中；仅 `docs/Final_Gate_Report.md` 中显式标为 Pass 的证据可使用，未通过 Gate 不代表 RTL、PPA 或标准向量已完成。
> 版本：v0.3.0
> 直接对照：`references/papers/Unified_HBS_Architecture_2026_Reader`
> 核心边界：μHBS 必须能脱离 HashFlow 独立构建和运行；不引入通用 runtime；不由软件逐任务或逐 Hash 喂入。

## 1. 执行摘要

μHBS 将实现为一个独立的、微码驱动的 HBS 硬件引擎。软件在初始化阶段可以装载微码和 layout 表，在任务阶段只提交一条粗粒度 Job Descriptor，然后等待完成中断或输出流。

从 `START` 被接受到 Job 完成期间：

- 软件不提交 `task_type`、Hash descriptor 或中间对象；
- 软件不计算循环边界、ADRS 字段、TreeHash 合并顺序或 lane 分配；
- 硬件 Microsequencer 自主完成全部 Keygen、Sign 或 Verify 流程；
- 任务输入量为 `O(1)` 条 Job 命令，不随动态 Hash 数增长。

研究上的目标不是重复“三类 HBS 共享 Hash 核”，而是验证：

> 相对固定 11-task 和分层计数器控制，可加载、正交的微指令能否在保持接近性能的同时，把新流程的扩展从“修改控制 RTL”变为“更换微码镜像”，并通过 TreeHash 和跨阶段转发降低存储与数据移动。

### 1.1 当前执行检查点（2026-09-16）

已闭合的工程能力：

- 18 个算法无关 opcode 已固定；Microsequencer 已具备有界 loop/call、`LOAD/STORE/XOR/EMIT`、`TREE_PUSH` 和 fail-closed 请求/响应控制；
- descriptor-driven SHAKE composer 已由 `HASH_LAYOUT` 直接查询 128-bit layout；除连续 Scratchpad 模式外，组件模式可组合 literal/zero/register、双寄存器仿射 Scratchpad 段和 XOR，并在组件内部跨 rate block 续传；XMSS Sign JSON layout 0--7/9--10 已 lowering 为 10 layout/91 component，PRF/H_msg RTL 一条 Job 实测 376 cycles；同一通用组件路径已从一条 Job 锁存并装载两个 256-bit seed，执行完整 h=10 Keygen 树，3,426,304 次微码 `HASH_LAYOUT`、1,024 leaf、1,023 parent，自主 root 写回/EMIT，607,591,418 cycles，root/auth oracle 一致；
- 128-bit data descriptor、无 DSP 串行 AGU、Scratchpad `LOAD/STORE/XOR`、固定优先级仲裁和 `EMIT` 已连成单 Job 数据切片；
- 组合切片已由同一微程序完成 STORE、4次 TREE_PUSH 和 EMIT，data/TreeHash/EMIT 共享一个单端口 Scratchpad，对应 32/16/1 次交易；
- TreeHash h=2 的 4 个 leaf、3 个 parent、root 和 auth path 已使用 RFC 8391 XMSS-SHAKE256 randomized H 与独立 oracle 一致，ADRS treeHeight/treeIndex 由 RTL 从 merge context 派生；
- 离线 logical-slot→64-bit-word lowering 已冻结，v2 RTL data slice 已消费多寄存器 binding side table，以单 Job 完成 XMSS `R5+R7`→`R6+R3` affine STORE→EMIT，缺失 binding 与动态越界 fail-closed；
- XMSS 功能路径已由同一 Job 和 6 条静态微指令在 RTL 内生成 1,024 个完整 WOTS+ leaf（每叶 67 PRF_keygen、1,005 randomized F、66 L-tree parent），复用一个 4-word 叶缓冲后直接 `TREE_PUSH`；h=10 root 和 10 层 auth path 与 RFC 8391 oracle 一致，实测 57,204,676 cycles；
- FIPS 205 SLH-DSA-SHAKE-128f n=16 parent 已按 `SHAKE256(PK.seed||ADRS||left||right,16)` 的单调用语义通过独立向量；TreeHash fault/cancel 已能排空旧响应并在无全局 reset 下恢复下一 Job；
- LMS、XMSS Sign/Verify 和 SLH-DSA Keygen/Sign 模型继续满足单 Job、BUSY 期间零 task/Hash 输入，并与标准向量及逐 Hash trace 一致；
- SLH-DSA 完整 ACVP 轨迹已接入 RTL 周期标定：U2 SHAKE stream 实测 1/2/5 block 为 15/30/75 cycles，64-bit 输出无背压实测 1/2/3 word 为 3/6/9 cycles；当前单有效 lane Sign 已计入下界为 2,034,645 cycles（20.34645 ms@100 MHz），不冒充完整 RTL 总周期；
- 版本化 tree descriptor 已在同一 RTL elaboration 选择 h=2/h=3 `TREEHASH_MIN`，精确产生 root/auth；SUBTREE/FULL 在 cache 未接入前 fail-closed；受界 SHA-256 与 RFC 8554 LMS parent 通过独立向量；
- 当前 CI 仅构建μHBS原生 RTL；HashFlow 和 SLH-Flow 均不得成为源码、拷贝 RTL、构建或运行依赖；
- 四个受影响的 Artix-7 100 MHz post-route 点已重跑并刷新 manifest：Control 720 LUT/725 FF/1 RAMB36/WNS +0.921 ns，P1/U2 randomized-F 7,685 LUT/6,039 FF/2 RAMB36/WNS +0.568 ns，windowed P2/U2 20,204 LUT/11,294 FF/3 RAMB36/WNS +0.368 ns，raw-Job P2/U2 14,811 LUT/10,850 FF/1 RAMB36/WNS +0.788 ns。

仍未闭合，因此不得声称完整算法 RTL 或论文优越性：

- 将已连通的 h=10 WOTS/TreeHash 路径与 data/output 合入同一 XMSS Keygen/Sign 顶层，并接入 cache refill；
- 将已通过的 v2 data slice 和 descriptor-selected MIN TreeHash 接入同一个完整 XMSS/LMS 微码顶层；
- 将 RFC 8554 LMS parent 接入 TreeHash，并让 descriptor 的 parent layout/node size 选择真实 composer/hash lane；将 SUBTREE/FULL descriptor 接入 cache refill/miss 重算；
- 完成 OTS rate-wide 路径、完整 P2/U2 签名 replay、B1 同数据路 fixed-controller 消融和完整 BRAM–Sign-latency Pareto。
- 已连通原子 Job latch 与 payload-only message stream，不使用 DMA；下一步完成其余 expression/base-w/context、FORS/Hypertree 与输出路径，不拆解或引入外部算法 FSM。

## 2. 不可退让的系统契约

### C1. 与 HashFlow 完全解耦

μHBS 的正确性、构建、仿真和综合不得依赖 HashFlow：

- 代码中不得 `import` HashFlow Python 模块；
- Makefile/脚本不得 `cd ../HashFlow` 或读取其 build/raw 目录；
- RTL 不得通过相对路径引用 HashFlow RTL；
- 测试向量和 oracle 必须来自标准文档、独立参考实现或 μHBS 自己的确定性生成器；
- 产物、临时文件和缓存使用项目内独立路径，不与 HashFlow 共享可写目录；
- 删除、移动或不 checkout HashFlow 时，μHBS `make ci` 仍必须通过。

若复用现有 Keccak 核，必须将其作为μHBS 内部的、固定来源与许可证的 IP 导入，或者放入独立的只读 `third_party/` 边界；不允许直接链接 HashFlow 工作树。

### C2. 不设通用 runtime

项目不实现以下结构：

- descriptor dependency runtime；
- object-valid scoreboard；
- 通用 task queue 或 task admission；
- dynamic work stealing；
- QoS/priority scheduler；
- 按 Hash 保存的 recipe/object 图；
- 多 Job 动态依赖解析。

可以存在的控制结构只是单个微程序执行所必需的确定性状态：PC、Loop Stack、Call Stack、有界计数器、lane busy/done、存储冲突等待和异常状态。本计划统一称其为 **Microsequencer**，避免与通用 runtime 混淆。

### C3. 软件不逐步驱动算法

外部控制面只允许：

1. 复位和配置；
2. 在空闲期装载或切换微码/layout 镜像；
3. 提交一条 Job Descriptor；
4. 处理输出流或完成中断；
5. 查询状态和错误。

任务执行期间不存在 `task_valid/task_type`、`hash_descriptor_valid`或类似接口。当前设计直接锁存固定 Job 字段并以 payload-only stream 接收消息，不需要 DMA；数据接口不决定算法步骤。

### C4. 论文对照不以 HashFlow 为基线

主基线是 `A Unified Hardware Architecture for Stateful and Stateless Hash-Based Key/Signature Generations` 中的：

- 11 个参数化 task；
- 分层计数器控制；
- 双 Keccak-p[1600]、P=2、U=2；
- OTS 1088-bit 单周期快路与其他任务的64-bit灵活路；
- 整层 Merkle 存储和分段签名流。

HashFlow 可在同一仓库中同时运行，但不进入μHBS 的对照表、主张或验收依赖。

## 3. 范围与非目标

### 3.1 当前范围

- SHAKE256-based LMS、XMSS 和 SLH-DSA/SPHINCS+ 工作流；
- Keygen 与 Sign 作为直接论文对照；
- Verify 作为冻结 RTL 后的扩展性验证；
- 主对照配置为 P=2、U=2；P=1/2 与 U=1/2 用于消融；
- `FULL_CACHE`、`SUBTREE_CACHE` 和 `TREEHASH_MIN` 三种存储模式；
- 流式输出作为与对照论文相同的主语义。

### 3.2 本计划不做

- 通用 CPU/ASIP；
- 任意整数程序；
- 操作系统驱动、OpenSSL 集成或 Linux 调度；
- 通用多 Job runtime；
- 逐 Hash 的软件服务调用；
- 侧信道防护实现或密码模块认证；
- 未匹配算法版本、Hash 工作量和输出语义的跨论文性能比较。

## 4. 顶层执行模型

```text
Initialization, infrequent:
    host -> PROGRAM_LOAD(microcode, layouts, manifest)

Per operation, exactly one command:
    host -> JOB_SUBMIT(entry, operation, parameters,
                       message/key/output locations, state_handle)

Autonomous hardware execution:
    Job Latch
      -> Microsequencer
      -> Loop/Call Stack
      -> AGU + Structured ADRS
      -> Banked Composer / OTS Fast Path
      -> Hash Lane 0/1
      -> Feedback / TreeHash / Scratchpad
      -> Output Stream / Root
      -> DONE or ERROR

During BUSY:
    no task ingress
    no hash descriptor ingress
    no host-computed address/ADRS update
```

### 4.1 外部 Job Descriptor

```text
JobDescriptor {
    program_entry,
    operation,
    parameter_set,
    message_base,
    message_length,
    secret_key_base,
    public_key_base,
    output_base,
    state_handle,
    flags
}
```

Job Descriptor 不包含任务序列、展平 trace、Hash 预映像或由软件生成的中间节点。

### 4.2 微码与 layout 装载的边界

微码由离线 assembler/compiler 生成是允许的，因为它描述整个算法，不在任务执行期间逐步驱动硬件。

必须满足：

- 镜像只能在 engine idle 时写入；
- 镜像带版本、长度、参数范围和 digest；
- 任务开始后微码和 layout 必须锁定；
- 新 Job 只选择已验证的 entry，不上传逐 Job 指令流；
- 开发时使用可写 RAM，论文同时报告固定 ROM 映射点。

## 5. 微架构基线

### 5.1 Microsequencer

- 单一确定性 PC；
- 最多 6 层 Loop Stack；
- 最多 4 层 Call Stack；
- 有界条件，仅允许公开参数、循环计数器和 Base-w digit 决定循环上界；
- 不提供通用 ALU、通用寄存器文件或任意间接跳转；
- 单发射起步，只在有证据表明控制成为瓶颈时评估双发射。

### 5.2 基础微操作

基础操作保持算法无关：

```text
CALL / RET / JUMP
LOOP_SETUP / LOOP_END
ADDR_SET / ADDR_INC / ADDR_BIND
LOAD / STORE / MOVE / XOR
HASH_LAYOUT
TREE_PUSH / TREE_REDUCE / TREE_CAPTURE
EMIT / RETURN_ROOT
WAIT / BARRIER
```

允许受控融合：

- Hash 结果本地反馈；
- `LOAD + HASH + STORE`；
- `TREE_PUSH + TREE_REDUCE`；
- Hash 完成后更新 ADRS；
- OTS 连续链步在 lane 内重启；
- 当前根直接绑定下一阶段消息。

任何融合操作都必须有可逆展开语义，并通过融合前后差分验证。

### 5.3 Hash 和输入路径

主论文配置使用两个 Keccak-p[1600] U2 lane，与对照论文匹配。输入组合器使用混合设计：

- 通用 banked layout composer 处理可变长消息、树节点、domain 和 ADRS；
- OTS 热点保留一周期 rate-wide 发射能力；
- rate-wide 快路不以 `algorithm_id` 选择，而以 layout capability 选择；
- P=1/2、U=1/2 作为参数化综合点。

如果通用 composer 不能保持 OTS 单周期 rate 输入，则不得把性能差异归因于微码控制。

### 5.4 存储与 TreeHash

- banked Scratchpad 只保存当前 Job 的有界中间值；
- TreeHash Stack 保存 `(node, height, identity)`；
- 认证路径在节点生成时捕获；
- `TREEHASH_MIN` 不保存完整树层；
- `SUBTREE_CACHE` 使用固定大小子树缓存；
- `FULL_CACHE` 匹配对照论文的快速 LMS/XMSS 签名边界；
- 所有模式分别报告 Keygen/Sign cycles、峰值存储和 RAM 访问数。

### 5.5 静态双 lane 协作

本设计不使用 runtime scheduler。lane 协作由微程序和简单硬件状态实现：

- `lane_mask` 选择 lane 0/1；
- `WAIT_LANE`/`BARRIER` 完成确定性同步；
- 规则性并行循环用 loop counter 按奇偶或块分配；
- 链内反馈始终保留在同一 lane；
- 未解决的存储 bank 冲突使发射器停顿，不触发动态重排。

## 6. 计划目录与命令契约

```text
μHBS/
├── README.md
├── Execution_Plan.md
├── LICENSE
├── Makefile
├── docs/
│   ├── Architecture.md
│   ├── Micro_ISA.md
│   ├── Job_Interface.md
│   ├── Correctness_Contract.md
│   ├── Comparison_Protocol.md
│   └── Final_Gate_Report.md
├── manifests/
│   ├── source_manifest.yaml
│   ├── toolchain.json
│   ├── programs/
│   └── experiments/
├── model/
│   ├── reference/
│   ├── microcode_assembler/
│   ├── microcode_verifier/
│   └── cycle_model/
├── microcode/
│   ├── lms/
│   ├── xmss/
│   └── slh_dsa/
├── rtl/
│   ├── top/
│   ├── sequencer/
│   ├── agu/
│   ├── composer/
│   ├── hash_lane/
│   ├── treehash/
│   ├── memory/
│   ├── output/
│   └── state_manager/
├── tb/
│   ├── unit/
│   ├── integration/
│   └── formal/
├── tests/
│   ├── kat/
│   ├── differential/
│   └── negative/
├── experiments/
│   ├── raw/
│   ├── processed/
│   └── plots/
├── artifact/
└── third_party/
```

计划命令：

```bash
make test
make lint
make sim-lms
make sim-xmss
make sim-slh-dsa
make test-autonomous-job
make test-state-recovery
make synth-p1u1
make synth-p2u2
make compare-unified-hbs-paper
make check-standalone
make reproduce
make artifact
```

`make check-standalone` 必须静态检查路径依赖，并在不可见 HashFlow 目录的临时工作树中完成构建、单元测试和至少一个完整 RTL 回放。

## 7. 分阶段执行计划

每个阶段以证据 Gate 结束；前一 Gate 未通过时，不把后续模块的存在当作阶段完成。

### Phase 0：边界、标准与工作量审计

任务：

- 冻结 C1–C4 系统契约；
- 固定标准版本、参数集、消息、密钥、签名索引和计时边界；
- 独立审计对照论文的 SPHINCS+ 与最终 FIPS 205 SLH-DSA 差异；
- 分类统计 PRF、OTS、FORS、Merkle 和消息 Hash 次数；
- 记录 Hash 调用数、Keccak permutation 数和实际吸收 block 数；
- 将对照论文中 24,184 LUT、13,659 FF、16.5 BRAM、108 MHz 及各算法 cycles 冻结为“报告值”，不冒充同源重测。

产物：

- `docs/Correctness_Contract.md`；
- `docs/Comparison_Protocol.md`；
- `manifests/source_manifest.yaml`；
- 工作量审计 JSON 和表格。

Gate 0：

- 两边标准、参数和计时边界可对齐；
- 每个主对照点的 permutation 下界不与报告 cycles 矛盾；
- 无法对齐的点标记为非严格比较，不用于声称加速比。

### Phase 1：独立参考模型和微码执行模型

任务：

- 接入标准兼容的独立 oracle；
- 定义μHBS trace：`pc/opcode/loop/address/layout/hash_input/hash_output/tree_event`；
- 实现 assembler、镜像 manifest 和指令级解释器；
- 实现非法 opcode、越界循环、栈溢出、非法 layout 和非法存储访问拒绝；
- 首先生成 LM-OTS/LMS 的单 lane 微程序。

Gate 1：

- 解释器与独立 oracle 的 Hash 输入、输出和最终根逐项一致；
- 主 profile 的静态程序不超过 512 条基础微指令，或对超限给出结构原因；
- 运行所需外部命令严格为一条 Job Descriptor。

### Phase 2：单 lane 自主 RTL 垂直切片

任务：

- 实现 program store、fetch/decode、Loop/Call Stack 和异常终止；
- 实现 AGU、ADRS、banked composer 和单个 Keccak lane；
- 实现 Scratchpad 与本地 Hash feedback；
- 用一条 Job Descriptor 完成 LM-OTS/LMS 完整垂直切片；
- 记录 host 控制写入计数器，证明 BUSY 期间没有任务级输入。

Gate 2：

- RTL 与微码解释器逐 Hash trace 零 mismatch；
- `START`到`DONE` 之间 host task writes = 0；
- top-level RTL 不存在 task/Hash descriptor ingress；
- reset、stall、非法程序和存储越界测试通过。

### Phase 3：TreeHash 和存储模式

任务：

- 实现 TreeHash push/reduce/capture；
- 实现 `TREEHASH_MIN`、`SUBTREE_CACHE`、`FULL_CACHE`；
- 对每种模式记录峰值 bytes、逻辑/物理 BRAM、RAM access 和 cycles；
- 验证认证路径捕获、树根和异常清理；
- 防止把重计算引起的签名延迟隐藏在存储节省数据中。

Gate 3：

- 所有模式的根和认证路径零 mismatch；
- `TREEHASH_MIN` 的树工作集与树高线性增长；
- `FULL_CACHE` 与对照论文的快速 LMS/XMSS Sign 功能边界一致；
- 形成完整 BRAM—latency Pareto，不只报最省存储点。

### Phase 4：XMSS 与 SLH-DSA 微程序

任务：

- 在不增加算法专用 sequencer opcode 的前提下实现 XMSS；
- 实现 mask/XOR、L-tree、WOTS+、FORS 和 Hypertree 流程；
- 实现 FORS root、XMSS root 和 WOTS 公钥压缩的跨阶段转发；
- 用标准向量和独立 oracle 验证 Keygen/Sign；
- 固定每个算法的静态微码大小、最大循环深度和最大暂存使用。

Gate 4：

- LMS、XMSS、SLH-DSA 的目标 Keygen/Sign 通过；
- 新增算法时不修改 Microsequencer、Hash lane 或 top-level Job 接口；
- 任何不可避免的 RTL 变化被分类为通用 capability 扩展，且单独报告；
- 所有对照点先通过工作量审计再比较 cycles。

### Phase 5：P=2/U=2 和 OTS 快路

任务：

- 将 lane 扩展到 P=2，将 Keccak 固定为主对照 U=2；
- 保留与对照论文匹配的 OTS 单周期 rate-wide 输入；
- 用微程序静态分配可并行 leaf/node；
- 分离 Hash round、input compose、memory wait、barrier、lane idle 周期；
- 实现 P=1/2、U=1/2 消融，不实现动态 scheduler。

Gate 5：

- P=2/U=2 功能零 mismatch；
- 主 OTS 路径的输入稳态不低于对照边界；
- 微码 issue 气泡、双 lane 尾部空闲和 bank 冲突可分别计量；
- 完成与固定 task-controller 的同 Hash-core、同 HIL 控制器替换实验。

### Phase 6：冻结 RTL 后的扩展性试验

任务：

- 冻结 top-level、Microsequencer、AGU、composer、Hash lane、TreeHash 和存储接口；
- 在冻结点后加入 Verify 微程序；
- 再选择 HSS、XMSS-MT 或一个未参与设计的 held-out 参数集；
- 保存冻结 commit 和扩展后 diff；
- 统计新增 microcode/layout bytes、新增 RTL 模块数和接口变化数。

Gate 6：

- 新流程通过向量；
- 核心 RTL 修改模块数 = 0；
- 新增内容仅限微码、layout、manifest 和测试；
- 如果必须增加 opcode 或数据路，扩展性主张降级，不把该点记为 Pass。

### Phase 7：状态安全与系统边界

任务：

- 实现 LMS/XMSS `RESERVE -> PERSIST -> RELEASE -> CONSUMED`；
- 验证 cancel/reset 后索引烧毁、恢复单调、防回滚和耗尽拒绝；
- 实现密钥、微码临时值、Hash feedback 和 TreeHash 节点清零；
- 将状态协议延迟与普通签名 cycles 分开报告。

Gate 7：

- 持久化确认前不暴露可用签名索引；
- 已预留索引永不重用；
- 异常路径的敏感状态清零通过断言；
- 新增 State Manager 面积和延迟单独列出，不与对照论文的计算核面积混合归因。

### Phase 8：PPA、消融与论文 Gate

任务：

- 在 Artix-7 `xc7a200t` 上使用统一流程完成 P=1/2、U=1/2 实现；
- 如 Vivado 2018.3 可用，生成与对照论文同版本点；否则明确标记工具差异；
- 完成固定 task controller、展平微码、循环压缩微码和完整μHBS 的递进消融；
- 报告 LUT、FF、BRAM、DSP、Fmax/WNS、cycles、latency、ATP 和 throughput/area；
- 报告微码存储、峰值中间存储、RAM 读写、lane 利用率和数据移动；
- 保留全部失败点、时序不收敛点和性能 crossover。

Gate 8：

- 功能 Gate 全部通过；
- 至少一个存储模式形成相对对照的明确 Pareto 改善；
- P=2/U=2 性能差异可归因于控制和数据移动，而非 Hash 核或输入语义不同；
- 冻结 RTL 扩展试验通过；
- 根据事先冻结的阈值给出 Go/No-Go，不在测量后改口径。

## 8. 比较与消融矩阵

### 8.1 对照实现

| ID | 控制 | Hash/HIL | 存储 | 用途 |
|---|---|---|---|---|
| B0 | 论文报告的 11-task/分层计数器 | P2/U2、OTS-wide | 整层树 | 外部主对照 |
| B1 | 本地重建的 fixed-task controller | 与μHBS相同 | 与μHBS相同 | 控制器因果对照 |
| B2 | 展平μHBS微码 | 与μHBS相同 | 与μHBS相同 | 循环压缩消融 |
| B3 | 循环压缩μHBS，无 forwarding | 与μHBS相同 | 与μHBS相同 | 转发消融 |
| B4 | 循环压缩μHBS，无 TreeHash | 与μHBS相同 | FULL_CACHE | TreeHash 消融 |
| M | 完整μHBS | P2/U2 hybrid composer | 三种模式 | 主方法 |

B1 必须标记为“根据论文重建的同数据路基线”，不得冒充原作者 RTL。

### 8.2 工作负载

主文至少包含：

- 对照论文中 SPHINCS+ `n=128/192/256` Keygen/Sign；
- LMS `h=10, w=2/4` Keygen/Sign；
- XMSS `h=10, w=2/4` Keygen/Sign；
- 一个 Verify 流程和一个 held-out 参数集；
- LMS/XMSS Sign 使用固定 seed 的 1,000 个随机消息，报告 mean/P50/P95/max；
- 边界索引、空消息、跨 rate 消息、输出背压和 reset/cancel。

### 8.3 必报指标

```text
Correctness:
  KAT/oracle result, root/signature equality, per-Hash trace mismatch

Autonomy:
  job commands per operation, host writes while BUSY,
  externally supplied task/hash descriptors

Program:
  static instruction count/bytes, layout bytes, maximum loop/call depth,
  dynamic micro-ops, micro-ops per Hash

Performance:
  cycles, latency, Fmax/WNS, jobs/s, first-output latency,
  issue/input/round/memory/barrier/idle cycle breakdown

Area:
  LUT, FF, BRAM, DSP,
  sequencer/AGU/composer/hash/treehash/memory/output/state breakdown

Memory/data movement:
  peak logical bytes, physical BRAM,
  Scratchpad reads/writes, tree push/pop, forwarding hits,
  externally moved bytes and eliminated Hash calls

Extensibility:
  core RTL modules changed, interface changes,
  new microcode/layout bytes, bitstream rebuild required
```

## 9. 自动化验收

### 9.1 独立性检查

`make check-standalone` 应至少完成：

1. 拒绝源码和构建文件中的 `../HashFlow`、HashFlow Python import 和 HashFlow raw-artifact 路径；
2. 将μHBS复制到不包含 HashFlow 的临时目录；
3. 从干净状态执行 lint、unit tests 和完整 LMS RTL replay；
4. 检查所有输出都在μHBS本地 build/artifact 目录；
5. 输出依赖 manifest 和文件 digest。

### 9.2 与 HashFlow 并行运行检查

在 CI 中同时启动两个项目的测试，并检查：

- 无共享临时文件、固定端口或全局 lock；
- 无同名产物覆盖；
- 任意一侧失败不改变另一侧结果；
- μHBS 的 result manifest 不引用 HashFlow experiment ID。

并行检查只用于证明工程解耦，不将 HashFlow 性能写入μHBS 论文对照。

### 9.3 单 Job 自主执行检查

测试平台必须记录并断言：

```text
accepted_job_commands == 1
host_control_writes_during_busy == 0
external_task_descriptors == 0
external_hash_descriptors == 0
algorithm_result == independent_oracle_result
done XOR error eventually becomes true
```

主机在输出背压期间可以操作 `ready`，但不能提供任务决策或中间计算结果。

## 10. 论文证据契约

### 10.1 可争取的主张

1. μHBS 在一条粗粒度 Job 命令后自主执行完整 HBS 流程。
2. 微程序只在 IDLE 初始化阶段整幅加载或切换，Job 执行期间锁定；算法扩展不需要增加算法专用 task FSM。
3. 相对 fixed-task 基线，μHBS 以受控的 PPA/延迟代价换取更低的扩展成本。
4. TreeHash 与缓存模式形成可测量的存储—延迟 Pareto。
5. 跨阶段转发降低可归因的 RAM 访问或重复 Hash。

### 10.2 禁止主张

- 首次使用分层计数器或嵌套循环；
- 首次统一 LMS/XMSS/SLH-DSA；
- 微码天然比固定控制更小或更快；
- TreeHash 在不重计算时无条件保持快速状态签名；
- 不匹配 Hash 工作量、U/P、输入路径和输出语义的性能胜负；
- 已经达到侧信道安全、故障安全或认证要求。

### 10.3 建议预注册的 Go/No-Go 条件

数字阈值必须在 PPA 测量前冻结。建议初始条件为：

- 正确性：所有主 profile 零 mismatch；
- 自主性：每个操作恰好 1 条 Job 命令，BUSY 期间 0 条任务/Hash 命令；
- 解耦：无 HashFlow 时 `make ci` 通过；
- 扩展：冻结 RTL 后新增至少一个完整流程，核心 RTL 修改模块数为 0；
- 程序：主 profile 静态微码不超过 4 KiB，或在冻结前调整并说明理由；
- 性能：同 P2/U2/Hash/HIL 的主对照 cycles 不超过 fixed-task 基线的 1.15×；
- 面积：主对照模式的总 LUT 不超过 fixed-task 基线的 1.10×；
- 存储：至少一个可用模式相对 16.5 BRAM 减少不低于 50%，且不隐藏其延迟代价；
- 时序：post-route 通过冻结时钟目标，且不以 pre-synthesis 估计代替。

若只有“微码可运行”而没有扩展性证据，则作为工程原型保留，独立论文 No-Go。

## 11. 验证和可复现策略

### 11.1 功能验证

- 标准 KAT 和独立 oracle；
- 解释器—RTL 逐微指令差分；
- 逐 Hash 输入/输出差分；
- 根、认证路径和签名流差分；
- P=1/2、U=1/2 结果一致性；
- 不同存储模式结果一致性。

### 11.2 断言与负向测试

- Loop/Call Stack 不溢出、不下溢；
- PC 不越界；
- layout 和存储访问不越界；
- Scratchpad bank 冲突不导致错误读写；
- ADRS/domain 与标准 trace 一致；
- Hash 结果在最后一字节写回前不可见；
- cancel/error 不产生有效完成 token；
- 微码在 BUSY 期间不可修改；
- 状态索引不重用；
- 敏感状态在 reset、cancel、error 和正常退出时清零。

### 11.3 结果身份

每个结果必须绑定：

```text
experiment_id =
  micro_isa_version /
  program_digest /
  algorithm_profile_operation /
  P_U_memory_mode_input_mode /
  device_constraint_seed /
  source_commit_toolchain
```

raw 结果 append-only；processed 数据必须由脚本生成；图表必须可追溯到 raw manifest。

## 12. 主要风险和停止条件

| 风险 | 可观测症状 | 处理 | 停止/降级条件 |
|---|---|---|---|
| 微码 issue 气泡 | cycles/Hash 显著上升 | 融合反馈与自动 ADRS 更新 | P2/U2 仍 >1.15×基线则放弃高性能主张 |
| 通用 composer 拖慢 OTS | input cycles 主导 | 保留 layout-driven rate-wide 快路 | 无法匹配单周期 OTS 输入则不做速度胜负 |
| TreeHash 拖慢状态签名 | Sign 接近 Keygen 延迟 | 加入子树/完整缓存模式 | 只把 `MIN` 作为低存储点，不声称快速签名 |
| ISA 不足以表达新流程 | 冻结后必须加 opcode | 优先扩展通用数据操作 | 核心 RTL 改动则扩展性 Gate 失败 |
| 静态双 lane 利用不足 | barrier/idle 占比过高 | 重写微程序的规则分块 | 不引入 runtime scheduler，接受或披露边界 |
| 微码使校验边界变复杂 | 非法程序无法 fail-closed | 镜像白名单、静态 verifier、执行时 bounds | 不允许现场执行未验证镜像 |
| 原论文工作量不可复现 | Hash/permutation 计数不闭合 | 只报同工作量的本地 fixed-task 对照 | 外部报告值降为背景，不报直接 speedup |

## 13. 最终交付

工程交付：

- 独立可构建的 μHBS RTL；
- 独立 oracle、assembler、verifier 和 cycle model；
- LMS、XMSS、SLH-DSA 微码镜像；
- 单 Job 自主执行测试；
- P=1/2、U=1/2 的功能与 PPA 数据；
- 三种存储模式的 Pareto 结果；
- 冻结 RTL 后扩展实验；
- 一键复现工件和最终 Gate 报告。

论文主文的最短证据链：

1. 单 Job 命令后硬件自主完成整个算法；
2. 同 P2/U2/Hash/HIL 条件下微码控制的性能与 PPA 代价受控；
3. TreeHash/缓存模式形成更优的存储—延迟 Pareto；
4. 冻结 RTL 后仅增加微码即完成新流程；
5. 失败点和不可严格比较的边界明确保留。

## 14. 立即下一步

实施从 Phase 0 开始，不先写 RTL。第一个可合并产物应同时包含：

1. `Correctness_Contract.md`；
2. `Comparison_Protocol.md`；
3. 独立 source manifest；
4. 对照论文与μHBS目标参数的工作量审计；
5. `make check-standalone` 的最小骨架。

在 Gate 0 之前，不冻结“μHBS 比对照更快”或“程序不超过多少字节”一类结果型主张。
