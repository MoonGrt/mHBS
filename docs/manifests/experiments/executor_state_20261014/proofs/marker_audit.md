# executor 状态与标记只读审计

证据基线为 `build/pu_sign_matrix/20261014_180342` 冻结源码及其 P1U1/P4U1/P12U1 `common` 综合。未启动 Vivado、综合或仿真；直接只读解压 DCP 内部 EDIF 获取寄存器实例，完整机器证据见 `marker_audit.json`。

## 状态编码与返回标记

基线 `state_t` 有 67 个名字、最大编码 70，声明 7 位。`PIPE_CAPTURE`、`PIPE_ADVANCE`、`SF_REDUCED`、`LT_PIPE_ADVANCE`、`FORS_RIGHT` 均无活动状态动作；去除它们及 `CHAIN_OUTPUT0=10`/`CHAIN_NEXT=14` 的历史编码空洞后，共 62 个名字，6 位足够。`PIPE_CAPTURE_NEXT` 仍作为 `OUTPUT_CHUNK` 的输出返回哨兵使用，应保留，尽管它不会进入主 FSM。

三点综合日志均未将 executor 提取/重编码为 FSM；主状态仍是二进制译码。EDIF 中 `state_reg` 物理 FF 分别为 53/43/42，全部是 7 个状态位及 `_rep` 扇出复制，而非几十个独立 one-hot 状态位。重新编码收益来自译码及布线拓扑改变，不能以删除 enum 名字数直接估算面积。

| 物理 FF，含扇出复制 | P1U1 | P4U1 | P12U1 |
|---|---:|---:|---:|
| state | 53 | 43 | 42 |
| hash_return | 9 | 9 | 6 |
| output_return | 6 | 7 | 7 |
| verify_return | 5 | 5 | 5 |

哈希、输出、Verify 接收等待在同一个主 FSM 上串行，因此三类返回寄存器可先合并为一个 `continuation`，保持写入边沿和返回边沿不变。还需保留父节点 `parent_right` 对 `PARENT_DONE` 的判别。`hash_return` 与 `verify_return` 已有综合常量位裁剪，实际收益需要 common 面积实测，不能假设完整 21 位都存在。

## 后续可研究的计数器复用

- `lt_count` 与 `fors_total`、`lt_cursor` 与 `fors_offset`、`lt_level` 与 `fors_level` 的用途分属 XMSS L-tree 与 SLH FORS，无交叠存活期。
- FORS 全层结果提交后才进入组根逐个入栈，因此 `fors_offset` 与 `fors_root_cursor` 可能共用。完成边沿的 RAM 读地址仍须由旧 offset 生成，不能提前覆盖。
- WOTS 的 `chain_cursor` 在 L-tree 前已完成，L-tree 后新叶会重新置零，因此它与 `lt_cursor` 值得单独验证；`transform_index` 在校验和完成后也不再被消费。
- 这些候选只分析，不纳入本轮返回寄存器/编码修改。P1 的大部分 FORS 批处理计数器已被综合裁剪，算法间计数器复用对 P1 未必降低面积。

不能合并滚动调度的 `pipe_next_chain` 与 `pipe_completed`，因为已发出数与已返回数同时存活；不能覆盖批次捕获消费期间的 `pipe_expected_mask`；不能将 `fors_base` 与 `leaf_cursor` 混用，二者在组根并入高层树期间同时存活。`value[0:3]`、result、emit_value、node_value 也可能在同一操作内同时存活，不能仅因算法互斥而覆盖。

## 重编码观察器风险

数字状态比较只出现在活动 `tb/tb.sv`、`tb/tb_fast.sv`、`scripts/profile_p4.py`。FORS_PICK=58、LT_COPY=46、LT_PIPE_ISSUE=55、HASH_WAIT=23、IDLE=0、FAILED=32 均应换成由枚举名导出的稳定整数别名。错误注入应用状态类型宽度的全 1 值；6 位 compact62 中 63 仍非法。profile 使用 continuation 的名字，并由源码 enum 自动导出名称映射。`tb_recipe.sv` 的 STREAM_STATE 属 recipe 独立状态机，保持原样。

观察器直接跨层引用 enum 常量触发 Verilator 5.008 internal fault，10 项失败已保存 `OBSERVER_DIRECT_ENUM_FAILURE.json`。独立 scratch 把 enum 名字转为 localparam integer STATE_* 后，全源码 tb P1 normal 与 tb_fast P12 SYN lint 通过，见 `observer_alias/VALIDATION.json`。正式观察器改为 STATE_* 别名；最终 10 项正常/SYN lint 的结果单独写入 `OBSERVER_VALIDATION.json`，patch 在 `observer.patch`。详细 lint 日志保留 build，正式实验仅归档摘要。

最终正常/SYN 观察器 lint **10/10 通过**，生产 8 个 RTL 源文件前后校验相同。局部 Python 编译和 `git diff --check` 也通过。本代理没有修改生产 RTL、没有启动综合或完整 Sign。新增的 STATE_* 常量由根代理维护。第二次兼容性失败由注释以 Verilator 开头而被工具当成 pragma 导致，摘要见 `OBSERVER_ALIAS_COMMENT_FAILURE.json`；重写注释后通过。
