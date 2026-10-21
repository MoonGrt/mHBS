# image-chain ATP候选完整回归

更新时间：2026-10-21T16:17:40+08:00；完成：True。

44项整核：{'pending': 0, 'running': 0, 'passed': 44, 'failed': 0}。
逐字节核对输出和签名缓存；核对64位Hash/块数；对相同冻结输入逐Hash前像和完整结果指纹进行count/SUM256/XOR256比较。指纹比较是概率性检查。
高树只执行真实高度Verify；h16/h15/h20完整Keygen、Sign未执行。详细日志保留在build，不复制到归档。

| 后端/参数/操作 | 原周期 | 新周期 | Hash | 块数 | 状态 |
|---|---:|---:|---:|---:|---|
| sha2/lms_h10/sign | 81206896 | 81139250 | 1101347 | 1136162 | passed |
| sha2/slh_128f/sign | 15616296 | 15409870 | 104925 | 211432 | passed |
| sha2/xmss_h10/sign | 498032990 | 497967390 | 3431950 | 7001183 | passed |
| shake/lms_h10/sign | 28707044 | 28639398 | 1101392 | 1116752 | passed |
| shake/slh_128f/sign | 3165156 | 2958730 | 104937 | 105641 | passed |
| shake/xmss_h10/sign | 86744390 | 86678790 | 3431815 | 3431815 | passed |
| sha2/lms_h10/keygen | 81156946 | 81093476 | 1100799 | 1135614 | passed |
| sha2/lms_h10/verify | 44884 | 44522 | 538 | 581 | passed |
| sha2/lms_h15/verify | 46049 | 45527 | 543 | 591 | passed |
| sha2/lms_h20/verify | 47214 | 46532 | 548 | 601 | passed |
| sha2/slh_128f/keygen | 646705 | 646025 | 4495 | 9062 | passed |
| sha2/slh_128f/verify | 991874 | 978648 | 6413 | 13031 | passed |
| sha2/slh_128s/keygen | 41400649 | 41355617 | 287743 | 580094 | passed |
| sha2/slh_128s/sign | 328510072 | 323019324 | 2185959 | 4404167 | passed |
| sha2/slh_128s/verify | 353314 | 343174 | 2190 | 4445 | passed |
| sha2/xmss_h10/keygen | 497796451 | 497735027 | 3430396 | 6998007 | passed |
| sha2/xmss_h10/verify | 269965 | 269623 | 1835 | 3747 | passed |
| sha2/xmss_h16/verify | 280765 | 280243 | 1904 | 3891 | passed |
| sha2/xmss_h20/verify | 264315 | 263673 | 1785 | 3657 | passed |
| shake/lms_h10/keygen | 28681159 | 28617689 | 1100799 | 1116159 | passed |
| shake/lms_h10/verify | 16414 | 16052 | 493 | 508 | passed |
| shake/lms_h15/verify | 16994 | 16472 | 498 | 513 | passed |
| shake/lms_h20/verify | 17574 | 16892 | 503 | 518 | passed |
| shake/slh_128f/keygen | 112902 | 112222 | 4495 | 4527 | passed |
| shake/slh_128f/verify | 232010 | 218752 | 6441 | 6533 | passed |
| shake/slh_128s/keygen | 7229886 | 7184854 | 287743 | 289791 | passed |
| shake/slh_128s/sign | 69160919 | 63670171 | 2185897 | 2200231 | passed |
| shake/slh_128s/verify | 92911 | 82781 | 2159 | 2189 | passed |
| shake/slh_192f/keygen | 164422 | 163742 | 6543 | 6615 | passed |
| shake/slh_192f/sign | 6344764 | 5567570 | 168881 | 170462 | passed |
| shake/slh_192f/verify | 317830 | 301986 | 8922 | 9126 | passed |
| shake/slh_192s/keygen | 10527166 | 10482134 | 418815 | 423423 | passed |
| shake/slh_192s/sign | 163684340 | 138286586 | 3766890 | 3799140 | passed |
| shake/slh_192s/verify | 128857 | 115863 | 3057 | 3123 | passed |
| shake/slh_256f/keygen | 433230 | 431846 | 17183 | 17439 | passed |
| shake/slh_256f/sign | 13152711 | 11513717 | 345414 | 349758 | passed |
| shake/slh_256f/verify | 332510 | 314812 | 9152 | 9432 | passed |
| shake/slh_256s/keygen | 6932670 | 6910166 | 274943 | 279039 | passed |
| shake/slh_256s/sign | 171898338 | 139268234 | 3280290 | 3313047 | passed |
| shake/slh_256s/verify | 185150 | 169042 | 4574 | 4707 | passed |
| shake/xmss_h10/keygen | 86697854 | 86636430 | 3430396 | 3430396 | passed |
| shake/xmss_h10/verify | 53376 | 53034 | 1970 | 1970 | passed |
| shake/xmss_h16/verify | 50937 | 50415 | 1859 | 1859 | passed |
| shake/xmss_h20/verify | 52866 | 52224 | 1920 | 1920 | passed |

