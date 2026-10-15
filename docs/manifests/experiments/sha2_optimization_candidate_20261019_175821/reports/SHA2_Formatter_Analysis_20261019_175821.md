# SHA2 固定窗口 formatter 优化归因

本轮只修改 SHA2 配方的块格式化与准备控制；SHA256 压缩原语、SHAKE 后端和执行器逐文件 SHA 与基线相同。测量使用 P1U1/P4U1/P12U1 的统一 common 核及 SLH128f、XMSS h10、LMS h10 完整 Sign。

原设计按字节进行可变源选择和宽位置运算，新设计登记格式控制，再以固定64位／128位窗口组成当前拍的数据。旧块准备路径为 SELECT→PREFETCH→4×BUILD→SEND，最少7拍；新路径首次为 SELECT→4×BUILD→SEND，最少6拍。SEND 接受当前块时准备下一块，连续块最少5拍；实际吞吐仍受压缩返回、槽位和多块依赖限制。

基线与候选使用同一工具版本、xc7a200tffg1156-3、100MHz、OOC、默认时序驱动、每进程2线程。等效Slice沿用项目口径：LUT/4 + FF/8 + 232.4×BRAM36 + 102.4×DSP，包含综合得到的共享存储。固定100MHz ATP是频率假设；综合数据路径用于定位瓶颈，不能当作布线Fmax或布线ATP。

完整Sign进度：{'pending': 0, 'running': 0, 'passed': 9, 'failed': 0}；整轮状态：已完成。

| 配置 | 原recipe自身 LUT | 新recipe自身 LUT | 变化 % | 原SHA256 LUT | 新SHA256 LUT | 原前20路径到block_buffer | 新前20路径到block_buffer |
|---|---:|---:|---:|---:|---:|---:|---:|
| P1U1 | 39,488.000 | 6,200.000 | -84.299 | 2,609.000 | 2,608.000 | 20/20 | 2/20 |
| P4U1 | 76,183.000 | 10,755.000 | -85.883 | 7,928.000 | 8,158.000 | 20/20 | 0/20 |
| P12U1 | 50,035.000 | 13,596.000 | -72.827 | 20,290.000 | 19,783.000 | 20/20 | 0/20 |

| 配置 | 原综合耗时 s | 新综合耗时 s | 原关键路径 | 新关键路径 |
|---|---:|---:|---|---|
| P1U1 | 310.322 | 92.819 | 11.629ns / 25级 / `core/lane/block_buffer_reg[105]/D` | 7.712ns / 17级 / `core/lane/compression/stages[0].state_reg[0][767]/D` |
| P4U1 | 491.320 | 106.430 | 14.798ns / 34级 / `core/lane/block_buffer_reg[19]/D` | 7.927ns / 14级 / `core/lane/compression/stages[1].state_reg[1][767]/D` |
| P12U1 | 345.597 | 149.799 | 13.829ns / 29级 / `core/lane/block_buffer_reg[449]/D` | 10.935ns / 18级 / `core/lane/payload_mask_reg[0]/D` |

recipe自身为分层报告中的 `(lane)` 行，不含其 `compression` 子模块；SHA256 单独取 `compression` 行。该统计覆盖配方控制、上下文和格式化逻辑，不能把全部recipe资源都归为formatter。候选与基线原始hierarchical.rpt、timing.rpt、critical_paths.rpt均归档；JSON保留路径端点与报告校验。综合耗时为各次实测墙钟时间，并发负载可能不同，不能视为独立受控的工具速度实验。

验证覆盖与限制：

- 标量配方764项通过（P1U1普通345、P12U1 SYNTHESIS 345、P4U1 mask 74）；另有最终P4U1 345项及统计测试通过。
- 批配方P4U1/P12U1/P4U2共36组通过，含乱序返回、退槽补发和空闲标签。P12局部测试使用4个同时活动标签，整核P12 Sign另测完整调度。
- 9项鲁棒性测试通过：停顿／复位重放、消息篡改、截断恢复、在途标量及批请求异常。
- 4条NIST ACVP确定性／随机化SHA2-128f/128s完整签名及3个目标SYNTHESIS完整Sign通过；统计声明预处理裁剪，测试包装统计为零，功能事件计数独立核对。
- SHA256原语和SHAKE源码未改，本轮未重复全部P/U原语或SHAKE大树回归；先前双后端完整回归继续后台运行。h20完整Keygen／Sign未启动。

所有局部摘要绑定当前冻结源码，并复核原始日志SHA；签名向量SHA保留在摘要和整核测量记录中。原始详细仿真日志保留build运行目录，归档只留摘要。

面积、周期、假定ATP及变化表见 [主测量报告](SHA2_Optimization_20261019_175821.md)。


最终取舍：保留候选1，当前工作区RTL已核验与其冻结源码一致。详见[阶段记录](SHA2_Optimization_Stages.md)及FINAL_SELECTION.json。
