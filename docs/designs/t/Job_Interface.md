# Job 与输出

种子、PRF、公共种子、randomizer、公钥根为256位，identifier128位，q32位。LMS C映射job_randomizer。消息输入64位，Verify节点和输出256位，ready/valid保持main接口。签名输出按out_bytes紧密拼接。

XMSS/LMS Keygen为标准68/56字节公钥，Sign为完整标准签名。Verify软件适配器先检查长度、类型、q及端序，再发送R/C、67条链节点和h个认证节点。SLH为main internal接口，不新增context/prehash。SLH消息1～87字节；stateful消息0～87字节；Keygen的消息长度必须为0。

q不自动持久化；上游承担唯一索引管理。每次复位一项Job。top签名缓存由MHBS_SIGNATURE_STORE选择，未启用时读回状态置零；统计/error_code端口仅非SYNTHESIS视图可见。
