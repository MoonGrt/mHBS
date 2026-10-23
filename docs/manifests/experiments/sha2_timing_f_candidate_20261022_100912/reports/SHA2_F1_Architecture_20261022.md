# SHA2 F1：格式化路径分级与轮运算提前计算

本候选基于 E2，整源冻结 SHA256：17b7146ad416e368697118c14a5730978a8a3e302d82322817d79af638baed4e。
SHAKE 与其余八份 RTL 保持基线，模块端口、合法 P/U、单 Hash lane、算法配方和完整认证路径重算不变。

## 已确认的基线路径

以下均为冻结 E2 的实际布线结果；不据负 WNS 估算 Fmax。

| 配置 | WNS ns | 数据路径 ns | 逻辑级数 | 起点 | 终点 |
|---|---:|---:|---:|---|---|
| P2U1 | -0.399 | 7.027 | 11 | core/lane/need_block_reg[0]/C | core/lane/payload_mask_reg[6]/D |
| P3U1 | -0.797 | 7.426 | 14 | core/leaf_cursor_reg[0]/C | core/lane/captured_reg[1][21]/D |
| P4U1 | -0.936 | 7.365 | 9 | core/lane/format_tag_reg[1]_rep__1_replica_4/C | core/lane/block_words[3].data_reg[5]/D |
| P8U1 | -1.84 | 8.507 | 12 | core/lane/schedule_cursor_reg[2]/C | core/lane/block_words[3].data_reg[4]/D |
| P12U1 | -2.683 | 9.349 | 15 | core/lane/schedule_cursor_reg[1]/C | core/lane/payload_mask_reg[0]/D |
| P2U2 | -0.122 | 10.146 | 21 | core/lane/compression/stages[1].state_reg[1][589]/C | core/lane/compression/stages[0].state_reg[0][766]/D |
| P3U2 | -0.322 | 10.345 | 23 | core/lane/schedule_cursor_reg[1]/C | core/lane/compression/stages[0].state_reg[0][766]/D |

## 改动与代价

1. 调度仅登记槽标签；后续 DESCRIBE 登记配方、长度、地址及块号，PREPARE 再生成首拍控制或固定前缀。调度选择不再与整块写入或字节掩码译码串联。
2. 用 192 位暂存隔开上下文/字选择与拼接/填充，配套延迟字节掩码和 beat 地址。非列表 beat 仍可每拍接收 128 位，最后 beat 在 DRAIN 提交后才发送完整块；列表的原有 RAM 捕获停顿保留。
3. 初始捕获通过一个 pending 标志/标签延后一拍，从已登记的步号和 digest 写回，避免叶索引加法、目标比较直接驱动宽寄存器。pending 槽禁止提前返回，零步链同样受保护。
4. SHA256 前 min(U,4) 轮用原先 K 的 32 位寄存器提前保存 H+K+W，减少轮反馈算术两级 carry-save 归约；无新增原语周期、上下文或执行通道。其他展开轮保持通用依赖实现。

相对 E2，独立配方组件中固定首前缀块新增 2 拍、普通块新增 3 拍；完整 Sign 的变化必须实测，不能由块数外推。新增格式化暂存的面积以及新块注入的预加法路径，均需用综合和布线判断。

## 验证与测量边界

原语 30 个合法 P/U、正常和 SYNTHESIS 共 60 组，每组 181 独立向量通过，原语周期/停顿/标签事件与 E2 相同。配方组件使用固定旧原语验证；F1 整源另跑 36 组功能、P12/P24 满槽检查，以及六点 18 项完整 Sign。组件通过不代替整源结果。

100 MHz common 诊断先行；固定目标为 U1=150 MHz、U2=100 MHz。候选实测状态和 ATP 见同目录动态主报告。尚未完成的测量留空，不声明频率或 ATP 收益。旧矩阵继续后台，综合超过十分钟只延后分析。

详细测试日志保留运行目录；摘要、冻结 RTL、源码校验、分层/时序报告与 Vivado 日志归档，不运行 h20 完整树。
