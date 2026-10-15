# SHA2 formatter 局部验证与只读审查

冻结 `rtl/hash/sha2-recipe.sv` SHA256：`798454974b2eb7ce98cafba2838e54f4f0961b8cfb9f2546c19216ac14874f81`。测试前后所有记录依赖校验一致。

| 测试 | 用例 | 结果 | 日志 |
|---|---:|---|---|
| p1u1_normal | 345 | PASS | `build/sha2_optimization/local_validation/p1u1_normal.log` |
| p12u1_synthesis | 345 | PASS | `build/sha2_optimization/local_validation/p12u1_synthesis.log` |
| p4u1_mask101e | 74 | PASS | `build/sha2_optimization/local_validation/p4u1_mask101e.log` |

合计 764 个配方案例。普通视图直接核对 Hash/压缩计数；SYNTHESIS 视图从功能完成事件独立计数，逐字节输出和捕获结果均一致。mask 0x101e 同时核对未启用 shape 拒绝，且拒绝前无 Hash。

## 拼接与填充核对

- 数据源采用 byte 0 位于低位的节点格式，提交 SHA256 前统一反序为高位字节先输入；CV 返回时按相反方向转换。长度域先 be64，再经同样字节输出，得到标准大端 64 位 bit length。
- `(L+8)>>6` 正确给出最后压缩块索引；在 byte L 插入 0x80，最后块 byte 56..63 填入 bit length。54/55 字节分别为尾部 6/7 字节数据；56、63 字节转入下一填充块，64、128 等整块长度增加填充块。
- SLH 86 字节前缀和 LMS 22 字节前缀都使用 6+10 字节 bridge；LMS seed/chain 23 字节前缀使用 7+9 bridge。后续固定 SHIFT_TWO / SHIFT_ONE 分别取跨 64 位字的偏移 2/1 字节窗口，无每字节可变源选择。
- SLH list 从全局 beat 6 起以节点对相对 word 1 开始，索引为 beat-6；LMS list 从 beat 2 起索引为 (beat-2)/2，偶数 beat 取 word 1，奇数取 word 3。长列表 2166/2214 字节覆盖多块索引，未再截断为 8 位 byte offset。
- SEND 接受旧 block 时才准备下一槽；旧 block_buffer 在握手沿后仍不被提前覆写。下一 BUILD 采用提前登记控制及 executor 提前一拍登记的相邻 RAM 地址，和现有异步读口配合正确。

全部编译警告均来自 tb_recipe 的固定常量宽度、计数比较宽度；本次未出现 sha2-recipe 或 sha256 RTL 警告。

验证范围：标量配方路径、捕获、统计、复位重放、响应停顿、mask 拒绝。整核计时、批量调度、综合面积由其他任务给出，本摘要不将标量测试替代这些证据。
