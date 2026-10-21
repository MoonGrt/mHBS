# 软件 CHAIN 尝试

更新时间：2026-10-21T17:45:19+08:00；完成：True；通过：True。

K1U1，单 Hash 通道；仅综合，不布线。面积使用相同配置 common，不含程序 ROM 或签名缓存。
100MHz仅为 ATP 的假定频率，低频综合时序不代表布线闭合。
44项默认测试＋12项q边界/空消息Sign。h16/h15/h20仅Verify，完整Keygen/Sign本轮未运行。
外部输入、期望输出及计数保持C1认证字节身份；仅替换program/template/descriptor。
逐字节核对输出及签名缓存，比较64位Hash/块数及完整原像/结果count、SUM256、XOR256指纹（概率性多重集检查）。

整核状态：`{'pending': 0, 'running': 0, 'passed': 56, 'failed': 0}`。

| 后端 | C1 LUT / FF | 新 LUT / FF | 新等效Slice | 状态 |
|---|---:|---:|---:|---|
| shake | 20099 / 6324 | 16983 / 5885 | 4981.375 | passed |
| sha2 | 17198 / 7273 | 15218 / 7155 | 4698.875 | passed |

## slh_128f Sign

| 后端 | C1周期 | 新周期 | C1 ATP | 新ATP | 变化 |
|---|---:|---:|---:|---:|---:|
| shake | 2958730 | 6860527 | 172057.546325 | 341748.576846 | +98.625% |
| sha2 | 15409870 | 19216660 | 802642.341287 | 902966.832575 | +12.499% |

## xmss_h10 Sign

| 后端 | C1周期 | 新周期 | C1 ATP | 新ATP | 变化 |
|---|---:|---:|---:|---:|---:|
| shake | 86678790 | 129792756 | 5040588.335475 | 6465463.899195 | +28.268% |
| sha2 | 497967390 | 541083021 | 25937253.967388 | 25424814.803014 | -1.976% |

## lms_h10 Sign

| 后端 | C1周期 | 新周期 | C1 ATP | 新ATP | 变化 |
|---|---:|---:|---:|---:|---:|
| shake | 28639398 | 69049671 | 1665452.592195 | 3439623.048776 | +106.528% |
| sha2 | 81139250 | 121547876 | 4226239.260313 | 5711382.758395 | +35.141% |

## 镜像容量与有效条数

| 后端/参数 | program | template | descriptor |
|---|---|---|---|
| shake/slh_128f | 169/256 | 13/32 | 24/32 |
| shake/slh_192f | 169/256 | 13/32 | 24/32 |
| shake/slh_256f | 169/256 | 13/32 | 24/32 |
| shake/slh_128s | 169/256 | 13/32 | 24/32 |
| shake/slh_192s | 169/256 | 13/32 | 24/32 |
| shake/slh_256s | 169/256 | 13/32 | 24/32 |
| shake/xmss_h10 | 134/256 | 9/32 | 18/32 |
| shake/xmss_h16 | 134/256 | 9/32 | 18/32 |
| shake/xmss_h20 | 134/256 | 9/32 | 18/32 |
| shake/lms_h10 | 123/256 | 10/32 | 21/32 |
| shake/lms_h15 | 123/256 | 10/32 | 21/32 |
| shake/lms_h20 | 123/256 | 10/32 | 21/32 |
| sha2/slh_128f | 169/256 | 13/32 | 24/32 |
| sha2/slh_128s | 169/256 | 13/32 | 24/32 |
| sha2/xmss_h10 | 134/256 | 9/32 | 18/32 |
| sha2/xmss_h16 | 134/256 | 9/32 | 18/32 |
| sha2/xmss_h20 | 134/256 | 9/32 | 18/32 |
| sha2/lms_h10 | 123/256 | 10/32 | 21/32 |
| sha2/lms_h15 | 123/256 | 10/32 | 21/32 |
| sha2/lms_h20 | 123/256 | 10/32 | 21/32 |

## 整核测试

