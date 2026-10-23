# P1／SHA 面积、延迟与 ATP 优化进展

更新时间：2026-10-21T21:50:00+08:00；状态：测量全部结束。

实测Sign：78/78；基线复用Sign：21；100MHz综合：33/33；新增指定频率布线：6。

基线B0为2026-10-21本轮开始时的完整冻结源码，RTL与193612双后端矩阵完全相同。其21项完整Sign和7点物理证据经过向量、RTL、日志与DCP散列核对后复用；7点100MHz诊断重新综合，不借用150MHz综合面积当同口径诊断基线。

C1：SHA256轮内加法的进位保留重写；C2：在C1上加SHA2列表三字读取登记与SHAKE P1反馈/填充选择优化；C3：在C2上将SHA256轮常数表按实际循环遍历宽度切分；C4：保留小轮常数表、恢复普通加法并提前登记配方末块标记。候选结构通用，不恢复P/U特化。

面积统一为相同后端、相同P/U的common OOC，器件xc7a200tffg1156-3，Vivado2025.2，默认时序驱动，每个Vivado2线程。等效Slice=LUT/4+FF/8+232.4×BRAM36+102.4×DSP。100MHz数据仅为面积和路径诊断；假设ATP使用U1=150MHz、U2=100MHz，不能作为闭合频率ATP。目标未通过的基线不推算Fmax，不借用其他候选频率；仅setup/hold、DRC与完整路由通过才给布线ATP。

完整Sign核对输出、签名缓存和64位Hash/置换/压缩计数。新增C2列表读取拍可能增加周期，按完整Sign实测统计。未执行h20完整Keygen/Sign，异常长综合标analysis_deferred并留后台。

## SHAKE 100MHz common诊断面积

| 候选 | 配置 | LUT | FF | BRAM36 | 等效Slice | 面积变化% | 路径ns | 级数 | 状态 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| B0_frozen_current_design | P1U1 | 19,711.000 | 6,241.000 | 0.000 | 5,707.875 | 0.000 | 6.604 | 12.000 | passed |
| B0_frozen_current_design | P1U2 | 20,001.000 | 6,179.000 | 0.000 | 5,772.625 | 0.000 | 7.033 | 12.000 | passed |
| C2_P1_feedback_sha2_list_fetch | P1U1 | 18,063.000 | 6,229.000 | 0.000 | 5,294.375 | -7.244 | 6.245 | 11.000 | passed |
| C2_P1_feedback_sha2_list_fetch | P1U2 | 20,368.000 | 6,212.000 | 0.000 | 5,868.500 | 1.661 | 6.712 | 13.000 | passed |
| C3_P1_list_fetch_small_K_table | P1U1 | 18,063.000 | 6,229.000 | 0.000 | 5,294.375 | -7.244 | 6.245 | 11.000 | passed |
| C3_P1_list_fetch_small_K_table | P1U2 | 20,368.000 | 6,212.000 | 0.000 | 5,868.500 | 1.661 | 6.712 | 13.000 | passed |
| C4_P1_list_fetch_small_K_plain_add_final_flag | P1U1 | 18,063.000 | 6,229.000 | 0.000 | 5,294.375 | -7.244 | 6.245 | 11.000 | passed |
| C4_P1_list_fetch_small_K_plain_add_final_flag | P1U2 | 20,368.000 | 6,212.000 | 0.000 | 5,868.500 | 1.661 | 6.712 | 13.000 | passed |

## SHA2 100MHz common诊断面积

