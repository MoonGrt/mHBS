# SHAKE／SHA2：14点P/U面积、周期与固定频率布线

更新时间：2026-10-23T18:15:50+08:00；状态：用户已停止，等待再次运行指令。

用户已停止本轮调度、Vivado、仿真及刷新进程；保留已完成结果与冻结源码，不自动恢复。未完成项标记为`stopped_by_user`。

任务状态：`{"routes": {"stopped_by_user": 28}, "tests": {"passed": 48, "stopped_by_user": 36}}`。

当前源码一次冻结；两个后端各14个common核，28次指定频率重新综合与布局布线；SLH-DSA 128f、XMSS h10、LMS h10完整Sign共84项。U1=150MHz，U2=100MHz。不搜索频率，不自动降频，不新增false-path/multicycle。器件xc7a200tffg1156-3，默认时序驱动、OOC、SYNTHESIS统计裁剪、通用Keccak；每Vivado两线程，全机批处理最多12个。

实现策略：{"id": "congestion_spread_v1", "place": "AltSpreadLogic_high", "phys_opt": "Default", "route": "Explore", "diagnostics_on_failure": true}。本轮布局扩散及路由策略与旧default流程不同，净变化包含RTL和实现策略的共同作用，不单独归因为RTL。失败时保存的failed_*报告仅作部分/非法路由诊断，不填写有效频率或ATP。

common面积不含外部ROM与可选签名缓存；三个算法共用同后端同P/U面积。等效Slice=LUT/4+FF/8+232.4×BRAM36+102.4×DSP，资源项在JSON完整列出。仿真逐字节核对输出、签名缓存及64位Hash/置换或压缩计数；认证路径完整重算，不执行h20。

指定时钟的完整路由、DRC及内部setup/hold均通过后才填写布线ATP并排名。频率严格按实际时钟周期判定：实际周期须不大于1000/目标MHz+0.000001ns，不采用标称频率的周期量化容忍；ATP始终使用实际时钟周期。未闭合点仍显示周期和目标频率时间，不借用其他配置面积或频率。排名按后端、算法分别计算，使用未舍入ATP；任务未全完时为暂定排名。

综合单点超过600秒只标记analysis_deferred，进程继续；该阈值不停止仿真或布线。

后台报告与归档全局每60秒最多刷新一次；初始与最终结果立即发布，任务结束后自动退出。

## common面积与布线STA

### SHAKE

| P/U | 目标MHz | 综合LUT | 综合FF | 综合BRAM36 | 综合Slice | 布线LUT | 布线FF | 布线BRAM36 | 布线Slice | WNS ns | WHS ns | 状态 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| P1U1 | 150.000 | 18,082.000 | 6,250.000 | 0.000 | 5,301.750 | — | — | — | — | — | — | stopped_by_user |
| P2U1 | 150.000 | 27,350.000 | 10,852.000 | 0.000 | 8,194.000 | — | — | — | — | — | — | stopped_by_user |
| P3U1 | 150.000 | 29,701.000 | 12,549.000 | 0.000 | 8,993.875 | — | — | — | — | — | — | stopped_by_user |
| P4U1 | 150.000 | 31,999.000 | 14,223.000 | 0.000 | 9,777.625 | — | — | — | — | — | — | stopped_by_user |
| P6U1 | 150.000 | 36,596.000 | 17,584.000 | 0.000 | 11,347.000 | — | — | — | — | — | — | stopped_by_user |
| P8U1 | 150.000 | 41,700.000 | 20,933.000 | 0.000 | 13,041.625 | — | — | — | — | — | — | stopped_by_user |
| P12U1 | 150.000 | — | — | — | — | — | — | — | — | — | — | stopped_by_user |
| P24U1 | 150.000 | — | — | — | — | — | — | — | — | — | — | stopped_by_user |
| P1U2 | 100.000 | — | — | — | — | — | — | — | — | — | — | stopped_by_user |
| P2U2 | 100.000 | — | — | — | — | — | — | — | — | — | — | stopped_by_user |
| P3U2 | 100.000 | — | — | — | — | — | — | — | — | — | — | stopped_by_user |
| P4U2 | 100.000 | — | — | — | — | — | — | — | — | — | — | stopped_by_user |
| P6U2 | 100.000 | — | — | — | — | — | — | — | — | — | — | stopped_by_user |
| P12U2 | 100.000 | — | — | — | — | — | — | — | — | — | — | stopped_by_user |

