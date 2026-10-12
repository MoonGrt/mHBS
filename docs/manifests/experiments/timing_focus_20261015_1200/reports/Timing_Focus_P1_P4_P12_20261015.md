# P1U1 / P4U1 / P4U2 / P12U1 布线时序优化

> 本轮已于 2026-10-15T15:00:58+08:00 按用户要求停止。全部综合、布线和自动续跑进程已退出；候选05布线取消，已有结果和日志保留。
更新时间：2026-10-15T15:00:23+08:00。本轮由用户明确授权布局布线；候选选择尚待实测。

工作区候选：`05_registered_phase`；与冻结 RTL 逐字节一致：`True`。候选01/02/03是逐步试验记录，未将其综合改善直接当作布线收益。

保持标准参数、单 Hash lane、模块接口和执行周期。面积采用对应配置 common；使用通用 Keccak、同器件和默认时序驱动综合，不增加时序例外。综合约束沿用 6.666667 ns；布线起点 U1=150 MHz、U2=100 MHz。

综合 WNS 只用于筛选，不能视为布线频率。布线搜索使用 0.1 ns 周期网格及相邻失败证据；报告实际 STA 频率。原长耗时综合继续后台，缺项保持空白，不借用其他配置。

## 基线瓶颈

| 配置 | 综合 WNS ns | 数据路径 ns | 逻辑级数 | 关键路径 |
|---|---:|---:|---:|---|
| P1U1 | -0.601 | 7.227 | 11 | FORS 索引算术与动态摘要选择 |
| P4U1 | -1.838 | 8.464 | 13 | 端点读址、RAM 与首轮 Keccak |
| P4U2 | — | — | — | 原综合未完成 |
| P12U1 | -1.826 | 8.452 | 17 | 链索引、步数选择与首轮 Keccak |

前三个已完成基线的前100条setup路径显示：P1U1有51条起于FORS组索引，P4U1有87条起于端点读址，P12U1有96条起于链游标。基线DCP只读扫描及源码/检查点校验见 baseline/paths；未更改约束。

## 候选与功能验证

### 01_physical_read_addresses

在原有端点地址准备拍登记奇偶物理RAM读址，读数据按逻辑顺序重排；无新增节点缓存或执行拍。

逐字节输出、签名缓存及工作量核对：12/12 项完成且与基线周期、Hash、置换计数完全一致。状态：`{'pending': 0, 'running': 1, 'passed': 15, 'failed': 0, 'cancelled': 0, 'skipped': 0}`。

### 02_control_and_valid

叠加FORS偏移/目标分拍预计算、批次链索引与digit预取，并移除中间Keccak级宽数据保持使能。末级保留sponge/结果及流式吸收保持；valid/tag/轮次/接口不变。空泡期间中间级翻转可能增加，当前未测动态功耗。

逐字节输出、签名缓存及工作量核对：12/12 项完成且与基线周期、Hash、置换计数完全一致。状态：`{'pending': 0, 'running': 0, 'passed': 16, 'failed': 0, 'cancelled': 0, 'skipped': 0}`。

### 03_ram_output_boundary

保留组合候选的预计算与中间级使能简化；将逻辑节点顺序选择放回RAM模块边界，物理地址仍提前登记。测试是否减少层次边界改变导致的格式化逻辑复制；不增加接口或周期。

逐字节输出、签名缓存及工作量核对：12/12 项完成且与基线周期、Hash、置换计数完全一致。状态：`{'pending': 0, 'running': 0, 'passed': 16, 'failed': 0, 'cancelled': 0, 'skipped': 0}`。

### 04_control_only

撤回全部物理RAM地址实验（value及端点读址恢复原基线），保留FORS分拍预计算、链索引/digit预取和Keccak中间级去保持使能。无P/U特化；与01/02/03逐步对照，以实测布线频率和ATP取舍。

逐字节输出、签名缓存及工作量核对：12/12 项完成且与基线周期、Hash、置换计数完全一致。状态：`{'pending': 0, 'running': 0, 'passed': 16, 'failed': 0, 'cancelled': 0, 'skipped': 0}`。

### 05_registered_phase

在04上将batch/FORS/L-tree阶段标志与原状态转移同拍登记，移除state多项译码到固定块格式化和首轮Keccak的串联。只增加四个窄控制位，P1自然裁剪；无新数据缓存或周期，逐拍断言核对原表达式。

