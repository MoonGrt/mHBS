# image-chain-tree 验证

当前入口见根 README。先执行源身份与镜像检查，再执行模型单元、lane/CHAIN/TREE协议单元、六SLH参数三操作回归、扩展故障/停顿检查、逐Hash工作核对、SYNTHESIS视图和top/cache等价检查。

`run_hash_backends.py all --tag <新tag> --extended` 在 `build/image-chain-tree/<tag>/` 留下原始日志和JSON。源输入、镜像或RTL改变后使用新tag；门禁拒绝绑定旧源码的验证摘要。宏和Hash监视区分普通HASH、独立CHAIN和TREE子链，不将子链Hash重复计入授权。

本分支仅SHAKE六SLH参数，不启动XMSS/LMS大树。程序ROM512条、descriptor32条、单物理lane、K1U1；ABI1/2/3/5镜像拒绝。本轮综合使用100MHz、2线程、共同核、PROFILE_ENABLE=0，不自动布线。

实验归档只保存Markdown/JSON验证摘要、冻结RTL、源校验和综合报告；原始仿真明细保留build。
