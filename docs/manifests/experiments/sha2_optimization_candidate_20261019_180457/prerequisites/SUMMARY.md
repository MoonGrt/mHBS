# SHA2 候选 2 调度仲裁等价验证

实际生产 RTL SHA256：`ef7948df9d287c1d5b400e20cd5b10f551c30272d1f6753e5e046444bb9820d0`。测试前后校验一致。

直接例化生产 recipe，clk 固定为 0，通过层级路径驱动 need_block 和 schedule_cursor；独立执行旧版环形 scan，逐项比较 candidate_valid、candidate 和 grant one-hot。未提取/复制候选仲裁实现。

| P | 方法 | 比较次数 |
|---:|---|---:|
| 1 | exhaustive | 2 |
| 2 | exhaustive | 8 |
| 3 | exhaustive | 24 |
| 4 | exhaustive | 64 |
| 6 | exhaustive | 384 |
| 8 | exhaustive | 2,048 |
| 12 | exhaustive | 49,152 |
| 24 | boundaries_random | 255,072 |

总计 **306,754 次 PASS**。P≤12 覆盖每个合法 cursor 和所有 need_block；P24 覆盖全部 cursor 的空/满、交替位、单请求、仅缺一请求、所有双请求、连续区间，以及每 cursor 10,000 个固定种子随机请求集合。

仲裁顺序一致：cursor 及之后存在请求时选择其中最低位，否则回绕选择所有请求中最低位；没有请求时 valid=0、candidate=0、grant=0。

仅比较可达的 cursor 范围 0～P−1；不把非 2 次幂 P 的未使用 cursor 编码或 X 传播视为功能等价承诺。该测试验证组合仲裁，完整批量握手/计算由其他回归覆盖。

`RESULTS.json` 记录命令、SHA、耗时及日志；`tb_arbiter.sv` 和 `run.py` 可复跑。
