# μHBS 正确性与自主执行契约

版本：v0.1.0（2026-09-15 冻结）

## 1. 适用边界

本契约覆盖 μHBS 的参考模型、微码解释器、RTL 和实验脚本。实现按以下规范分别判定，不把算法名称相近视为互操作等价：

| 算法 | 规范基线 | 当前冻结 profile | 判定状态 |
|---|---|---|---|
| LMS/LM-OTS | RFC 8554（含已验证 errata） | SHA256/N32/H10，W2 与 W4 | 严格目标 |
| XMSS | RFC 8391 | SHAKE_10_256/W16；补充 W4 仅作研究点 | W16 严格目标，W4 非标准研究点 |
| SLH-DSA | FIPS 205 final，2024-08-13 | SHAKE-128f/192f/256f | 严格目标 |
| 论文 SPHINCS+ | 论文 Table 2、2022 FIPS 205 draft 语境 | SHAKE fast 三档 | 报告值；语义未核同前不得称严格相同 |

论文实现宣称仅支持 SHAKE256；RFC 8554 的原始互操作 profile 使用 SHA-256。因此论文的 LMS 数据不能直接作为 RFC 8554 μHBS 的严格 cycle speedup 分母。

XMSS 参数记法必须显式换算：RFC 8391 的 `w=16` 是 Winternitz 基数，
对照论文的 `w=4` 是每个 digit 的 bit 数，两者均得到 `len=67`。
μHBS 使用官方 OID `0x00000010` 作为严格 `XMSS-SHAKE256_10_256`
目标；论文 `w=2/len=133` 对应的 RFC 内部基数为 4，但没有该组合的
RFC OID，因此只标记为研究 profile。

### 已固定的 XMSS 独立交叉验证

- RFC 8391 官方伴随实现：`XMSS/xmss-reference` commit
  `171ccbd26f098542a67eb5d2b128281c80bd71a6`（CC0-1.0）；
- 固定 seed `00..5f`、index 5 和消息 `micro-hbs-xmss-kat-v1`；
- μHBS 独立 Python oracle 与官方 C 实现的 public key、R、WOTS+
  签名摘要、认证路径摘要、完整签名摘要和更新后 index 一致；
- 完整签名长 2500 bytes，SHA-256 摘要为
  `d4382f3c15c6e876fd75566df439f70d9c4e39e64c3a7b7a6e31b42c0127dbb0`；
- 该官方实现只用于离线 KAT 交叉验证，不是 μHBS build/runtime 依赖。

### 已固定的 SLH-DSA 独立交叉验证

- NIST ACVP-Server `SLH-DSA-keyGen-FIPS205` 与
  `SLH-DSA-sigGen-FIPS205` samples，commit
  `975de31eb83d87039ec88934fdc47d8c312b892d`；
- profile `SLH-DSA-SHAKE-128f`；Keygen group/case `4/31`，deterministic
  SigGen group/case `16/137`；
- μHBS 独立 FIPS 205 oracle 的 secret/public key 与 NIST 向量一致；
- Keygen 微程序的 4,495 个有序 SHAKE 输入/输出与 oracle 一致；
- oracle 重建完整 17,088-byte 签名，其 SHA-256、`R`、首尾 64 bytes
  与 NIST 向量一致；验签通过且一位篡改被拒绝；
- 144-word Sign 微程序从一条 Job 展开完整 FORS 与 22 层 Hypertree，
  104,937 个有序 SHAKE 输入/输出与 oracle 一致；
- 项目只保存紧凑 KAT，ACVP-Server 不是 build/runtime 依赖；
- Sign 的通用表达式/条件 layout 尚未接入完整微码
  datapath，因此 descriptor-driven μHBS 仍不得标为完整
  `STANDARD_PASS`。外部项目的固定算法 FSM 不作为本项目正确性证据。

## 2. 数据与编码

- 字节串是唯一外部语义；所有整数按各规范指定的字节序编码。
- 每个 KAT 固定规范版本、profile、消息、种子、状态索引和期望输出 digest。
- 不允许用最终 root 相等代替逐 Hash 输入语义核对。
- `hash_input` trace 保存完整输入的 SHA-256 digest、长度、domain/layout 和调用序号；敏感明文默认不写入长期 artifact。
- SHAKE256 的 permutation 计数按 rate=136 byte、domain suffix 和最终 padding 后的吸收/挤出 block 计算。

## 3. 单 Job 自主执行

每个 Keygen、Sign 或 Verify 操作必须满足：

```text
accepted_job_commands == 1
host_control_writes_during_busy == 0
external_task_descriptors == 0
external_hash_descriptors == 0
done XOR error eventually becomes true
```

初始化期可以装载整幅微码/layout 镜像；`BUSY=1` 后镜像锁定。主机可以对数据流施加背压，但不得提供 task、Hash 输入模板、ADRS 更新、循环边界、树合并决策或 lane 分配。

## 4. 解释器与 RTL 等价

对同一 Job 和程序镜像，比较以下有序事件：

```text
pc, opcode, loop_depth, call_depth, effective_address,
layout_id, hash_input_digest, hash_output, tree_event, emit_event
```

允许 cycle 编号因 stall 不同而变化；不允许事件丢失、重排（显式双 lane 并行组内部除外）或内容不一致。最终输出必须同时匹配独立 oracle。

## 5. Fail-closed 条件

下列情况必须进入 `ERROR`，不得产生有效 `DONE` token：

- 未定义 opcode 或保留位非零；
- PC 越过已验证程序长度；
- Loop/Call Stack 上溢或下溢；
- loop bound 超过 manifest 上限；
- layout 未定义、输入长度越界或 capability 不匹配；
- Scratchpad/TreeHash/输出地址越界；
- BUSY 时修改程序、layout 或 Job 锁存参数；
- stateful profile 的索引未持久化、回滚、耗尽或重用。

## 6. 状态式签名

LMS/XMSS 索引遵循：

```text
FREE -> RESERVED -> PERSISTED -> RELEASED -> CONSUMED
```

对外可见签名只能使用 `PERSISTED` 索引。reset、cancel 或 error 后，已经 RESERVED 的索引必须烧毁而非回收。状态协议时间与纯计算时间分开报告。

## 7. 验收等级

- `MODEL_PASS`：独立 oracle、解释器和 trace 一致。
- `RTL_PASS`：RTL 与解释器逐事件一致，且自主性断言通过。
- `STANDARD_PASS`：完整标准 KAT/ACVP 或 RFC 向量通过。
- `PAPER_COMPARABLE`：算法版本、profile、Hash 输入、工作量、P/U、计时和输出边界全部对齐。

任何低等级结果不得被表述成更高等级结果。
