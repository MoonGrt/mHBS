# mHBS — image-chain

本分支从 `050512998fea28cc44667a1cd694d5ad5077767c` 直接分出，移植源 HashFlow 提交 `db6594602ee2f7c58c7118f3d500ccb4f799d93b`。生产实现覆盖回本仓库原有命名和目录；运行、生成镜像及验证不依赖父仓库。

固定 **K1U1、一个物理 Hash 通道、一个 Hash 在途**。执行源 **ABI3**：image 选择每条链并控制树遍历、合并、认证路径和输出；阻塞 `CHAIN` 只执行选中的一条 WOTS 链，包括 PRF、至多15步F及截取。普通 `HASH/WAIT` 一次执行一个 SHAKE256 Hash。

只支持源节点已有的六组 **SLH-DSA-SHAKE 128f/128s、192f/192s、256f/256s**，全部支持 Keygen、Sign、Verify。此分支不含 XMSS、LMS、SHA2、P/U 流水或 ABI5。它们保留在历史 Git 分支中。

## 结构与兼容性

| 现有文件 | 职责 |
|---|---|
| `rtl/executor/executor.sv` | ABI3取指、类型化执行、单链宏及128×256单读单写节点RAM |
| `rtl/hash/shake-recipe.sv` | 单次SHAKE配方及私有 `shake_context` |
| `rtl/top/common.sv` | 外部程序/descriptor、Job及启动逻辑；共同核综合顶层 |
| `rtl/top/top.sv` | 程序/descriptor ROM和可选签名缓存 |
| `model/microcode.py`、`mHBS.py`、`executor.py` | ISA、镜像生成器和逐指令VM |

`sources.txt` 是唯一生产源码列表。仅规范模块标识符、路径和文件组合；保留源端口、32位统计、`PROFILE_ENABLE`、存储及逻辑，不在移植中优化。共同核不包含程序ROM或签名缓存。

program 为512×64位同步一拍ROM；descriptor为32×64位异步ROM；无template。六组源镜像位于 `tb/vectors/<profile>/`，12个mem文件与源提交逐字一致；重新生成也必须一致。ABI1/2/4/5镜像均拒绝执行。

接口沿用源合同：Job输入在整个操作保持稳定；64位消息、256位节点与输出，Sign/Verify消息1～87字节，每次复位执行一项Job。[ABI与单链宏](docs/ABI.md)、[完整指令表](docs/Micro_ISA.md)、[端口协议](docs/Job_Interface.md)提供具体规则。

## 生成与仿真

需要 Python3、Verilator、C++编译器、OpenSSL开发库；Vivado仅综合需要。

```bash
python3 scripts/check_source_import.py
python3 scripts/run_hash_backends.py images
python3 scripts/run_hash_backends.py all --tag example --jobs 3
python3 scripts/run_hash_backends.py all --tag image_chain_verified --jobs 3 --extended
```

入口保留源工具的 `images/models/rtl/all` 阶段。完整回归为六参数三操作共18项，逐字节检查输出、Verify节点和缓存，并核对动态指令、宏、Hash/置换计数及逐Hash前像/结果。扩展覆盖停顿、复位、截断/篡改、非法编码、ABI不匹配和宏边界。

```bash
python3 scripts/check_recipes.py
python3 scripts/check_hash_backend_contracts.py
```

源码身份验证不需要原父仓库：原材料、受控替换表和原回归小型JSON均封存在本分支实验目录。详细仿真日志只保留在build，归档保存验证摘要、冻结RTL和综合证据。

## 综合与报告

默认100MHz、xc7a200tffg1156-3、OOC、Vivado每任务2线程、`PROFILE_ENABLE=0`，只综合 `common`，不自动布局布线。与源共同核 **12,339 LUT / 4,113 FF / 0 BRAM / 0 DSP** 对照，LUT与FF偏差分别不得超过1%。100MHz仅是综合诊断约束，报告中的ATP按假定100MHz计算。

```bash
python3 scripts/synthesize.py
python3 scripts/report_atp.py
```

本次记录：[移植报告](docs/manifests/experiments/image_chain_import_20261021/reports/Image_Chain.md)。历史设计及实验报告保留；活动 `SOURCE.json` 与 `VALIDATION.json` 仅指本次移植。
