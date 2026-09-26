# μHBS v4.2：SLH 共同硬件与独立操作

支持 **SLH-DSA SHAKE 128f、192f、256f**。三个参数点及 Keygen/Sign 共用一套硬件；
唯一生产顶层 `uhbs_top` 输入仅 `clk`、高有效 `rst`，复位后装载输入，执行镜像选择的一项操作，然后停机。
Sign 镜像提供公钥根，不依赖前一次 Keygen 的内部状态。结果流无背压。

保留 HASH / CHAIN / TREE / TRANSFORM / EMIT 五类宏指令及 RUN/LOOP。
微码决定操作顺序，宏内部使用 U2、两个 Hash 上下文。
物理格式为 **`slh64_v4.2`（布局修订 2）**，沿用 ABI 4 宏语义；旧镜像不能直接装载。
program 64×64、template 16×64、descriptor 32×64，保持三个独立数据结构。
格式和引用在离线工具中验证，硬件不扫描校验镜像。

三个数组直接使用 `$readmemh`。执行核独立综合，ROM 使用算法无关构建数据完成推断，
每个候选只综合、布线一次，随后替换六套 INIT 并核验单元、连接、布局、布线和资源一致。
实际镜像不会常量传播到执行核形成专用设计。

## 构建和验证

以下命令使用同一个新候选名；不要在捕获源码后修改文件再复用该名称。

```bash
make compile-microcode                    # 六组软件执行、独立参考/KAT、离线格式检查
make rtl-unit-test                        # Icarus 12
make rtl-all-profiles TAG=my_v42           # 六组独立运行，Verilator 5.008
make rtl-verification TAG=my_v42           # 根转交、交换、复位、消息、故障和微码轨迹
make synth-common TAG=my_v42
make route-common TAG=my_v42
make freeze-common TAG=my_v42
python3 scripts/finalize_v42.py my_v42_route --verification-tag my_v42
make report-v42 reproduce-v42
```

单点仿真可用 `make rtl-profile-test TAG=my_v42 PROFILE=slh_192f OPERATION=sign`。
单点结果不能代替整机 PPA 所需的完整六组结果；正式候选先运行 `rtl-all-profiles`。
构建与仿真产物位于 `build/v4.2/`，生产 RTL 清单为 `manifests/v42_sources.txt`。

## 结果与复现

- [v4.2 架构及镜像](docs/v4.2/Architecture_and_Image.md)
- [v4.2 优化结果与论文对照](docs/v4.2/Optimization_and_Paper_Comparison.md)
- `manifests/experiments/unified_hbs_v4.2/`：软件门禁、六组镜像、候选源码快照及 PPA 证据。
- `make reproduce-v42`：核对来源、面积/ATP 计算、冻结证据及最终验收；没有完成验收时会报未完成。

选择以签名 ATP 为主、面积为次。最终要求三个 Sign ATP 均优于指定 v4.1 已布线基线，
论文作为 NON_STRICT 对照，不作为本轮硬门槛。Boot 与操作周期分列；独立 Sign 的公钥根为外部预置输入。
综合归一化结果、功能通过与布线性能通过分别标记。

历史 XMSS/LMS、七点共同核、V3/V4/v4.1 报告与未完成 U4 候选保留，使用封存源码复现。

```bash
make reproduce-slh-only reproduce-paper-comparison
```
