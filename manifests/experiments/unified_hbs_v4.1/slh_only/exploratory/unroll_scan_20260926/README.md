# U1/U3 探索记录

这些是优化 Hash 输入路径之前的探索，源码对应完整提交
`506e1b04aaf69190f7649be5a551b7b939b1c91b`。归档在运行后补做；当时未自动保存运行时源码哈希，因此 `results.json` 明确记录这一来源限制。

- 三种配置均通过三个 SLH 参数点的完整正常流输出和 Hash/置换计数比对。
- U1/L2 仅综合；归一化 ATP 不具备优势。
- U3/L1、U3/L2 的布线被中断；保留 post-place 检查点和运行日志。没有最终频率，不能当作性能验收结果。
- 这里的 100 MHz 只用于归一化计算。生产构建仍固定 U2。

## 复现正常流及综合

在独立工作目录解开 `source_snapshot.tar.gz`，确保运行目录中有 `build/v4.1/`，然后对 `(UNROLL,LANES)=(1,2),(3,1),(3,2)` 分别执行：

```bash
mkdir -p build/v4.1
mapfile -t rtl_sources < manifests/unified_sources.txt
verilator --binary --timing -O3 -j 8 -Wno-fatal -Wno-WIDTH -Wno-UNOPTFLAT \
  --top-module tb_uhbs_autonomous -GUNROLL=3 -GLANES=2 -GSWAP=0 \
  --Mdir build/v4.1/plan_u3_l2 "${rtl_sources[@]}" tb/integration/tb_uhbs_autonomous.sv
for profile in slh_128f slh_192f slh_256f; do
  build/v4.1/plan_u3_l2/Vtb_uhbs_autonomous \
    "+IMAGE=manifests/experiments/unified_hbs_v4.1/slh_only/images/$profile"
done
vivado -mode tcl -nolog -nojournal <<'TCL'
set argv {plan_u3_l2_synth 2 3}
set argc 3
set f [open experiments/v4.1/synth.tcl]
set script [read $f]
close $f
set script [string map [list {set root [file normalize [file join [file dirname [info script]] ../..]]} {set root [pwd]} {$unroll != 2} {$unroll ni {1 2 3}}] $script]
eval $script
exit
TCL
```

综合只在 Tcl 内存副本中放开参数检查，没有修改当时的生产源码。布线日志中的中间 slack 仅供瓶颈分析，不据此填入最终频率。
