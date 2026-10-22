# main 三层镜像 ABI：slh64_v4.2 / external layout 3

当前 image-chain-tree 使用 main05051299 的 program16×64、template16×64、descriptor32×64。不使用历史 `hbs_micro64 ABI4` 的512条 opcode 程序；两者不可混用。

program 的 [63:62] 为 SINGLE/RUN/LOOP/HALT；普通 token 的 [61:58] 为模板号、[57:47] 为 layer/group 坐标、[46:41] 为剩余重复数、[40:30] 为坐标步长，低30位保留零。LOOP 支持两级有界循环。Keygen/Sign 入口来自 descriptor0；Verify 使用 Sign 入口并由执行器的 Verify 数据路径执行。

template 低17位：[2:0] 为 HASH=1、CHAIN=2、TREE=3、TRANSFORM=4、EMIT=5；[7:3] descriptor、[12:8] route；[13] CAPTURE、[14] AUTH、[15] EXTERNAL_ROOT、[16] SIGN_ONLY，其余位为零。

descriptor 包括 profile、单 Hash 配方、整组 CHAIN、TREE、route、transform 和输出段。profile bit5 表示 SHA2，低5位为配置码；SLH为0/1/2/4/5/6，XMSS为0x18/19/1a，LMS为0x1b/1c/1d。SHA2拒绝SLH192/256。TREE高度的低4位为[43:40]，高位为39。

CHAIN/TREE 通过描述符引用配方，不在 program 中编码旧36/37操作码。HASH配方可包含标准XMSS key/mask或SHA2 HMAC/MGF1；密码学Hash计数以实际完整SHAKE/SHA256调用为准。

生成器为 model/mHBS.py、model/stateful.py；逻辑VM为model/executor.py。ROM容量固定，实际使用条目和非零条目分开统计（有语义的零profile不算填充）。全部已有main标准参数镜像须逐字匹配冻结基线。