### SHA2

| P/U | 目标MHz | 综合LUT | 综合FF | 综合BRAM36 | 综合Slice | 布线LUT | 布线FF | 布线BRAM36 | 布线Slice | WNS ns | WHS ns | 状态 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| P1U1 | 150.000 | 18,276.000 | 9,427.000 | 0.000 | 5,747.375 | — | — | — | — | — | — | stopped_by_user |
| P2U1 | 150.000 | 22,436.000 | 11,272.000 | 0.000 | 7,018.000 | — | — | — | — | — | — | stopped_by_user |
| P3U1 | 150.000 | 24,828.000 | 13,233.000 | 0.000 | 7,861.125 | — | — | — | — | — | — | stopped_by_user |
| P4U1 | 150.000 | 25,859.000 | 15,179.000 | 0.000 | 8,362.125 | — | — | — | — | — | — | stopped_by_user |
| P6U1 | 150.000 | 32,810.000 | 19,221.000 | 0.000 | 10,605.125 | — | — | — | — | — | — | stopped_by_user |
| P8U1 | 150.000 | 32,617.000 | 23,013.000 | 0.000 | 11,030.875 | — | — | — | — | — | — | stopped_by_user |
| P12U1 | 150.000 | — | — | — | — | — | — | — | — | — | — | stopped_by_user |
| P24U1 | 150.000 | — | — | — | — | — | — | — | — | — | — | stopped_by_user |
| P1U2 | 100.000 | — | — | — | — | — | — | — | — | — | — | stopped_by_user |
| P2U2 | 100.000 | — | — | — | — | — | — | — | — | — | — | stopped_by_user |
| P3U2 | 100.000 | — | — | — | — | — | — | — | — | — | — | stopped_by_user |
| P4U2 | 100.000 | — | — | — | — | — | — | — | — | — | — | stopped_by_user |
| P6U2 | 100.000 | — | — | — | — | — | — | — | — | — | — | stopped_by_user |
| P12U2 | 100.000 | — | — | — | — | — | — | — | — | — | — | stopped_by_user |


## SLH-DSA 128f Sign

| 后端 | ATP排名 | P/U | Sign周期 | Hash | 置换/压缩 | 目标时间ms | 闭合MHz | 布线时间ms | 布线ATP Slice·ms | 仿真/物理 |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---|
| shake | — | P1U1 | 2,619,846.000 | 104,937.000 | 105,641.000 | 17.466 | — | — | — | passed/stopped_by_user |
| shake | — | P2U1 | 1,432,676.000 | 104,937.000 | 105,641.000 | 9.551 | — | — | — | passed/stopped_by_user |
| shake | — | P3U1 | 1,007,375.000 | 104,937.000 | 105,641.000 | 6.716 | — | — | — | passed/stopped_by_user |
| shake | — | P4U1 | 764,949.000 | 104,937.000 | 105,641.000 | 5.100 | — | — | — | passed/stopped_by_user |
| shake | — | P6U1 | 535,693.000 | 104,937.000 | 105,641.000 | 3.571 | — | — | — | passed/stopped_by_user |
| shake | — | P8U1 | 449,566.000 | 104,937.000 | 105,641.000 | 2.997 | — | — | — | passed/stopped_by_user |
| shake | — | P12U1 | 300,869.000 | 104,937.000 | 105,641.000 | 2.006 | — | — | — | passed/stopped_by_user |
| shake | — | P24U1 | 218,036.000 | 104,937.000 | 105,641.000 | 1.454 | — | — | — | passed/stopped_by_user |
| shake | — | P1U2 | 1,352,154.000 | 104,937.000 | 105,641.000 | 13.522 | — | — | — | passed/stopped_by_user |
| shake | — | P2U2 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |
| shake | — | P3U2 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |
| shake | — | P4U2 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |
| shake | — | P6U2 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |
| shake | — | P12U2 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |
| sha2 | — | P1U1 | 7,051,236.000 | 104,925.000 | 106,513.000 | 47.008 | — | — | — | passed/stopped_by_user |
| sha2 | — | P2U1 | 3,876,061.000 | 104,925.000 | 106,513.000 | 25.840 | — | — | — | passed/stopped_by_user |
| sha2 | — | P3U1 | 2,809,474.000 | 104,925.000 | 106,513.000 | 18.730 | — | — | — | passed/stopped_by_user |
| sha2 | — | P4U1 | 2,082,514.000 | 104,925.000 | 106,513.000 | 13.883 | — | — | — | passed/stopped_by_user |
| sha2 | — | P6U1 | 1,522,895.000 | 104,925.000 | 106,513.000 | 10.153 | — | — | — | passed/stopped_by_user |
| sha2 | — | P8U1 | 1,251,276.000 | 104,925.000 | 106,513.000 | 8.342 | — | — | — | passed/stopped_by_user |
| sha2 | — | P12U1 | 932,160.000 | 104,925.000 | 106,513.000 | 6.214 | — | — | — | passed/stopped_by_user |
| sha2 | — | P24U1 | 687,338.000 | 104,925.000 | 106,513.000 | 4.582 | — | — | — | passed/stopped_by_user |
| sha2 | — | P1U2 | 3,642,820.000 | 104,925.000 | 106,513.000 | 36.428 | — | — | — | passed/stopped_by_user |
| sha2 | — | P2U2 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |
| sha2 | — | P3U2 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |
| sha2 | — | P4U2 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |
| sha2 | — | P6U2 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |
| sha2 | — | P12U2 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |

