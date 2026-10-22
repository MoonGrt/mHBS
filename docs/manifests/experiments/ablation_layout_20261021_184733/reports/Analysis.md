# 三粒度设计目录整合验证

更新时间：2026-10-21T18:47:35+08:00；完成：True；通过：False。

`i` = image，`c` = image-chain C1，`t` = image-chain-tree C3。原设计文件、镜像、工具和历史证据按目录隔离，生产文件不作修改。

本轮仅验证搬迁：60组静态镜像、18项 K1U1 Verify；逐字节输出检查，并与冻结原版本比较周期、Hash/块数、动态指标和前像/结果指纹。指纹为概率性核对。

未运行完整高树 Keygen/Sign；未新增综合或布线；现有面积与时序结论仍绑定各自历史冻结源码。

| 设计 | 后端 | 配置 | 状态 | 周期 | Hash | 块数 |
|---|---|---|---|---:|---:|---:|

综合与时序证据沿用下列原样归档；本次没有新的 hierarchical.rpt / timing.rpt。

- `i`：[原验收记录](../../../../../i/docs/manifests/experiments/image_optimization_20261021_182828/VALIDATION_SUMMARY.json)；[独立历史实验索引](../../../../../i/docs/manifests/experiments/INDEX.md)。
- `c`：[原验收记录](../../../../../c/docs/manifests/experiments/macro_atp_acceptance_20261021_161437/VALIDATION_SUMMARY.json)；[独立历史实验索引](../../../../../c/docs/manifests/experiments/INDEX.md)。
- `t`：[原验收记录](../../../../../t/docs/manifests/experiments/macro_atp_acceptance_20261021_164159/VALIDATION_SUMMARY.json)；[独立历史实验索引](../../../../../t/docs/manifests/experiments/INDEX.md)。

失败原因：t: static image generation failed; /tmp/mhbs-ablation/build/ablation_layout/20261021_184733/t_static_images.log