逐字节输出、签名缓存及工作量核对：12/12 项完成且与基线周期、Hash、置换计数完全一致。状态：`{'pending': 0, 'running': 0, 'passed': 16, 'failed': 0, 'cancelled': 0, 'skipped': 0}`。

## 综合对照

| 候选 | 配置 | 等效 Slice | 面积变化 | WNS ns | WNS 改善 ns | 级数 | 综合耗时 s | 状态 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| 01_physical_read_addresses | P1U1 | 5,370.000 | 5.542% | -0.528 | 0.073 | 12 | 198.2 | passed |
| 01_physical_read_addresses | P4U1 | 8,986.500 | 0.575% | -2.118 | -0.280 | 15 | 503.1 | passed |
| 01_physical_read_addresses | P4U2 | — | — | — | — | — | — | analysis_deferred（继续后台） |
| 01_physical_read_addresses | P12U1 | 15,201.750 | 0.610% | -3.004 | -1.178 | 13 | 528.0 | passed |
| 02_control_and_valid | P1U1 | 5,410.125 | 6.331% | -0.227 | 0.374 | 10 | 232.0 | passed |
| 02_control_and_valid | P4U1 | 9,044.875 | 1.228% | -1.160 | 0.678 | 10 | 576.9 | passed |
| 02_control_and_valid | P4U2 | 11,105.500 | — | -3.776 | — | 17 | 1,172.4 | passed |
| 02_control_and_valid | P12U1 | 15,258.500 | 0.985% | -3.206 | -1.380 | 13 | 753.7 | passed |
| 03_ram_output_boundary | P1U1 | 5,443.625 | 6.989% | -0.232 | 0.369 | 10 | 248.3 | passed |
| 03_ram_output_boundary | P4U1 | 8,857.250 | -0.872% | -1.734 | 0.104 | 13 | 637.1 | passed |
| 03_ram_output_boundary | P4U2 | 11,327.625 | — | -3.642 | — | 15 | 1,067.9 | passed |
| 03_ram_output_boundary | P12U1 | 15,116.000 | 0.042% | -2.824 | -0.998 | 12 | 613.5 | passed |
| 04_control_only | P1U1 | 5,295.250 | 4.073% | -0.582 | 0.019 | 10 | 352.3 | passed |
| 04_control_only | P4U1 | 8,912.375 | -0.255% | -1.614 | 0.224 | 13 | 1,409.4 | passed |
| 04_control_only | P4U2 | 11,160.875 | — | -3.509 | — | 16 | 913.7 | passed |
| 04_control_only | P12U1 | 15,193.875 | 0.558% | -2.294 | -0.468 | 13 | 1,044.6 | passed |
| 05_registered_phase | P1U1 | 5,313.500 | 4.432% | -0.696 | -0.095 | 11 | 293.1 | passed |
| 05_registered_phase | P4U1 | 9,139.500 | 2.287% | -1.505 | 0.333 | 13 | 1,028.2 | passed |
| 05_registered_phase | P4U2 | 11,295.375 | — | -3.807 | — | 17 | 755.9 | passed |
| 05_registered_phase | P12U1 | 15,286.125 | 1.168% | -1.729 | 0.097 | 14 | 712.6 | passed |

## 布线对照

