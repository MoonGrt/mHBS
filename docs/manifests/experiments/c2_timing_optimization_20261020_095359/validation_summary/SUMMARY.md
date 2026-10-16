# R1 功能验证摘要

冻结源码：`/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/tmp/mHBS/build/c2_timing_optimization/candidate_20261020_095359/source`。源码清单 SHA256：`1e2849cdec2ab4934ecdbd6156822deba9af04a17ba481d77af956e62e6c052b`。

结果：**52/52 组通过**，0 失败，耗时 70.509 秒；冻结文件 SHA 全部一致：True。

- P4U1/P12U1 正常与 SYNTHESIS batch KAT 共 384 个请求；原冻结 tb_pipeline 只核对 batch_read_digest/capture 延迟读口，发布响应数据端口未连接，明确为 deferred-only 覆盖。
- P12 batch bench 使用 4 个活动 tag，不据此声称 12 槽满占用；保留乱序、零步、停顿、同拍补发和无效请求字段扰动。
- 1,836 条独立 hashlib 配方 KAT：P4/P12 SYNTHESIS 和 P2U12 正常/SYNTHESIS。
- P4/P12 三算法及 P2U12 XMSS Verify 共 7 组，覆盖停顿、重放、在途复位、截断恢复；另外 30 组篡改、6 组故障通过。
- SHA2 P4U1 SLH128f 完整 Sign 兼容通过。
- 未新增 P6 或全六 SLH 参数回归；未执行 h20 完整 Keygen/Sign；未启动 Vivado；未修改生产或冻结源码。

逐组命令和日志校验见 VALIDATION.json；详细日志仅留 build 运行目录。
