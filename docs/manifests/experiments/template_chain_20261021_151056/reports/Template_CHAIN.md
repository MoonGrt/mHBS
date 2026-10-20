# image-chain：program 树控制与 CHAIN 模板

更新时间：2026-10-21T15:14:56+08:00；任务完成。

基线 `050512998fea28cc44667a1cd694d5ad5077767c`；K1U1、SHAKE＋SHA2、单物理 Hash lane。
program128×64、template32×64、descriptor32×64；CHAIN为整组链及叶构造；主树/FORS树由program控制，无TREE模板执行。
默认SHAKE28项＋SHA2 16项；高树只执行真实高度Verify，独立合成兄弟路径，不计算完整树。
实际填充块＋完整摘要的count/SUM256/XOR256指纹与VM/独立Verify任务集核对，同时逐字节核对输出和签名缓存。该指纹是概率校验。
使用冻结main输入与原配方；逐Hash前像/结果与显式控制VM核对。链分支改变调度周期，旧opcode36设计属于历史尝试。
整核状态：{'pending': 0, 'running': 0, 'passed': 0, 'failed': 44}。

| 后端 | LUT | FF | BRAM36 | 等效Slice | 状态 |
|---|---:|---:|---:|---:|---|
| shake | — | — | — | — | failed |
| sha2 | — | — | — | — | failed |

100MHz仅用于共同核综合诊断及假定ATP，不含ROM/签名缓存，本轮不布线。

| 后端/参数/操作 | 周期 | Hash | 块 | ATP@100MHz Slice·ms | 主程序CHAIN | TREE | TREE子CHAIN | 状态 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| shake/slh_128f/keygen | — | — | — | — | — | — | — | failed |
| shake/slh_128f/sign | — | — | — | — | — | — | — | failed |
| shake/slh_128f/verify | — | — | — | — | — | — | — | failed |
| shake/slh_192f/keygen | — | — | — | — | — | — | — | failed |
| shake/slh_192f/sign | — | — | — | — | — | — | — | failed |
| shake/slh_192f/verify | — | — | — | — | — | — | — | failed |
| shake/slh_256f/keygen | — | — | — | — | — | — | — | failed |
| shake/slh_256f/sign | — | — | — | — | — | — | — | failed |
| shake/slh_256f/verify | — | — | — | — | — | — | — | failed |
| shake/slh_128s/keygen | — | — | — | — | — | — | — | failed |
| shake/slh_128s/sign | — | — | — | — | — | — | — | failed |
| shake/slh_128s/verify | — | — | — | — | — | — | — | failed |
| shake/slh_192s/keygen | — | — | — | — | — | — | — | failed |
| shake/slh_192s/sign | — | — | — | — | — | — | — | failed |
| shake/slh_192s/verify | — | — | — | — | — | — | — | failed |
| shake/slh_256s/keygen | — | — | — | — | — | — | — | failed |
| shake/slh_256s/sign | — | — | — | — | — | — | — | failed |
| shake/slh_256s/verify | — | — | — | — | — | — | — | failed |
| shake/xmss_h10/keygen | — | — | — | — | — | — | — | failed |
| shake/xmss_h10/sign | — | — | — | — | — | — | — | failed |
| shake/xmss_h10/verify | — | — | — | — | — | — | — | failed |
| shake/lms_h10/keygen | — | — | — | — | — | — | — | failed |
| shake/lms_h10/sign | — | — | — | — | — | — | — | failed |
| shake/lms_h10/verify | — | — | — | — | — | — | — | failed |
| sha2/slh_128f/keygen | — | — | — | — | — | — | — | failed |
| sha2/slh_128f/sign | — | — | — | — | — | — | — | failed |
| sha2/slh_128f/verify | — | — | — | — | — | — | — | failed |
| sha2/slh_128s/keygen | — | — | — | — | — | — | — | failed |
| sha2/slh_128s/sign | — | — | — | — | — | — | — | failed |
| sha2/slh_128s/verify | — | — | — | — | — | — | — | failed |
| sha2/xmss_h10/keygen | — | — | — | — | — | — | — | failed |
| sha2/xmss_h10/sign | — | — | — | — | — | — | — | failed |
| sha2/xmss_h10/verify | — | — | — | — | — | — | — | failed |
| sha2/lms_h10/keygen | — | — | — | — | — | — | — | failed |
| sha2/lms_h10/sign | — | — | — | — | — | — | — | failed |
| sha2/lms_h10/verify | — | — | — | — | — | — | — | failed |
| shake/xmss_h16/verify | — | — | — | — | — | — | — | failed |
| shake/xmss_h20/verify | — | — | — | — | — | — | — | failed |
| shake/lms_h15/verify | — | — | — | — | — | — | — | failed |
| shake/lms_h20/verify | — | — | — | — | — | — | — | failed |
| sha2/xmss_h16/verify | — | — | — | — | — | — | — | failed |
| sha2/xmss_h20/verify | — | — | — | — | — | — | — | failed |
| sha2/lms_h15/verify | — | — | — | — | — | — | — | failed |
| sha2/lms_h20/verify | — | — | — | — | — | — | — | failed |

附加检查：142项，失败75。
未验证：XMSS h16/h20、LMS h15/h20完整Keygen/Sign；h20完整树保持停止。
详细日志：`/tmp/mhbs-image-chain/build/template_chain/20261021_151056`；归档仅保留摘要、冻结RTL和综合证据。
