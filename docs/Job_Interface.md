# K1U1 Job接口

每次复位执行一项Job。common使用外部program/template/descriptor端口，top集成同格式ROM。三个算法互斥。上游从复位释放到done/error保持Job字段稳定；消息和Verify节点采用ready/valid握手。

Job包含secret seed、secret PRF、public seed、randomizer、public root、q和identifier。LMS C映射到job_randomizer。q必须满足0≤q<2^h；q的持久化与复用防止由上游承担。

消息每拍64位；SLH接受1～87字节，XMSS/LMS接受0～87字节。Verify输入及输出数据256位，out_bytes指出本拍有效字节。

| 操作 | 输出/输入 |
|---|---|
| XMSS Keygen | 标准68字节公钥：OID、root、public seed |
| LMS Keygen | 标准56字节公钥：LMS type、LMOTS type、I、root |
| SLH Keygen | main原有密钥对序列化，共6n字节 |
| Sign | 标准完整签名字节，并可写签名缓存 |
| Verify | 上游先校验签名长度、类型、q及端序，再送R/C、链节点、认证节点；RTL比较根 |

软件标准格式解析/验证见model/reference/stateful_shake.py的parse_signature、parse_public_key、verify_serialized。当前image分支仍输出root/节点payload，与两个宏分支比较时统一成标准格式。

统计为64位仿真诊断，SYNTHESIS移除调试接口及寄存器；功能性error保持。签名保存由MHBS_SIGNATURE_STORE控制。握手、复位和停顿测试覆盖两后端。
