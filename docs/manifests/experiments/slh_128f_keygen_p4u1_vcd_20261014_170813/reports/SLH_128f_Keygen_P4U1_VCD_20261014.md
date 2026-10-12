# SLH-DSA 128f Keygen P4U1 VCD

更新时间：2026-10-14T17:13:02+08:00。

当前工作区冻结源码，单 Hash lane、P4U1、通用 Keccak，正常统计视图。完整 Keygen 仿真通过，输出逐字节与参考向量匹配；Hash/置换计数一致。

| 计算周期 | 总周期 | Hash | 置换 | 输出字节 |
|---:|---:|---:|---:|---:|
| 30,851 | 30,856 | 4,495 | 4,527 | 96 |

[完整 VCD](/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/waveform/slh_128f_keygen_P4U1_20261014_170813/slh_128f_keygen_P4U1.vcd)，2,029,064,428 字节，时间精度1ps。

测试台时钟周期10ns。波形含复位、Job/ROM、输出握手、executor状态、recipe上下文、Keccak流水各级及端点RAM；数组最大追踪136项，不追踪测试向量的大型数组。此时钟仅用于仿真。

[原始仿真日志](/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/waveform/slh_128f_keygen_P4U1_20261014_170813/source/build/sim/P4U1_synthesis0_vcd/slh_128f_keygen.log)；[编译日志](/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/waveform/slh_128f_keygen_P4U1_20261014_170813/source/build/sim/P4U1_synthesis0_vcd/compile.log)。

复现命令：

```bash
SIM_VCD=1 bash scripts/simulate.sh slh_128f keygen 4 1 +VCD=/absolute/path/slh_128f_keygen_P4U1.vcd
```

## 综合与源码证据

冻结RTL压缩包：`../rtl.tar.gz`；源码校验：`../RTL_SOURCE.json` 和 `../SOURCE.json`。

共同核综合：xc7a200tffg1156-3、Vivado2025.2、OOC、6.666667ns默认时序驱动、2线程、SYNTHESIS统计裁剪。

综合已完成：[分层报告](../synth/P4U1/common/hierarchical.rpt)、[时序报告](../synth/P4U1/common/timing.rpt)、[综合日志](../synth/P4U1/common/vivado.log)。

归档保留验证摘要、冻结RTL及综合证据。VCD与sim明细日志保留在运行目录，源码与波形SHA256见验证摘要。
