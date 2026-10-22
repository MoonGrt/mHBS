# image 软件控制优化：F4

更新时间：2026-10-21T18:37:19+08:00；完成：True；通过：True。

K1U1，单 Hash 通道；仅综合，不布线。面积使用相同配置 common，不含程序 ROM 或签名缓存。
100MHz仅为 ATP 的假定频率，低频综合时序不代表布线闭合。
44项默认测试＋12项q边界/空消息Sign。h16/h15/h20仅Verify，完整Keygen/Sign本轮未运行。
外部输入、期望输出、20组ROM及密码学工作量保持 image 基线认证身份。
逐字节核对输出及签名缓存，比较64位Hash/块数及完整原像/结果count、SUM256、XOR256指纹（概率性多重集检查）。

整核状态：`{'pending': 0, 'running': 0, 'passed': 56, 'failed': 0}`。

| 后端 | 基线 LUT / FF | 新 LUT / FF | 新等效Slice | 状态 |
|---|---:|---:|---:|---|
| shake | 16983 / 5885 | 16319 / 5845 | 4810.375 | passed |
| sha2 | 15218 / 7155 | 14588 / 7133 | 4538.625 | passed |

## slh_128f Sign

| 后端 | 基线周期 | 新周期 | 基线 ATP | 新ATP | 变化 |
|---|---:|---:|---:|---:|---:|
| shake | 6860527 | 5825429 | 341748.576846 | 280224.980259 | -18.003% |
| sha2 | 19216660 | 18181762 | 902966.832575 | 825201.995573 | -8.612% |

## xmss_h10 Sign

| 后端 | 基线周期 | 新周期 | 基线 ATP | 新ATP | 变化 |
|---|---:|---:|---:|---:|---:|
| shake | 129792756 | 119396316 | 6465463.899195 | 5743410.535785 | -11.168% |
| sha2 | 541083021 | 530686176 | 25424814.803014 | 24085855.455480 | -5.266% |

## lms_h10 Sign

| 后端 | 基线周期 | 新周期 | 基线 ATP | 新ATP | 变化 |
|---|---:|---:|---:|---:|---:|
| shake | 69049671 | 59188121 | 3439623.048776 | 2847170.575554 | -17.224% |
| sha2 | 121547876 | 111686725 | 5711382.758395 | 5069041.622531 | -11.247% |

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
| sha2/lms_h10/sign | 111686725 | 1101347 | 1136162 | 11033319 | passed |
| sha2/slh_128f/sign | 18181762 | 104925 | 211432 | 1152117 | passed |
| sha2/xmss_h10/sign | 530686176 | 3431950 | 7001183 | 11848580 | passed |
| shake/lms_h10/sign | 59188121 | 1101392 | 1116752 | 11033763 | passed |
| shake/slh_128f/sign | 5825429 | 104937 | 105641 | 1152332 | passed |
| shake/xmss_h10/sign | 119396316 | 3431815 | 3431815 | 11848130 | passed |
| sha2/lms_h10/keygen | 111627309 | 1100799 | 1135614 | 11025496 | passed |
| sha2/lms_h10/verify | 52671 | 538 | 581 | 3371 | passed |
| sha2/lms_h15/verify | 53601 | 543 | 591 | 3456 | passed |
| sha2/lms_h20/verify | 54531 | 548 | 601 | 3541 | passed |
| sha2/slh_128f/keygen | 774731 | 4495 | 9062 | 47376 | passed |
| sha2/slh_128f/verify | 1068827 | 6413 | 13031 | 43843 | passed |
| sha2/slh_128s/keygen | 49318499 | 287743 | 580094 | 2895984 | passed |
| sha2/slh_128s/sign | 377312249 | 2185959 | 4404167 | 23315758 | passed |
| sha2/slh_128s/verify | 369048 | 2190 | 4445 | 17073 | passed |
| sha2/xmss_h10/keygen | 530439739 | 3430396 | 6998007 | 11840601 | passed |
| sha2/xmss_h10/verify | 279691 | 1835 | 3747 | 4083 | passed |
| sha2/xmss_h16/verify | 290437 | 1904 | 3891 | 4254 | passed |
| sha2/xmss_h20/verify | 273181 | 1785 | 3657 | 4093 | passed |
| shake/lms_h10/keygen | 59151522 | 1100799 | 1116159 | 11025496 | passed |
| shake/lms_h10/verify | 23571 | 493 | 508 | 3146 | passed |
| shake/lms_h15/verify | 23916 | 498 | 513 | 3231 | passed |
| shake/lms_h20/verify | 24261 | 503 | 518 | 3316 | passed |
| shake/slh_128f/keygen | 245128 | 4495 | 4527 | 47376 | passed |
| shake/slh_128f/verify | 309335 | 6441 | 6533 | 44009 | passed |
| shake/slh_128s/keygen | 15416536 | 287743 | 289791 | 2895984 | passed |
| shake/slh_128s/sign | 119899605 | 2185897 | 2200231 | 23314938 | passed |
| shake/slh_128s/verify | 108240 | 2159 | 2189 | 16918 | passed |
| shake/slh_192f/keygen | 357512 | 6543 | 6615 | 68848 | passed |
| shake/slh_192f/sign | 9617913 | 168881 | 170462 | 1959535 | passed |
| shake/slh_192f/verify | 430080 | 8922 | 9126 | 60259 | passed |
| shake/slh_192s/keygen | 22484120 | 418815 | 423423 | 4207696 | passed |
| shake/slh_192s/sign | 215598003 | 3766890 | 3799140 | 44219250 | passed |
| shake/slh_192s/verify | 153108 | 3057 | 3123 | 23459 | passed |
| shake/slh_256f/keygen | 932792 | 17183 | 17439 | 176496 | passed |
| shake/slh_256f/sign | 19588241 | 345414 | 349758 | 3947181 | passed |
| shake/slh_256f/verify | 444775 | 9152 | 9432 | 62252 | passed |
| shake/slh_256s/keygen | 14800472 | 274943 | 279039 | 2761776 | passed |
| shake/slh_256s/sign | 193717937 | 3280290 | 3313047 | 41195991 | passed |
| shake/slh_256s/verify | 227524 | 4574 | 4707 | 33756 | passed |
| shake/xmss_h10/keygen | 119341142 | 3430396 | 3430396 | 11840601 | passed |
| shake/xmss_h10/verify | 63732 | 1970 | 1970 | 4308 | passed |
| shake/xmss_h16/verify | 60399 | 1859 | 1859 | 4179 | passed |
| shake/xmss_h20/verify | 62362 | 1920 | 1920 | 4318 | passed |
| shake/xmss_h10/sign_q1 | 119396304 | 3431815 | 3431815 | 11848124 | passed |
| shake/lms_h10/sign_q1 | 59188139 | 1101392 | 1116752 | 11033772 | passed |
| shake/lms_h10/sign_q1023 | 59184164 | 1101317 | 1116677 | 11033022 | passed |
| shake/xmss_h10/sign_q1023 | 119396310 | 3431815 | 3431815 | 11848127 | passed |
| sha2/xmss_h10/sign_q1 | 530713404 | 3432130 | 7001543 | 11849174 | passed |
| sha2/lms_h10/sign_q1 | 111695611 | 1101437 | 1136252 | 11034207 | passed |
| sha2/xmss_h10/sign_q1023 | 530699784 | 3432040 | 7001363 | 11848874 | passed |
| sha2/lms_h10/sign_q1023 | 111692659 | 1101407 | 1136222 | 11033916 | passed |
| shake/xmss_h10/sign_empty | 119399399 | 3431905 | 3431905 | 11848427 | passed |
| shake/lms_h10/sign_empty | 59189728 | 1101422 | 1116782 | 11034072 | passed |
| sha2/lms_h10/sign_empty | 111683748 | 1101317 | 1136132 | 11033016 | passed |
| sha2/xmss_h10/sign_empty | 530706575 | 3432085 | 7001453 | 11849015 | passed |

