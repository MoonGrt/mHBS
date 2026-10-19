# main 模板宏架构

common 负责外部 Job 和 program/template/descriptor 接口；sequencer 单次发出一个宏命令；executor 完成 HASH、整组 CHAIN、完整 TREE、变换和输出；recipe 负责后端标准前像及单物理 Hash 通道。

本轮K1U1的SHAKE采用标量迭代Keccak，SHA2采用单任务SHA256。main保留的P/U参数结构不作为本轮新增并发功能。共享128×256位节点区保留main布局：端点0～66，树栈68～87，认证路径88～107，FORS临时节点复用已经失效的端点36～59。没有为算法各建一份树存储。

TREE逐叶调用CHAIN，CHAIN内部生成整组链并压缩成叶子。XMSS的L-tree和LMS列表压缩均属于叶构造；FORS/Merkle父节点、目标路径和认证输出由TREE控制。计数报告区分主程序直接CHAIN命令和TREE对子CHAIN的调用。

历史ABI4单链宏设计已被替换；仅历史快照、历史报告仍描述它。
