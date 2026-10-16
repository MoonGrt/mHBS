# V2 executor control subunit evidence

本目录保存父节点路径标记与滚动空槽预选的数学状态验证、Verilator elaboration 和精确复现源码。**模型只检查下一状态关系与坐标关系；不执行 RTL，也不能替代整核输出、签名缓存、Hash 计数及周期回归。** elaboration 只检查结构、参数和宏视图，不测周期或算法输出。整核 Sign 结果由主实验验证摘要单独记录。

候选包括 `variants/parent_path_executor.sv`、`allocator_executor.sv` 及 `combined_executor.sv`。相应 `from_U5_*.patch` 记录与 U5 executor 的精确差异。组合版对应 V2 冻结 executor。

源身份核对时，production、独立组合副本及 V2 冻结 executor 三者**字节级完全一致**，SHA256 均为 `bfa343af6e9bb411652575e457c3d7978ec55621258869293c4f48abe51e93e7`；去空白代码比较也相同。两个 `combined_to_*.patch` 文件均为空，准确记录当前没有缩进差异。真实路径、校验与记录时间见 `SOURCE_IDENTITY.json`。

验证结果：

- `check_models.py`：P=1/2/3/4/6/8/12/24 各 100,000 拍，共 800,000 拍，将分配器方程与独立集合所有权模型比较；覆盖满槽退休、同拍完成/提交、低标签释放、停顿及 setup。该模型没有执行 recipe 或 Hash RTL。
- 同一模型对 0/2 起始层的父节点坐标上升检查 400,520 次，包含 1023/1024、32767/32768、65535/65536、2^20 及 21 位边界。它验证标志更新公式，未独立证明所有 RTL 状态都执行了对应更新；实际 RTL 内另有仿真不变量。
- `check_elaboration.py`：组合版在 SHAKE/SHA2 × P1/P4/P12 × 普通/SYNTHESIS 视图共 12 项通过；独立 parent_path、allocator 各补 P12U1 SHAKE 普通视图，共 14 项通过。无错误、组合环路、锁存或多驱动警告。工具为 Verilator，具体版本及每项命令见 `ELABORATION.json`。
- 本次归档前针对 V2 冻结 source 重新执行 elaboration；全部 10 份 RTL 的 SHA 与 V2 SOURCE.json 一致，执行前后未改变。数学模型结果与初次临时检查结果完全一致。

目录保留两个测试脚本、候选源码、精确 patch、JSON 结果和 SHA。elaboration 明细日志仅保留在 `build/u5_atp_optimization/candidate_20261020_145941/executor_control_subunit_logs/`，未复制入实验归档。未改 production、冻结源码或综合设置，未启动 Vivado。

从任意目录复现，使用 Python 3 与 Verilator，并将原始日志输出到归档以外：

```bash
python3 check_models.py --output /tmp/V2_executor_model.json
python3 check_elaboration.py --source-root /path/to/V2/source \
  --log-dir /tmp/V2_executor_elaboration_logs --output /tmp/V2_executor_elaboration.json
```

`--source-root` 应为主实验 SOURCE.json 所指的冻结目录，或解压主实验 `rtl.tar.gz` 后包含 `rtl/` 的目录；其 10 份 RTL 应与 `ELABORATION.json` 的 `source_sha256` 一致。精确历史结果及源码身份以本目录 JSON 与 SHA256SUMS 为准。
