# μHBS ABI 4 fixed Job interface

## Product wrapper

SLH-DSA、XMSS、LMS 顶层均直接实例化 `mhbs_hbs`。Job 数据来自综合参数：
`SECRET`、`PRF`、`PUBLIC`、`RANDOM`、`IDENTIFIER`、`INITIAL_Q`、
`MESSAGE_BYTES`；默认值由通过软件仿真的现有 KAT 生成。顶层没有 Job 数据端口，
镜像 ROM 在运行时不可写。七点分别静态综合，顶层命名为 `mhbs_<profile>_top`。

`start && ready` 启动一次 Keygen → 消息接收 → Sign；每次启动只签一次。
`keygen_done` 和 `done` 是单周期脉冲，分别伴随锁存的 `keygen_cycles` 和
`sign_cycles`。计数包含消息等待、输出背压和索引提交等待。

| 接口 | 语义 |
|---|---|
| `message_valid/ready` | 64 位消息流，只在 Keygen 完成后接收 |
| `message_keep` | 从 bit 0 开始连续有效的字节掩码，不接受零或空洞 |
| `message_last` | 必须恰好落在综合时指定的消息长度 |
| `out_valid/ready` | 64 位结果流直接输出片段；背压期间 data/keep/last/kind 保持 |
| `out_keep` | 从低字节开始的有效掩码；非末拍也允许不足 8 字节，接收方依掩码串接 |
| `result_kind` | 0 为 SK\|\|PK，1 为签名；各自有 `out_last` |
| `state_commit_valid/ready` | XMSS/LMS 的下一索引持久化确认 |
| `state_next_q` | 外部应持久化的 q+1，允许终值 1024 |
| `error/error_code` | 错误保持到下一次内部 Job 接受，错误操作不发 done |
| `hash_count/permutation_count` | PROFILE_ENABLE 验证构建的操作计数 |

## Stateful 索引与缓存

Keygen 计算完整 h=10 树，只缓存当前 q 所需的认证路径和根。
Sign 在获得 q+1 的提交确认之前不会输出签名字节。已确认的索引在执行失败后
仍然烧毁；重新启动 Keygen 使用保留的下一索引。q=1023 是最后可签索引，
下一索引 1024 拒绝继续 Keygen/Sign。未确认提交时可以持续等待。

再次 `start` 将重建下一 q 的路径，因此这里没有跨多个签名复用完整树缓存的
吞吐量承诺。reset 清除易失状态和缓存；固定 Job 顶层用于完整流程和 PPA 测量，
不是掉电恢复接口。外部持久化服务不计入本核面积。

## 内部核接口

`mhbs_hbs` 的 `job_valid/ready`、`job_operation` 和 Job 数据仅连接到固定参数
与 `mhbs_job_sequence`。`job_operation=0/1` 选择同一镜像的 Keygen/Sign 入口。
算法顶层不需要理解宏操作、Hash 输入、树节点或 lane 调度。

错误码：3001 镜像/profile；3002 消息；3003 缓存/索引不匹配；
3004 初始索引/耗尽；3005 输出长度；3006 宏操作/descriptor；
3007 Hash lane；31xx sequencer；25xx stateful guard。
