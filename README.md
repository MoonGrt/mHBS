# μHBS v4.1：固定硬件，替换三个镜像

工程版本 **v4.1**，微码 **ABI 4**。唯一生产顶层 `uhbs_top` 仅输入 `clk` 和高有效 `rst`，
复位释放后自动执行 **镜像校验 → Keygen → 从 ROM 读取消息 → Sign → 停机**。

七个 profile 共用固定硬件，通过替换 program / template / descriptor 三个独立 ROM 的初始化内容选择算法。
program 含指令、Job 和消息；结果直接输出，无反压。XMSS/LMS 使用固定 q，无索引 guard 或提交握手；复位允许固定向量重放。
当前优化固定 U2、双 lane，保留三个分布式 ROM。

支持 SLH-DSA SHAKE 128f/192f/256f、XMSS ω=2/4、LMS ω=2/4（SHAKE256/256 研究 profile）。
ω 是每个 Winternitz 数字的位数。

## 构建与验证

```bash
make test                         # 软件模型、独立参考/KAT、镜像门禁
make compile-microcode            # 门禁有效后导出三个镜像
make rtl-unit-test                # Icarus 12
make rtl-profile-test PROFILE=slh_192f  # Verilator 5.008 --binary --timing
make rtl-all-profiles LANES=2 UNROLL=2  # 同一仿真二进制替换七套镜像
make rtl-verification             # 边界索引、复位重放、lane 交换
make synth-common TAG=my_candidate LANES=2 UNROLL=2
make route-common TAG=my_candidate  # 输出 my_candidate_route，保留综合证据
make freeze-common TAG=my_candidate
```

共同候选按 post-synth 面积和 100 MHz 归一化签名 ATP 筛选，再进行 post-route 验收。
每个候选只综合、布线一套共同硬件，冻结后仅修改 ROM INIT。
功能通过和性能通过分别记录；七项 ATP 与三项 V3 不退化条件均通过才完成性能验收。

## 文件与证据

- [v4.1 架构与镜像](docs/v4.1/Architecture_and_Image.md)
- `rtl/top/uhbs_top.sv`：唯一生产顶层；`uhbs_processor`：通用 ROM 接口处理器；`uhbs_hbs`：执行核。
- `manifests/unified_sources.txt`：当前生产 RTL 编译闭包。
- `manifests/experiments/unified_hbs_v4.1/`：软件门禁、镜像、仿真、共同硬件验收证据。
- `build/v4.1/`：仿真二进制、源码快照及 Vivado 工作目录。
- `manifests/experiments/unified_hbs_V3/`：历史三点与未完成 U4 候选。
- `manifests/experiments/unified_hbs_v4/`：历史七点分别静态综合的证据。

历史结果不代表 v4.1 的共同面积与性能。旧架构报告保留原数据；对应源码从固定版本或归档快照复现。

```bash
python3 scripts/reproduce_paper_comparison.py  # V3
python3 scripts/reproduce_seven_profiles.py    # V4
make reproduce-paper-comparison               # V3、V4、v4.1 联合核验
python3 scripts/replay_profile.py slh_192f --run rtl-profile-test  # V4 快照重跑
```

论文比较的算法版本、固定输入和缓存策略差异均标为 **NON_STRICT**。
