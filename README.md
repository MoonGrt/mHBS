# mHBS — image-chain 模板架构

本分支以 `main@050512998fea28cc44667a1cd694d5ad5077767c` 的 `program + template + descriptor` 架构为基础，固定 K1U1、单物理 Hash 通道、单任务在途。默认 SHAKE；定义 `MHBS_SHA2` 选择 SHA2。硬件只包含所选后端。

| 分支 | 控制粒度 | Program / Template / Descriptor 容量（64位字） |
|---|---|---|
| image | image 显式控制 Hash、链和树 | 512 / 0 / 32 |
| image-chain | template 执行整组 CHAIN，program 控制主树及 FORS 树 | 128 / 32 / 32 |
| image-chain-tree | main 的 CHAIN＋TREE 模板架构 | 16 / 16 / 32 |

CHAIN 包含整组 WOTS／LMOTS、端点归约、XMSS L-tree 和叶压缩。主树和 FORS 树的叶遍历、父 Hash、树栈、认证路径均由 program 的显式指令控制，硬件没有 TREE 操作。控制器复用128×256位工作区，不增加通用寄存器文件或第二个节点银行。

本分支使用独立的模板控制镜像版本，header 标识为 `0x53`。它不是历史 HashFlow ABI3／ABI4 的 opcode36／37 镜像；旧镜像与 main TREE 镜像均不得混用。具体编码、权限及故障语义见 [Chain_Template_ISA.md](docs/Chain_Template_ISA.md)。历史尝试保留在 Git 和原实验目录中。

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

[实验索引](docs/manifests/experiments/INDEX.md) 保存各次冻结源码、镜像校验、验证摘要、分层面积和时序报告。程序有效字数、模板记录数、描述符记录数与动态宏调用次数分别统计；TREE 子 CHAIN 与 program 直接 CHAIN 不混计。
