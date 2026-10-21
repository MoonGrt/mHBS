# 当前执行指令

当前权威规范是[Chain_Template_ISA.md](Chain_Template_ISA.md)和[ABI.md](ABI.md)。本文件替换旧的hbs_micro64/opcode36指令说明；旧版通过Git历史恢复。

- 模板任务：HASH、整组CHAIN、TRANSFORM、EMIT；TREE不受支持。
- program控制：上下文装载/搬运、加法/递增、移位/异或、条件跳转、单级CALL/RET、单节点LOAD/STORE、Verify INPUT、OUTPUT和宽值搬运。
- Hash请求来自显式HASH模板或显式CHAIN模板内的有界链操作；普通控制指令不会启动Hash。
- 标量只允许已定义上下文，q等Job属性只读；移位、字段宽度、层高及RAM地址按规范检查。禁止嵌套CALL、无CALL的RET、非法模板、跨后端或旧格式镜像。

编译器检查128/32/32容量，解码器检查格式/配方权限。main兼容的RUN/LOOP保留；当前编译器通过SINGLE和显式分支生成树程序。
