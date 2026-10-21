# image-chain 控制精简与周期压缩 C1

基线 `27166641`，K1U1，SHAKE/SHA2 单 Hash 通道。program/template/descriptor 与外部接口不变。

原实现将每条 control token 从 sequencer 复制到 executor，并经历独立发射与执行空拍。C1在 sequencer LOAD 直接授权，executor FETCH 同一接受边沿执行；WAIT_CONTROL 保持原 token 稳定，删除重复64位保存。RAM、Verify输入和输出保留所需后续拍。每条动态控制精确减少2拍，无自主树控制或密码学工作量变化。

| 后端 | 基线LUT / FF | C1 LUT / FF | 基线等效Slice | C1等效Slice | 面积下降 | 综合WNS ns |
|---|---:|---:|---:|---:|---:|---:|
| shake | 20,511 / 6,400 | 20,099 / 6,324 | 5,927.750 | 5,815.250 | 1.898% | -3.489 |
| sha2 | 17,905 / 7,362 | 17,198 / 7,273 | 5,396.500 | 5,208.625 | 3.481% | -3.012 |

两后端BRAM/DSP均为0，SYNTHESIS视图无诊断寄存器。Vivado2025.2、xc7a200tffg1156-3、100MHz OOC、每任务2线程、默认时序优化。面积为common，不含ROM/签名缓存。

SHAKE SLH-DSA128f Sign完整实跑：3,165,156→2,958,730周期，减少206,426=2×103,213（6.522%）；104,937次Hash与105,641块不变，逐字节输出、签名缓存和逐Hash输入/结果指纹通过。

假定100MHz ATP：187,622.534790→172,057.546325 Slice·ms，下降8.295906%。未进行布线；100MHz仅为假定ATP，综合WNS不能视为频率验收。

控制故障/边界四配置（两后端×普通/SYNTHESIS）80项全部通过。完整44项整核及协议回归由独立归档 `macro_atp_acceptance_20261021_161437` 记录；本候选记录不提前声明完整验收。h16/h15/h20完整Keygen/Sign均未启动。

冻结RTL为 `frozen_rtl.tar.gz`，源码身份为 `SOURCE.json`，当前生产文件一致性见 `PRODUCTION_SOURCE_MATCH.json`。完整仿真明细留build，归档仅存结果摘要。
