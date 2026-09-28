# Program 16 条容量实验与新频率

候选 `program16_20260927_v1`：program 从 32×64 缩为 16×64；六组布局布线全部通过，最低核内频率 **102.040816 MHz**。共同核面积 **6312.500 等效 Slice**，比上一版增加 **1.750（0.028%）**；本次缩容没有带来整核面积下降。

## 实现与资源

三种 f 参数的 program 均使用地址 0～13，剩余两条空闲；template 仍为 16 条，descriptor 仍为 32 条。三组 ROM 合计逻辑容量从 640 B 缩为 512 B。

PC、循环返回 PC、程序地址及内部入口地址从 5 位缩为 4 位。头部原有 5 位入口字段位置保持不变，软件检查入口小于 16，拒绝超过容量的镜像及 legacy 转换中的非零溢出指令。共同核提取、仿真 stub、ROM 构造镜像、INIT 映射和逐位审计同步更新。

| 共同核指标 | 32 条版本 | 16 条版本 | 差值 |
|---|---:|---:|---:|
| LUT | 20854 | 20857 | +3 |
| FF | 8778 | 8786 | +8 |
| LUTRAM（包含于 LUT） | 1112 | 1112 | +0 |
| 等效 Slice | 6310.75 | 6312.5 | +1.75 |

序列器本身从 169 LUT / 155 FF 降至 165 LUT / 152 FF。综合网表确认 PC/循环 PC 少了 3 个 FF，头部入口少了 2 个 FF；同时 Vivado 新增 8 个 list_cursor 和 6 个 node_level 复制寄存器、减少 1 个 message_received 复制寄存器，因此整核 FF 净增 8。这些是综合自动产生的寄存器副本，没有增加 RTL 状态或流水级；详细差异保存在 progress/register_difference.json。其他层级的 LUT 映射变化也抵消了序列器的节省。程序 ROM 每个数据位由 LUT5 改为 LUT4，仍需一个逻辑 LUT，存储位数减半不代表 FPGA LUT 数减半。完整分层报告保留了实际映射结果，未把逻辑容量缩减当作面积收益。

## 验证

模型六组参考输出、镜像容量与入口越界检查、14 项单元测试及合约/lint 通过。序列器新增从地址 12 启动、嵌套循环回跳、地址 15 停机测试，并保留握手停顿和延迟完成检查。

完整 RTL 回归通过：6 组 keygen/sign、33 项扩展、6 组共同核等价、12 组统计关闭、2 项统计关闭扩展、6 项故障退出、65 项 verify 节点测试。与 `shared_list_store_20260927_v1` 比较，六组输出 SHA-256、启动/计算/总周期、Hash/置换次数一致；62 项非故障 verify 的结果、节点数、Hash/置换数和扣除输入等待后的周期一致。

生产综合 `PROFILE_ENABLE=0`，统计和目标冗余寄存器审计通过。六个参数外壳的共同核指纹一致，综合和布线后的 ROM 每一位均核验通过。

## 本轮实测频率

器件 `xc7a200tffg1156-3`，Vivado 2025.2；保留至少 0.1 ns setup 裕量，核内 hold、脉宽与布线完整性检查通过。

| 配置 | 计算周期 | 时钟周期 ns | 核内频率 MHz | WNS ns | WHS ns |
|---|---:|---:|---:|---:|---:|
| slh_128f_keygen | 29862 | 9.8 | 102.040816 | 0.177 | 0.080 |
| slh_128f_sign | 729983 | 9.6 | 104.166667 | 0.100 | 0.078 |
| slh_192f_keygen | 43654 | 9.6 | 104.166667 | 0.115 | 0.101 |
| slh_192f_sign | 1249491 | 9.5 | 105.263158 | 0.171 | 0.076 |
| slh_256f_keygen | 115766 | 9.8 | 102.040816 | 0.187 | 0.077 |
| slh_256f_sign | 2579236 | 9.7 | 103.092784 | 0.182 | 0.093 |

以上为当前支持 verify 的共同核在六个 keygen/sign 参数外壳中的 OOC 核内时序。外部输入/输出路径不计入频率，接口未时序签核；没有额外测量 verify 专用外壳。上一版 32 条共享存储版本仅做过综合，未测频率，因此不能用本轮数据断言 PC 缩短带来了频率提升。更早的 104.166667 MHz 属于新增 verify 之前的历史实现，不作为同版本对照。

## 证据

- [当前 PPA](Current_PPA.md)
- [分层面积](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/program16_20260927_v1/synthesis/core_hierarchical.rpt)
- [布线结果](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/program16_20260927_v1/route/result.json)
- [输出与周期对照](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/program16_20260927_v1/program16_comparison.json)

候选目录保存独立源码快照、增量补丁、完整日志、功能证据和六组综合网表/布线检查点。源码快照 SHA-256：`f0d93b1ef1735fef55b134076735d11d974a62c1829c0a2d651a42cc85f1462c`。本轮未提交或推送。