附加检查：`{'control_faults': 'passed', 'model_verify_bounds': 'passed', 'ordered_hash_trace': 'passed', 'shake_recipes': 'passed', 'shake_recipes_synthesis': 'passed', 'shake_signature_views': 'passed', 'shake_slh_128f_stall_reset': 'passed', 'shake_slh_128f_truncate': 'passed', 'shake_slh_128f_tamper1': 'passed', 'shake_slh_128f_tamper2': 'passed', 'shake_slh_128f_tamper3': 'passed', 'shake_slh_128f_tamper4': 'passed', 'shake_slh_128f_tamper5': 'passed', 'shake_xmss_h10_stall_reset': 'passed', 'shake_xmss_h10_truncate': 'passed', 'shake_xmss_h10_tamper1': 'passed', 'shake_xmss_h10_tamper2': 'passed', 'shake_xmss_h10_tamper3': 'passed', 'shake_xmss_h10_tamper4': 'passed', 'shake_xmss_h10_tamper5': 'passed', 'shake_lms_h10_stall_reset': 'passed', 'shake_lms_h10_truncate': 'passed', 'shake_lms_h10_tamper1': 'passed', 'shake_lms_h10_tamper2': 'passed', 'shake_lms_h10_tamper3': 'passed', 'shake_lms_h10_tamper4': 'passed', 'shake_lms_h10_tamper5': 'passed', 'shake_xmss_h10_q_overflow': 'passed', 'shake_lms_h10_q_overflow': 'passed', 'sha2_recipes': 'passed', 'sha2_recipes_synthesis': 'passed', 'sha2_signature_views': 'passed', 'sha2_slh_128f_stall_reset': 'passed', 'sha2_slh_128f_truncate': 'passed', 'sha2_slh_128f_tamper1': 'passed', 'sha2_slh_128f_tamper2': 'passed', 'sha2_slh_128f_tamper3': 'passed', 'sha2_slh_128f_tamper4': 'passed', 'sha2_slh_128f_tamper5': 'passed', 'sha2_xmss_h10_stall_reset': 'passed', 'sha2_xmss_h10_truncate': 'passed', 'sha2_xmss_h10_tamper1': 'passed', 'sha2_xmss_h10_tamper2': 'passed', 'sha2_xmss_h10_tamper3': 'passed', 'sha2_xmss_h10_tamper4': 'passed', 'sha2_xmss_h10_tamper5': 'passed', 'sha2_lms_h10_stall_reset': 'passed', 'sha2_lms_h10_truncate': 'passed', 'sha2_lms_h10_tamper1': 'passed', 'sha2_lms_h10_tamper2': 'passed', 'sha2_lms_h10_tamper3': 'passed', 'sha2_lms_h10_tamper4': 'passed', 'sha2_lms_h10_tamper5': 'passed', 'sha2_xmss_h10_q_overflow': 'passed', 'sha2_lms_h10_q_overflow': 'passed'}`。

详细仿真日志保留于 `/tmp/mhbs-image-soft-chain/build/image_optimization/20261021_182828`；归档只保留摘要、冻结源码及综合证据。
