# mHBS 项目包

固定单 Hash lane，保留 `PIPELINE=P`、`UNROLL=U`。包含当前有效 RTL、统一 Verilator 测试平台、独立 Python 软件模型、向量生成与共同核综合入口。源码版本及文件来源记录于 `SOURCE.json`。

支持 SLH-DSA SHAKE 的 `slh_128f/192f/256f/128s/192s/256s`，以及 `xmss_omega2/4`、`lms_omega2/4` 的 Keygen、Sign、Verify。XMSS/LMS 使用仓库实验 SHAKE256 配方，n=32、h=10；omega2/4 为每个数字 2/4 位，对应 133/67 条链。Sign 包含完整认证路径重算。

## 文件

```text
rtl/                 当前生产 RTL 与导出的共同核
model/               算法解释器、镜像编码、独立验证器与默认输入
tb/tb.sv             统一测试平台
tb/vectors/          十参数 × 三操作的镜像、输入和期望输出
model/vectors.py     从软件模型生成全部镜像与向量
scripts/simulate.sh  Verilator 编译、仿真入口
scripts/synthesize.sh / synth.tcl
                     Vivado 综合入口
scripts/clock.xdc     时钟约束
sources.txt          完整 RTL 源码清单
SOURCE.json          原始提交、修改说明、SHA-256
VALIDATION.json      独立重生成、仿真与综合验证结果
LICENSE              MIT 许可证
```

包可整体移动。仿真与综合脚本可从任意目录调用；生成向量前先进入包根目录。软件模型与默认输入均在包内，无需原仓库、历史实验、测试归档或参考 RTL。仿真编译产物和完整日志写入 `build/`。

## 独立生成向量

只需 Python 3.10 或更新版本及其标准库，不需要 pip 依赖。即使删除整个 `tb/vectors/`，也能从 `model/default_jobs.json` 的种子、消息和 q 重新生成：

```bash
python3 -m model.vectors                # 十参数三操作，默认四进程
python3 -m model.vectors --profile slh_128f
python3 -m model.vectors --output build/new_vectors --workers 2
python3 -m model.vectors --profile lms_omega4 --q 1 --message-hex 010203
python3 -m model.vectors --profile xmss_omega2 --message-length 9
python3 -m model.vectors --profile lms_omega4 --q 1 --message-hex 010203 --output build/custom_vectors
VECTORS_DIR=build/custom_vectors ./scripts/simulate.sh lms_omega4 verify 4 1
```

每次为所选参数生成 Keygen/Sign/Verify 三组八文件向量，以及 `generation.json` 中的 Hash/置换次数、根和文件 SHA-256。默认输入复现随包提供的向量。生成过程计算完整公钥根与签名；随后使用独立验证器验证签名并统计 Verify 工作量，不从已有向量或历史结果复制期望输出。s 参数和 XMSS/LMS 的完整树计算耗时较长。

`--job inputs.json` 接收输入覆盖：单参数时可直接提供 `secret_seed`、`secret_prf`、`public_seed`、`randomizer`、`identifier`、`message` 的十六进制字串及整数 `q`；多参数可按参数名组织对象。缺省字段来自包内默认输入。节点字段须恰好 n 字节，identifier 为 16 字节，消息为 1～87 字节，q 为 0～1023；SLH 的 q/identifier 必须为零。软件默认重算 XMSS/LMS 认证路径，与当前 RTL 一致。

软件接口为 `model.executor.Job/Machine`、`model.mHBS.compile_image`。`mHBS.py` 默认生成 Job 外部输入的 16/16/32 字镜像；独立验证器位于 `model/reference/slh_dsa.py` 和 `model/reference/stateful_shake.py`。在包根目录运行 `python3 -m model.vectors` 生成向量。

## 仿真

已验证工具：Verilator 5.008、Bash；编译使用系统 C++ 编译器和 make，每次最多 2 个编译线程。默认配置为 P1U2、统计开启。

```bash
./scripts/simulate.sh
./scripts/simulate.sh slh_128f sign 4 1
./scripts/simulate.sh xmss_omega4 verify 4 1
./scripts/simulate.sh --smoke 4 1
./scripts/simulate.sh --all 4 1
PROFILE_ENABLE=0 ./scripts/simulate.sh slh_128f sign 4 1
```

`--smoke` 执行十参数 Verify，加上 128f Keygen/Sign，共 12 项；`--all` 执行全部 30 项。XMSS/LMS 的 Keygen/Sign 计算完整树，运行较久。运行时读取所选向量，不必为每种算法重新编译；P/U、统计配置或源码变化时重新编译。

测试逐字节检查公钥/签名、Verify 结果、Hash/置换次数以及签名缓存读回，并输出计算/总周期。出现不匹配即返回非零状态。支持附加 `+STALL=1`、`+REPLAYS=2`、`+INTERRUPT=1`；例如：

```bash
./scripts/simulate.sh lms_omega4 verify 4 1 +STALL=1 +REPLAYS=2 +INTERRUPT=1
```