| 候选 | 配置 | LUT | FF | BRAM36 | 等效Slice | 面积变化% | 路径ns | 级数 | 状态 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| B0_frozen_current_design | P1U1 | 15,428.000 | 7,218.000 | 0.000 | 4,759.250 | 0.000 | 7.712 | 17.000 | passed |
| B0_frozen_current_design | P1U2 | 15,873.000 | 7,213.000 | 0.000 | 4,869.875 | 0.000 | 10.326 | 20.000 | passed |
| B0_frozen_current_design | P4U1 | 25,999.000 | 12,634.000 | 1.500 | 8,427.600 | 0.000 | 7.927 | 14.000 | passed |
| B0_frozen_current_design | P4U2 | 27,276.000 | 12,605.000 | 1.500 | 8,743.225 | 0.000 | 9.648 | 23.000 | passed |
| B0_frozen_current_design | P12U1 | 42,037.000 | 27,541.000 | 1.000 | 14,184.275 | 0.000 | 11.540 | 19.000 | passed |
| C1_sha256_carry_save | P1U1 | 15,494.000 | 7,208.000 | 0.000 | 4,774.500 | 0.320 | 7.414 | 18.000 | passed |
| C1_sha256_carry_save | P1U2 | 15,562.000 | 7,209.000 | 0.000 | 4,791.625 | -1.607 | 9.914 | 29.000 | passed |
| C1_sha256_carry_save | P4U1 | 26,904.000 | 12,586.000 | 1.500 | 8,647.850 | 2.613 | 8.244 | 18.000 | passed |
| C1_sha256_carry_save | P4U2 | 26,913.000 | 12,638.000 | 2.500 | 8,889.000 | 1.667 | 9.062 | 23.000 | passed |
| C1_sha256_carry_save | P12U1 | 43,604.000 | 27,371.000 | 5.500 | 15,600.575 | 9.985 | 11.899 | 19.000 | passed |
| C2_P1_feedback_sha2_list_fetch | P1U1 | 15,227.000 | 7,345.000 | 0.000 | 4,724.875 | -0.722 | 7.414 | 18.000 | passed |
| C2_P1_feedback_sha2_list_fetch | P1U2 | 15,859.000 | 7,341.000 | 0.000 | 4,882.375 | 0.257 | 9.164 | 23.000 | passed |
| C2_P1_feedback_sha2_list_fetch | P4U1 | 26,569.000 | 12,744.000 | 1.500 | 8,583.850 | 1.854 | 7.617 | 12.000 | passed |
| C2_P1_feedback_sha2_list_fetch | P4U2 | 27,640.000 | 12,738.000 | 3.000 | 9,199.450 | 5.218 | 9.034 | 23.000 | passed |
| C2_P1_feedback_sha2_list_fetch | P12U1 | 44,119.000 | 27,561.000 | 5.500 | 15,753.075 | 11.060 | 11.258 | 18.000 | passed |
| C3_P1_list_fetch_small_K_table | P1U1 | 14,764.000 | 7,332.000 | 0.000 | 4,607.500 | -3.189 | 6.552 | 16.000 | passed |
| C3_P1_list_fetch_small_K_table | P1U2 | 16,205.000 | 7,344.000 | 0.000 | 4,969.250 | 2.041 | 9.340 | 20.000 | passed |
| C3_P1_list_fetch_small_K_table | P4U1 | 24,507.000 | 12,733.000 | 0.000 | 7,718.375 | -8.416 | 7.187 | 14.000 | passed |
| C3_P1_list_fetch_small_K_table | P4U2 | 28,267.000 | 12,701.000 | 0.000 | 8,654.375 | -1.016 | 9.530 | 21.000 | passed |
| C3_P1_list_fetch_small_K_table | P12U1 | 45,850.000 | 27,529.000 | 0.000 | 14,903.625 | 5.071 | 12.630 | 19.000 | passed |
| C4_P1_list_fetch_small_K_plain_add_final_flag | P1U1 | 15,807.000 | 7,329.000 | 0.000 | 4,867.875 | 2.282 | 7.928 | 17.000 | passed |
| C4_P1_list_fetch_small_K_plain_add_final_flag | P1U2 | 15,759.000 | 7,353.000 | 0.000 | 4,858.875 | -0.226 | 10.012 | 23.000 | passed |
| C4_P1_list_fetch_small_K_plain_add_final_flag | P4U1 | 24,649.000 | 12,699.000 | 0.000 | 7,749.625 | -8.045 | 7.969 | 11.000 | passed |
| C4_P1_list_fetch_small_K_plain_add_final_flag | P4U2 | 25,740.000 | 12,745.000 | 0.000 | 8,028.125 | -8.179 | 9.802 | 24.000 | passed |
| C4_P1_list_fetch_small_K_plain_add_final_flag | P12U1 | 43,475.000 | 27,710.000 | 0.000 | 14,332.500 | 1.045 | 11.758 | 20.000 | passed |

