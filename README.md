# mHBS v4.2

默认 L2U2P1 共同核，支持 SLH-DSA SHAKE **128f、192f、256f、128s、192s、256s** 的 Keygen、Sign 和外部节点 Verify。唯一顶层为 `rtl/top/mhbs_top.sv`，每次同步复位后执行一次操作。

此前封存的 L2U2P1 版本：**21,043 LUT、7,932 FF、1,112 LUTRAM、6252.250 等效 Slice**，BRAM/DSP 为零。这是共同核综合数据；没有该版本的新布线频率。详见[当前面积报告](docs/v4.2/LUT21k.md)和[六参数周期](docs/v4.2/Cycles.md)。

新增 L/U/P 实验：L 为 lane 数、U 为每级轮展开数、P 为流水级数。P>1 时，普通哈希和多上下文链共用同一套 P×U 轮逻辑。本轮仅验证 128f sign，参见 [LUP ATP 报告](docs/v4.2/LUP_128f_Sign_ATP.md)。历史 K 与 L 同义；冻结证据的路径与名称保持原样。

## 构建与验证

```bash
make lup-unit-test
make lup-atp LUP_TAG=lup_shared_128f_20261007_v2  # 四组共同核综合，无布线
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

- 五个 Job 参数：SECRET_SEED、SECRET_PRF、PUBLIC_SEED、RANDOMIZER、PUBLIC_ROOT；`OPERATION=0/1/2` 选择 Keygen/Sign/Verify。
- 消息：64 位 valid/ready 输入；Sign/Verify 长度 1–87 字节，Keygen 长度为零。
- 输出：256 位节点拍，`out_bytes` 指明有效低位字节，无输出背压。
- Verify：256 位外部节点 valid/ready 输入，完成后读取 `verify_pass`。
- 镜像保持文件加载：program 16×64、template 16×64、descriptor 32×64；有效条目分别为 14、11、30，含填充容量为 512 B。

[架构](docs/Architecture.md) · [端口协议](docs/Job_Interface.md) · [物理 ABI](docs/ABI.md) · [宏语义](docs/Unified_HBS_ABI.md)

## 文件与证据

- `rtl/`：源清单中的生产模块；FORS 根和 WOTS 端点共用 `mhbs_value_store`。
- `model/`、`tests/`、`tb/`：当前镜像生成、软件参考、协议和密码运算回归；旧命名的模型仍属于编译依赖。
- `scripts/`、`experiments/v4.2/external_job_message/`：当前验证、综合、布线及 ROM 映射工具。
- 当前源码快照、原始综合报告、DCP、完整回归日志和哈希由 `manifests/experiments/unified_hbs_v4.2/external_job_message/current_core.json` 指向。
- [最新 K/U 报告](docs/v4.2/KU_Sign_ATP_150_110_67_48.md)和[原始 K/U 归档](manifests/experiments/ku_sign_latest/README.md)独立保留；`make report-ku`、`make reproduce-ku` 不依赖 build。
- 旧候选、重复报告和实验驱动已删除，可从 Git 恢复。清理清单：`manifests/cleanup_20261002.json`。
- `source/`、`tmp/` 是本地研究资料和工作笔记，不属于生产源码或已提交备份。

当前 K1P1U1～K1P4U1 的统一 Keccak 实现及最新共同核综合结果见 [第二轮 ATP 报告](docs/v4.2/KPU_ATP_Unified_Optimization.md)。150 MHz 为假定频率，未布线。
