# SHAKE／SHA2：14点P/U面积、周期与固定频率布线

更新时间：2026-10-21T19:36:11+08:00；状态：用户要求重跑，旧轮未完成任务已停止。

任务状态：`{"routes": {"cancelled_for_user_rerun": 28}, "tests": {"cancelled_for_user_rerun": 65, "passed": 19}}`。

当前源码一次冻结；两个后端各14个common核，28次指定频率重新综合与布局布线；SLH-DSA 128f、XMSS h10、LMS h10完整Sign共84项。U1=150MHz，U2=100MHz。不搜索频率，不自动降频，不新增false-path/multicycle。器件xc7a200tffg1156-3，默认时序驱动、OOC、SYNTHESIS统计裁剪、通用Keccak；每Vivado两线程，全机批处理最多12个。

common面积不含外部ROM与可选签名缓存；三个算法共用同后端同P/U面积。等效Slice=LUT/4+FF/8+232.4×BRAM36+102.4×DSP，资源项在JSON完整列出。仿真逐字节核对输出、签名缓存及64位Hash/置换或压缩计数；认证路径完整重算，不执行h20。

指定时钟的完整路由、DRC及内部setup/hold均通过后才填写布线ATP并排名。150MHz在Vivado可能量化为6.667ns（149.992500MHz），标称判定容许0.0005ns周期量化，JSON另列严格数值判定；ATP始终使用实际时钟周期。未闭合点仍显示周期和目标频率时间，不借用其他配置面积或频率。排名按后端、算法分别计算，使用未舍入ATP；任务未全完时为暂定排名。

综合单点超过600秒只标记analysis_deferred，进程继续；该阈值不停止仿真或布线。

## common面积与布线STA

### SHAKE

| P/U | 目标MHz | 综合LUT | 综合FF | 综合BRAM36 | 综合Slice | 布线LUT | 布线FF | 布线BRAM36 | 布线Slice | WNS ns | WHS ns | 状态 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| P1U1 | 150.000 | — | — | — | — | — | — | — | — | — | — | cancelled_for_user_rerun |
| P2U1 | 150.000 | — | — | — | — | — | — | — | — | — | — | cancelled_for_user_rerun |
| P3U1 | 150.000 | — | — | — | — | — | — | — | — | — | — | cancelled_for_user_rerun |
| P4U1 | 150.000 | — | — | — | — | — | — | — | — | — | — | cancelled_for_user_rerun |
| P6U1 | 150.000 | — | — | — | — | — | — | — | — | — | — | cancelled_for_user_rerun |
| P8U1 | 150.000 | — | — | — | — | — | — | — | — | — | — | cancelled_for_user_rerun |
| P12U1 | 150.000 | — | — | — | — | — | — | — | — | — | — | cancelled_for_user_rerun |
| P24U1 | 150.000 | — | — | — | — | — | — | — | — | — | — | cancelled_for_user_rerun |
| P1U2 | 100.000 | — | — | — | — | — | — | — | — | — | — | cancelled_for_user_rerun |
| P2U2 | 100.000 | — | — | — | — | — | — | — | — | — | — | cancelled_for_user_rerun |
| P3U2 | 100.000 | — | — | — | — | — | — | — | — | — | — | cancelled_for_user_rerun |
| P4U2 | 100.000 | — | — | — | — | — | — | — | — | — | — | cancelled_for_user_rerun |
| P6U2 | 100.000 | — | — | — | — | — | — | — | — | — | — | cancelled_for_user_rerun |
| P12U2 | 100.000 | — | — | — | — | — | — | — | — | — | — | cancelled_for_user_rerun |

### SHA2