## slh_128f 完整Sign

| 候选 | 后端／配置 | 周期 | 变化% | 假设时间ms | 假设ATP Slice·ms | ATP变化% | 闭合MHz | 布线ATP Slice·ms | 状态 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| B0_frozen_current_design | shake/P1U1 | 2,619,846.000 | 0.000 | 17.466 | 99,691.690 | 0.000 | — | — | passed |
| B0_frozen_current_design | shake/P1U2 | 1,352,154.000 | 0.000 | 13.522 | 78,054.780 | 0.000 | — | — | passed |
| B0_frozen_current_design | sha2/P1U1 | 15,071,002.000 | 0.000 | 100.473 | 478,177.775 | 0.000 | — | — | passed |
| B0_frozen_current_design | sha2/P1U2 | 8,305,178.000 | 0.000 | 83.052 | 404,451.787 | 0.000 | — | — | passed |
| B0_frozen_current_design | sha2/P4U1 | 4,209,812.000 | 0.000 | 28.065 | 236,524.077 | 0.000 | — | — | passed |
| B0_frozen_current_design | sha2/P4U2 | 2,350,356.000 | 0.000 | 23.504 | 205,496.913 | 0.000 | — | — | passed |
| B0_frozen_current_design | sha2/P12U1 | 1,790,978.000 | 0.000 | 11.940 | 169,358.163 | 0.000 | — | — | passed |
| C1_sha256_carry_save | sha2/P1U1 | 15,071,002.000 | 0.000 | 100.473 | 479,709.994 | 0.320 | — | — | passed |
| C1_sha256_carry_save | sha2/P1U2 | 8,305,178.000 | 0.000 | 83.052 | 397,952.985 | -1.607 | — | — | passed |
| C1_sha256_carry_save | sha2/P4U1 | 4,209,812.000 | 0.000 | 28.065 | 242,705.485 | 2.613 | — | — | passed |
| C1_sha256_carry_save | sha2/P4U2 | 2,350,356.000 | 0.000 | 23.504 | 208,923.145 | 1.667 | — | — | passed |
| C1_sha256_carry_save | sha2/P12U1 | 1,790,978.000 | 0.000 | 11.940 | 186,268.577 | 9.985 | — | — | passed |
| C2_P1_feedback_sha2_list_fetch | shake/P1U1 | 2,619,846.000 | 0.000 | 17.466 | 92,469.648 | -7.244 | — | — | passed |
| C2_P1_feedback_sha2_list_fetch | shake/P1U2 | 1,352,154.000 | 0.000 | 13.522 | 79,351.157 | 1.661 | — | — | passed |
| C2_P1_feedback_sha2_list_fetch | sha2/P1U1 | 15,077,862.000 | 0.046 | 100.519 | 474,940.088 | -0.677 | — | — | passed |
| C2_P1_feedback_sha2_list_fetch | sha2/P1U2 | 8,312,038.000 | 0.083 | 83.120 | 405,824.865 | 0.339 | — | — | passed |
| C2_P1_feedback_sha2_list_fetch | sha2/P4U1 | 4,216,672.000 | 0.163 | 28.111 | 241,301.866 | 2.020 | — | — | passed |
| C2_P1_feedback_sha2_list_fetch | sha2/P4U2 | 2,357,216.000 | 0.292 | 23.572 | 216,850.907 | 5.525 | — | — | passed |
| C2_P1_feedback_sha2_list_fetch | sha2/P12U1 | 1,797,838.000 | 0.383 | 11.986 | 188,809.846 | 11.486 | — | — | passed |
| C3_P1_list_fetch_small_K_table | shake/P1U1 | 2,619,846.000 | 0.000 | 17.466 | 92,469.648 | -7.244 | — | — | passed |
| C3_P1_list_fetch_small_K_table | shake/P1U2 | 1,352,154.000 | 0.000 | 13.522 | 79,351.157 | 1.661 | 100.000 | 79,119.601 | passed |
| C3_P1_list_fetch_small_K_table | sha2/P1U1 | 15,077,862.000 | 0.046 | 100.519 | 463,141.661 | -3.144 | — | — | passed |
| C3_P1_list_fetch_small_K_table | sha2/P1U2 | 8,312,038.000 | 0.083 | 83.120 | 413,045.948 | 2.125 | — | — | passed |
| C3_P1_list_fetch_small_K_table | sha2/P4U1 | 4,216,672.000 | 0.163 | 28.111 | 216,972.372 | -8.266 | — | — | passed |
| C3_P1_list_fetch_small_K_table | sha2/P4U2 | 2,357,216.000 | 0.292 | 23.572 | 204,002.312 | -0.727 | 100.000 | 204,164.371 | passed |
| C3_P1_list_fetch_small_K_table | sha2/P12U1 | 1,797,838.000 | 0.383 | 11.986 | 178,628.689 | 5.474 | — | — | passed |
| C4_P1_list_fetch_small_K_plain_add_final_flag | shake/P1U1 | 2,619,846.000 | 0.000 | 17.466 | 92,469.648 | -7.244 | — | — | passed |
| C4_P1_list_fetch_small_K_plain_add_final_flag | shake/P1U2 | 1,352,154.000 | 0.000 | 13.522 | 79,351.157 | 1.661 | — | — | passed |
| C4_P1_list_fetch_small_K_plain_add_final_flag | sha2/P1U1 | 15,077,862.000 | 0.046 | 100.519 | 489,314.317 | 2.329 | — | — | passed |
| C4_P1_list_fetch_small_K_plain_add_final_flag | sha2/P1U2 | 8,312,038.000 | 0.083 | 83.120 | 403,871.536 | -0.143 | — | — | passed |
| C4_P1_list_fetch_small_K_plain_add_final_flag | sha2/P4U1 | 4,216,672.000 | 0.163 | 28.111 | 217,850.845 | -7.895 | — | — | passed |
| C4_P1_list_fetch_small_K_plain_add_final_flag | sha2/P4U2 | 2,357,216.000 | 0.292 | 23.572 | 189,240.247 | -7.911 | — | — | passed |
| C4_P1_list_fetch_small_K_plain_add_final_flag | sha2/P12U1 | 1,797,838.000 | 0.383 | 11.986 | 171,783.421 | 1.432 | — | — | passed |

