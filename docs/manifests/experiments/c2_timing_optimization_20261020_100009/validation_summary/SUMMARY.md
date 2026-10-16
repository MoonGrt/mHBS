# R4 功能验证摘要

冻结源码：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/c2_timing_optimization/candidate_20261020_100009/source`。源码清单 SHA256：`0c7486edaa3d7a4c18a5263a31ed491246585d240546e9848190d566518729cc`。

结果：**59/59 组通过**，0 失败，耗时 75.071 秒；冻结文件 SHA 全部一致：True。

- 保留原 52 组完整边界套件：P4/P12 发布与延迟读口 KAT、停顿、乱序、同拍补发、零步与请求字段扰动；三算法 Verify 重放/复位/截断、30 组篡改、6 组在途故障；P2U12 配方及 Verify；SHA2 P4 SLH128f 完整 Sign。
- 添加 P1U1 459 条 scalar recipe KAT 和三个目标 Verify 停顿冒烟。
- 添加 P6U1 三个目标完整 Sign；SLH FORS 微组 8 叶、按 6+2 两波，覆盖非四整批；XMSS 包含奇数 L-tree，LMS 包含长列表。
- 全部配方 KAT 共 2,295 条，batch KAT 384 个请求。P12 batch bench 使用 4 个活动 tag，完整 Sign 由主运行器另行覆盖。
- 未执行 h20 完整 Keygen/Sign；未启动 Vivado；未修改生产或冻结 RTL。

完整 Sign 通过行：

- `STATEFUL_PASS P6U1 op=1 cycles=534241 total=534246 hashes=104937 permutations=105641 tamper=0 seconds=0.795415`
- `STATEFUL_PASS P6U1 op=1 cycles=15964292 total=15964297 hashes=3431815 permutations=3431815 tamper=0 seconds=22.121`
- `STATEFUL_PASS P6U1 op=1 cycles=5605232 total=5605237 hashes=1101392 permutations=1116752 tamper=0 seconds=7.72116`
- `STATEFUL_PASS P4U1 op=1 cycles=4207370 total=4207375 hashes=104925 permutations=211432 tamper=0 seconds=1.24897`

逐组命令和日志校验见 `VALIDATION.json`；详细原始日志仅留 build 运行目录。
