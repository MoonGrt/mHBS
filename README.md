# HBS 控制粒度消融：ablation

一个项目中保留三种设计，按组件分目录：

```text
rtl/                  # 三套 RTL，分别编译
  i/                  # image：软件控制链与树
  c/                  # image-chain：RTL CHAIN，软件控制树
  t/                  # image-chain-tree：RTL CHAIN 和 TREE
image/
  i/{shake,sha2}/      # 各参数的 program/template/descriptor.mem
  c/{shake,sha2}/
  t/{shake,sha2}/
model/                # 共用模型、参考；variants/ 保存实现差异
scripts/              # 共用构建与测试入口
tb/                   # 共用测试台；i/c/t/ 保存测试台差异
  vectors/{i,c,t}/     # 输入、输出参考数据，不重复保存 ROM
docs/                 # 共用文档和历史实验归档
```

| 设计 | 链与端点归约控制 | Merkle／FORS 树控制 | Program / Template / Descriptor 容量（64位字） |
|---|---|---|---|
| i：image，F4 | 软件程序 | 软件程序 | 256 / 32 / 32 |
| c：image-chain，C1 | RTL CHAIN 模板 | 软件程序 | 128 / 32 / 32 |
| t：image-chain-tree，C3 | RTL CHAIN 模板 | RTL TREE 模板 | 16 / 16 / 32 |

三者均为 K1U1、单物理 Hash 通道，支持 SHAKE／SHA2；各自 ABI 和镜像保持原样。`rtl/<设计>/sources.txt` 是对应构建清单，根目录 `sources.txt` 默认选择 i。来源提交、目录映射及源码校验见 [DESIGNS.json](DESIGNS.json)。历史报告保持原实验内容及结论，差异文档在 `docs/designs/`。

从当前项目根目录运行：

```sh
# SHAKE，SLH-DSA 128f Verify
scripts/ablation.sh i simulate-fast slh_128f verify 1 1
scripts/ablation.sh c simulate-fast slh_128f verify 1 1
scripts/ablation.sh t simulate-fast slh_128f verify 1 1

# SHA2，XMSS h10 Verify
HASH_BACKEND=sha2 scripts/ablation.sh i simulate-fast xmss_h10 verify 1 1

# 只生成真实高度 Verify 向量
scripts/ablation.sh c generate --profile xmss_h20 --hash shake --verify-only

# 100MHz common 综合，不启动布线
scripts/ablation.sh t synthesize 1 1

# 目录兼容性：60组镜像及18项 Verify
python3 scripts/check_ablation.py
```

也可设置 `MHBS_DESIGN=i|c|t` 后直接使用共用脚本或 Python 模型，默认 i。Python 使用 `--hash shake|sha2`，Shell 使用 `HASH_BACKEND=shake|sha2`。仿真自动把规范镜像与输入向量组合到 `build/ablation/<设计>/`，不改写源镜像。

高树 h16/h15/h20 不自动启动完整 Keygen／Sign；h20 完整树保持停止。本次仅整理目录并验证功能，未新增综合或布线。历史证据及本次检查见[实验索引](docs/manifests/experiments/INDEX.md)。