## XMSS h10 Sign

| 后端 | ATP排名 | P/U | Sign周期 | Hash | 置换/压缩 | 目标时间ms | 闭合MHz | 布线时间ms | 布线ATP Slice·ms | 仿真/物理 |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---|
| shake | — | P1U1 | 86,567,075.000 | 3,431,815.000 | 3,431,815.000 | 577.114 | — | — | — | passed/stopped_by_user |
| shake | — | P2U1 | 44,155,823.000 | 3,431,815.000 | 3,431,815.000 | 294.372 | — | — | — | passed/stopped_by_user |
| shake | — | P3U1 | 30,074,116.000 | 3,431,815.000 | 3,431,815.000 | 200.494 | — | — | — | passed/stopped_by_user |
| shake | — | P4U1 | 22,446,318.000 | 3,431,815.000 | 3,431,815.000 | 149.642 | — | — | — | passed/stopped_by_user |
| shake | — | P6U1 | 15,991,940.000 | 3,431,815.000 | 3,431,815.000 | 106.613 | — | — | — | passed/stopped_by_user |
| shake | — | P8U1 | 12,232,549.000 | 3,431,815.000 | 3,431,815.000 | 81.550 | — | — | — | passed/stopped_by_user |
| shake | — | P12U1 | 8,365,786.000 | 3,431,815.000 | 3,431,815.000 | 55.772 | — | — | — | passed/stopped_by_user |
| shake | — | P24U1 | 4,615,004.000 | 3,431,815.000 | 3,431,815.000 | 30.767 | — | — | — | passed/stopped_by_user |
| shake | — | P1U2 | 45,385,295.000 | 3,431,815.000 | 3,431,815.000 | 453.853 | — | — | — | passed/stopped_by_user |
| shake | — | P2U2 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |
| shake | — | P3U2 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |
| shake | — | P4U2 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |
| shake | — | P6U2 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |
| shake | — | P12U2 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |
| sha2 | — | P1U1 | 323,103,304.000 | 3,431,950.000 | 4,736,133.000 | 2,154.022 | — | — | — | passed/stopped_by_user |
| sha2 | — | P2U1 | 164,895,583.000 | 3,431,950.000 | 4,736,133.000 | 1,099.304 | — | — | — | passed/stopped_by_user |
| sha2 | — | P3U1 | 115,607,879.000 | 3,431,950.000 | 4,736,133.000 | 770.719 | — | — | — | passed/stopped_by_user |
| sha2 | — | P4U1 | 83,907,551.000 | 3,431,950.000 | 4,736,133.000 | 559.384 | — | — | — | passed/stopped_by_user |
| sha2 | — | P6U1 | 62,184,737.000 | 3,431,950.000 | 4,736,133.000 | 414.565 | — | — | — | passed/stopped_by_user |
| sha2 | — | P8U1 | 47,356,728.000 | 3,431,950.000 | 4,736,133.000 | 315.712 | — | — | — | passed/stopped_by_user |
| sha2 | — | P12U1 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |
| sha2 | — | P24U1 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |
| sha2 | — | P1U2 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |
| sha2 | — | P2U2 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |
| sha2 | — | P3U2 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |
| sha2 | — | P4U2 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |
| sha2 | — | P6U2 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |
| sha2 | — | P12U2 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |

## LMS h10 Sign

| 后端 | ATP排名 | P/U | Sign周期 | Hash | 置换/压缩 | 目标时间ms | 闭合MHz | 布线时间ms | 布线ATP Slice·ms | 仿真/物理 |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---|
| shake | — | P1U1 | 28,524,614.000 | 1,101,392.000 | 1,116,752.000 | 190.164 | — | — | — | passed/stopped_by_user |
| shake | — | P2U1 | 14,724,825.000 | 1,101,392.000 | 1,116,752.000 | 98.165 | — | — | — | passed/stopped_by_user |
| shake | — | P3U1 | 10,171,344.000 | 1,101,392.000 | 1,116,752.000 | 67.809 | — | — | — | passed/stopped_by_user |
| shake | — | P4U1 | 7,689,760.000 | 1,101,392.000 | 1,116,752.000 | 51.265 | — | — | — | passed/stopped_by_user |
| shake | — | P6U1 | 5,617,520.000 | 1,101,392.000 | 1,116,752.000 | 37.450 | — | — | — | passed/stopped_by_user |
| shake | — | P8U1 | 4,377,597.000 | 1,101,392.000 | 1,116,752.000 | 29.184 | — | — | — | passed/stopped_by_user |
| shake | — | P12U1 | 3,139,451.000 | 1,101,392.000 | 1,116,752.000 | 20.930 | — | — | — | passed/stopped_by_user |
| shake | — | P24U1 | 1,909,517.000 | 1,101,392.000 | 1,116,752.000 | 12.730 | — | — | — | passed/stopped_by_user |
| shake | — | P1U2 | 15,123,590.000 | 1,101,392.000 | 1,116,752.000 | 151.236 | — | — | — | passed/stopped_by_user |
| shake | — | P2U2 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |
| shake | — | P3U2 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |
| shake | — | P4U2 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |
| shake | — | P6U2 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |
| shake | — | P12U2 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |
| sha2 | — | P1U1 | 74,878,551.000 | 1,101,347.000 | 1,136,162.000 | 499.190 | — | — | — | passed/stopped_by_user |
| sha2 | — | P2U1 | 40,839,871.000 | 1,101,347.000 | 1,136,162.000 | 272.266 | — | — | — | passed/stopped_by_user |
| sha2 | — | P3U1 | 29,352,521.000 | 1,101,347.000 | 1,136,162.000 | 195.683 | — | — | — | passed/stopped_by_user |
| sha2 | — | P4U1 | 21,859,814.000 | 1,101,347.000 | 1,136,162.000 | 145.732 | — | — | — | passed/stopped_by_user |
| sha2 | — | P6U1 | 16,841,122.000 | 1,101,347.000 | 1,136,162.000 | 112.274 | — | — | — | passed/stopped_by_user |
| sha2 | — | P8U1 | 13,238,719.000 | 1,101,347.000 | 1,136,162.000 | 88.258 | — | — | — | passed/stopped_by_user |
| sha2 | — | P12U1 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |
| sha2 | — | P24U1 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |
| sha2 | — | P1U2 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |
| sha2 | — | P2U2 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |
| sha2 | — | P3U2 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |
| sha2 | — | P4U2 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |
| sha2 | — | P6U2 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |
| sha2 | — | P12U2 | — | — | — | — | — | — | — | stopped_by_user/stopped_by_user |

运行目录：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/dual_pu_route_matrix/20261023_180629`；冻结源码校验：`00571ac523cca78cc28e725f33b0071c372a83118eae485f9828d11add19cca2`。

冻结RTL、控制脚本、验证摘要、完整Vivado日志与综合/布线分层、时序、DRC、路由报告归档；DCP和仿真明细日志保留运行目录。缺项在ARTIFACTS.json列明。共同核结果不代表板级或顶层I/O时序。