`P` 范围为 1～12，`U>0`，要求 `P×U` 整除 24。常用 U1 的 P1/2/3/4/6/8/12，U2 的 P1/2/3/4/6/12。P1 使用普通链请求，P>1 可交错执行 P 个独立链上下文；每级组合展开 U 轮，完成总计 24 轮才返回置换结果。

## 综合

```bash
./scripts/synthesize.sh          # P1U2
./scripts/synthesize.sh 4 1      # P4U1
```

Vivado 2025.2，器件 `xc7a200tffg1156-3`，4 线程，约束 6.666667 ns。综合顶层为 `common`，统计显式关闭；检查周期及 Hash/置换计数寄存器已裁剪。终端仅显示阶段结果，完整日志和分层面积、总面积、综合时序报告位于 `build/synth/PxUy/`。本入口只综合、不布局布线；综合约束不是实测频率。

共同核面积包含控制器、算法数据存储与 Hash lane，ROM 和完整签名缓存由外部提供。生产 `top` 内含这些 ROM，并可启用完整签名缓存，面积口径不同。

## 顶层与接口

- `rtl/top/top.sv`／`top`：生产顶层，Job 参数在综合/实例化时配置，含 program/template/descriptor ROM 和可选签名缓存。默认 ROM 路径为包内 128f Sign 镜像。
- `rtl/top/common.sv`／`common`：从生产顶层执行区域导出，Job/ROM 为运行时端口，供统一测试与共同核面积综合使用。
- 其余文件和模块同名：`keccak`、`recipe`、`pipeline`、`executor`、`sequencer`、`value`、`signature`。`sources.txt`、实例引用、仿真和综合入口已统一使用新名称。

两个入口每次复位执行一项操作，完成/错误状态保持至复位。`rst` 高有效、同步；切换 Job 或镜像后重新复位。生产顶层 `OPERATION=0/1/2` 对应 Keygen/Sign/Verify；共同核使用 `job_operation`。秘密种子、PRF 种子、公种子、R 随机量、公钥根分别通过生产顶层参数或共同核 `job_*` 端口提供，使用节点低 128/192/256 位。

| 端口 | 用法 |
|---|---|
| `message_length[6:0]` | Keygen 为 0；Sign/Verify 为 1～87，在接受 Job 时锁存 |
| `message_valid/ready`、`message_data[63:0]` | 上升沿 valid/ready 同为 1 时接收；等待时保持数据；低字节在先，尾拍多余字节忽略 |
| `verify_valid/ready`、`verify_data[255:0]` | 同样握手，每拍一个低位 n 字节节点；不足节点时等待 |
| `out_valid`、`out_data[255:0]`、`out_bytes[5:0]` | 每有效拍输出低位 4/16/24/32 字节，低字节在先，无输出背压 |
| `done`、`error/error_code` | 操作完成/执行错误；Verify 根不匹配不属于执行错误 |
| `verify_pass` | Verify 完成且 error=0 时判断签名是否通过 |
| `PROFILE_ENABLE` | 仿真开启统计；综合入口设为 0，统计端口置零 |

Verify 使用节点接口，由外部拆分签名并校验总长度。SLH 顺序为 R、各 FORS 树的秘密节点和认证路径、各层 WOTS 签名与认证路径。XMSS/LMS 顺序为 R、133/67 个链节点、10 个认证节点，路径从叶到根；q 和 LMS 类型字段不作为节点输入。公钥根由调用方提供。

XMSS/LMS 的 `KEY_INDEX`／`job_index` 为 q（0～1023），LMS 的 `IDENTIFIER`／`job_identifier` 为 16 字节 I。q 由外部持久化管理，每次签名只能使用一次；复位不恢复可用索引。

生产顶层 `SIGNATURE_STORE_ENABLE=1` 时保存完整 Sign 输出。`signature_valid=1` 后按节点索引发起 `signature_read_enable/address`，下一同步读响应使用 `signature_read_valid/data/bytes`；将各项低位有效字节拼接即可恢复签名。

## 向量格式

每个 `tb/vectors/<profile>/<operation>/` 目录包含八个文本文件：

| 文件 | 内容 |
|---|---|
| `program.mem`、`template.mem`、`descriptor.mem` | 16/16/32 项微码镜像，按 `sources.txt` 中的控制器解码 |
| `job.mem` | 五个种子/根字段、identifier、q、操作、消息长度（共 9 项） |
| `message.mem` | 消息字节 |
| `nodes.mem` | Verify 输入节点；其他操作不使用 |
| `expected.mem` | Keygen/Sign 期望输出字节；Verify 没有输出数据流 |
| `meta.mem` | 输出字节数、Hash 次数、置换次数、Verify 节点数、预期 Verify 通过标记 |

随包保留默认向量，也可全部由包内软件重新生成。使用新的输入时，运行生成脚本一次即可同步更新镜像、Job、节点和期望结果。
