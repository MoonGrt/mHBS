# image-chain-tree：program＋template＋descriptor

本分支采用本仓库 `main` 提交 `050512998fea28cc44667a1cd694d5ad5077767c` 的真实三层镜像架构。此前没有 template ROM 的 ABI4 移植属于失败尝试，保存在 `e241611` 及历史实验中，其面积和周期不作为当前实现的验收证据。

本轮固定 **K1U1、单物理 Hash 通道、单宏任务在途**。program 选择 template，template 选择 HASH、CHAIN、TREE、TRANSFORM、EMIT 和 descriptor。CHAIN 执行整组 WOTS/LMOTS 链及叶构造（包括 XMSS L-tree）；TREE 调用 CHAIN 并完成一棵 FORS/Merkle 树和认证路径。SLH Sign 的主程序可以没有直接 CHAIN 调用，TREE 内仍执行子 CHAIN。

| 镜像 | 容量 | 接口 |
|---|---:|---|
| program.mem | 16×64 位 | 4位地址 |
| template.mem | 16×64 位 | 4位地址 |
| descriptor.mem | 32×64 位 | 两个5位异步地址 |

SHAKE 支持六组 SLH-DSA，以及 `xmss_h10/h16/h20`、`lms_h10/h15/h20`。SHA2 支持 SLH-DSA 128f/128s，以及同组 XMSS/LMS；由 `MHBS_SHA2`、`HASH_BACKEND=sha2` 和软件 `--hash sha2` 选择，默认 SHAKE。XMSS n=32/w=16；LMS m=32/LMOTS w=4；均67条链、最多15步。旧 omega 名称报错。

XMSS/LMS Keygen 输出标准68/56字节公钥，Sign 输出标准完整签名；SLH 保留 main internal 接口。Verify 输入是通过软件检查标准类型、长度和 q 后拆分的节点。消息 SLH 为1～87字节，XMSS/LMS为0～87字节。LMS C 通过 `job_randomizer` 输入。每次复位执行一个 Job，索引持久化由上游管理。

```bash
bash scripts/simulate_fast.sh slh_128f sign 1 1
HASH_BACKEND=sha2 bash scripts/simulate_fast.sh xmss_h10 verify 1 1
SIM_HASH_TRACE=1 bash scripts/simulate_fast.sh lms_h10 sign 1 1
SIM_SYNTHESIS=1 bash scripts/simulate_fast.sh slh_128f verify 1 1
python3 -m model.vectors --profile xmss_h20 --verify-only --output build/verify_vectors
VECTORS_DIR=build/verify_vectors bash scripts/simulate_fast.sh xmss_h20 verify 1 1
python3 scripts/run_hash_backends.py --launch
HASH_BACKEND=shake bash scripts/synthesize.sh 1 1
```

生成器默认只生成六组 SLH 和 XMSS/LMS h10 完整三操作；高树使用 `--verify-only` 构造真实高度认证路径。**本轮不运行 h16/h15/h20 完整 Keygen/Sign**，h20 完整树保持停止。默认44项为 SHAKE28＋SHA2 16：低树完整三操作加各后端四组高树 Verify。独立 C 参考首次构建需 GCC、Git、OpenSSL；快速仿真的常数空间 Hash 轨迹指纹也链接 libcrypto。

统计与 error_code 等诊断由 `SYNTHESIS` 裁剪，生产接口不含这些端口。`MHBS_SIGNATURE_STORE` 控制 top 的签名缓存；common 面积不含 ROM 与签名缓存。脚本默认100MHz OOC综合，不自动布线；ATP只标为假定100MHz。报告、冻结RTL、ROM身份、源码校验和综合证据位于 [实验索引](docs/manifests/experiments/INDEX.md)，仿真明细留在 build。
