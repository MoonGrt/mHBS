# main SHA2行为修正同步到i／c／t

完成时间：2026-10-23T18:44:07.468756+08:00

已将main `a4a09e6f6ef901585e63aa8f37175b4931fad1cf` 的SHA2配方及SHA256通道同步到当前ablation分支的三种实现；六个模块文件与上游逐字节一致。未执行切分支或提交操作，main分支引用保持原值。
任务先在隔离工作树验证；期间主工作区自行切到ablation，随后同步到当前分支。只写入SHA2模块、相关测试适配和缺失的Verify输入；其他生产RTL保持当前分支原样。

## 同步内容

- SLH：缓存PK.seed低128位加48字节零的原始SHA256前缀链值。
- XMSS：缓存toByte(3,32)||PK.seed全256位，仅用于KEY／MASK0／MASK1；其他PRF、FINAL保持各自输入。
- 同步种子与家族匹配、并发冷填充屏障、复位失效，以及配套固定块装配、链反馈和SHA256数据通道。
- i仍逐次程序HASH，c使用CHAIN，t使用CHAIN／TREE；指令、程序／模板／描述符和控制粒度保持原样。
- 模型／向量meta保留逻辑块数；统计和测试改为核对实际压缩数。trace使用压缩器真实输入握手，覆盖replay。
- 隔离c的执行器／SHAKE面积改动保留在隔离工作树，未顺带带入当前ablation。旧SHA2移位装配／单槽CV直连由上游配套架构替代。

## SHA2-128f Sign：P1U1实测

| 实现 | 历史周期 | 同步后周期 | 变化 | 完整Hash | 实际压缩 | 逻辑压缩 |
|---|---:|---:|---:|---:|---:|---:|
| i | 18,181,762 | **10,633,206** | -41.52% | 104,925 | 106,513 | 211,432 |
| c | 15,409,870 | **7,390,104** | -52.04% | 104,925 | 106,513 | 211,432 |
| t | 15,065,766 | **7,046,000** | -53.23% | 104,925 | 106,513 | 211,432 |

三者实际压缩输入及完整Hash结果的多重集sum256、xor256指纹完全一致，工作量相同，均从复位后冷缓存开始。当前c的原执行器版本与隔离面积优化版本在本次补验的周期／输出／计数／轨迹也完全一致。

## 回归结果

- 60组镜像重新生成比对通过，ROM格式及内容不变，不生成完整h20树。
- 隔离i/c/t各执行SLH128f、XMSS h10、LMS h10完整Keygen／Sign／Verify，共27项；逐字节检查输出、公钥、签名缓存，并严格核对Hash与实际压缩。
- 隔离三者各执行SLH128s Verify、XMSS h20 Verify、LMS h20 Verify，共9项；补齐下述缺失输入后，正常整核36/36通过。12种算法／操作的跨设计压缩／Hash指纹全部一致。
- 当前ablation的i/t生产RTL与上述受验RTL逐字节一致。当前c保留其原执行器与SHAKE实现，额外实跑三算法完整Sign、SHAKE128f Sign及SYNTHESIS完整SHA2-128f Sign，5/5通过；周期、字节、工作量及指纹与隔离结果相同。
- 各设计345项SHA2配方，共1035项通过；SHA256原语181向量通过，覆盖停顿和复位重放。
- 后端缓存测试P1U1、P4U1及P1U1 SYNTHESIS视图通过；每视图29项标量序列及6组批次，覆盖冷／热缓存、种子高低半变化、家族切换、并发填充、返回停顿、列表、HMAC／MGF1及复位。P4仅为独立后端覆盖，整核仍为K1U1。
- c的top内置signature保存及SYNTHESIS视图通过。宏视图功能通过不等同新综合网表审计。
- SHAKE128f Sign周期保持i=5,825,429、c=2,958,730、t=2,614,610。h20 Keygen／Sign始终未运行。

## 测试输入缺项与证据范围

首轮t在完成10项后，因缺少xmss_h20／lms_h20 Verify目录停止。复用已经通过i/c核验的标准Verify输入，由prepare_vector接入t自己的ROM，两项补测均通过。原缺项记录保留在initial_validation_summary.json，补充输入来源／校验和与结果单独归档；未修改历史报告。
主工作区18:27:04由main切至ablation，属验证期间观察到的外部切换。本任务没有执行checkout，也没有更改main提交。当前分支同步前现场保存在target_before_source.tar.gz及TARGET_BEFORE.json。

## 面积与ATP

本轮仅同步与功能回归，未启动综合、布线或频率搜索。旧面积和ATP不代表同步后RTL，新面积／闭合频率／ATP留空。今后比较三种控制粒度应采用本次共同SHA2后端重新测量。

## 归档与复现

rtl.tar.gz及CURRENT_SOURCE.json对应当前ablation源码；isolated_rtl.tar.gz及SOURCE.json对应最初完整隔离回归。support.tar.gz保留初始测试支持源码，supplemental_verify_fixtures.tar.gz补充两组Verify输入；before_source.tar.gz为隔离同步前现场。详细日志和构建文件保留运行目录，归档只收结果摘要及源码，不复制仿真明细。
旧check_ablation.py默认比较历史迁移周期，不用于验收本次有意改变周期与压缩数的后端；其static-only模式仍用于60组ROM核对。报告按60秒刷新，全部结束后刷新进程退出。

```bash
MHBS_DESIGN=t HASH_BACKEND=sha2 bash scripts/simulate_fast.sh slh_128f sign 1 1
MHBS_DESIGN=c python3 scripts/check_sha2_prefix_cache.py --pipeline 4 --unroll 1
```
