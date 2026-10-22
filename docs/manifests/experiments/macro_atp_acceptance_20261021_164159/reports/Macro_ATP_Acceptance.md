# image-chain-tree ATP候选完整回归

更新时间：2026-10-21T16:45:56+08:00；完成：True。

44项整核：{'pending': 0, 'running': 0, 'passed': 44, 'failed': 0}。
逐字节核对输出和签名缓存；核对64位Hash/块数；对相同冻结输入逐Hash前像和完整结果指纹进行count/SUM256/XOR256比较。指纹比较是概率性检查。
高树只执行真实高度Verify；h16/h15/h20完整Keygen、Sign未执行。详细日志保留在build，不复制到归档。

| 后端/参数/操作 | 原周期 | 新周期 | Hash | 块数 | 状态 |
|---|---:|---:|---:|---:|---|
| sha2/lms_h10/sign | 81024466 | 80956882 | 1101347 | 1136162 | passed |
| sha2/slh_128f/sign | 15071002 | 15065766 | 104925 | 211432 | passed |
| sha2/xmss_h10/sign | 497855675 | 497788091 | 3431950 | 7001183 | passed |
| shake/lms_h10/sign | 28524614 | 28457030 | 1101392 | 1116752 | passed |
| shake/slh_128f/sign | 2619846 | 2614610 | 104937 | 105641 | passed |
| shake/xmss_h10/sign | 86567075 | 86499491 | 3431815 | 3431815 | passed |
| sha2/lms_h10/keygen | 80984975 | 80917391 | 1100799 | 1135614 | passed |
| sha2/lms_h10/verify | 43938 | 43872 | 538 | 581 | passed |
| sha2/lms_h15/verify | 44678 | 44612 | 543 | 591 | passed |
| sha2/lms_h20/verify | 45418 | 45352 | 548 | 601 | passed |
| sha2/slh_128f/keygen | 644917 | 644645 | 4495 | 9062 | passed |
| sha2/slh_128f/verify | 957599 | 956851 | 6413 | 13031 | passed |
| sha2/slh_128s/keygen | 41281429 | 41264021 | 287743 | 580094 | passed |
| sha2/slh_128s/sign | 313991183 | 313869565 | 2185959 | 4404167 | passed |
| sha2/slh_128s/verify | 326844 | 326606 | 2190 | 4445 | passed |
| sha2/xmss_h10/keygen | 497629595 | 497562011 | 3430396 | 6998007 | passed |
| sha2/xmss_h10/verify | 269069 | 269003 | 1835 | 3747 | passed |
| sha2/xmss_h16/verify | 279389 | 279323 | 1904 | 3891 | passed |
| sha2/xmss_h20/verify | 262619 | 262553 | 1785 | 3657 | passed |
| shake/lms_h10/keygen | 28509188 | 28441604 | 1100799 | 1116159 | passed |
| shake/lms_h10/verify | 15468 | 15402 | 493 | 508 | passed |
| shake/lms_h15/verify | 15623 | 15557 | 498 | 513 | passed |
| shake/lms_h20/verify | 15778 | 15712 | 503 | 518 | passed |
| shake/slh_128f/keygen | 111114 | 110842 | 4495 | 4527 | passed |
| shake/slh_128f/verify | 197655 | 196907 | 6441 | 6533 | passed |
| shake/slh_128s/keygen | 7110666 | 7093258 | 287743 | 289791 | passed |
| shake/slh_128s/sign | 54642035 | 54520417 | 2185897 | 2200231 | passed |
| shake/slh_128s/verify | 66466 | 66228 | 2159 | 2189 | passed |
| shake/slh_192f/keygen | 162634 | 162234 | 6543 | 6615 | passed |
| shake/slh_192f/sign | 4290061 | 4282361 | 168881 | 170462 | passed |
| shake/slh_192f/verify | 276680 | 275580 | 8922 | 9126 | passed |
| shake/slh_192s/keygen | 10407946 | 10382346 | 418815 | 423423 | passed |
| shake/slh_192s/sign | 96522494 | 96343644 | 3766890 | 3799140 | passed |
| shake/slh_192s/verify | 94902 | 94552 | 3057 | 3123 | passed |
| shake/slh_256f/keygen | 429578 | 428522 | 17183 | 17439 | passed |
| shake/slh_256f/sign | 8818996 | 8802166 | 345414 | 349758 | passed |
| shake/slh_256f/verify | 286435 | 285313 | 9152 | 9432 | passed |
| shake/slh_256s/keygen | 6873098 | 6856202 | 274943 | 279039 | passed |
| shake/slh_256s/sign | 85610582 | 85475942 | 3280290 | 3313047 | passed |
| shake/slh_256s/verify | 143060 | 142532 | 4574 | 4707 | passed |
| shake/xmss_h10/keygen | 86530998 | 86463414 | 3430396 | 3430396 | passed |
| shake/xmss_h10/verify | 52480 | 52414 | 1970 | 1970 | passed |
| shake/xmss_h16/verify | 49561 | 49495 | 1859 | 1859 | passed |
| shake/xmss_h20/verify | 51170 | 51104 | 1920 | 1920 | passed |

