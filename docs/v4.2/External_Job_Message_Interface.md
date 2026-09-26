# μHBS v4.2：Job 参数与外部消息接口

生产物理格式 `slh64_v4.2`，布局修订 **3**；保留 ABI 4 五类宏操作语义。当前为功能及 post-synth 验收，通过后不推定布线频率。

## 接口与执行

`uhbs_top` 通过 256 位参数 `SECRET_SEED / SECRET_PRF / PUBLIC_SEED / RANDOMIZER / PUBLIC_ROOT` 直接提供 Job。128f/192f/256f 使用低 128/192/256 位，节点第一个字节位于低 8 位。参数默认采用现有 128f 测试向量。
`OPERATION=0/1` 分别为 Keygen/Sign；`message_length[6:0]` 是顶层输入，Keygen 必须为 0，Sign 范围 1–87。在 Job 提交沿检查并锁存合法长度；非法长度以错误码 `0x3002` 停机。Sign 的公钥根由调用方预先提供。
消息使用 `message_data[63:0] / message_valid / message_ready`，低字节先传；只在 valid 与 ready 同时为 1 的时钟沿接收。尾拍多余字节忽略，无 last/keep 输入。发送端须在 valid=1、ready=0 时保持数据及 valid；Keygen、接收完成、完成停机及错误停机时 ready 为 0。消息长度在 Job 提交前保持稳定，此后可改变。
全体 RTL 使用高有效同步 `rst`，仅在时钟上升沿复位，无复位同步器。每次复位自动执行一次操作，然后保持完成/错误状态。结果流保持无背压。Job 参数在一次运行中恒定。

```systemverilog
uhbs_top #(
    .SECRET_SEED(256'h...), .SECRET_PRF(256'h...),
    .PUBLIC_SEED(256'h...), .RANDOMIZER(256'h...), .PUBLIC_ROOT(256'h...),
    .OPERATION(1),
    .PROGRAM_INIT_FILE("program.mem"),
    .TEMPLATE_INIT_FILE("template.mem"),
    .DESCRIPTOR_INIT_FILE("descriptor.mem")
) dut (
    .clk(clk), .rst(rst), .message_length(message_length),
    .message_data(message_data), .message_valid(message_valid),
    .message_ready(message_ready),
    // 连接现有结果流、状态及周期/Hash计数输出
    ...
);
```

## 镜像布局与共同核边界

program 为 **32×64** 纯指令；template 为 **16×64**；descriptor 为 **32×64、双读**。每个 SLH 参数点共用 Keygen/Sign 两个入口，只需一组三 ROM 镜像。Job 配置和测试消息在 `vectors/<profile>/<operation>/` 中单独记录。
descriptor 0：bits17:0 为 Sign 输出字节数，bits35:18 为 Keygen 输出字节数，bits40:36 为 Keygen 入口，bits45:41 为 Sign 入口，其余为零。descriptor 1 保留参数集编号 0/1/2。软件验证入口与程序边界一致；生产硬件不扫描校验镜像。
旧布局 2 转换：`python3 scripts/convert_v42_external.py <旧镜像目录> <输出目录>`，输出三份布局 3 镜像、独立 job.json 和 message.mem。旧数据及布局 2 模型保留，用于历史复现。
`uhbs_processor.sv` 已删除；镜像读取、启动、入口选择、消息长度检查和操作周期统计位于 `uhbs_top`。Boot 为 2 拍。五类宏指令及 Hash 数据通路由 `uhbs_hbs` 执行。
构建工具从顶层源码提取启动控制与执行核，生成仅用于构建的 `uhbs_common`，一起综合一次；Job、消息和 ROM 数据均为输入；六个参数外壳分别综合后链接同一份 EDIF。共同核设置 DONT_TOUCH，防止外层常量继续裁剪。核的单元配置与内部连接指纹一致；外部常量及边界连接允许不同，完整顶层不再承诺同一布局布线。

## 实测资源与周期

所有新资源均为 Vivado 2025.2、xc7a200tffg1156-3 的 **post-synth** 结果；U2、双 Hash lane。面积公式为 LUT/4 + FF/8 + BRAM36×232.4 + DSP×102.4。