附加检查：{'shake_recipes': 'passed', 'shake_recipes_synthesis': 'passed', 'shake_signature_views': 'passed', 'shake_slh_128f_stall_reset': 'passed', 'shake_slh_128f_truncate': 'passed', 'shake_slh_128f_tamper1': 'passed', 'shake_slh_128f_tamper2': 'passed', 'shake_slh_128f_tamper3': 'passed', 'shake_slh_128f_tamper4': 'passed', 'shake_slh_128f_tamper5': 'passed', 'shake_xmss_h10_stall_reset': 'passed', 'shake_xmss_h10_truncate': 'passed', 'shake_xmss_h10_tamper1': 'passed', 'shake_xmss_h10_tamper2': 'passed', 'shake_xmss_h10_tamper3': 'passed', 'shake_xmss_h10_tamper4': 'passed', 'shake_xmss_h10_tamper5': 'passed', 'shake_lms_h10_stall_reset': 'passed', 'shake_lms_h10_truncate': 'passed', 'shake_lms_h10_tamper1': 'passed', 'shake_lms_h10_tamper2': 'passed', 'shake_lms_h10_tamper3': 'passed', 'shake_lms_h10_tamper4': 'passed', 'shake_lms_h10_tamper5': 'passed', 'shake_xmss_h10_q_overflow': 'passed', 'shake_lms_h10_q_overflow': 'passed', 'sha2_recipes': 'passed', 'sha2_recipes_synthesis': 'passed', 'sha2_signature_views': 'passed', 'sha2_slh_128f_stall_reset': 'passed', 'sha2_slh_128f_truncate': 'passed', 'sha2_slh_128f_tamper1': 'passed', 'sha2_slh_128f_tamper2': 'passed', 'sha2_slh_128f_tamper3': 'passed', 'sha2_slh_128f_tamper4': 'passed', 'sha2_slh_128f_tamper5': 'passed', 'sha2_xmss_h10_stall_reset': 'passed', 'sha2_xmss_h10_truncate': 'passed', 'sha2_xmss_h10_tamper1': 'passed', 'sha2_xmss_h10_tamper2': 'passed', 'sha2_xmss_h10_tamper3': 'passed', 'sha2_xmss_h10_tamper4': 'passed', 'sha2_xmss_h10_tamper5': 'passed', 'sha2_lms_h10_stall_reset': 'passed', 'sha2_lms_h10_truncate': 'passed', 'sha2_lms_h10_tamper1': 'passed', 'sha2_lms_h10_tamper2': 'passed', 'sha2_lms_h10_tamper3': 'passed', 'sha2_lms_h10_tamper4': 'passed', 'sha2_lms_h10_tamper5': 'passed', 'sha2_xmss_h10_q_overflow': 'passed', 'sha2_lms_h10_q_overflow': 'passed', 'control_faults': 'passed'}

日志运行目录：`/tmp/mhbs-image-chain/build/macro_atp_acceptance/20261021_161437`。
