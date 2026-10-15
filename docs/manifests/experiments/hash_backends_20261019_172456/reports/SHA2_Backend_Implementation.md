# SHAKE／SHA2 双后端实现记录

本次增加编译时 SHA2 后端，默认 SHAKE 命令与算法入口继续有效。生产 RTL 已冻结，完整回归与综合正在后台；最终通过数、周期和面积以 [自动更新结果](Hash_Backends_20261019_172456.md) 为准。本报告不提前认定全部验收通过。

标准依据：[RFC 8391](https://www.rfc-editor.org/rfc/rfc8391.html)、[RFC 8554](https://www.rfc-editor.org/rfc/rfc8554.html)、[FIPS 205](https://nvlpubs.nist.gov/nistpubs/FIPS/NIST.FIPS.205.pdf)。

## 参数与硬件

- `MHBS_SHA2` 未定义时编译 `shake-recipe.sv`；定义时编译同接口的 `sha2-recipe.sv`，后者使用一个 `sha256` 压缩通道。旧 `recipe.sv` 已更名。保留全部30个合法 P/U 组合和单 Hash lane。
- SHA2 支持 XMSS h10/16/20（OID 1/2/3）、LMS h10/15/20（LMS 6/7/8，LMOTS 3）以及 SLH-SHA2-128f/s。h20 保留配置与实现，本轮不运行其完整 Keygen/Sign。
- profile bit5 为后端标志，低5位配置码不变，高位必须为零；宏与 ROM 不符时拒绝执行，SHA2 拒绝 SLH192/256。节点／消息／公钥／签名握手和格式不变。
- SHA256 使用 P 级、每级 U 轮的循环通道；超出第63轮的尾轮旁路工作状态和消息调度窗口，最后单独寄存 feed-forward。配方阶段与压缩块状态分开，多块完成后才推进链、Key/Mask 或 HMAC/MGF1。
- 保留 XMSS KEY/MASK0/MASK1/FINAL，SLH22字节地址和64字节公共种子前缀，HMAC与MGF1，以及 LMS 标准域分离和34块列表。公共前缀中间态不缓存。
- 新SHA2 formatter每块至少7拍：SELECT、PREFETCH、四拍128位BUILD和SEND；压缩通道背压会增加等待。这是首版工作量／周期基线的重要限制，不声称已达到SHAKE流水利用率。

首批100 MHz综合已暴露格式化路径的时序限制：SHA2 P1U1 WNS为−1.670 ns，P12U1为−3.870 ns，最差数据路径分别为11.629 ns与13.829 ns，均终止于块暂存寄存器。自动结果表中的 `passed` 表示综合任务成功完成，不代表时序闭合；这些结果不能证明100 MHz硬件运行。本轮保留此首版测量，尚未进行格式化数据选择和地址计算的时序优化。

## 工具与统计

Python 使用 `--hash shake|sha2`，Shell 使用 `HASH_BACKEND=shake|sha2`；缺省为 SHAKE。SHA2 默认向量目录为 `tb/vectors/sha2`，仿真缓存和综合目录增加后端后缀。模型参数与镜像携带后端，后端不匹配的输出目录不混写。默认全参数生成与完整回归排除 h20 完整树。

SHA2 的 `hash_count` 按完整 SHA256 调用计数，HMAC内／外层与各次MGF1分别计；`permutation_count` 按64字节压缩块计数。快速仿真观察独立功能事件，`SYNTHESIS` 视图继续裁剪统计端口与寄存器。100 MHz综合诊断不能作为布线频率或ATP验收证据。

## 已完成局部验证

| 项目 | 结果 |
|---|---|
| SHA256所有合法P/U | 30/30；每组181个独立压缩向量，包含尾轮旁路、标签对齐、停顿和复位 |
| SHA256综合视图 | P12U1，1/1通过 |
| SHA2标量配方 | P1U1普通、P12U1综合视图各345项；逐字节与Hash／压缩次数核对 |
| SHA2配方裁剪 | RECIPE_MASK=0x101e，74项加非法shape／禁用mask拒绝通过 |
| 批量链 | SHA2与SHAKE各12组，三算法、四个叶地址、乱序、同拍回收、capture与idle tag检查 |
| SHAKE配方兼容 | 459项通过，包括新增非链capture检查 |
| 64位统计 | SHA2 P4U1正常、P1U1综合视图通过 |
| debug裁剪 | SHA2四种SYNTHESIS／signature宏视图预处理与lint通过 |
| 独立模型 | SHA2六参数18组向量生成通过；API两后端20配置检查通过 |
| 整核综合视图 | 三目标P4U1 Sign＋Verify，共6/6；独立功能事件与字节输出核对通过 |
| 后端／类型入口 | 四个宏视图各86项admission检查，以及SHA2错误配方完成检查通过 |
| 整核鲁棒性 | 10/10；随机停顿、双重放、消息篡改、截断恢复、Sign中断重放、批量／标量在途异常；SLH FORS低两位四位置覆盖 |
| NIST ACVP完整RTL Sign | 128f/s各确定性／随机化，共4/4逐字节通过 |

批量局部测试台固定使用低四个标签；`--pipeline 12` 可验证该P/U下四标签交错，但不代表12槽全部占满。全部P/U原语测试另行覆盖压缩通道的标签及尾轮行为。

ACVP绑定用户指定提交 `975de31eb83d87039ec88934fdc47d8c312b892d`。其 `internalProjection.json` 与下载提交对应同一Git blob `5ff182bc29ae00b02a219cf68fff370d9963a12c`；提交关系、下载来源、所选官方向量与模型／RTL摘要保存于 `../prerequisites/acvp/`。未将项目模型自身输出当作官方向量。

修复过程保留两项记录：SHA2批量排空后闲置返回标签必须归零，避免SLH首个capture读到最后退槽；非链固定请求capture按旧接口契约映射。新增的低层非法shape“零Hash”断言只适用SHA2，后续限定了测试台宏范围；SHAKE生产RTL未因此改变。该测试台修正及初次失败日志校验见 `../prerequisites/TOOLS_VALIDATION.json`，后台完整回归使用已冻结的 `tb_fast`，不受影响。

## 后台完整验收

本次后台为87项仿真：SHA2 18项P4U1三操作与9项额外P/U完整Sign，SHAKE 30项完整三操作，以及迁移前冻结版相同30项。SHAKE新旧逐项比较未舍入周期、总周期、Hash、置换和向量校验；公钥／签名及签名缓存由测试台逐字节验证。

两后端各P1U1/P4U1/P12U1，共6次common综合；同器件 `xc7a200tffg1156-3`、100MHz、每Vivado两线程、默认时序驱动，无布局布线。单点超过10分钟标记分析延后且保留后台运行。每个结果记录冻结源码清单SHA、向量SHA与日志SHA；原始日志留运行目录，归档只保存验证摘要、冻结RTL和综合证据。

去除宏包装及分隔空行后，SHAKE recipe主体与迁移前版本逐字节SHA一致（`62b778d2001a2ceeff47553bfbf550272fa1516b1f5c2b33c729b92fbd36f2e3`）；结构证据保存于 `../prerequisites/SHAKE_BODY_IDENTITY.json`，不替代完整周期回归。

迁移前基线取 `build/sha2_migration_baseline`，不是其他历史优化阶段的周期表。背景任务冻结目录为 `build/hash_backends/20261019_172456`。未完成项目保留待完成状态，不能据已通过的小样例宣称大树或全矩阵通过。

独立参考源与复现：`../prerequisites/reference_native/manifest.json` 记录XMSS/Cisco LMS固定提交及适配后源码校验，`adapter.patch` 保存适配补丁。`../candidate/support_source.tar.gz` 按冻结SOURCE.json归档模型、C适配器、构建／仿真／综合脚本、测试台和向量；RTL独立存于rtl.tar.gz。冻结后追加的入口契约测试源单独放在 `../prerequisites/supplement/`，保留校验且未覆盖历史snapshot。
