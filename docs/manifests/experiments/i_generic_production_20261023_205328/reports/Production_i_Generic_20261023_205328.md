# 生产采用 i-generic

根据用户要求，生产模型与20组i镜像采用原通用软件链循环，保留当前指令预取、Hash边界压缩、FORS/DIGIT操作数登记等RTL时序修复。c/t及两后端Hash实现不变。i-opt保留在提交 `f9887f5b` 与历史冻结包中。

| 后端 | 33B Sign周期 | Hash周期 | Remaining | i→c降幅 | c→t降幅 |
|---|---:|---:|---:|---:|---:|
| SHAKE | 4,441,035 | 2,536,104 | 1,904,931 | 30.38% | 15.41% |
| SHA2 | 9,247,544 | 6,923,410 | 2,324,134 | 18.66% | 6.33% |

既有两后端33字节KAT已逐字节核对签名和缓存，Hash及物理块数与i-opt一致。生产模型、ROM和全部i RTL与该次实测输入逐字节一致；20组i及60组全设计静态镜像核对通过。额外20组生产Verify结果归档为VERIFY_SUMMARY.json，原始明细留在运行目录。h20只执行Verify，不启动完整Keygen/Sign。

两后端100MHz证据对应相同common RTL；本次未新增综合/布线，不覆盖含ROM的top。SHA2 i-generic的Remaining高于SLotH，先前双后端低于SLotH的结论仅适用于i-opt。
