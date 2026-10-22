# 当前 ISA

见 [ABI](ABI.md)。程序token选择template；template选择HASH/CHAIN/TREE/TRANSFORM/EMIT。CHAIN是main整组链及叶构造；TREE是完整单棵树。主程序没有旧ABI3/4的opcode36/37，指令数、模板数、描述符数与动态宏调用数应分别报告。

软件只接受生成器验证的有限镜像；生产RTL依赖离线验证合同，不能宣称对任意恶意program/template都有完整逐指令硬件权限防护。Job启动会检查profile、后端和q，异常Hash会进入故障停止。