## xmss_h10 完整Sign

| 候选 | 后端／配置 | 周期 | 变化% | 假设时间ms | 假设ATP Slice·ms | ATP变化% | 闭合MHz | 布线ATP Slice·ms | 状态 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| B0_frozen_current_design | shake/P1U1 | 86,567,075.000 | 0.000 | 577.114 | 3,294,093.621 | 0.000 | — | — | passed |
| B0_frozen_current_design | shake/P1U2 | 45,385,295.000 | 0.000 | 453.853 | 2,619,922.885 | 0.000 | — | — | passed |
| B0_frozen_current_design | sha2/P1U1 | 497,855,675.000 | 0.000 | 3,319.038 | 15,796,130.808 | 0.000 | — | — | passed |
| B0_frozen_current_design | sha2/P1U2 | 273,817,819.000 | 0.000 | 2,738.178 | 13,334,585.513 | 0.000 | — | — | passed |
| B0_frozen_current_design | sha2/P4U1 | 130,829,618.000 | 0.000 | 872.197 | 7,350,531.258 | 0.000 | — | — | passed |
| B0_frozen_current_design | sha2/P4U2 | 72,787,666.000 | 0.000 | 727.877 | 6,363,989.411 | 0.000 | — | — | passed |
| B0_frozen_current_design | sha2/P12U1 | 55,081,078.000 | 0.000 | 367.207 | 5,208,567.718 | 0.000 | — | — | passed |
| C1_sha256_carry_save | sha2/P1U1 | 497,855,675.000 | 0.000 | 3,319.038 | 15,846,746.135 | 0.320 | — | — | passed |
| C1_sha256_carry_save | sha2/P1U2 | 273,817,819.000 | 0.000 | 2,738.178 | 13,120,323.070 | -1.607 | — | — | passed |
| C1_sha256_carry_save | sha2/P4U1 | 130,829,618.000 | 0.000 | 872.197 | 7,542,632.747 | 2.613 | — | — | passed |
| C1_sha256_carry_save | sha2/P4U2 | 72,787,666.000 | 0.000 | 727.877 | 6,470,095.631 | 1.667 | — | — | passed |
| C1_sha256_carry_save | sha2/P12U1 | 55,081,078.000 | 0.000 | 367.207 | 5,728,643.256 | 9.985 | — | — | passed |
| C2_P1_feedback_sha2_list_fetch | shake/P1U1 | 86,567,075.000 | 0.000 | 577.114 | 3,055,457.051 | -7.244 | — | — | passed |
| C2_P1_feedback_sha2_list_fetch | shake/P1U2 | 45,385,295.000 | 0.000 | 453.853 | 2,663,436.037 | 1.661 | — | — | passed |
| C2_P1_feedback_sha2_list_fetch | sha2/P1U1 | 497,855,675.000 | 0.000 | 3,319.038 | 15,682,038.883 | -0.722 | — | — | passed |
| C2_P1_feedback_sha2_list_fetch | sha2/P1U2 | 273,817,819.000 | 0.000 | 2,738.178 | 13,368,812.740 | 0.257 | — | — | passed |
| C2_P1_feedback_sha2_list_fetch | sha2/P4U1 | 130,829,618.000 | 0.000 | 872.197 | 7,486,812.110 | 1.854 | — | — | passed |
| C2_P1_feedback_sha2_list_fetch | sha2/P4U2 | 72,787,666.000 | 0.000 | 727.877 | 6,696,064.940 | 5.218 | — | — | passed |
| C2_P1_feedback_sha2_list_fetch | sha2/P12U1 | 55,081,078.000 | 0.000 | 367.207 | 5,784,642.352 | 11.060 | — | — | passed |
| C3_P1_list_fetch_small_K_table | shake/P1U1 | 86,567,075.000 | 0.000 | 577.114 | 3,055,457.051 | -7.244 | — | — | passed |
| C3_P1_list_fetch_small_K_table | shake/P1U2 | 45,385,295.000 | 0.000 | 453.853 | 2,663,436.037 | 1.661 | 100.000 | 2,655,663.805 | passed |
| C3_P1_list_fetch_small_K_table | sha2/P1U1 | 497,855,675.000 | 0.000 | 3,319.038 | 15,292,466.817 | -3.189 | — | — | passed |
| C3_P1_list_fetch_small_K_table | sha2/P1U2 | 273,817,819.000 | 0.000 | 2,738.178 | 13,606,691.971 | 2.041 | — | — | passed |
| C3_P1_list_fetch_small_K_table | sha2/P4U1 | 130,829,618.000 | 0.000 | 872.197 | 6,731,947.019 | -8.416 | — | — | passed |
| C3_P1_list_fetch_small_K_table | sha2/P4U2 | 72,787,666.000 | 0.000 | 727.877 | 6,299,317.569 | -1.016 | 100.000 | 6,304,321.721 | passed |
| C3_P1_list_fetch_small_K_table | sha2/P12U1 | 55,081,078.000 | 0.000 | 367.207 | 5,472,718.207 | 5.071 | — | — | passed |
| C4_P1_list_fetch_small_K_plain_add_final_flag | shake/P1U1 | 86,567,075.000 | 0.000 | 577.114 | 3,055,457.051 | -7.244 | — | — | passed |
| C4_P1_list_fetch_small_K_plain_add_final_flag | shake/P1U2 | 45,385,295.000 | 0.000 | 453.853 | 2,663,436.037 | 1.661 | — | — | passed |
| C4_P1_list_fetch_small_K_plain_add_final_flag | sha2/P1U1 | 497,855,675.000 | 0.000 | 3,319.038 | 16,156,661.293 | 2.282 | — | — | passed |
| C4_P1_list_fetch_small_K_plain_add_final_flag | sha2/P1U2 | 273,817,819.000 | 0.000 | 2,738.178 | 13,304,465.553 | -0.226 | — | — | passed |
| C4_P1_list_fetch_small_K_plain_add_final_flag | sha2/P4U1 | 130,829,618.000 | 0.000 | 872.197 | 6,759,203.189 | -8.045 | — | — | passed |
| C4_P1_list_fetch_small_K_plain_add_final_flag | sha2/P4U2 | 72,787,666.000 | 0.000 | 727.877 | 5,843,484.811 | -8.179 | — | — | passed |
| C4_P1_list_fetch_small_K_plain_add_final_flag | sha2/P12U1 | 55,081,078.000 | 0.000 | 367.207 | 5,262,997.003 | 1.045 | — | — | passed |

