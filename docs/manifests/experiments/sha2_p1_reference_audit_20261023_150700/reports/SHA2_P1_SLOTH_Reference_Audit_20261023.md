# SHA2 P1U1：SLOTH 周期差与独立 C 签名核验

完成时间：2026-10-23T15:13:48+08:00。SHA2、P1U1、SLH-DSA-128f、internal 签名接口。

已确认：本轮六组完整 RTL 签名及签名缓存均与用户指定的 `../../source/slhdsa-c` 完全一致；两个 NIST ACVP 样例也逐字节一致。当前性能的主要损失是重复压缩公共种子前缀，不能由周期差认定签名错误。

本次仅增加独立 C 核验入口和可选二进制输出，生产 RTL 的十个源文件均未变化，且与 `dual_pu_route_matrix_20261023_100739` 冻结设计一致。现有矩阵未被停止。

## 实际签名字节核验

每组均执行实际 P1U1 Keygen、Sign、Verify（共18项）；从 RTL 输出流和 signature 缓存分别导出17,088字节。C 适配器仅从 job/message 读取种子、随机数和消息，直接调用外部 C 的 `slh_keygen_internal`、`slh_sign_internal`、`slh_verify_internal`，不调用本仓库模型、ROM或配方执行器。

| 用例 | 消息字节 | RTL Sign周期 | RTL压缩次数 | C实际压缩次数 | 签名／缓存与C |
|---|---:|---:|---:|---:|---|
| default | 1 | 15,192,941 | 211,432 | 106,513 | 全字节一致 |
| msg1_randomized | 1 | 15,195,066 | 211,462 | 106,528 | 全字节一致 |
| msg56_randomized | 56 | 15,197,385 | 211,494 | 106,545 | 全字节一致 |
| msg87_randomized | 87 | 15,193,158 | 211,435 | 106,516 | 全字节一致 |
| acvp_tg13_tc115 | 1 | 15,195,072 | 211,462 | 106,528 | 全字节一致 |
| acvp_tg49_tc433 | 1 | 15,197,217 | 211,492 | 106,543 | 全字节一致 |

全部用例的实际 RTL Keygen 输出等于 C 的 `SK || PK`，公钥为32字节；C 验证实际 RTL 签名通过，翻转签名或消息后拒绝。额外把实际 RTL 签名翻转一位送入独立 C 工具，确认核验以非零退出码拒绝。

两个ACVP样例为 tg13/tc115（确定性）与 tg49/tc433（随机化），来源提交 `975de31eb83d87039ec88934fdc47d8c312b892d`；本地原始JSON校验为 `62b42e7c27fda5de8a94aba2943ae413b59b6ea08141f3bc035b1eceae235dba`，未联网替换输入。

默认签名SHA256：`7d620e77679ba029c2783b4a8345dffbe7fae5c4d04aff4bb9d50b7df509fae1`。原始 C 构建和启用现有压缩统计的 C 构建均独立执行并比较公私钥和完整签名，避免统计宏改变功能而未察觉。

## 周期损失：公共前缀没有缓存

| 默认SLH SHA2-128f Sign | 数量／周期 |
|---|---:|
| 当前P1U1实测周期 | 15,192,941 |
| 用户提供的SLOTH周期 | 9,127,150 |
| 完整SHA256调用 | 104,925 |
| 当前实际压缩块 | 211,432 |
| 每块接受到完成的实测周期 | 65（64轮＋feed-forward） |
| 压缩本身总周期 | 13,743,080 |
| 其他调度、格式化和执行控制周期 | 1,449,861 |
| 相同公共种子首块执行次数 | 104,920 |
| C参考使用前缀缓存后的实际压缩块 | 106,513 |

当前总周期比SLOTH高66.46%。`sha2-recipe.sv:550` 为 SLH_SEED／SLH_VALUE／SLH_LIST 构造同一个 `PK.seed || 48零字节` 首块，`:758–760`、`:781–786` 每个新Hash从IV和块0开始，因此重复处理公共前缀。

SLOTH的 `drv/sloth_sha2.c:591–608` 预计算公共前缀中间态并写入S256_SEED；`rtl/sha256_sloth.v:208–229` 从该状态执行F／PRF，`:262–267` 自动衔接链步骤。外部C参考 `slh_sha2.c` 同样缓存并复制公共种子的SHA256上下文。

六个用例均精确满足 `C压缩块 = RTL压缩块 − (RTL完整Hash数 − 5) + 1`。5次为HMAC内外层2次及H_msg／两次MGF1共3次；其余地址Hash均有相同公共首块，C仅在Job初始化时计算一次。因此默认少104,919次压缩，差额全部得到解释。

重复首块共耗6,819,800拍，占当前总周期44.89%；留一次初始化后可避免104,919次压缩。仅机械扣除这些65拍压缩、保持其他开销不变，得到8,373,206拍（比SLOTH低8.26%）。这只是结构估算，并非已经实现或仿真实测的候选。

## 为什么不能照搬SHAKE的比例

当前SHAKE P1U1为2,619,846拍、105,641次置换；24轮的运算量为2,535,384拍，其他开销仅84,462拍。用户提供SLOTH SHAKE为4,903,978拍。SHA2除了64轮压缩更长，还存在上述公共前缀重复和更大的格式化／控制开销；SLOTH已有前缀缓存及链自主执行，不能推断SHA2必然获得与SHAKE相同的周期优势。SLOTH论文周期取用户提供值，本次没有声称重测其完整系统，也未确认其消息与随机种子恰与本仓库默认用例相同。

## 证据与复现

本地slhdsa-c和SLOTH目录均没有独立Git元数据，无法声称其上游commit；已归档实际源码和逐文件校验。`slhdsa-c` README声明该代码由SLotH驱动派生，属于独立于本仓库模型／RTL的实现；额外使用固定NIST向量作第二个结果依据。

默认C参考的源文件集合SHA256：`bd152813dec84d3dac95a864fcf18c60cfb10fca6db7d1e51875b6c59f4d4784`。

```bash
HASH_BACKEND=sha2 SIM_COMPILE_ONLY=1 SIM_FAST_OPT_SLOW=-O1 bash scripts/simulate_fast.sh slh_128f sign 1 1
build/sim/P1U1_fast_o3_synthesis0_slow_O1_sha2/obj/Vtb_fast +VECTOR=tb/vectors/sha2/slh_128f/sign +OUTPUT_BIN=/tmp/sha2_p1_sig.bin +CACHE_BIN=/tmp/sha2_p1_cache.bin
python3 scripts/check_slhdsa_c.py --vector tb/vectors/sha2/slh_128f/sign --output build/sha2_c_recheck --verify-signature /tmp/sha2_p1_sig.bin
```

报告JSON保留六组周期、签名校验和、C来源与逐项结果。归档包含冻结RTL、参考源码、审计工具、验证摘要及同源码已有P1U1 common综合／布线上下文报告；没有启动新的综合或布线。原始输入向量、实际二进制签名、编译／仿真细节日志保留在 `build/sha2_p1_audit/20261023_150700`，明细日志不复制进实验归档。

后续优化应优先缓存单Job公共种子的256位原始压缩链值，不能缓存已填充的SHA256完整摘要；续算需保留已处理64字节的逻辑长度，并在Job／公共种子切换及复位时失效。优化后实际压缩计数应反映省下的块，再重新测量周期、面积和布线频率，不能沿用本轮结构估算作为ATP。
