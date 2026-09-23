# ABI 4 七参数点实验

`final.json` 是通过全部门槛后的选择结果；候选目录中的单个 `ppa.json`
不代表最终接受。最终七点必须来自相同 RTL 源码，镜像按参数点分别固定。

## 记录

- `software_gate.json` / `.log`：RTL 修改前完成的独立模型验证及源码摘要。
- `model_gate.json`：七点完整输出摘要、Hash/置换计数及镜像参数。
- `boundary_counts.json`：q=0/1023 的独立已验证向量计数。
- `candidates/`：各轮综合筛选、布线报告、源码快照和来源摘要。
- `screening.csv`：候选资源、LUTRAM、周期、时序和 ATP；综合统一按 100 MHz。
- `simulations/`：正常流、背压/交换、单双 lane、索引边界及状态驻留日志。
- `verification.json`：最终源码对应的验证矩阵及单元测试来源摘要。
- `verification_sources/`、`icarus_units.log`：最终单元测试源码与日志。
- `tool_versions.json`：Icarus、Verilator、Vivado 实际版本输出。
- `comparison.csv` / `.json`：当前七点与论文的资源、Keygen/Sign 周期、时间、ATP。

## 候选命名

`v4_` 为功能扩展初版；`v4b_` 增加静态裁剪、直接输出和双 lane FORS 叶计算；
`v4c_` 是 B 版禁止 DSP 推断的综合对照；`v4d_` 增加吸收输入流水、静态前缀，
并继续禁止 DSP 推断。后缀 `uN_lM` 表示每周期 Keccak 轮数和 lane 数。
模拟后缀 `sN_bM_qQ` 表示交换、背压、索引；省略 q 时使用基准索引。
所有阶段的 Hash 算法、选定向量和 Keygen 完整树工作量一致。

早期候选只用于解释筛选过程，不与最终版本的周期或面积交叉拼接。
旧 ABI 3 数据和未完成 U4 候选保留在相邻 `unified_hbs_V3/` 目录中。

## 复现

```bash
make reproduce-paper-comparison
python3 scripts/replay_profile.py slh_192f --run rtl-profile-test
python3 scripts/replay_profile.py slh_256f --run route-profile
```

默认解包到 `build/replay/<profile>`，重复复现请指定新的 `--destination`。
`route-profile` 自动先仿真和综合。归档源文件逐项校验 SHA-256 后才解包。
重新布线的结果可能变化；归档报告的算术、来源及验收核验不依赖重新布线。

全部比较均为 NON_STRICT：FIPS SLH-DSA 与论文 SPHINCS+ 有版本差异；
LMS 使用 SHAKE 研究 profile；固定输入、选定认证路径缓存和分别静态综合
与论文的硬件/测量边界不同。Sign ATP 不能替代 Keygen 或生命周期 ATP。