| P/U | 目标MHz | 综合LUT | 综合FF | 综合BRAM36 | 综合Slice | 布线LUT | 布线FF | 布线BRAM36 | 布线Slice | WNS ns | WHS ns | 状态 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| P1U1 | 150.000 | 15,447.000 | 7,219.000 | 0.000 | 4,764.125 | — | — | — | — | — | — | cancelled_for_user_rerun |
| P2U1 | 150.000 | 21,311.000 | 8,918.000 | 0.500 | 6,558.700 | — | — | — | — | — | — | cancelled_for_user_rerun |
| P3U1 | 150.000 | 24,958.000 | 10,741.000 | 1.000 | 7,814.525 | — | — | — | — | — | — | cancelled_for_user_rerun |
| P4U1 | 150.000 | 26,229.000 | 12,634.000 | 1.500 | 8,485.100 | — | — | — | — | — | — | cancelled_for_user_rerun |
| P6U1 | 150.000 | 31,683.000 | 16,306.000 | 2.500 | 10,540.000 | — | — | — | — | — | — | cancelled_for_user_rerun |
| P8U1 | 150.000 | 28,198.000 | 19,986.000 | 3.500 | 10,361.150 | — | — | — | — | — | — | cancelled_for_user_rerun |
| P12U1 | 150.000 | — | — | — | — | — | — | — | — | — | — | cancelled_for_user_rerun |
| P24U1 | 150.000 | — | — | — | — | — | — | — | — | — | — | cancelled_for_user_rerun |
| P1U2 | 100.000 | — | — | — | — | — | — | — | — | — | — | cancelled_for_user_rerun |
| P2U2 | 100.000 | — | — | — | — | — | — | — | — | — | — | cancelled_for_user_rerun |
| P3U2 | 100.000 | — | — | — | — | — | — | — | — | — | — | cancelled_for_user_rerun |
| P4U2 | 100.000 | — | — | — | — | — | — | — | — | — | — | cancelled_for_user_rerun |
| P6U2 | 100.000 | — | — | — | — | — | — | — | — | — | — | cancelled_for_user_rerun |
| P12U2 | 100.000 | — | — | — | — | — | — | — | — | — | — | cancelled_for_user_rerun |


## SLH-DSA 128f Sign

| 后端 | ATP排名 | P/U | Sign周期 | Hash | 置换/压缩 | 目标时间ms | 闭合MHz | 布线时间ms | 布线ATP Slice·ms | 仿真/物理 |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---|
| shake | — | P1U1 | 2,619,846.000 | 104,937.000 | 105,641.000 | 17.466 | — | — | — | passed/cancelled_for_user_rerun |
| shake | — | P2U1 | 1,432,676.000 | 104,937.000 | 105,641.000 | 9.551 | — | — | — | passed/cancelled_for_user_rerun |
| shake | — | P3U1 | 1,007,375.000 | 104,937.000 | 105,641.000 | 6.716 | — | — | — | passed/cancelled_for_user_rerun |
| shake | — | P4U1 | 764,949.000 | 104,937.000 | 105,641.000 | 5.100 | — | — | — | passed/cancelled_for_user_rerun |
| shake | — | P6U1 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| shake | — | P8U1 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| shake | — | P12U1 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| shake | — | P24U1 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| shake | — | P1U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| shake | — | P2U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| shake | — | P3U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| shake | — | P4U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| shake | — | P6U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| shake | — | P12U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P1U1 | 15,071,002.000 | 104,925.000 | 211,432.000 | 100.473 | — | — | — | passed/cancelled_for_user_rerun |
| sha2 | — | P2U1 | 7,907,313.000 | 104,925.000 | 211,432.000 | 52.715 | — | — | — | passed/cancelled_for_user_rerun |
| sha2 | — | P3U1 | 5,728,976.000 | 104,925.000 | 211,432.000 | 38.193 | — | — | — | passed/cancelled_for_user_rerun |
| sha2 | — | P4U1 | 4,209,812.000 | 104,925.000 | 211,432.000 | 28.065 | — | — | — | passed/cancelled_for_user_rerun |
| sha2 | — | P6U1 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P8U1 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P12U1 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P24U1 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P1U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P2U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P3U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P4U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P6U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P12U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |

## XMSS h10 Sign

