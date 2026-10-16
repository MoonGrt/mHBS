# T3 功能验证摘要

冻结源码：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/s4_timing_optimization/candidate_20261020_115825/source`。源码清单 SHA256：`5e34070f534d800fce6b8ddf37e56599fe40dc7cc58cb3b05f731e4eee1146ec`。

结果：**75/75 组通过**，0 失败，耗时 105.950 秒；冻结文件 SHA 全部一致：True。

- 保留原 52 组完整边界套件：P4/P12 发布与延迟读口 KAT、停顿、乱序、同拍补发、零步与请求字段扰动；三算法 Verify 重放/复位/截断、30 组篡改、6 组在途故障；P2U12 配方及 Verify；SHA2 P4 SLH128f 完整 Sign。
- 添加 P1U1 459 条 scalar recipe KAT 和三个目标 Verify 停顿冒烟。
- P4U1/P12U1 各执行全部六个 SLH 参数的 Verify（其余五参数增加重放/复位/截断/停顿）；两配置正常与 SYNTHESIS 视图均执行完整 recipe KAT。
- T3 保留 S4 的响应队列位图逐槽等价断言（awaiting_response = complete & ~held）、有效前缀字 source7 断言、目标索引影子等价断言及 checksum nibble 等价断言均保留启用；459 条 recipe KAT 包含 SLH n=24、流式停顿和消息/填充边界。
- 添加 P6U1 三个目标完整 Sign；SLH FORS 微组 8 叶、按 6+2 两波，覆盖非四整批；XMSS 包含奇数 L-tree，LMS 包含长列表。
- 全部配方 KAT 共 3,213 条，batch KAT 384 个请求。P12 batch bench 使用 4 个活动 tag，完整 Sign 由主运行器另行覆盖。
- 新增4组P4/P12 XMSS/LMS h20 Verify，使用冻结目录已经存在的向量，带stall/replay/reset/cut；未生成完整树，未执行 h20 Keygen/Sign；未启动 Vivado；未修改生产或冻结 RTL。
- T3 沿用 S4 提前登记相邻地址、认证节点匹配和低于根层标记，RTL内全部对应等价断言保持开启；scheduled recipe FSM 的 one-hot 综合编码属性保留。T3增加寄存退槽和预取选择控制，工作区写提交通过双读口转发保持算法语义；周期小幅变化由六项 Sign 主运行器单独实测。

完整 Sign 通过行：

- `STATEFUL_PASS P6U1 op=1 cycles=534923 total=534928 hashes=104937 permutations=105641 tamper=0 seconds=1.02261`
- `STATEFUL_PASS P6U1 op=1 cycles=15980676 total=15980681 hashes=3431815 permutations=3431815 tamper=0 seconds=26.1624`
- `STATEFUL_PASS P6U1 op=1 cycles=5606256 total=5606261 hashes=1101392 permutations=1116752 tamper=0 seconds=8.24544`
- `STATEFUL_PASS P4U1 op=1 cycles=4208580 total=4208585 hashes=104925 permutations=211432 tamper=0 seconds=1.37169`

逐组命令和日志校验见 `VALIDATION.json`；详细原始日志仅留 build 运行目录。
