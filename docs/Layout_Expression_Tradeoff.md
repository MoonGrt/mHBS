# Layout expression architecture decision

更新：2026-09-15。这里的结果用于选择 μHBS 内部 composer 架构，不是与
Unified HBS Architecture 的整机论文比较点。

## 同流程 OOC 结果

器件为 Artix-7 `xc7a200tffg1156-2`，Vivado 2025.2，约束 100 MHz。

| 方案 | 值宽 | LUT | FF | BRAM/DSP | WNS | 决策 |
|---|---:|---:|---:|---:|---:|---|
| 全宽 postfix engine | 288 bit | 10,929 | 6,307 | 0 / 0 | −7.749 ns | 拒绝 |
| 窄 postfix engine | 32 bit | 993 | 922 | 0 / 0 | +0.253 ns | 保留为 ADRS/index capability |

32 位方案相对 288 位方案减少 90.91% LUT 和 85.38% FF，并在相同约束下
由时序失败变为通过。288 位失败点由独立 RTL/testbench 快照与报告哈希
固定；后续修改主实现不会改变该负结果。

## 采用的拆分

- 32 位 layout ALU 只计算循环索引、叶节点号、树高和 ADRS 字段；配置仅在
  IDLE 时写入，Job 接受后由硬件自行求值，不需要软件逐步提供任务或地址。
- 272 位消息摘要中的 FORS/base-w digit 由静态、MSB-first bitstream wiring
  解包；NIST ACVP tc137 的 33 个 6-bit FORS index 已逐项验证。Vivado 将
  该模块综合为 0-cell 纯重排，不引入算法状态机；空网表不具有可报告的
  place/route 时序。
- 96 位 tree address 的固定移位/截断采用字段级 wiring/寄存器，而不经过
  288 位通用 barrel shifter。
- 32/64-byte 节点顺序由独立 `ordered_pair` capability 选择，避免把整条
  rate-wide 数据路塞进通用表达式栈。

因此，保留的是“预装载 layout + 自主硬件求值”的机制，不引入通用软件
runtime。当前模块尚未接入完整 SLH-DSA datapath，不能据此声称整机面积或
周期收益。

机器可读证据：

- `manifests/experiments/layout_expr_v0.1.0.json`
- `manifests/experiments/layout_expr32_v0.1.0.json`
- `manifests/experiments/digit_unpack_v0.1.0.json`