| 候选 | 配置 | 基线 MHz | 候选 MHz | 频率变化 | 候选布线 Slice | 搜索进度 |
|---|---|---:|---:|---:|---:|---|
| 01_physical_read_addresses | P1U1 | 129.870 | — | — | — | 归因测量；不启动布线 |
| 01_physical_read_addresses | P4U1 | — | — | — | — | 归因测量；不启动布线 |
| 01_physical_read_addresses | P4U2 | — | — | — | — | 归因测量；不启动布线 |
| 01_physical_read_addresses | P12U1 | — | — | — | — | 归因测量；不启动布线 |
| 02_control_and_valid | P1U1 | 129.870 | 133.333 | 2.667% | 5,425.125 | passed |
| 02_control_and_valid | P4U1 | — | — | — | — | cancelled_by_user |
| 02_control_and_valid | P4U2 | — | — | — | — | cancelled_by_user |
| 02_control_and_valid | P12U1 | — | — | — | — | cancelled_by_user |
| 03_ram_output_boundary | P1U1 | 129.870 | — | — | — | 归因候选；P1面积+7%、P12综合WNS回退，未启动布线 |
| 03_ram_output_boundary | P4U1 | — | — | — | — | 归因候选；P1面积+7%、P12综合WNS回退，未启动布线 |
| 03_ram_output_boundary | P4U2 | — | — | — | — | 归因候选；P1面积+7%、P12综合WNS回退，未启动布线 |
| 03_ram_output_boundary | P12U1 | — | — | — | — | 归因候选；P1面积+7%、P12综合WNS回退，未启动布线 |
| 04_control_only | P1U1 | 129.870 | 129.870 | 0.000% | 5,365.750 | passed |
| 04_control_only | P4U1 | — | — | — | — | cancelled_by_user（停止前：
| 04_control_only | P4U2 | — | — | — | — | cancelled_by_user |
| 04_control_only | P12U1 | — | — | — | — | cancelled_by_user |
| 05_registered_phase | P1U1 | 129.870 | — | — | — | cancelled_by_user_before_launch |
| 05_registered_phase | P4U1 | — | — | — | — | cancelled_by_user_before_launch |
| 05_registered_phase | P4U2 | — | — | — | — | cancelled_by_user_before_launch |
| 05_registered_phase | P12U1 | — | — | — | — | cancelled_by_user_before_launch |

## SLH-DSA 128f Sign 实测布线 ATP

| 候选 | 配置 | 周期 | 基线 ATP Slice·ms | 候选 ATP Slice·ms | ATP 变化 |
|---|---|---:|---:|---:|---:|
| 01_physical_read_addresses | P1U1 | 2,619,846 | 105,271.831 | — | — |
| 01_physical_read_addresses | P4U1 | 725,742 | — | — | — |
| 01_physical_read_addresses | P4U2 | 378,234 | — | — | — |
| 01_physical_read_addresses | P12U1 | 285,531 | — | — | — |
| 02_control_and_valid | P1U1 | 2,619,846 | 105,271.831 | 106,597.440 | 1.259% |
| 02_control_and_valid | P4U1 | 725,742 | — | — | — |
| 02_control_and_valid | P4U2 | 378,234 | — | — | — |
| 02_control_and_valid | P12U1 | 285,531 | — | — | — |
| 03_ram_output_boundary | P1U1 | 2,619,846 | 105,271.831 | — | — |
| 03_ram_output_boundary | P4U1 | 725,742 | — | — | — |
| 03_ram_output_boundary | P4U2 | 378,234 | — | — | — |
| 03_ram_output_boundary | P12U1 | 285,531 | — | — | — |
| 04_control_only | P1U1 | 2,619,846 | 105,271.831 | 108,242.278 | 2.822% |
| 04_control_only | P4U1 | 725,742 | — | — | — |
| 04_control_only | P4U2 | 378,234 | — | — | — |
| 04_control_only | P12U1 | 285,531 | — | — | — |
| 05_registered_phase | P1U1 | 2,619,846 | 105,271.831 | — | — |
| 05_registered_phase | P4U1 | 725,742 | — | — | — |
| 05_registered_phase | P4U2 | 378,234 | — | — | — |
| 05_registered_phase | P12U1 | 285,531 | — | — | — |

## XMSS h10 Sign 实测布线 ATP

| 候选 | 配置 | 周期 | 基线 ATP Slice·ms | 候选 ATP Slice·ms | ATP 变化 |
|---|---|---:|---:|---:|---:|
| 01_physical_read_addresses | P1U1 | 86,567,075 | 3,478,477.163 | — | — |
| 01_physical_read_addresses | P4U1 | 21,443,190 | — | — | — |
| 01_physical_read_addresses | P4U2 | 10,794,618 | — | — | — |
| 01_physical_read_addresses | P12U1 | 7,986,643 | — | — | — |
| 02_control_and_valid | P1U1 | 86,567,075 | 3,478,477.163 | 3,522,279.021 | 1.259% |
| 02_control_and_valid | P4U1 | 21,443,190 | — | — | — |
| 02_control_and_valid | P4U2 | 10,794,618 | — | — | — |
| 02_control_and_valid | P12U1 | 7,986,643 | — | — | — |
| 03_ram_output_boundary | P1U1 | 86,567,075 | 3,478,477.163 | — | — |
| 03_ram_output_boundary | P4U1 | 21,443,190 | — | — | — |
| 03_ram_output_boundary | P4U2 | 10,794,618 | — | — | — |
| 03_ram_output_boundary | P12U1 | 7,986,643 | — | — | — |
| 04_control_only | P1U1 | 86,567,075 | 3,478,477.163 | 3,576,629.077 | 2.822% |
| 04_control_only | P4U1 | 21,443,190 | — | — | — |
| 04_control_only | P4U2 | 10,794,618 | — | — | — |
| 04_control_only | P12U1 | 7,986,643 | — | — | — |
| 05_registered_phase | P1U1 | 86,567,075 | 3,478,477.163 | — | — |
| 05_registered_phase | P4U1 | 21,443,190 | — | — | — |
| 05_registered_phase | P4U2 | 10,794,618 | — | — | — |
| 05_registered_phase | P12U1 | 7,986,643 | — | — | — |

