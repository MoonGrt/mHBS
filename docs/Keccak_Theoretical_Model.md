# Keccak 算法理论周期下限

`model.keccak_utilization` 计算给定输入、给定工作量的**周期下界、有效轮利用率上界和空闲率下界**。这是理想同时批次模型，不是当前 RTL 的周期预测，不模拟逐个发射、流水寄存器或存储端口。结果不需要频率、Vivado 或 HDL 仿真。

## 用法

```bash
# 单点；XMSS/LMS Sign 默认不重算认证路径
python3 -m model.keccak_utilization --profile xmss_omega4 --operation sign --p 4 --u 2 --output build/xmss_theory

# 当前十参数三操作、13 组 P/U；另列两种认证路径配置
python3 -m model.keccak_utilization --both-auth

# 只计算重算认证树的 LMS Sign
python3 -m model.keccak_utilization --profile lms_omega4 --operation sign --recompute-auth

# Python-only 验证，包括全 1024 种五节点前向 DAG 的穷举调度对照
python3 -m unittest discover -s tests -p test_keccak_utilization.py
```

Python API：`analyze(name, operation, p=1, u=1, *, recompute_auth=False, inputs=None)`。

不指定 P/U 时扫描 U1 的 P1/2/3/4/6/8/12，以及 U2 的 P1/2/3/4/6/12；显式参数也允许其他满足 `P>0, U>0, 24%(P*U)==0` 的整数配置。输出同名前缀的 Markdown、CSV、JSON。

## 理想计算口径

P 个独立 **Keccak-f[1600] 置换**同时开始，经过 `24/U` 周期同时完成。链的下一步、多块 SHAKE 的下一次置换及树父节点等待所需结果；地址运算、校验和、异或、复制、接口和存储全部零周期。一个 Hash 可能需要多次置换，不能将多块 Hash 当成一批完成。

输入在时刻零可用。只有真实数据与控制依赖建立边；不因 Python 的遍历顺序或微码指令顺序增加边。不同树叶、链和树层可在输入就绪后提前计算。XMSS 的 key/mask 生成不依赖待掩码节点，允许与链节点计算并行；按地址重复调用的 Hash 仍按当前工作量保留，不作公共子表达式消除。

SHAKE 每个吸收块仅依赖覆盖该块的输入字节和前一个置换，完整 rate 边界仍增加填充块。列表首块可在对应前缀就绪后计算，不必等待所有端点。当前算法输出均小于 136 字节。工具内部能计数多次 squeeze，但本轮不扩展算法到长 XOF 输出。

## 认证路径

`recompute_auth` 仅影响 XMSS/LMS Sign：

- **false（默认）**：公钥根、认证路径已有，不计其生成成本；仅计 R／消息处理、链种子及签名链步骤。它不是当前无缓存 RTL Sign 的工作量。内部用占位认证节点完成零成本输出，不生成认证路径；比较参考签名时仅比较认证路径之前的部分。
- **true**：使用当前 `cold_image` 微码工作量，包含认证树重算及其中的重复计算。

Keygen、Verify、SLH-DSA 忽略该开关，报告该字段为 `null`／`—`。XMSS/LMS 指仓库 n=32、h=10、SHAKE256 实验参数，不代表注册的标准参数编码。

## 下界算法及证明范围

每个图节点为一次置换；令 N 为节点数，`d(v)` 为从输入到 v 的最长节点路径长度，`t(v)` 为从 v 到输出的最长节点路径长度。图按明确生产者 ID 记录依赖，不靠摘要相等匹配来源。

最少批次数 B 至少满足：

- 总容量：`B ≥ ceil(N/P)`。
- 依赖关键路径：`B ≥ max d(v)`。
- 对任意 a、b，满足 `d(v)≥a 且 t(v)≥b` 的节点只能放在第 a 至第 `B-b+1` 批；因此 `B ≥ a+b-2+ceil(N_ab/P)`。

工具枚举实际深度和反向深度形成的非空窗口，取上述下界的最大值为 `B_lb`。这可以同时计入必然的串行前段、并行中段和串行后段，不强行将整个算法按阶段串行化。单独的正向／反向窗口下界也输出到 JSON/CSV，便于解释限制因素。

```
cycles_lb         = B_lb * (24/U)
utilization_upper = N / (P * B_lb)
idle_lower        = 1 - utilization_upper
```

**窗口容量条件是必要条件，不保证足以构造对应调度。** 除 P=1 或全部节点组成依赖链等可直接证明的情形，`optimality` 标为 `lower_bound_only`；不能将 `cycles_lb` 称为已求得的最短可达周期。空闲率为容量浪费比例的下界，不是实际逐拍空闲、时钟门控率或功耗。固定输入和 P，改变 U 仅按比例缩放周期，空闲率不变。

## 输入与验证证据

默认读取已入库的 `manifests/experiments/fixed_p4u2_20261009/vectors/jobs/`：这只是冻结输入来源，不使用固定 P4U2 的 RTL、周期或综合结果。报告记录来源及完整输入内容 SHA-256；不输出私钥字段。

自定义输入：`--profile <name> --input <file.json>`。JSON 包含十六进制字符串 `secret, prf, public, random, root, message`，可选 `identifier`（默认16字节零）、`q`（默认0）、`signature`。节点按参数集 n 字节，消息1～87字节。Verify 必须提供完整签名并验证成功；Sign 若提供签名则核对结果；Keygen 核对给定根。

所有十参数的 Keygen、冷 Sign、Verify 逐项核对冻结向量的 Hash／置换次数和根／签名字节。缓存 Sign 对照未修改的原始模型。另以五节点 DAG 穷举最优调度验证下界不超过真实最优，并检查串行、独立、分叉汇合、多块边界、掩码依赖及 U 缩放。

汇总见 [理论下界报告](report/Keccak_Theoretical_Bounds.md)。本次不修改 RTL，不运行硬件工具，也不改写历史实测报告。
