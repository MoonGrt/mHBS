# image-chain 架构

硬件固定K1U1、一个物理Hash通道、单任务在途。生产文件仍采用本项目的common/top、sequencer/executor、SHAKE/SHA2 recipe、value/signature模块名称；无平行mhbs包装。

program通过template调用HASH、CHAIN、TRANSFORM、EMIT；descriptor决定配方、链规格、路由与序列化。CHAIN执行整组WOTS/LMOTS、端点归约、XMSS L-tree及叶压缩。SHA2的HMAC/MGF和XMSS key/mask仍属于main配方语义。

主树/FORS树由program显式执行：设置叶地址→CHAIN→认证节点判断/保存→读树栈→父HASH→更新层/索引→分支。硬件没有TREE遍历、自动父节点续算或TREE_STEP。

复用一份128×256工作区，链端点/根列表0～66，树栈68～87，认证路径88～107；108～127不开放给普通控制指令。遵守main的奇偶双读和单写口限制。同一Job中同时存活的数据使用不同区域；SLH/XMSS/LMS按Job互斥。

标量上下文复用叶/索引/层/目标等寄存器，单级CALL返回地址，不新增通用寄存器文件。四个值槽和Hash前端所需的左右节点按生命周期复用。只有CHAIN自动推进内部链步骤；树级步骤必须由指令推进。

[镜像ABI](ABI.md) · [控制ISA](Chain_Template_ISA.md) · [Job接口](Job_Interface.md)