## lms_h10 完整Sign

| 候选 | 后端／配置 | 周期 | 变化% | 假设时间ms | 假设ATP Slice·ms | ATP变化% | 闭合MHz | 布线ATP Slice·ms | 状态 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| B0_frozen_current_design | shake/P1U1 | 28,524,614.000 | 0.000 | 190.164 | 1,085,432.874 | 0.000 | — | — | passed |
| B0_frozen_current_design | shake/P1U2 | 15,123,590.000 | 0.000 | 151.236 | 873,028.137 | 0.000 | — | — | passed |
| B0_frozen_current_design | sha2/P1U1 | 81,024,466.000 | 0.000 | 540.163 | 2,570,771.265 | 0.000 | — | — | passed |
| B0_frozen_current_design | sha2/P1U2 | 44,667,282.000 | 0.000 | 446.673 | 2,175,240.799 | 0.000 | — | — | passed |
| B0_frozen_current_design | sha2/P4U1 | 22,806,856.000 | 0.000 | 152.046 | 1,281,380.398 | 0.000 | — | — | passed |
| B0_frozen_current_design | sha2/P4U2 | 12,674,376.000 | 0.000 | 126.744 | 1,108,149.211 | 0.000 | — | — | passed |
| B0_frozen_current_design | sha2/P12U1 | 11,063,107.000 | 0.000 | 73.754 | 1,046,147.680 | 0.000 | — | — | passed |
| C1_sha256_carry_save | sha2/P1U1 | 81,024,466.000 | 0.000 | 540.163 | 2,579,008.753 | 0.320 | — | — | passed |
| C1_sha256_carry_save | sha2/P1U2 | 44,667,282.000 | 0.000 | 446.673 | 2,140,288.651 | -1.607 | — | — | passed |
| C1_sha256_carry_save | sha2/P4U1 | 22,806,856.000 | 0.000 | 152.046 | 1,314,868.464 | 2.613 | — | — | passed |
| C1_sha256_carry_save | sha2/P4U2 | 12,674,376.000 | 0.000 | 126.744 | 1,126,625.283 | 1.667 | — | — | passed |
| C1_sha256_carry_save | sha2/P12U1 | 11,063,107.000 | 0.000 | 73.754 | 1,150,605.537 | 9.985 | — | — | passed |
| C2_P1_feedback_sha2_list_fetch | shake/P1U1 | 28,524,614.000 | 0.000 | 190.164 | 1,006,800.022 | -7.244 | — | — | passed |
| C2_P1_feedback_sha2_list_fetch | shake/P1U2 | 15,123,590.000 | 0.000 | 151.236 | 887,527.879 | 1.661 | — | — | passed |
| C2_P1_feedback_sha2_list_fetch | sha2/P1U1 | 81,162,706.000 | 0.171 | 541.085 | 2,556,557.603 | -0.553 | — | — | passed |
| C2_P1_feedback_sha2_list_fetch | sha2/P1U2 | 44,805,522.000 | 0.309 | 448.055 | 2,187,573.605 | 0.567 | — | — | passed |
| C2_P1_feedback_sha2_list_fetch | sha2/P4U1 | 22,945,096.000 | 0.606 | 152.967 | 1,313,048.415 | 2.471 | — | — | passed |
| C2_P1_feedback_sha2_list_fetch | sha2/P4U2 | 12,812,616.000 | 1.091 | 128.126 | 1,178,690.203 | 6.366 | — | — | passed |
| C2_P1_feedback_sha2_list_fetch | sha2/P12U1 | 11,201,347.000 | 1.250 | 74.676 | 1,176,371.063 | 12.448 | — | — | passed |
| C3_P1_list_fetch_small_K_table | shake/P1U1 | 28,524,614.000 | 0.000 | 190.164 | 1,006,800.022 | -7.244 | — | — | passed |
| C3_P1_list_fetch_small_K_table | shake/P1U2 | 15,123,590.000 | 0.000 | 151.236 | 887,527.879 | 1.661 | 100.000 | 884,937.964 | passed |
| C3_P1_list_fetch_small_K_table | sha2/P1U1 | 81,162,706.000 | 0.171 | 541.085 | 2,493,047.786 | -3.023 | — | — | passed |
| C3_P1_list_fetch_small_K_table | sha2/P1U2 | 44,805,522.000 | 0.309 | 448.055 | 2,226,498.402 | 2.356 | — | — | passed |
| C3_P1_list_fetch_small_K_table | sha2/P4U1 | 22,945,096.000 | 0.606 | 152.967 | 1,180,659.036 | -7.860 | — | — | passed |
| C3_P1_list_fetch_small_K_table | sha2/P4U2 | 12,812,616.000 | 1.091 | 128.126 | 1,108,851.836 | 0.063 | 100.000 | 1,109,732.703 | passed |
| C3_P1_list_fetch_small_K_table | sha2/P12U1 | 11,201,347.000 | 1.250 | 74.676 | 1,112,937.835 | 6.384 | — | — | passed |
| C4_P1_list_fetch_small_K_plain_add_final_flag | shake/P1U1 | 28,524,614.000 | 0.000 | 190.164 | 1,006,800.022 | -7.244 | — | — | passed |
| C4_P1_list_fetch_small_K_plain_add_final_flag | shake/P1U2 | 15,123,590.000 | 0.000 | 151.236 | 887,527.879 | 1.661 | — | — | passed |
| C4_P1_list_fetch_small_K_plain_add_final_flag | sha2/P1U1 | 81,162,706.000 | 0.171 | 541.085 | 2,633,932.716 | 2.457 | — | — | passed |
| C4_P1_list_fetch_small_K_plain_add_final_flag | sha2/P1U2 | 44,805,522.000 | 0.309 | 448.055 | 2,177,044.307 | 0.083 | — | — | passed |
| C4_P1_list_fetch_small_K_plain_add_final_flag | sha2/P4U1 | 22,945,096.000 | 0.606 | 152.967 | 1,185,439.264 | -7.487 | — | — | passed |
| C4_P1_list_fetch_small_K_plain_add_final_flag | sha2/P4U2 | 12,812,616.000 | 1.091 | 128.126 | 1,028,612.828 | -7.177 | — | — | passed |
| C4_P1_list_fetch_small_K_plain_add_final_flag | sha2/P12U1 | 11,201,347.000 | 1.250 | 74.676 | 1,070,288.706 | 2.308 | — | — | passed |