## LMS h10 Sign 实测布线 ATP

| 候选 | 配置 | 周期 | 基线 ATP Slice·ms | 候选 ATP Slice·ms | ATP 变化 |
|---|---|---:|---:|---:|---:|
| 01_physical_read_addresses | P1U1 | 28,524,614 | 1,146,188.876 | — | — |
| 01_physical_read_addresses | P4U1 | 7,335,182 | — | — | — |
| 01_physical_read_addresses | P4U2 | 3,768,770 | — | — | — |
| 01_physical_read_addresses | P12U1 | 2,999,059 | — | — | — |
| 02_control_and_valid | P1U1 | 28,524,614 | 1,146,188.876 | 1,160,621.974 | 1.259% |
| 02_control_and_valid | P4U1 | 7,335,182 | — | — | — |
| 02_control_and_valid | P4U2 | 3,768,770 | — | — | — |
| 02_control_and_valid | P12U1 | 2,999,059 | — | — | — |
| 03_ram_output_boundary | P1U1 | 28,524,614 | 1,146,188.876 | — | — |
| 03_ram_output_boundary | P4U1 | 7,335,182 | — | — | — |
| 03_ram_output_boundary | P4U2 | 3,768,770 | — | — | — |
| 03_ram_output_boundary | P12U1 | 2,999,059 | — | — | — |
| 04_control_only | P1U1 | 28,524,614 | 1,146,188.876 | 1,178,530.796 | 2.822% |
| 04_control_only | P4U1 | 7,335,182 | — | — | — |
| 04_control_only | P4U2 | 3,768,770 | — | — | — |
| 04_control_only | P12U1 | 2,999,059 | — | — | — |
| 05_registered_phase | P1U1 | 28,524,614 | 1,146,188.876 | — | — |
| 05_registered_phase | P4U1 | 7,335,182 | — | — | — |
| 05_registered_phase | P4U2 | 3,768,770 | — | — | — |
| 05_registered_phase | P12U1 | 2,999,059 | — | — | — |

## 附加验证摘要

- `CONTROL_VALIDATION`：passed；详见同目录 JSON 的 validation 字段。
- `PHASE_STALL_VALIDATION`：passed；详见同目录 JSON 的 validation 字段。
- `CONTROL_ONLY_STALL_VALIDATION`：passed；详见同目录 JSON 的 validation 字段。
- `RECIPE_VALIDATION`：passed；详见同目录 JSON 的 validation 字段。
- `VALUE_BOUNDARY_VALIDATION`：passed；详见同目录 JSON 的 validation 字段。
- `PHASE_FULL_VALIDATION`：30；详见同目录 JSON 的 validation 字段。
- `PHASE_LINT`：True；详见同目录 JSON 的 validation 字段。
- `BOUNDARY_FULL_VALIDATION`：30；详见同目录 JSON 的 validation 字段。
- `VALUE_VALIDATION`：passed；详见同目录 JSON 的 validation 字段。
- `CONTROL_ONLY_LINT`：True；详见同目录 JSON 的 validation 字段。
- `VERIFY_VALIDATION`：21；详见同目录 JSON 的 validation 字段。
- `CONTROL_ONLY_FULL_VALIDATION`：30；详见同目录 JSON 的 validation 字段。

当前 RTL 为待验收候选。未结束的布线不报告最终频率或 ATP 收益；原始综合与仿真明细保留在各 build 目录。归档仅保留验证摘要、冻结源码及综合/布线证据，不保留 sim/validation 明细日志。

实验控制：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/timing_focus_20261015_1200`。
