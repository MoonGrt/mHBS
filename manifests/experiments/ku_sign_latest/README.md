# KU 最新实验原始证据

本目录独立于项目根目录 `build/`。保存原 K∈{1,2,4}、U∈{1,2,3,4} 的面积与三参数集 Sign 仿真，以及最新汇总中引用的全部历史时序尝试。新十六点综合证据另见 `../ku_sixteen_area_20261006_v1/`；汇总入口为 [KU Sign ATP 报告](../../../docs/v4.2/KU_Sign_ATP_150_110_67_48.md)。

## 内容

- `results/v4.2/external_job_message/`：十二点原始输入参数、源码快照、综合资源/分层报告、仿真日志与逐字节输出、U3 补测结果。
- `results/v4.2/sign*/`：固定频率和扫描的原始状态、时序/布线/分层资源报告、ROM 审计、约束与日志；包括中断和失败证据。
- `manifests/experiments/`：原九点扩展回归证据、Program16 对照、镜像和参考向量。
- `experiment_source.tar.gz`：参数化实验源码、模型、测试、实验 Tcl 和脚本；生产 RTL 未被替换。
- `results/*.py` / `results/*.tcl`：原来仅存于工作区 build 的调度脚本、时序脚本和 U3 补测脚本。
- `worktree_changes/`：五个 detached worktree 相对各自 HEAD 的补丁和未跟踪文件包。基础提交记录在同名 JSON 中。
- `archive_manifest.json`：逐文件原路径、大小和 SHA-256。原始 JSON 中的绝对路径及 DCP 哈希均保留为来源信息，不要求这些原路径仍存在。
- `SHA256SUMS`：本目录全部实际文件的校验清单（清单自身除外）。
- `cleanup_manifest.json`：本次清理路径与清理前 Git 提交。

所有原始报告保持原字节。重复的展开网表文本、大型 DCP、编译器中间文件及波形不放入精简归档；原始哈希仍保留在运行元数据中。删除原 build 后不能从旧 DCP 断点继续，若再做实现须从封存源码重新综合。

## 无 build 复核

在仓库根目录执行：

```sh
python3 scripts/report_ku_sign_atp.py
python3 scripts/verify_ku_archive.py
```

第一个命令重新计算全部 36 行资源/周期/ATP，并审计合格频率的原目标周期、Setup >0、Hold ≥0、完整布线和 ROM 内容；不启动 Vivado。第二个命令检查全部原始证据和最新报告的哈希。路径均以本仓库为基准，移动仓库后仍可使用。

指定 U1/U2/U3/U4 频率为 151/112/67/48 MHz，只对 K2 的 128f Sign 有对应通过证据；其他 K/参数集的 ATP 是指定频率估算。

若恢复实验源码，可将 `experiment_source.tar.gz` 解压到新的隔离目录，并将本目录 `manifests/experiments/unified_hbs_v4.2/external_job_message/` 下的镜像和向量复制到相应位置。原调度脚本中的运行目录需要按新目录配置；此归档不承诺原进程或 DCP 断点恢复。
