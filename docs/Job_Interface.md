# mHBS 当前 Job 与流接口

唯一生产顶层为 `rtl/top/mhbs_top.sv`。支持 SLH-DSA SHAKE 128f、192f、256f，每次复位执行一次 Keygen 或 Sign。

## 配置

`OPERATION=0/1` 分别选择 Keygen/Sign。`SECRET_SEED`、`SECRET_PRF`、`PUBLIC_SEED`、`RANDOMIZER`、`PUBLIC_ROOT` 为五个 256 位综合参数，分别使用低 128/192/256 位；首字节位于低 8 位。默认值来自 128f 测试向量。切换参数集须同时使用对应镜像和 Job 参数。Sign 的公钥根由调用方提供。

ROM 路径使用 `PROGRAM_INIT_FILE`、`TEMPLATE_INIT_FILE`、`DESCRIPTOR_INIT_FILE` 参数指定。顶层没有运行时 Job 写入、start 或输出背压端口。

## 端口协议

| 端口 | 语义 |
|---|---|
| `clk` / `rst` | 时钟；高有效同步复位，至少覆盖一个上升沿 |
| `message_length[6:0]` | Keygen 为 0；Sign 为 1–87，在内部 Job 接受时锁存 |
| `message_data[63:0]` | 低字节先传，尾拍多余字节忽略 |
| `message_valid` / `message_ready` | 上升沿两者同时为 1 时接收一拍；等待 ready 时保持 valid 和 data |
| `out_valid` / `out_data[63:0]` | 结果流，无 out_ready；接收方必须及时接收 |
| `out_keep[7:0]` | 有效字节掩码，按低字节到高字节顺序拼接；非末拍也可能不足 8 字节 |
| `out_last` | 当前结果的最后一拍，与 out_valid 一起判断 |
| `result_kind` | 0 为 Keygen 的 SK\|\|PK；1 为签名 |
| `busy` | 复位时置 1，完成或错误时清零 |
| `done` | 操作完成后保持为 1，直到复位 |
| `keygen_done` | Keygen 完成单周期脉冲 |
| `error` / `error_code[15:0]` | 错误状态保持到复位，错误操作不产生 done |
| `boot_cycles` | header/profile 读取计数，正常为 2 |
| `keygen_cycles` / `sign_cycles` | 完成时锁存对应操作周期，未执行的操作为 0；包含消息等待 |
| `hash_count` / `permutation_count` | 当前操作的 Hash / Keccak 置换次数 |

在复位释放前设置好 message_length。Sign 可将长度保持到首次 message_ready，再开始发送消息；Keygen 保持 0 即可。消息没有 last/keep 输入，接收长度只由锁存的 message_length 决定。Keygen、消息接收结束、完成和错误停机阶段，message_ready 均为 0。

同步复位可以中断运行；重新释放复位后从头执行。顶层不自动将 Keygen 根接入随后一次 Sign，也不在完成后自动接受下一项任务。

错误码 `0x3002` 表示消息长度非法，`0x3005` 表示输出长度不匹配，`0x3006` 表示宏操作错误，`0x3007` 表示 Hash lane 错误。镜像的全面合法性检查由软件生成阶段完成。

验证命令及验收边界见 [Verification.md](Verification.md)。

## 仿真统计与综合裁剪

`PROFILE_ENABLE` 在仿真默认开启，在定义 `SYNTHESIS` 时默认关闭；生产共同核综合也显式设置为 0。关闭后 `boot_cycles`、`keygen_cycles`、`sign_cycles`、`hash_count` 和 `permutation_count` 保留端口但恒为零，内部计数寄存器、基准寄存器及统计加减逻辑裁除。此开关不影响签名/公钥输出、握手、错误处理和完成周期。仿真 testbench 另从实际完成的 permutation 和 hash 事件观察统计，用于检查两种配置行为一致。
