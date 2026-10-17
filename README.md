# mHBS image-chain-tree

移植父项目固定提交 `cc1f60b408f38f2c1346f2300681ce1692d0ce16` 的 ABI4 设计。分支独立基于 `050512998fea28cc44667a1cd694d5ad5077767c`，保留源 ABI、镜像和 K1U1 执行语义。

单物理 SHAKE256 通道，每周期一轮 Keccak，仅一个 Hash 在途。支持 SLH-DSA-SHAKE 128f/192f/256f/128s/192s/256s 的 Keygen、Sign、Verify。`CHAIN` 完成单条链，`TREE` 完成当前 GROUP/LAYER 的单棵树；外层组、层和列表压缩仍由 image 控制。本分支不提供 SHA2、XMSS/LMS 或 P/U 扩展。

## 构建与检查

```bash
python3 scripts/check_source_import.py
python3 scripts/check_standard_models.py -q
python3 scripts/check_hash_backend_contracts.py --out build/image-chain-tree/units
python3 scripts/run_hash_backends.py all --tag check --jobs 4 --extended
python3 scripts/check_hash_work.py --image-root build/image-chain-tree/check/images --out build/image-chain-tree/check/hash_work --jobs 3
python3 scripts/check_statistics.py --run build/image-chain-tree/check --profile all --jobs 2
python3 scripts/check_top_signature.py --vector build/image-chain-tree/check/vectors/slh_128f/sign --out build/image-chain-tree/check/top --jobs 2
./scripts/synthesize.sh --background
```

程序位于 `tb/vectors/<profile>/program.mem`（512×64），描述符位于相邻的 `descriptor.mem`（32×64），没有 template。`model/microcode.py`、`model/mHBS.py`、`model/executor.py` 分别定义 ISA、编译器和逐指令 VM；三个入口共用同一份镜像。重新生成镜像：`python3 scripts/run_hash_backends.py images`。

`rtl/top/common.sv` 是源顶层按原 partition 工具提取的共同核；`rtl/top/top.sv` 保存 ROM 和签名缓存外壳。生产清单为 `sources.txt`。端口与 32 位统计保持源设计，面积测量使用 `PROFILE_ENABLE=0`；程序 ROM 和签名缓存不计入共同核面积。

源校验不依赖父仓库：原始源文件、12个镜像和原回归证据保存在[移植实验](docs/manifests/experiments/image_chain_tree_import_20261021/reports/Import.md)。检查器对生产文件执行受控标识符/路径映射后的代码 token 比较，并逐字核对原始及重新生成的镜像。这不宣称形式验证工具等价。

[ABI](docs/ABI.md) · [ISA](docs/ISA.md) · [Job接口](docs/Job_Interface.md) · [架构](docs/Architecture.md)

100 MHz 综合结果仅用于面积与诊断路径，不代表完成布线或已验证板上频率。历史报告对应各自冻结源码，不能作为本分支当前结果。
