# 三粒度设计目录整合验证

更新时间：2026-10-21T18:48:19+08:00；完成：True；通过：True。

`i` = image，`c` = image-chain C1，`t` = image-chain-tree C3。原设计文件、镜像、工具和历史证据按目录隔离，生产文件不作修改。

本轮仅验证搬迁：60组静态镜像、18项 K1U1 Verify；逐字节输出检查，并与冻结原版本比较周期、Hash/块数、动态指标和前像/结果指纹。指纹为概率性核对。

未运行完整高树 Keygen/Sign；未新增综合或布线；现有面积与时序结论仍绑定各自历史冻结源码。

| 设计 | 后端 | 配置 | 状态 | 周期 | Hash | 块数 |
|---|---|---|---|---:|---:|---:|
| c | sha2 | lms_h10 Verify | passed | 44522 | 538 | 581 |
| c | sha2 | slh_128f Verify | passed | 978648 | 6413 | 13031 |
| c | sha2 | xmss_h10 Verify | passed | 269623 | 1835 | 3747 |
| c | shake | lms_h10 Verify | passed | 16052 | 493 | 508 |
| c | shake | slh_128f Verify | passed | 218752 | 6441 | 6533 |
| c | shake | xmss_h10 Verify | passed | 53034 | 1970 | 1970 |
| i | sha2 | lms_h10 Verify | passed | 52671 | 538 | 581 |
| i | sha2 | slh_128f Verify | passed | 1068827 | 6413 | 13031 |
| i | sha2 | xmss_h10 Verify | passed | 279691 | 1835 | 3747 |
| i | shake | lms_h10 Verify | passed | 23571 | 493 | 508 |
| i | shake | slh_128f Verify | passed | 309335 | 6441 | 6533 |
| i | shake | xmss_h10 Verify | passed | 63732 | 1970 | 1970 |
| t | sha2 | lms_h10 Verify | passed | 43872 | 538 | 581 |
| t | sha2 | slh_128f Verify | passed | 956851 | 6413 | 13031 |
| t | sha2 | xmss_h10 Verify | passed | 269003 | 1835 | 3747 |
| t | shake | lms_h10 Verify | passed | 15402 | 493 | 508 |
| t | shake | slh_128f Verify | passed | 196907 | 6441 | 6533 |
| t | shake | xmss_h10 Verify | passed | 52414 | 1970 | 1970 |

综合与时序证据沿用下列原样归档；本次没有新的 hierarchical.rpt / timing.rpt。

- `i`：[原验收记录](../../../../../i/docs/manifests/experiments/image_optimization_20261021_182828/VALIDATION_SUMMARY.json)；[独立历史实验索引](../../../../../i/docs/manifests/experiments/INDEX.md)。
- `c`：[原验收记录](../../../../../c/docs/manifests/experiments/macro_atp_acceptance_20261021_161437/VALIDATION_SUMMARY.json)；[独立历史实验索引](../../../../../c/docs/manifests/experiments/INDEX.md)。
- `t`：[原验收记录](../../../../../t/docs/manifests/experiments/macro_atp_acceptance_20261021_164159/VALIDATION_SUMMARY.json)；[独立历史实验索引](../../../../../t/docs/manifests/experiments/INDEX.md)。
