# mHBS v4.2：SLH 共同核、参数 Job 与外部消息

本仓库从原 `Vivado/idea/slh-dsa-acceleration/projects/μHBS` 项目独立复制而来，原仓库提交为 `1bf8007917e67ab318385102f78cf9ce971928a2`，对应的项目子树提交为 `3e0f1408e50020f319a908948fb691c12292a91b`。保留项目 Git 历史、当前源码和最新实验原始证据；论文复现所需资料在本仓库的 `docs/references/papers/`。当前 RTL 模块及微码文件统一使用 `mhbs` 名称。过时构建输出与旧报告已精简，历史源码和已提交资料可从 Git 恢复。

支持 **SLH-DSA SHAKE 128f、192f、256f、128s、192s、256s**。唯一生产顶层 `mhbs_top` 保留高有效同步 `rst`，复位后自动执行一次 Keygen、Sign 或 Verify，然后停机。

Job 通过五个 256 位参数 `SECRET_SEED / SECRET_PRF / PUBLIC_SEED / RANDOMIZER / PUBLIC_ROOT` 提供；`OPERATION=0/1/2` 选择 Keygen/Sign/Verify。
消息使用 **64 位 message_data + valid/ready** 外部输入，长度由 `message_length[6:0]` 输入给出（Keygen 为 0，Sign/Verify 为 1–87）。低字节先传，尾拍多余字节忽略。Sign/Verify 的公钥根须预先配置，结果流无背压。Verify 使用外部节点 `verify_data[255:0] + valid/ready`，完成时读取 `verify_pass`，不使用签名字节流解析器。接口与实测见 [Verify 节点扩展](docs/v4.2/Verify_Nodes.md)。

保留 HASH / CHAIN / TREE / TRANSFORM / EMIT 五类宏指令、RUN/LOOP、U2 和两个 Hash lane。
物理格式为 **`slh64_v4.2`，布局修订 3**，宏语义沿用 ABI 4：program **16×64** 只存指令；template **16×64**；descriptor **32×64、双读**。
三个独立数组使用 `$readmemh`；每个参数点的一组镜像含 Keygen/Sign 两个入口，Job 和消息已移出 program。

`mhbs_processor.sv` 已删除，启动控制并入顶层。构建时从顶层自动提取“启动控制＋执行核”作为共同综合区域，十二种 Keygen/Sign 参数外壳链接同一网表。共同核受保护，外层常量连接允许不同。
共同核与完整顶层分别测量 post-synth 资源；十二个 Keygen/Sign 参数外壳分别布局布线，最终频率按 OOC 核内寄存器间时序统计，外部接口时序单列。当前六参数扩展与面积见 [s 参数扩展](docs/v4.2/S_Parameters.md)；独立 K/U 历史测量见 [K/U Sign ATP 报告](docs/v4.2/KU_Sign_ATP_151_112_67_48.md)。

## 使用与验证

```bash
make test TAG=my_external       # 模型、契约、lint、单元、十二组 RTL
make verify TAG=my_external     # 完整验收，包含 test + 扩展与共同核验证
make synth-common TAG=my_external
make route-common TAG=my_external
make report-v42 reproduce-v42
```

仿真依赖 Python 3.12、GNU Make、Icarus Verilog、Verilator 和 C++ 编译器，**不需要 Vivado**；只有综合需要 Vivado。完整流程与证据说明见 [验证指南](docs/Verification.md)。

单点仿真：`make rtl-profile-test TAG=my_external PROFILE=slh_192f OPERATION=sign`。
PPA 验收需要先完成同一源码的六组正常仿真、扩展验证及单元验证。捕获源码后修改文件需使用新候选名。

旧布局转换：

```bash
python3 scripts/convert_v42_external.py <旧布局2镜像目录> <新输出目录>
```

输出三份布局 3 镜像，以及分离的 `job.json`、`message.mem`。

## 文档与证据

- [当前架构](docs/Architecture.md)
- [当前 Job 与流接口](docs/Job_Interface.md)
- [构建与完整验证](docs/Verification.md)
- [封存候选的接口、实测资源和复现说明](docs/v4.2/External_Job_Message_Interface.md)
- [历史布局2架构](docs/v4.2/Architecture_and_Image.md)
- [最新 K/U Sign ATP 报告](docs/v4.2/KU_Sign_ATP_151_112_67_48.md)
- [KU 原始证据与实验源码归档](manifests/experiments/ku_sign_latest/README.md)
- 当前证据：`manifests/experiments/unified_hbs_v4.2/external_job_message/`
- 当前构建：`build/v4.2/external_job_message/`
- 生产 RTL 清单：`manifests/v42_sources.txt`

历史提交 **366b614** 的 7,249 Slice、101.010101 MHz 属于旧接口的已布线结果。
历史候选与旧汇总报告已清理，旧版复现需先从 Git 恢复对应版本。`make reproduce-v42` 核验保留的生产 Program16 证据；`make reproduce-ku` 校验最新 KU 独立归档。

当前输出采用 256 位节点拍：`out_valid` 有效时接收 `out_data` 的低 `out_bytes` 个字节（16/24/32），`done` 标记整项结束；无输出反压、out_keep 或 out_last。测试端仍逐字节检查完整 SK/PK/签名和精确总长度。原 64 位输出波形及周期属于历史版本。

## 精简后的数据管理

- 最新汇总仅保留 `docs/v4.2/KU_Sign_ATP_151_112_67_48.*` 与配套 `_Timing.csv`；接口、架构和验证规范继续保留。
- KU 原始综合/分层/时序报告、日志、36 组 Sign 结果、源码快照、镜像与向量均封存在 `manifests/experiments/ku_sign_latest/`。
- `python3 scripts/report_ku_sign_atp.py` 默认读取此归档，无需 `build/`，不会启动 Vivado。
- 根目录 `build/` 本次未删除；其中工作树的修改已保存为补丁和源码包。以后删除该目录会丢弃 DCP 和内存外的运行检查点，重新做布局布线需从源码综合。删除后可运行 `git worktree prune` 清理失效登记。
- 清理明细：`manifests/experiments/ku_sign_latest/cleanup_manifest.json`。未改写历史、未提交或推送。

## 当前源码范围

- `rtl/` 只保留 `manifests/v42_sources.txt` 中的 8 个生产模块；已删除旧 scoreboard、独立 ROM、状态管理、ring Keccak 和旧微码目录。
- 当前 Program16 镜像位于 `manifests/experiments/unified_hbs_v4.2/external_job_message/images/`，由 `make compile-microcode` 生成。
- `scripts/` 保留当前编译、仿真、综合、布线、验收及最新 KU 报告工具；旧七参数和历史版本流程已删除。
- `tb/` 保留当前 Keygen/Sign/Verify 集成测试、协议/存储/Hash 单元及三个 SLH lane 向量。
- `tests/slh_fixtures.py` 提供当前 KAT 输入和 Hash 轨迹观察器；旧 XMSS/LMS、自主调度测试及其参考模型已删除。
- `model/unified_hbs.py`、`static_task_microcode.py`、`profiles.py` 和 `slh64.py` 仍被当前镜像编译器调用，因此保留。历史命名不等于闲置代码。
- 源文件删除清单见 `manifests/source_cleanup.json`；KU 原始封存源码和实验报告保持完整。
