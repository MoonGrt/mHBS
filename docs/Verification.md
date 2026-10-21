# 模板CHAIN验证口径

默认整核44项：SHAKE六组SLH与XMSS/LMS h10的三操作24项、四组高树Verify4项；SHA2两组SLH与XMSS/LMS h10的三操作12项、四组高树Verify4项。

完整Keygen/Sign逐字节检查输出和签名缓存，核对64位Hash/置换计数。实际填充块与完整Hash结果使用count/SUM256/XOR256指纹和ControlVM比较，允许合法调度改变任务顺序；指纹属于概率校验。ControlVM另与main逻辑VM核对任务多重集。

附加检查覆盖控制指令权限、CALL/RET、溢出、RAM边界、后端/profile拒绝、q和地址边界、空/87字节消息、停顿、截断、篡改、复位、异常、统计裁剪及签名保存宏。

h16/h15/h20只做真实高度Verify，不生成完整树；合成兄弟路径不代表完整Keygen/Sign正确性。h20完整Keygen/Sign保持停止。

最终通过/失败/待完成状态以[实验索引](manifests/experiments/INDEX.md)链接的冻结实验报告为准。首轮template_chain_20261021_151056保留测试入口缺陷记录；修正后的整批验收为template_chain_20261021_151824，生产RTL一致。面积统一为common，不含ROM/签名缓存，100MHz ATP是假定频率，本轮未布线。
