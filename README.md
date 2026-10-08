# mHBS v4.2

固定单 lane、默认 P1U2 共同核，支持 SLH-DSA SHAKE **128f、192f、256f、128s、192s、256s** 的 Keygen、Sign 和外部节点 Verify。新增实验 SHAKE256 XMSS/LMS（n=32、h=10、omega=2/4）的三种操作，见 [扩展报告](docs/v4.2/Stateful_XMSS_LMS.md)。唯一顶层为 `rtl/top/mhbs_top.sv`，每次同步复位后执行一次操作。

`LANES` 与 `SWAP_PHYSICAL_LANES` 已删除，不能通过参数恢复多 lane。只保留 `PIPELINE/UNROLL`（P/U）：P>1 时普通哈希和多上下文链共用一套 P×U 轮逻辑。十种算法参数和三种操作均保留。

XMSS/LMS 的 Keygen、Sign、Verify 已接入 P>1 链上下文；P1 保留原路径，L-tree、列表压缩和 Merkle 父节点仍顺序执行。实现与测量见 [XMSS/LMS 链流水报告](docs/report/Stateful_Pipeline_20261012.md)。

最新单 lane 裁剪、周期等价与共同核面积见 [单 lane 优化报告](docs/report/Single_Lane_Optimization.md)。历史 K/L 报告、路径和源码快照保持原样，不能作为当前版本的面积或周期。

## 构建与验证

```bash
make pu-unit-test
make pu-atp PU_TAG=my_pu      # P1–P4/U1–U2，共同核综合，无布线
make single-lane-regression   # 对照冻结旧 L1：十参数三操作与边界检查
make contract-test lint
make smoke TAG=my_smoke       # 模型、单元、12 组 KG/SG、6 组 Verify 和封存证据
make verify TAG=my_full       # 再含扩展、共同核等价、统计关闭、故障及完整 Verify
make synth-core TAG=my_full   # Vivado 共同核综合
make synth-common TAG=my_full # 共同核与十二个参数外壳
make route-common TAG=my_full
make reproduce-v42 reproduce-ku
```

仿真使用 Python、Icarus Verilog、Verilator、GNU Make 和 C++ 编译器；综合/布线使用 Vivado。完整流程见[验证指南](docs/Verification.md)。修改源码后使用新的 TAG。

单点：`make rtl-profile-test TAG=probe PROFILE=slh_192f OPERATION=sign`。

## 接口与镜像

- Stateful Job 另有 KEY_INDEX 与 IDENTIFIER，索引由外部持久化管理。五个节点 Job 参数：SECRET_SEED、SECRET_PRF、PUBLIC_SEED、RANDOMIZER、PUBLIC_ROOT；`OPERATION=0/1/2` 选择 Keygen/Sign/Verify。
- 消息：64 位 valid/ready 输入；Sign/Verify 长度 1–87 字节，Keygen 长度为零。
- 输出：256 位节点拍，`out_bytes` 指明有效低位字节，无输出背压。
- Verify：256 位外部节点 valid/ready 输入，完成后读取 `verify_pass`。
- 镜像保持文件加载：program 16×64、template 16×64、descriptor 32×64；SLH 有效条目分别为 14、11、30；新 XMSS/LMS 为 10、8、26/29，含填充容量为 512 B。

[架构](docs/Architecture.md) · [端口协议](docs/Job_Interface.md) · [物理 ABI](docs/ABI.md) · [宏语义](docs/Unified_HBS_ABI.md)

## 文件与证据

- `rtl/`：源清单中的生产模块；FORS 根和 WOTS 端点共用 `mhbs_value_store`。
- `model/`、`tests/`、`tb/`：当前镜像生成、软件参考、协议和密码运算回归；旧命名的模型仍属于编译依赖。
- `scripts/`、`experiments/v4.2/external_job_message/`：当前验证、综合、布线及 ROM 映射工具。
- 本轮源码快照、原始分层报告和验证日志在 `manifests/experiments/single_lane_20261008/`；`current_core.json` 仍指向历史封存版本。
- [最新 K/U 报告](docs/v4.2/KU_Sign_ATP_150_110_67_48.md)和[原始 K/U 归档](manifests/experiments/ku_sign_latest/README.md)独立保留；`make report-ku`、`make reproduce-ku` 不依赖 build。
- 旧候选、重复报告和实验驱动已删除，可从 Git 恢复。清理清单：`manifests/cleanup_20261002.json`。
- `source/`、`tmp/` 是本地研究资料和工作笔记，不属于生产源码或已提交备份。

历史 K1P1U1～K1P4U1 的统一 Keccak 实现及当时共同核综合结果见 [第二轮 ATP 报告](docs/v4.2/KPU_ATP_Unified_Optimization.md)。150 MHz 为假定频率，未布线。
