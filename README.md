# mHBS — image 软件控制架构

本分支从 `main@05051299` 独立长出，使用已验证的 C1 软件链迁移作为功能基线；历史快照为 `39477f5`，重接分支后的快照为 `ba1b25a4`。固定 K1U1、一个物理 Hash 通道和单任务在途；默认 SHAKE，定义 `MHBS_SHA2` 选择 SHA2。

保留 `program + template + descriptor`，将完整 CHAIN 控制移到 program：链号和链步推进、签名捕获、端点存取、XMSS L-tree、LMS 列表及叶压缩均由显式指令决定。硬件只接受 HASH、TRANSFORM、EMIT 模板。C1 的复合 Hash 配方保留，包括 XMSS KEY/MASK 和 SHA2 HMAC/MGF1；本尝试只研究 CHAIN 控制归属。

程序 ROM 为 256×64 位，模板和描述符各为 32×64 位。布局修订版为 5，header 标识 `0x54`，与原 C1 布局不兼容。三个7位入口指向地址0/1/2跳板，跳板通过8位目标访问实际程序。CALL最多嵌套两层。具体字段和权限见 [Chain_Template_ISA.md](docs/Chain_Template_ISA.md)。

沿用128×256位工作区和窄上下文，不增加节点缓存或通用寄存器文件。旧显式 Hash 架构保存在 `image-old`；`image-chain`、`image-chain-tree` 保持独立。

## 参数和数据接口

- SHAKE：SLH-DSA 128f/s、192f/s、256f/s；XMSS h10/h16/h20；LMS h10/h15/h20。
- SHA2：SLH-DSA 128f/s，以及相同六组 XMSS/LMS 参数。
- XMSS n=32、w=16；LMS m=32、LMOTS w=4。配置名称只按树高命名，旧 omega 名称报错。
- XMSS/LMS Keygen 输出标准公钥，Sign 输出标准完整签名。Verify 接收拆分后的 R/C、链节点和认证节点；上游检查标准类型、签名长度及 q。
- 消息输入64位，节点及输出256位。SLH 消息1～87字节；XMSS/LMS 消息0～87字节。LMS C 使用 `job_randomizer`，q 持久化由上游负责。
- 三算法按 Job 互斥执行，每次复位执行一项 Job。Sign 完整重算认证路径，不使用 BDS。
- `SYNTHESIS` 裁剪调试端口和统计寄存器，不使用 `PROFILE_ENABLE`。签名缓存沿用 `MHBS_SIGNATURE_STORE` 宏。

## 生成与仿真

```sh
python3 -m model.vectors --profile slh_128f --hash shake
HASH_BACKEND=shake scripts/simulate_fast.sh slh_128f sign 1 1

python3 -m model.vectors --profile xmss_h10 --hash sha2
HASH_BACKEND=sha2 scripts/simulate_fast.sh xmss_h10 sign 1 1

SIM_SYNTHESIS=1 HASH_BACKEND=shake scripts/simulate_fast.sh slh_128f verify 1 1
```

镜像为每个操作目录下的 `program.mem`、`template.mem`、`descriptor.mem`；构建使用本分支的 `sources.txt`，不依赖父仓库。生成器检查容量和后端身份，不静默扩容。

h16／h15 本轮只执行真实高度 Verify；h20 完整 Keygen／Sign 继续停止。高树 Verify 使用独立构造的认证路径，不先生成完整树：

```sh
python3 -m model.vectors --profile xmss_h20 --hash shake --verify-only
HASH_BACKEND=shake scripts/simulate_fast.sh xmss_h20 verify 1 1
```

## 综合与实验

```sh
HASH_BACKEND=shake scripts/synthesize.sh 1 1
HASH_BACKEND=sha2 scripts/synthesize.sh 1 1
```

面积使用 `common`，不包含程序／模板／描述符 ROM 和签名缓存。实验使用 Vivado2025.2、`xc7a200tffg1156-3`、100MHz OOC、每任务2线程；不自动布局布线。100MHz ATP 是假定频率指标，综合时序不能当作布线频率证据。

[实验索引](docs/manifests/experiments/INDEX.md) 保存各次冻结源码、镜像校验、验证摘要、分层面积和时序报告。程序有效字数、模板记录数、描述符记录数与动态指令数分别统计。验收要求 CHAIN 控制完全来自程序，且密码学工作量与冻结 C1 一致；不预设面积、周期或 ATP 排序。

## 软件控制优化

当前候选保持 layout5 和全部镜像逐字不变。算术、分支、CALL/RET、WMOV 在执行边沿完成握手；RAM 与输入输出仍等待真实完成。窄上下文用两个共享读取网络，节点 LOAD/INPUT/WMOV 共用写数据选择器。SHAKE固定块按已有one-hot配方选择直接拼接，避免重复编码和译码；密码学配方不变。

候选及逐阶段证据见 [image 优化报告](docs/manifests/experiments/image_optimization_20261021_182828/reports/Image_Optimization.md)。本次冻结源码的56项整核、55项附加检查和两后端100MHz共同核综合均已通过。SHAKE为16,319 LUT / 5,845 FF，SHA2为14,588 LUT / 7,133 FF；按假定100MHz，六项目标Sign ATP均下降。不报告实际Fmax。