附加检查：{'shake_recipes': 'passed', 'shake_recipes_synthesis': 'passed', 'shake_signature_views': 'passed', 'shake_slh_128f_stall_reset': 'passed', 'shake_slh_128f_truncate': 'passed', 'shake_slh_128f_tamper1': 'passed', 'shake_slh_128f_tamper2': 'passed', 'shake_slh_128f_tamper3': 'passed', 'shake_slh_128f_tamper4': 'passed', 'shake_slh_128f_tamper5': 'passed', 'shake_xmss_h10_stall_reset': 'passed', 'shake_xmss_h10_truncate': 'passed', 'shake_xmss_h10_tamper1': 'passed', 'shake_xmss_h10_tamper2': 'passed', 'shake_xmss_h10_tamper3': 'passed', 'shake_xmss_h10_tamper4': 'passed', 'shake_xmss_h10_tamper5': 'passed', 'shake_lms_h10_stall_reset': 'passed', 'shake_lms_h10_truncate': 'passed', 'shake_lms_h10_tamper1': 'passed', 'shake_lms_h10_tamper2': 'passed', 'shake_lms_h10_tamper3': 'passed', 'shake_lms_h10_tamper4': 'passed', 'shake_lms_h10_tamper5': 'passed', 'shake_xmss_h10_q_overflow': 'passed', 'shake_lms_h10_q_overflow': 'passed', 'sha2_recipes': 'passed', 'sha2_recipes_synthesis': 'passed', 'sha2_signature_views': 'passed', 'sha2_slh_128f_stall_reset': 'passed', 'sha2_slh_128f_truncate': 'passed', 'sha2_slh_128f_tamper1': 'passed', 'sha2_slh_128f_tamper2': 'passed', 'sha2_slh_128f_tamper3': 'passed', 'sha2_slh_128f_tamper4': 'passed', 'sha2_slh_128f_tamper5': 'passed', 'sha2_xmss_h10_stall_reset': 'passed', 'sha2_xmss_h10_truncate': 'passed', 'sha2_xmss_h10_tamper1': 'passed', 'sha2_xmss_h10_tamper2': 'passed', 'sha2_xmss_h10_tamper3': 'passed', 'sha2_xmss_h10_tamper4': 'passed', 'sha2_xmss_h10_tamper5': 'passed', 'sha2_lms_h10_stall_reset': 'passed', 'sha2_lms_h10_truncate': 'passed', 'sha2_lms_h10_tamper1': 'passed', 'sha2_lms_h10_tamper2': 'passed', 'sha2_lms_h10_tamper3': 'passed', 'sha2_lms_h10_tamper4': 'passed', 'sha2_lms_h10_tamper5': 'passed', 'sha2_xmss_h10_q_overflow': 'passed', 'sha2_lms_h10_q_overflow': 'passed'}

日志运行目录：`/tmp/mhbs-image-chain-tree/build/macro_atp_acceptance/20261021_164159`。
