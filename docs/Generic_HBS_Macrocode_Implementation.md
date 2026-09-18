# 通用 HBS 宏微码 K2/U2 实现

## 实现状态

当前生产 Sign 顶层已经切换到通用宏微码核心
`micro_hbs_horizontal_hbs_top`。同一核心通过不同的只读镜像完成：

- SLH-DSA-SHAKE-128f Sign；
- SLH-DSA-SHAKE-128f Keygen，并输出完整 96-byte `SK || PK`。

旧的固定算法 FSM 已重命名为 reference top，不在生产包装器中实例化。
生产数据通路保持两条 RTL 完全相同、可物理互换的 U2 Keccak lane；TREE
宏内部也只通过这两条 lane 执行叶、链和父节点任务。

## 控制层

128-bit `SINGLE/RUN/LOOP/HALT` token 由静态 sequencer 展开。每个有效
slot 是一个 48-bit command：

```text
macro[3:0] | descriptor_id[7:0] | route_id[7:0]
| flags[3:0] | coordinate[23:0]
```

宏执行器支持五种算法无关操作：

| 宏 | 行为 |
|---|---|
| `HASH` | 按 segment recipe 组织单块或多块 SHAKE 输入并路由摘要 |
| `CHAIN` | 执行 seed recipe、lane-local feedback、运行时 capture 和可选 endpoint 压缩 |
| `TREE` | 生成叶、逐层归约、捕获认证路径并路由 root；内部统一调度 K2 |
| `TRANSFORM` | 执行 base-w/checksum 和 tree/leaf index 更新 |
| `EMIT` | 按 segment 列表流式输出非 Hash 数据 |

RTL 状态只表示 fetch、descriptor/compose、issue/wait、route、tree iterator、
transform 和 emit；不存在 `FORS_*`、`WOTS_*` 或 `XMSS_*` 执行状态。

## 描述符与 ROM

64-bit 描述符包括 image header、Hash recipe、input segment、address map、
chain、tree、transform、result route/action 和 emit。地址类型、输入布局和
结果去向均来自镜像。编译器检查描述符类型与边界、引用、TREE 高度、
CHAIN seed/reduce recipe、双 slot 组合、事件冲突及 HALT 可达性。

首版 compact composer 在格式中保留最多八个 segment 的字段，但硬件一次
缓存最多四个；编译器会拒绝多于四个的 recipe，避免静默截断。当前 Sign
和 Keygen recipe 最多使用四个 segment。

| 镜像 | token | template | 展开宏字 | descriptor words |
|---|---:|---:|---:|---:|
| Sign | 11 | 9 | 102 | 118 |
| Keygen | 3 | 2 | 3 | 118 |

这些镜像全部通过 `$readmemh` 静态装入，没有运行时写端口，也不包含消息
或密钥内容。由于实际镜像很小且有多个并行读点，Vivado 将其优化成
LUTROM；因此 BRAM 使用量为 0，而不是没有微码。

## 算法映射

Sign 程序结构为：

```text
HASH(PRF_msg)
HASH(H_msg) + digest route
RUN 33 x TREE(FORS)
HASH(FORS roots)
TRANSFORM(base-w)
TREE(XMSS layer 0)
LOOP 20 x {INDEX_STEP; BASE_W; TREE(XMSS)}
TREE(XMSS layer 21, external root)
HALT
```

Keygen 程序结构为：

```text
TREE(top XMSS, no auth/capture)
EMIT(sk_seed || sk_prf || pk_seed || root || pk_seed || root)
HALT
```

## 验证结果

| 验证 | 结果 |
|---|---:|
| tc137 Sign | 2,136 个 64-bit beat 全部一致 |
| tc137 cycles | 851,378 |
| tc137 Hash context / permutation | 10,680 / 105,641 |
| lane 物理互换 | 结果、周期、计数相同 |
| 消息长度 1/8/31/64/87 | 同一 Sign ROM 全部逐字一致 |
| 随机输出背压 | 逐字一致，851,878 cycles |
| Keygen tc31 | 12 个 64-bit beat、完整 `SK || PK` 一致 |
| Keygen cycles / logical Hash / permutation | 32,355 / 4,495 / 4,527 |
| standalone `CHAIN` macro KAT | 通过，67 cycles |

## 最终 PPA

器件为 `xc7a200tffg1156-3`，U2，100 MHz，`PROFILE_ENABLE=0`：

| 指标 | post-synth | post-route |
|---|---:|---:|
| LUT / FF | 22,778 / 9,177 | 22,446 / 9,175 |
| LUTRAM | 704 | 690 |
| RAMB36 / DSP | 0 / 0 | 0 / 0 |
| Equivalent Slice (`LUT/4 + FF/8`) | 6,841.63 | 6,758.38 |
| WNS / TNS | +0.068 / 0 ns | +0.024 / 0 ns |

分层 post-synth 面积：

| 层级 | LUT | FF | LUTRAM |
|---|---:|---:|---:|
| 通用执行器控制/compose/route | 5,783 | 4,675 | 0 |
| lane 0 | 7,258 | 2,194 | 0 |
| lane 1 | 7,258 | 2,194 | 0 |
| endpoint store | 1,140 | 0 | 264 |
| node store | 992 | 0 | 440 |
| macro sequencer（含 scoreboard） | 347 | 114 | 0 |

构建报告位于
`build/vivado/generic_macro_sign_stage7_chainmacro/` 和
`build/vivado/generic_macro_sign_stage7_chainmacro_postroute/`。最终路由
没有 failed、unrouted 或 partially-routed net。

## 已知边界

首版只实现 SHAKE-128f、`n=16`、1--87 byte 消息和高度不超过 6 的树。
Sign 与 Keygen 使用两个重新综合时选择的静态 ROM，不支持运行时切换。
Verify、XMSS、LMS、192/256 参数集和 SHA-2 后端不属于本轮实现。
