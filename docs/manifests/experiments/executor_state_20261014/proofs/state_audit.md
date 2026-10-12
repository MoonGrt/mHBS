# executor state_t 只读审计（2026-10-14）

审计源是冻结 baseline `20261014_182411/source/rtl/executor/executor.sv`；行号均指该源，源码 SHA256 见 `state_audit.json`。

当前三个算法已经共用一个主状态寄存器，Job 互斥使算法阶段资源可复用，但不能自动删除等待、RAM 读写和握手所需拍数。真正低风险的冗余是三套返回地址存储。

| 候选 | 行为变化 | 周期预期 | 面积预期及边界 |
|---|---|---|---|
| A：hash/output/verify 返回寄存器共用 continuation | 不改任何主状态数字和跃迁，消费者仍在原拍执行 | 完全相同 | 声明宽度21→7；考虑常量折叠后可变位估计18→7，直接FF节省最多11，新增写选择器须实测 |
| B：删除无引用状态并紧凑6位编码 |67个名称减5死名称，清理4个数字空洞，保留输出哨兵 | 完全相同 |62个名称可用6位表示；直接FF收益很小，主要观察译码映射，不能先验保证面积下降 |
| L-tree/FORS共享 issue 状态 | 两者 issue槽递增和结束测试相同，以锁存xmss识别算法 | 逐拍一对一可保持 | 需要同步合并端点读地址/返回ready/pipe_mode译码；保留FORS_LEFT预读拍 |
| L-tree/LMS共享叶提交状态 |仅输入节点来源不同，共用node/value写和PUSH转换 | 逐拍一对一可保持 | 新256位源选择可能抵消控制节省，须实测 |

`PIPE_CAPTURE`、`PIPE_ADVANCE`、`SF_REDUCED`、`LT_PIPE_ADVANCE`、`FORS_RIGHT` 完全没有功能引用；删除用于可读性，综合原本就不会为不可达状态生成有效功能。`PIPE_CAPTURE_NEXT`不同：它虽不进入主case，仍是OUTPUT_CHUNK连续输出捕获的哨兵，必须保留。`LT_SETUP/LT_STORE/LT_NEXT`是P1真实标量L-tree状态，不能删除。

A的生命周期证据：start_hash先登记返回地址，再进入HASH_ISSUE/HASH_WAIT，中途不启动output或Verify输入；返回在lane_valid拍消费。P1 recipe多次读取外部parent_right，因此整个HASH_ISSUE/HASH_WAIT期间continuation必须不变，不能只检查请求接受拍。start_output先登记再进入OUTPUT_CHUNK；多拍捕获保留哨兵，直到末拍退批。read_verify_node先登记再进入VERIFY_INPUT，节点接受后才有后续hash。它们按阶段序列互斥，甚至不依赖跨算法Job互斥。

复位把共享continuation初始化IDLE，保留原verify_return的复位语义。旧hash_return/output_return无复位，但它们只在对应task已写入之后消费；新增初始化不会改变功能。inactive parent_right可能不同，recipe不接受它；活跃哈希期间必须逐拍一致。

需要保留的状态包括FORS_LEFT（RAM地址提前登记）、PUSH_STACK（认证节点与树栈同写口冲突串行化）、LT_COPY（奇数L-tree尾节点搬移）。同一算法内同时存活的树栈/认证路径及hash/out/input边沿，不能因算法Job互斥就覆盖或删拍。

逐拍验证脚本在 `lockstep/run_lockstep.py`，只在独立build目录把baseline executor/common改名gold；冻结源和生产RTL不修改。它比较主state（按名称归一化，支持B重新编码）、公共握手/ROM地址/输出、RAM地址/写数据、活跃task和parent_right、batch输入、消费者活跃期返回地址、统计以及现有C++driver的逐字节输出和签名缓存。增量结果见 `lockstep/A/SUMMARY.json`。这是所跑向量的逐拍检查，并非全输入形式化证明。
