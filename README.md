# mHBS — image-chain-tree

本分支在移植基线 `a6d113e8` 上增加标准 XMSS／LMS。固定 **SHAKE256、K1U1、一个物理 Hash 通道、一个 Hash 在途**，保留 ABI4、512×64 程序、32×64 描述符及 9 位 PC。原六组 SLH 镜像逐字保留。

| 算法 | 配置名 | 标准参数 |
|---|---|---|
| SLH-DSA-SHAKE | slh_128f/128s、slh_192f/192s、slh_256f/256s | 原六参数 |
| XMSS | xmss_h10/h16/h20 | n=32、w=16、67链、15步 |
| LMS | lms_h10/h15/h20 | m=32、LMOTS w=4、类型0x0B、67链、15步 |

全部实现 Keygen、Sign、Verify。`xmss`／`lms` 默认 h10；旧 omega 名称报迁移错误。Sign 完整重算认证路径，无 BDS。本轮不增加 SHA2 或并发流水。

CHAIN=36执行选中单链；TREE=37按family执行整棵树，包括链、XMSS L-tree／LMS叶压缩、主树与认证路径。image保留R/C、消息摘要、DIGITS、目标q和根比较。stateful禁止TOP_SHORTCUT。 两分支增加 `XMSS_MASK=38`，仅允许 XMSS。XMSS 完整链为 SECRET + 15×(KEY/MASK/F)，共46次 Hash；LMS 完整链为16次 Hash。

## 源码与接口

生产列表为 `sources.txt`：executor、SHAKE recipe/context、Keccak、common、top及可选signature。节点工作区仍为128×256单读单写RAM；XMSS KEY复用SLH专属摘要暂存，无新增节点银行。端口和例化保持紧凑分组。

`common` 使用外部 program/descriptor；`top` 包含ROM和可选签名缓存。新增运行时 `job_index[31:0]`、`job_identifier[127:0]`、`job_lms_c[255:0]`，在Job接受时锁存；SLH连接零。种子及根按现有合同在整个Job期间保持稳定。消息为64位、节点和输出为256位、低字节在先。SLH消息1～87字节，XMSS/LMS为0～87字节。

XMSS/LMS Keygen仅输出32字节root；Sign及缓存保存R/C、67条链节点和h个认证节点。`model/stateful.py` 负责标准公钥和签名的组装、类型、长度、q及端序检查。q的持久化及随机输入由调用方管理。统计全链路64位，保留 `PROFILE_ENABLE`；生产综合显式设为0。

详见 [ABI](docs/ABI.md)、[指令表](docs/ISA.md)、[接口](docs/Job_Interface.md)。

## 生成与验证

```bash
python3 scripts/check_source_import.py --historical
python3 scripts/run_hash_backends.py images
python3 scripts/run_hash_backends.py all --tag example --profile all --jobs 4
python3 scripts/check_stateful_models.py --mode quick
python3 scripts/check_stateful_models.py --mode full --profile xmss_h10
python3 scripts/check_stateful_models.py --mode full --profile lms_h10
python3 scripts/check_recipes.py
python3 scripts/check_hash_backend_contracts.py
```

默认整核回归28项：六组SLH三操作、XMSS/LMS h10三操作、四组高树真实高度Verify。高树Verify使用明确标注的合成认证兄弟节点，不代表完整树生成。h16/h15/h20完整Keygen／Sign不自动生成或执行，h20保持停止。

原SLH输出、缓存、Hash／置换及周期须精确匹配移植基线；新算法核对独立标准参考的完整输出、标准签名、缓存及有序逐Hash轨迹。独立模型另比较宏／显式执行的完整Hash前像和结果多重集，保留重复次数。`--historical` 将原源码映射证明绑定历史冻结快照，只对当前SLH ROM检查逐字兼容，不宣称扩展RTL仍与旧源逐字相同。

## 综合与证据

```bash
python3 scripts/synthesize.py --background
python3 scripts/report_atp.py --run <综合运行目录> --regression <回归目录>
```

Vivado2025.2、xc7a200tffg1156-3、100MHz OOC、每任务2线程、PROFILE_ENABLE=0，仅综合common，不布线。面积不含程序ROM及签名缓存。原SLH基线为 **15,698 LUT／4,205 FF**；增加算法后报告面积增量，不再应用原移植±1%闸门。100MHz ATP为假定频率指标，不能证明布线频率。

新结果归档于 [标准stateful扩展报告](docs/manifests/experiments/image_chain_tree_stateful_20261021_121656/reports/Stateful_Extension.md)，历史移植报告保留。运行日志在build，归档仅保留摘要、冻结RTL、源码与镜像校验及综合证据。
