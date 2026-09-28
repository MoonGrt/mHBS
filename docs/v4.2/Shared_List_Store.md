# FORS 根与 WOTS 端点存储合并

保留 `shared_list_store_20260927_v1`。面积 **6370.250 → 6310.750 等效 Slice**，减少 **59.500（0.93%）**。综合关闭统计；未布局布线，不声明新频率。

## 资源

| 指标 | 合并前 | 合并后 | 差值 |
|---|---:|---:|---:|
| LUT | 21079 | 20854 | -225 |
| FF | 8804 | 8778 | -26 |
| LUTRAM（包含于 LUT） | 1454 | 1112 | -342 |
| 等效 Slice | 6370.250 | 6310.750 | -59.500 |

BRAM/DSP 均为 0。删除根存储节省的 LUTRAM 不是整核净 LUT 节省量：共享写入增加了选择逻辑，其他逻辑映射也发生变化。

## 实现

- 生产核只保留一个 `mhbs_value_store` 实例（实例名仍为 endpoints），68 个 256 位节点，两个写端口、一个有效读端口。
- FORS 阶段按 group_index 保存树根；压缩所有根后，WOTS 再覆盖相同存储。两类有效数据的生命周期不重叠。
- FORS 叶节点直接用于树计算，禁止原先 CHAIN_STORE 对列表存储的无用写入，防止覆盖已经保存的根。
- 根写入按地址奇偶送到对应 bank 的写端口，保持偶/奇端口地址最低位固定，避免引入任意双写端口交叉选择。
- 删除独立 g_roots 实例、task_list_roots 寄存器和两份列表读数据之间的选择。mhbs_root_store.sv 仅保留为兼容单元测试源文件，不出现在生产综合网表中。
- 接口、微码、Keccak、输出节点顺序及所有正常执行周期不变。

## 验证

合约/lint、14 项 RTL 单元、6 组 keygen/sign、65 项 Verify，以及 33 项扩展、6 组共同核等价、12 组统计关闭、2 项统计关闭扩展和 6 项故障退出全部通过。软件模型和镜像未改动，沿用并核验其源文件绑定的六组参考门禁。

两个集成 testbench 新增独立逻辑列表 scoreboard：从宏计算结果记录期望节点，逐字节核对实际存储读取；检查读前写入、FORS 叶禁止写入、根压缩完成前不得被 WOTS 覆盖。覆盖三种参数集、单侧尾项、lane 交换、输入停顿、复位重放和异常退出。

与上一版本比较，六组 keygen/sign 输出 SHA-256、启动/计算/总周期、Hash/置换次数一致；62 个非故障 Verify 用例的结果、节点数、Hash/置换数及扣除输入等待后的周期一致。

| 参数 | Keygen 周期 | Sign 周期 | Verify 正常周期（含启动） |
|---|---:|---:|---:|
| slh_128f | 29862 | 729983 | 84040 |
| slh_192f | 43654 | 1249491 | 118019 |
| slh_256f | 115766 | 2579236 | 123463 |

## 证据与复现

- [分层面积报告](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/shared_list_store_20260927_v1/synthesis/core_hierarchical.rpt)
- [候选结果](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/shared_list_store_20260927_v1/result.json)：同目录包含源码快照、增量补丁、回归日志、综合网表和证据 SHA-256。
- [完整功能审计](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/shared_list_store_20260927_v1/verification.json)
- [机器可读汇总](../../manifests/experiments/unified_hbs_v4.2/external_job_message/shared_list_store.json)

```bash
make verify TAG=<fresh_tag>
python3 scripts/v42_external_synth.py <fresh_tag> --core-only
```

未提交或推送；保留用户已有暂存内容。旧频率及旧波形只代表各自历史快照。