| 测量对象 | LUT | FF | LUTRAM | BRAM36 | DSP | 等效 Slice |
|---|---:|---:|---:|---:|---:|---:|
| 共同执行区（启动＋核） | 23,091 | 10,893 | 1,456 | 0 | 0 | 7,134.375 |
| slh_128f_keygen | 23,219 | 10,893 | 1,456 | 0 | 0 | 7,166.375 |
| slh_128f_sign | 23,219 | 10,893 | 1,456 | 0 | 0 | 7,166.375 |
| slh_192f_keygen | 23,219 | 10,893 | 1,456 | 0 | 0 | 7,166.375 |
| slh_192f_sign | 23,219 | 10,893 | 1,456 | 0 | 0 | 7,166.375 |
| slh_256f_keygen | 23,219 | 10,893 | 1,456 | 0 | 0 | 7,166.375 |
| slh_256f_sign | 23,219 | 10,893 | 1,456 | 0 | 0 | 7,166.375 |

| 顶层配置 | Boot | 操作周期 | 上电总周期 | Hash/置换 | 完整顶层 ATP@100MHz |
|---|---:|---:|---:|---|---:|
| slh_128f_keygen | 2 | 29,868 | 29,873 | 4,495/4,527 | 2,140.453 |
| slh_128f_sign | 2 | 731,050 | 731,055 | 104,937/105,641 | 52,389.784 |
| slh_192f_keygen | 2 | 43,666 | 43,671 | 6,543/6,615 | 3,129.269 |
| slh_192f_sign | 2 | 1,252,461 | 1,252,466 | 168,881/170,462 | 89,756.052 |
| slh_256f_keygen | 2 | 115,784 | 115,789 | 17,183/17,439 | 8,297.516 |
| slh_256f_sign | 2 | 2,583,908 | 2,583,913 | 345,414/349,758 | 185,172.537 |

旧布局 2 同阶段综合基线：23,073 LUT、12,195 FF、7,292.625 Slice。旧布线基线另列为 7,249.000 Slice、101.010101 MHz，不能把这个频率用于新顶层。
前一版外部消息顶层（含 `uhbs_processor`）同阶段综合面积为 7,110.000 Slice；本候选将启动逻辑并入顶层，按完整顶层资源比较。本轮保持启动控制与核共同综合，内部固定连接继续参与优化；构建产物 `uhbs_common` 不属于生产 RTL。
100 MHz 仅用于 ATP 归一化，不是本轮已通过布线的频率。表中为现有固定向量、连续供数；Sign 周期包含消息接收和输入停顿，消息改变也可能改变链计算周期。上电总周期包含启停控制，无两拍复位同步器开销。

## 验证与复现

软件六组输出、独立模型/KAT、Hash轨迹/计数及旧布局转换通过；Icarus 启动协议、复位、入口、单次运行、消息握手与既有宏/Hash/存储单元通过。
Verilator 六组正常执行及 33 项扩展验证通过：实际 RTL Keygen 根配置到独立 Sign 参数、物理 lane 交换、复位中断重放、1/7/8/9/87 字节、尾拍噪声及 87 字节中途停顿。停顿增加的 Sign 周期与记录的等待拍数一致。提取后的共同执行区另跑六组完整仿真，与直接顶层输出、计数和周期一致。
共同核内部指纹：`c6f77e58f573f74fb95ab6767250ee00604e861665493c47e2b198f9a4e4db98`。六个外壳分别检查推断 ROM 的 256 个 LUT 单元及初始化映射。原始综合层次资源、关键路径和每阶段耗时封存在候选 `sync_c0`。
本轮验收为 **功能通过、共同核结构通过、post-synth 通过**；post-route 未执行。历史提交 `366b614` 及原 v4.2 完整布线证据保留。

```bash
make compile-microcode rtl-unit-test
make rtl-all-profiles TAG=<新候选>
make rtl-verification TAG=<新候选>
make synth-common TAG=<新候选>
make report-v42 reproduce-v42
```

精确复跑本次候选时，解开 source_snapshot.tar.gz，并叠加 verification_tools.tar.gz 中补充的测试/复现工具；实测 RTL 与镜像必须保持 inputs.json 记录的哈希。新证据位于 `manifests/experiments/unified_hbs_v4.2/external_job_message/`；工具工作目录位于 `build/v4.2/external_job_message/`。
