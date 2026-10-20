# image-chain：模板控制镜像

当前为 `main_chain64_v4` / layout 4：program128×64、template32×64、descriptor32×64，PC7位、模板索引5位。它与历史 HashFlow opcode36/37 的 ABI3/ABI4 不兼容。历史实现保存在 `3a625c1` 及之前的 Git 提交。

[完整控制 ISA](Chain_Template_ISA.md) 定义所有指令与权限。HASH、CHAIN、TRANSFORM、EMIT 沿用 main 的宏及配方语义，TREE 模板被拒绝。

## 物理字段

- descriptor0：`[63:57]=0x53`；Verify入口`[56:50]`、Sign入口`[49:43]`、Keygen入口`[42:36]`；`[35:18]` Keygen输出长度，`[17:0]` Sign输出长度。
- descriptor1：`[4:0]`配置码，bit5后端（0 SHAKE、1 SHA2），`[63:6]`必须为零。SLH配置码0/1/2/4/5/6，XMSS为0x18～0x1A，LMS为0x1B～0x1D。SHA2只允许SLH128f/s及stateful配置。
- template：`[2:0]`操作（HASH1、CHAIN2、TRANSFORM4、EMIT5）；`[7:3]`描述符；`[12:8]`路由；bit13 CAPTURE、bit14 AUTH、bit15 EXTERNAL_ROOT、bit16 SIGN_ONLY；高位为零。
- 普通program保留main的SINGLE/RUN/LOOP字段；bit29扩展模板索引，bit28表示保留软件设置的坐标。kind3用于显式控制，opcode0为HALT，其余字段见完整ISA。

描述符保留main的格式及物理引用映射，只有header采用新入口/版本字段。固定表中保留合法但未使用的TREE参数记录，不意味着硬件支持TREE。有效记录数、程序可达记录数、非零记录数分别统计；零值profile身份仍是有效记录。

镜像必须在部署前经过Python解码/权限校验。硬件检查后端、profile、q、模板类型及执行中的标量/RAM权限，不代替完整离线验证。错误后停止，直到复位。