## 指定频率物理证据

| 候选 | 后端／配置 | 目标MHz | 布线Slice | WNS ns | WHS ns | 状态 |
|---|---|---:|---:|---:|---:|---|
| B0_frozen_current_design | shake/P1U1 | 150.000 | 5,942.250 | -0.723 | 0.131 | target_not_met |
| B0_frozen_current_design | shake/P1U2 | 100.000 | 5,785.625 | -0.238 | 0.138 | target_not_met |
| B0_frozen_current_design | sha2/P1U1 | 150.000 | 4,911.375 | -0.988 | 0.130 | target_not_met |
| B0_frozen_current_design | sha2/P1U2 | 100.000 | 4,818.750 | -0.785 | 0.130 | target_not_met |
| B0_frozen_current_design | sha2/P4U1 | 150.000 | 8,704.100 | -1.729 | 0.094 | target_not_met |
| B0_frozen_current_design | sha2/P4U2 | 100.000 | 8,728.725 | -0.634 | 0.096 | target_not_met |
| B0_frozen_current_design | sha2/P12U1 | 150.000 | 14,466.400 | -4.346 | 0.079 | target_not_met |
| C3_P1_list_fetch_small_K_table | shake/P1U1 | 150.000 | 5,360.750 | -0.010 | 0.116 | target_not_met |
| C3_P1_list_fetch_small_K_table | shake/P1U2 | 100.000 | 5,851.375 | 0.208 | 0.141 | passed |
| C3_P1_list_fetch_small_K_table | sha2/P1U1 | 150.000 | 4,613.375 | -0.083 | 0.109 | target_not_met |
| C3_P1_list_fetch_small_K_table | sha2/P1U2 | 100.000 | 4,985.125 | -0.313 | 0.096 | target_not_met |
| C3_P1_list_fetch_small_K_table | sha2/P4U1 | 150.000 | 7,968.750 | -1.118 | 0.096 | target_not_met |
| C3_P1_list_fetch_small_K_table | sha2/P4U2 | 100.000 | 8,661.250 | 0.008 | 0.096 | passed |

