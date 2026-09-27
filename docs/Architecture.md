# mHBS 当前生产架构

生产源码以 `manifests/v42_sources.txt` 为准；`manifests/unified_sources.txt` 是内容相同的兼容清单。当前仅支持 SLH-DSA SHAKE 128f、192f、256f 的 Keygen/Sign，唯一顶层为 `mhbs_top`。验证入口见 [Verification.md](Verification.md)，端口协议见 [Job_Interface.md](Job_Interface.md)。

## 执行路径

```text
mhbs_top：三组镜像 ROM、启动控制、固定 Job 参数、外部消息
  └─ mhbs_hbs：宏操作调度、树归约、消息缓冲、结果输出
      ├─ mhbs_program_sequencer：RUN / LOOP → 单个待完成宏指令
      ├─ mhbs_value_store / mhbs_root_store：链端点与 FORS 根
      └─ 两个 mhbs_recipe_lane：Hash 输入构造与局部链反馈
          └─ mhbs_compact_shake_context_lane：SHAKE 状态与吸收控制
              └─ mhbs_keccak：默认每拍展开两轮（U2）
```

五类宏操作为 HASH、CHAIN、TREE、TRANSFORM、EMIT。Sequencer 等待当前宏操作完成后才提交下一条；双 lane 并行位于宏操作内部。逻辑 lane 0 支持完整 recipe 集，逻辑 lane 1 主要执行链计算；`SWAP_PHYSICAL_LANES` 可交换物理位置，逻辑能力不变。

核使用 256 位节点存储，由 descriptor 中的 profile 编码选择有效的 16/24/32 字节。链端点存储深度为 68；树栈和认证路径各为 16 个节点。消息缓冲上限为 87 字节。

## 镜像与启动

物理格式为 `slh64_v4.2`、布局修订 3，沿用 ABI 4 宏语义：

| 镜像 | 逻辑容量 | 用途 |
|---|---:|---|
| program | 32 × 64 bit | RUN / LOOP 等控制指令 |
| template | 16 × 64 bit | 宏指令模板 |
| descriptor | 32 × 64 bit，双读 | 参数集、入口、输出长度及 recipe |

三组独立数组通过 `$readmemh` 初始化，共 640 字节逻辑容量。每个参数集的一组镜像同时包含 Keygen 和 Sign 入口；Job 与消息不放在程序镜像中。软件 `model/slh64_external.py` 负责镜像边界和字段检查，硬件按可信、不可变镜像执行，不做完整镜像扫描。

顶层同步复位后依次读取 header 与 profile，释放执行核，再提交一次 Job。Boot 计数为两拍；它不等于从复位释放到 Job 开始的全部控制开销。操作完成或失败后顶层停机，下次操作需要再次复位。

## 共同核综合

`scripts/v42_common_partition.py` 从顶层标记区域提取启动控制和执行核，生成构建用的 `mhbs_common`。Job、消息和 ROM 数据成为该区域输入，内部连接保持不变。共同区域综合一次，六个参数外壳分别链接同一网表；验收检查内部结构指纹、ROM 初始化映射以及提取前后的完整 RTL 输出和周期一致性。

支持共同核 post-synth 流程，以及六个参数外壳分别进行的布局布线。`route-common` 完成布线和验收，`freeze-common` 封存已验收的结果。频率口径为 OOC 核内寄存器间路径，核内同步控制参与检查，外部输入/输出路径排除。0 ns 外部输入假设下的端口 hold 违例单独保留，接口尚未时序签核。资源或频率结论绑定实际测量的源码快照，最新结果见 [Current_PPA.md](v4.2/Current_PPA.md)。

## K2U2 数据通路裁剪

当前生产核要求 `LANES=2, UNROLL=2`，任务数组、掩码及输出控制按双通道构建；保留物理 lane 交换验证。配方形状和长度解码受各 lane 的 `RECIPE_MASK` 静态约束，链专用 lane 不构建流式输入路径。SLH 普通链复用 sponge 保留的摘要，普通链和 compact chain 共用 sponge capture 寄存器；请求字段仍保持到响应握手，不增加流水级。旧 masked 配方仅在模块参数允许它时保留跨中间哈希的值寄存器，不进入生产网表。

统计开关沿 top/common/core/lane 传递，生产综合关闭，仿真保留。综合阶段检查实际网表，禁止统计寄存器和被替代的重复值/capture 寄存器残留。