| 测试 | 周期 | Hash | 块数 | 动态指令 | 状态 |
|---|---:|---:|---:|---:|---|
| sha2/lms_h10/sign | 121547876 | 1101347 | 1136162 | 11033319 | passed |
| sha2/slh_128f/sign | 19216660 | 104925 | 211432 | 1152117 | passed |
| sha2/xmss_h10/sign | 541083021 | 3431950 | 7001183 | 11848580 | passed |
| shake/lms_h10/sign | 69049671 | 1101392 | 1116752 | 11033763 | passed |
| shake/slh_128f/sign | 6860527 | 104937 | 105641 | 1152332 | passed |
| shake/xmss_h10/sign | 129792756 | 3431815 | 3431815 | 11848130 | passed |
| sha2/lms_h10/keygen | 121481351 | 1100799 | 1135614 | 11025496 | passed |
| sha2/lms_h10/verify | 55357 | 538 | 581 | 3371 | passed |
| sha2/lms_h15/verify | 56362 | 543 | 591 | 3456 | passed |
| sha2/lms_h20/verify | 57367 | 548 | 601 | 3541 | passed |
| sha2/slh_128f/keygen | 817317 | 4495 | 9062 | 47376 | passed |
| sha2/slh_128f/verify | 1104345 | 6413 | 13031 | 43843 | passed |
| sha2/slh_128s/keygen | 51907797 | 287743 | 580094 | 2895984 | passed |
| sha2/slh_128s/sign | 398193817 | 2185959 | 4404167 | 23315758 | passed |
| sha2/slh_128s/verify | 383169 | 2190 | 4445 | 17073 | passed |
| sha2/xmss_h10/keygen | 540829334 | 3430396 | 6998007 | 11840601 | passed |
| sha2/xmss_h10/verify | 282831 | 1835 | 3747 | 4083 | passed |
| sha2/xmss_h16/verify | 293721 | 1904 | 3891 | 4254 | passed |
| sha2/xmss_h20/verify | 276341 | 1785 | 3657 | 4093 | passed |
| shake/lms_h10/keygen | 69005564 | 1100799 | 1116159 | 11025496 | passed |
| shake/lms_h10/verify | 26077 | 493 | 508 | 3146 | passed |
| shake/lms_h15/verify | 26497 | 498 | 513 | 3231 | passed |
| shake/lms_h20/verify | 26917 | 503 | 518 | 3316 | passed |
| shake/slh_128f/keygen | 287714 | 4495 | 4527 | 47376 | passed |
| shake/slh_128f/verify | 344989 | 6441 | 6533 | 44009 | passed |
| shake/slh_128s/keygen | 18005834 | 287743 | 289791 | 2895984 | passed |
| shake/slh_128s/sign | 140780413 | 2185897 | 2200231 | 23314938 | passed |
| shake/slh_128s/verify | 122236 | 2159 | 2189 | 16918 | passed |
| shake/slh_192f/keygen | 419394 | 6543 | 6615 | 68848 | passed |
| shake/slh_192f/sign | 11380232 | 168881 | 170462 | 1959535 | passed |
| shake/slh_192f/verify | 478733 | 8922 | 9126 | 60259 | passed |
| shake/slh_192s/keygen | 26245866 | 418815 | 423423 | 4207696 | passed |
| shake/slh_192s/sign | 255302096 | 3766890 | 3799140 | 44219250 | passed |
| shake/slh_192s/verify | 172447 | 3057 | 3123 | 23459 | passed |
| shake/slh_256f/keygen | 1091002 | 17183 | 17439 | 176496 | passed |
| shake/slh_256f/sign | 23133113 | 345414 | 349758 | 3947181 | passed |
| shake/slh_256f/verify | 495110 | 9152 | 9432 | 62252 | passed |
| shake/slh_256s/keygen | 17269642 | 274943 | 279039 | 2761776 | passed |
| shake/slh_256s/sign | 230769779 | 3280290 | 3313047 | 41195991 | passed |
| shake/slh_256s/verify | 255202 | 4574 | 4707 | 33756 | passed |
| shake/xmss_h10/keygen | 129730737 | 3430396 | 3430396 | 11840601 | passed |
| shake/xmss_h10/verify | 67052 | 1970 | 1970 | 4308 | passed |
| shake/xmss_h16/verify | 63623 | 1859 | 1859 | 4179 | passed |
| shake/xmss_h20/verify | 65702 | 1920 | 1920 | 4318 | passed |
| shake/xmss_h10/sign_q1 | 129792738 | 3431815 | 3431815 | 11848124 | passed |
| shake/lms_h10/sign_q1 | 69049698 | 1101392 | 1116752 | 11033772 | passed |
| shake/lms_h10/sign_q1023 | 69045048 | 1101317 | 1116677 | 11033022 | passed |
| shake/xmss_h10/sign_q1023 | 129792747 | 3431815 | 3431815 | 11848127 | passed |
| sha2/xmss_h10/sign_q1 | 541110783 | 3432130 | 7001543 | 11849174 | passed |
| sha2/lms_h10/sign_q1 | 121557560 | 1101437 | 1136252 | 11034207 | passed |
| sha2/xmss_h10/sign_q1023 | 541096893 | 3432040 | 7001363 | 11848874 | passed |
| sha2/lms_h10/sign_q1023 | 121554347 | 1101407 | 1136222 | 11033916 | passed |
| shake/xmss_h10/sign_empty | 129796106 | 3431905 | 3431905 | 11848427 | passed |
| shake/lms_h10/sign_empty | 69051557 | 1101422 | 1116782 | 11034072 | passed |
| sha2/lms_h10/sign_empty | 121544626 | 1101317 | 1136132 | 11033016 | passed |
| sha2/xmss_h10/sign_empty | 541103810 | 3432085 | 7001453 | 11849015 | passed |