## 源码与归档

当前工作区与最新冻结候选RTL不一致（rtl/hash/shake-recipe.sv, rtl/hash/sha256.sv, rtl/hash/sha2-recipe.sv）。

- [B0_frozen_current_design](docs/manifests/experiments/p1sha_atp_baseline_20261021_202753/reports/P1_SHA_ATP_20261021_202753.md)：`4fe3963885ffb04b710a3475285fba269f654d7ca7c009f0ae94bcff5c75e185`。
- [C1_sha256_carry_save](docs/manifests/experiments/p1sha_atp_candidate_20261021_203205/reports/P1_SHA_ATP_20261021_203205.md)：`dd9de762439cbb945cc939946e0dd9c053461345b20f3abbddc1d23c7f8f92ca`。
- [C2_P1_feedback_sha2_list_fetch](docs/manifests/experiments/p1sha_atp_candidate_20261021_203456/reports/P1_SHA_ATP_20261021_203456.md)：`f5d688f211537a1393e6df5c3dc5161747e38fcecb83f80dcefde4cfac02b1db`。
- [C3_P1_list_fetch_small_K_table](docs/manifests/experiments/p1sha_atp_candidate_20261021_203556/reports/P1_SHA_ATP_20261021_203556.md)：`b96cb542044c062f8623ac69cdcf25b6d7bc26a3fa0da1038df099fc70aaa7f1`。
- [C4_P1_list_fetch_small_K_plain_add_final_flag](docs/manifests/experiments/p1sha_atp_candidate_20261021_204522/reports/P1_SHA_ATP_20261021_204522.md)：`e0521aa4884b25f7e089255a15fadc83a9ddac66a5e94edb7c80f48eb72dd9d4`。

初版两个控制器在进程启动窗口曾同时占用最后一槽，短暂出现13个Vivado；随后只暂停了新增候选诊断，并在容量释放后恢复；旧矩阵未修改。C2起采用跨进程预约锁及物理阶段顺序调度，限制全机12个、每个2线程。该调度修正及自动恢复记录保留运行目录，未终止任何旧任务。

RTL/support压缩包、源码/控制器SHA、分层面积、时序与Vivado日志随各候选归档。原始仿真和验证详细日志在运行目录；归档只保留验证摘要与原始日志路径/散列。
