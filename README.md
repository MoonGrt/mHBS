# mHBS v4.2：SLH 共同核、参数 Job 与外部消息

本仓库从原 `Vivado/idea/slh-dsa-acceleration/projects/μHBS` 项目独立复制而来，原仓库提交为 `1bf8007917e67ab318385102f78cf9ce971928a2`，对应的项目子树提交为 `3e0f1408e50020f319a908948fb691c12292a91b`。保留项目 Git 历史、当前工作树和历史构建证据；论文复现所需资料在本仓库的 `references/papers/`。当前 RTL 模块及微码文件统一使用 `mhbs` 名称。历史构建证据保留当时的命名及哈希，以便原样复现。

支持 **SLH-DSA SHAKE 128f、192f、256f**。唯一生产顶层 `mhbs_top` 保留高有效同步 `rst`，复位后自动执行一次 Keygen 或 Sign，然后停机。

Job 通过五个 256 位参数 `SECRET_SEED / SECRET_PRF / PUBLIC_SEED / RANDOMIZER / PUBLIC_ROOT` 提供；`OPERATION=0/1` 选择 Keygen/Sign。
消息使用 **64 位 message_data + valid/ready** 外部输入，长度由 `message_length[6:0]` 输入给出（Keygen 为 0，Sign 为 1–87）。低字节先传，尾拍多余字节忽略。Sign 的公钥根须预先配置，结果流无背压。

保留 HASH / CHAIN / TREE / TRANSFORM / EMIT 五类宏指令、RUN/LOOP、U2 和两个 Hash lane。
物理格式为 **`slh64_v4.2`，布局修订 3**，宏语义沿用 ABI 4：program **32×64** 只存指令；template **16×64**；descriptor **32×64、双读**。
三个独立数组使用 `$readmemh`；每个参数点的一组镜像含 Keygen/Sign 两个入口，Job 和消息已移出 program。

`mhbs_processor.sv` 已删除，启动控制并入顶层。构建时从顶层自动提取“启动控制＋执行核”作为共同综合区域，六种参数外壳链接同一网表。共同核受保护，外层常量连接允许不同。
本轮分别测量共同核和完整顶层的 post-synth 资源，**没有新接口的 post-route 频率**。

## 使用与验证

```bash
make compile-microcode rtl-unit-test
make rtl-all-profiles TAG=my_external
make rtl-verification TAG=my_external
make synth-common TAG=my_external
make report-v42 reproduce-v42
```

单点仿真：`make rtl-profile-test TAG=my_external PROFILE=slh_192f OPERATION=sign`。
PPA 验收需要先完成同一源码的六组正常仿真、扩展验证及单元验证。捕获源码后修改文件需使用新候选名。

旧布局转换：

```bash
python3 scripts/convert_v42_external.py <旧布局2镜像目录> <新输出目录>
```

输出三份布局 3 镜像，以及分离的 `job.json`、`message.mem`。

## 文档与证据

- [当前接口、实测资源和复现说明](docs/v4.2/External_Job_Message_Interface.md)
- [历史布局2架构](docs/v4.2/Architecture_and_Image.md)
- [历史v4.2布线结果与论文对照](docs/v4.2/Optimization_and_Paper_Comparison.md)
- 当前证据：`manifests/experiments/unified_hbs_v4.2/external_job_message/`
- 当前构建：`build/v4.2/external_job_message/`
- 生产 RTL 清单：`manifests/v42_sources.txt`

历史提交 **366b614** 的 7,249 Slice、101.010101 MHz 属于旧接口的已布线结果。
历史 V3/V4/v4.1、XMSS/LMS 和未完成 U4 候选保留，可用 `make reproduce-slh-only reproduce-paper-comparison` 核验。
