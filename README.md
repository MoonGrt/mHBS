# μHBS：统一 token / template / descriptor 执行核

当前实现使用 ABI 4。SLH-DSA、XMSS、LMS 的固定 Job 顶层都实例化同一个
`uhbs_hbs` RTL 核，分别静态综合。一次 `start` 执行 Keygen、接收一条消息，
然后执行一次 Sign。XMSS/LMS 在外部确认索引持久化之前不输出签名。

支持 `slh_128f`、`slh_192f`、`slh_256f`、`xmss_omega2`、`xmss_omega4`、
`lms_omega2`、`lms_omega4`。omega 是每个 Winternitz 数字的位数。LMS 延续
SHAKE256/256 研究 profile。结果流直接输出片段，以 `out_keep` 指明有效字节。

```bash
make rtl-profile-test PROFILE=slh_192f
make rtl-verification             # 全七点、单/双 lane、交换、背压、索引边界
make synth-profile PROFILE=lms_omega2
make route-profile PROFILE=lms_omega2
```

新实验记录位于 `manifests/experiments/unified_hbs_v4/`。通过软件 gate 后才能生成
新镜像；每个 PPA 候选保存独立源码快照，并绑定完整算法仿真的源码/镜像哈希。
历史三个入口仍分别映射 128f、XMSS omega=4、LMS omega=4。

## 目录

- `model/unified_hbs.py`：五宏微码的软件执行模型；`model/reference/` 是独立算法模型。
- `rtl/`：当前统一核、Hash lane、镜像及七个固定参数产品顶层。
- `tb/`、`tests/`：当前 Icarus 单元、Verilator 完整周期和软件 KAT 测试。
- `experiments/`：当前综合、布线与最终时钟检查的 Vivado 脚本。
- `manifests/experiments/unified_hbs_V3/`：U2 原始验证和 PPA 证据；三组未完成的 U4 候选完整保留。
- `manifests/experiments/unified_hbs_final.json`：历史三个 U2 产品的选取结果。
- `manifests/experiments/unified_hbs_v4/final.json`：当前七点验收结果；同目录保存软件、仿真、实现与复现证据。

历史架构、试验脚本和测试已从工作树移除，可在 Git 历史中查看。

## 复现

```bash
make compile-microcode             # 软件 gate，重新生成镜像、向量和固定 Job 顶层
make rtl-unit-test                 # Icarus Verilog 12.0
make rtl-slh-dsa-test              # Verilator 5.008 --binary --timing
make rtl-xmss-test
make rtl-lms-test
make reproduce-paper-comparison    # 核对历史三点与当前七点的原始证据和门槛
python3 scripts/replay_profile.py slh_192f --run rtl-profile-test
```

完整算法压力场景可在各 `rtl-*-test` 命令后添加 `SWAP=1 BACKPRESSURE=1`。
当前 `make test` 只执行统一核的软件和 RTL 契约测试。重跑完整 PPA 的综合、布线、
时钟核查步骤见 [结果说明](docs/Unified_HBS_Results.md)；论文取数、比较限制及
每项数据见 [论文对比报告](docs/Unified_HBS_Paper_Comparison.md)。

历史 ABI 3 post-route 签名 ATP（SLH-DSA / XMSS / LMS）为 **48,225.754 /
888.939 / 373.916 Slice·ms**，均低于约定的论文数值门槛。
这些是 `xc7a200tffg1156-3` 上的 OOC 内部时序结果；跨实现比较为 NON_STRICT。

进一步参见 [架构](docs/Architecture.md)、[镜像 ABI](docs/Unified_HBS_ABI.md)、
[固定 Job 接口](docs/Job_Interface.md)和[微码影响 RTL 的解释](docs/Why_Microcode_Affects_Hardware.md)。
