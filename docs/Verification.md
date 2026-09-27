# 当前项目的构建与验证

## 依赖

在仓库根目录运行。已验证环境：Python 3.12、GNU Make、Icarus Verilog 12.0（iverilog/vvp）、Verilator 5.008、C++ 编译器。Python 模型仅使用标准库。仿真流程不调用 Vivado，也不要求 Vivado 安装或许可证；综合另外要求 Vivado（已有流程使用 2025.2）。工具须位于 PATH。

## 推荐入口

```bash
make test TAG=my_current
make verify TAG=my_current
```

`make test` 顺序执行结构/工具契约、lint、六组软件模型/KAT、RTL 单元和三参数集 × Keygen/Sign 六组完整 RTL 仿真。`make verify` 包含上述测试，再执行 33 项扩展验证、六组提取后共同核仿真和证据核验。仅需完整验收时直接运行第二条即可。

模型与单元证据生成先于快照捕获；`make -j` 也保留这一顺序。单元测试每次重新执行，防止只修改 testbench 时复用过期结果。

| 入口 | 范围 |
|---|---|
| `make contract-test` | 当前接口/源码闭包、无 Vivado 环境捕获、工具错误和快照失配检查 |
| `make lint` | 当前生产 RTL 的 Verilator 检查；仍屏蔽 WIDTH/UNOPTFLAT 且告警非致命 |
| `make compile-microcode` | 三参数集六组模型、参考实现/KAT、镜像生成与非法输入检查 |
| `make rtl-unit-test` | 启动协议，以及存储/sequencer/SHAKE/recipe/padding 单元 |
| `make rtl-test TAG=...` | 单元 + 六组正常 RTL；使用已生成的镜像与向量 |
| `make rtl-verification TAG=...` | 已有六组正常结果之上的扩展与共同核仿真 |
| `python3 scripts/verify_v42_current.py <tag>` | 只核验已有完整证据，生成 verification.json |

单点仿真示例：

```bash
make rtl-profile-test TAG=probe_192f PROFILE=slh_192f OPERATION=sign
```

单点结果不满足六组验收要求。`rtl-profile-test` 会写入该 tag 的 simulation.json；单点探测建议使用独立 tag，避免覆盖完整运行的汇总。

## 验收内容与证据

33 项扩展验证覆盖实际 RTL Keygen 根传入 Sign、物理 lane 交换、输入停顿、复位中断/重放、1/7/8/9/87 字节消息和尾拍噪声。共同核仿真须与直接顶层在输出字节、Hash/置换计数、Boot/操作/总周期上全部一致。

工作目录为 `build/v4.2/external_job_message/<tag>/`：

- `inputs.json` / `source_snapshot.tar.gz`：源码、镜像与验证工具快照及工具版本。
- `simulation.json` / `extended.json` / `simulation_partition.json`：6/33/6 组结果。
- `logs/`：逐项日志和完整输出字节。
- `verification.json`：当前源码功能验收汇总及证据哈希。

软件和单元门禁记录位于 `manifests/experiments/unified_hbs_v4.2/external_job_message/`。构建会更新这些工作证据；封存候选不受影响。快照捕获后修改源码、测试工具、镜像或向量必须使用新 tag。同一 tag 可在输入完全一致时重跑。

功能验收汇总明确不声明综合资源或布线频率。进一步运行：

```bash
make synth-common TAG=my_current
make route-common TAG=my_current
make report-v42
```

该步骤要求 Vivado，记录实际综合工具版本，完成共同核及六个外壳的 post-synth 资源、ROM 映射与结构指纹验收。`route-common` 对六个参数外壳分别布线，并检查核内 setup/hold/脉宽、布线完整性、时序覆盖及 ROM 内容，再封存结果。`freeze-common` 可单独封存已完成的布线结果。100 MHz 是初始布线目标，最终频率只覆盖 OOC 核内寄存器间路径，外部输入/输出路径排除。0 ns 输入假设下的端口 hold 违例单独保留；接口没有完成时序签核，需要系统级 I/O 约束。该频率不代表板级或整接口工作频率。

`make reproduce-v42` 核验封存候选，不能替代 `make verify` 对当前工作树的验证。使用封存资源数据时应核对对应快照哈希。

## 冗余裁剪回归

`make rtl-verification TAG=<tag>` 还运行 `scripts/verify_v42_pruning.py`：对照 `current_complete_20260927_v2` 的六组输出、操作/总周期和计数；分别验证直接顶层、提取共同核在统计关闭时的六组结果，以及关闭统计的停顿、复位重放和六项故障退出。独立 SHAKE 向量检查普通链/compact chain 的首、中、末捕获及连续请求与响应停顿。`pruning_verification.json` 和综合网表 `pruning_audit.json` 一并归档。

Vivado 的完整输出保存到候选目录的 `synth.log` 和各外壳 `route.log`，终端仅展示阶段摘要。面积采用统计关闭的网表；周期由统计开启仿真测得，并由关闭统计的 testbench 观察器复核。