| 后端 | ATP排名 | P/U | Sign周期 | Hash | 置换/压缩 | 目标时间ms | 闭合MHz | 布线时间ms | 布线ATP Slice·ms | 仿真/物理 |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---|
| shake | — | P1U1 | 86,567,075.000 | 3,431,815.000 | 3,431,815.000 | 577.114 | — | — | — | passed/cancelled_for_user_rerun |
| shake | — | P2U1 | 44,155,823.000 | 3,431,815.000 | 3,431,815.000 | 294.372 | — | — | — | passed/cancelled_for_user_rerun |
| shake | — | P3U1 | 30,074,116.000 | 3,431,815.000 | 3,431,815.000 | 200.494 | — | — | — | passed/cancelled_for_user_rerun |
| shake | — | P4U1 | 22,446,318.000 | 3,431,815.000 | 3,431,815.000 | 149.642 | — | — | — | passed/cancelled_for_user_rerun |
| shake | — | P6U1 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| shake | — | P8U1 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| shake | — | P12U1 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| shake | — | P24U1 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| shake | — | P1U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| shake | — | P2U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| shake | — | P3U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| shake | — | P4U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| shake | — | P6U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| shake | — | P12U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P1U1 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P2U1 | 254,057,797.000 | 3,431,950.000 | 7,001,183.000 | 1,693.719 | — | — | — | passed/cancelled_for_user_rerun |
| sha2 | — | P3U1 | 180,159,306.000 | 3,431,950.000 | 7,001,183.000 | 1,201.062 | — | — | — | passed/cancelled_for_user_rerun |
| sha2 | — | P4U1 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P6U1 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P8U1 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P12U1 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P24U1 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P1U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P2U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P3U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P4U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P6U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P12U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |

## LMS h10 Sign

| 后端 | ATP排名 | P/U | Sign周期 | Hash | 置换/压缩 | 目标时间ms | 闭合MHz | 布线时间ms | 布线ATP Slice·ms | 仿真/物理 |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---|
| shake | — | P1U1 | 28,524,614.000 | 1,101,392.000 | 1,116,752.000 | 190.164 | — | — | — | passed/cancelled_for_user_rerun |
| shake | — | P2U1 | 14,724,825.000 | 1,101,392.000 | 1,116,752.000 | 98.165 | — | — | — | passed/cancelled_for_user_rerun |
| shake | — | P3U1 | 10,171,344.000 | 1,101,392.000 | 1,116,752.000 | 67.809 | — | — | — | passed/cancelled_for_user_rerun |
| shake | — | P4U1 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| shake | — | P6U1 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| shake | — | P8U1 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| shake | — | P12U1 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| shake | — | P24U1 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| shake | — | P1U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| shake | — | P2U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| shake | — | P3U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| shake | — | P4U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| shake | — | P6U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| shake | — | P12U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P1U1 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P2U1 | 42,388,684.000 | 1,101,347.000 | 1,136,162.000 | 282.591 | — | — | — | passed/cancelled_for_user_rerun |
| sha2 | — | P3U1 | 30,720,799.000 | 1,101,347.000 | 1,136,162.000 | 204.805 | — | — | — | passed/cancelled_for_user_rerun |
| sha2 | — | P4U1 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P6U1 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P8U1 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P12U1 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P24U1 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P1U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P2U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P3U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P4U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P6U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |
| sha2 | — | P12U2 | — | — | — | — | — | — | — | cancelled_for_user_rerun/cancelled_for_user_rerun |

运行目录：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/dual_pu_route_matrix/20261021_193230`；冻结源码校验：`27012b28ef32497bad342f560f5a665630048fcb183d8e23e20f414bdc90f206`。

冻结RTL、控制脚本、验证摘要、完整Vivado日志与综合/布线分层、时序、DRC、路由报告归档；DCP和仿真明细日志保留运行目录。缺项在ARTIFACTS.json列明。共同核结果不代表板级或顶层I/O时序。