附加检查：`{'control_faults': 'passed', 'model_verify_bounds': 'passed', 'ordered_hash_trace': 'passed', 'shake_recipes': 'passed', 'shake_recipes_synthesis': 'passed', 'shake_signature_views': 'passed', 'shake_slh_128f_stall_reset': 'passed', 'shake_slh_128f_truncate': 'passed', 'shake_slh_128f_tamper1': 'passed', 'shake_slh_128f_tamper2': 'passed', 'shake_slh_128f_tamper3': 'passed', 'shake_slh_128f_tamper4': 'passed', 'shake_slh_128f_tamper5': 'passed', 'shake_xmss_h10_stall_reset': 'passed', 'shake_xmss_h10_truncate': 'passed', 'shake_xmss_h10_tamper1': 'passed', 'shake_xmss_h10_tamper2': 'passed', 'shake_xmss_h10_tamper3': 'passed', 'shake_xmss_h10_tamper4': 'passed', 'shake_xmss_h10_tamper5': 'passed', 'shake_lms_h10_stall_reset': 'passed', 'shake_lms_h10_truncate': 'passed', 'shake_lms_h10_tamper1': 'passed', 'shake_lms_h10_tamper2': 'passed', 'shake_lms_h10_tamper3': 'passed', 'shake_lms_h10_tamper4': 'passed', 'shake_lms_h10_tamper5': 'passed', 'shake_xmss_h10_q_overflow': 'passed', 'shake_lms_h10_q_overflow': 'passed', 'sha2_recipes': 'passed', 'sha2_recipes_synthesis': 'passed', 'sha2_signature_views': 'passed', 'sha2_slh_128f_stall_reset': 'passed', 'sha2_slh_128f_truncate': 'passed', 'sha2_slh_128f_tamper1': 'passed', 'sha2_slh_128f_tamper2': 'passed', 'sha2_slh_128f_tamper3': 'passed', 'sha2_slh_128f_tamper4': 'passed', 'sha2_slh_128f_tamper5': 'passed', 'sha2_xmss_h10_stall_reset': 'passed', 'sha2_xmss_h10_truncate': 'passed', 'sha2_xmss_h10_tamper1': 'passed', 'sha2_xmss_h10_tamper2': 'passed', 'sha2_xmss_h10_tamper3': 'passed', 'sha2_xmss_h10_tamper4': 'passed', 'sha2_xmss_h10_tamper5': 'passed', 'sha2_lms_h10_stall_reset': 'passed', 'sha2_lms_h10_truncate': 'passed', 'sha2_lms_h10_tamper1': 'passed', 'sha2_lms_h10_tamper2': 'passed', 'sha2_lms_h10_tamper3': 'passed', 'sha2_lms_h10_tamper4': 'passed', 'sha2_lms_h10_tamper5': 'passed', 'sha2_xmss_h10_q_overflow': 'passed', 'sha2_lms_h10_q_overflow': 'passed'}`。

详细仿真日志保留于 `/tmp/mhbs-image-soft-chain/build/soft_chain/20261021_173641`；归档只保留摘要、冻结源码及综合证据。
