#!/usr/bin/env python3
"""Render the measured mHBS cycle evidence and bounded SLOTH comparison."""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
ORDER = ['128f', '192f', '256f', '128s', '192s', '256s']


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tag', default='mhbs_cycle_profile_20261002_v1')
    ap.add_argument('--k1-tag', default='mhbs_cycle_profile_k1u1_20261002_v1')
    args = ap.parse_args()
    archive = ROOT / 'manifests/analysis' / args.tag
    result = json.loads((archive / 'results.json').read_text())
    rows = result['cases']
    assert result['passed'] and len(rows) == 18
    sloth = {}
    for line in (archive / 'SLOTH_SHAKE_CYCLE_REPORT.md').read_text().splitlines():
        cols = [c.strip() for c in line.split('|')[1:-1]]
        if len(cols) == 9 and cols[0].startswith('SHAKE-'):
            sloth[cols[0][6:] + '_' + cols[1]] = dict(zip(
                ('total', 'other', 'transfer', 'hash'), [int(cols[i].replace(',', '')) for i in (2, 3, 5, 7)]))
    assert len(sloth) == 18
    pct = lambda a, b: f'{100*a/b:.2f}%'
    num = lambda n: f'{n:,}'
    evidence = f'../../manifests/analysis/{args.tag}'
    text = [f'''# mHBS SHAKE 周期构成与 Hash 输入组织效率分析

日期：2026-10-02。基线候选：`{result['candidate']}`。配置：K2U2，六种 SLH-DSA SHAKE 参数，Keygen／Sign／Verify。

## 1. 结论与贡献定位

本次在独立冻结源码上加入 testbench 只读观察器，完成 18 项 RTL 仿真。所有 Keygen/Sign 输出仍逐字节通过现有参考检查，Verify 接受正确签名；总周期与已验收基线完全一致。观察器未修改生产 RTL，也未启动综合或布线。

本设计使用微码表达宏操作顺序和循环，再由 recipe 数据通路生成 ADRS、选择 seed/节点/消息、拼接填充并驱动 Hash lane。短输入采用宽并行快装，长输入采用分块构造，链计算在 lane 内反馈。周期数据可以评估这种联合设计使 Hash 数据通路持续工作的程度。

本报告将“组织 Hash 的输入消息”作为贡献方向。其中的消息包括 PK.seed、ADRS、中间节点和用户消息等组成的 Hash 输入，不仅指外部待签名消息。**现有结果支持较低的非置换周期占比；相对 RISC-V＋Hash 的因果收益还需对齐 K/U、输入向量和算法调度后做消融。**

## 2. 测量边界与分类

### 2.1 环境与正确性

- 使用 Verilator 5.008，`--binary --timing -O3`；每次构建 8 线程，最多 3 项并行。
- 当前生产 RTL 与归档候选源码哈希匹配后冻结；镜像、向量、测试平台、命令、编译及仿真日志保存在证据目录。
- Keygen 消息长度为 0，Sign/Verify 为仓库的 1 B 消息向量；正常供数，无主动外部停顿。
- 统计复位释放至首次完成的总周期，包含启动与结束，不含完成后 40 拍的稳定性检查。Keygen/Sign 的核内计算周期为总周期减 5。
- SLOTH 参考报告使用 33 B 消息及首个 KAT，边界为软件函数入口至返回；两者边界和工作负载不同，本文直接比值只作已有实现快照对照。
- 本次只运行正常 KG/Sign/Verify；完整错误与复位回归沿用归档候选证据，不将其说成本次重新执行。

### 2.2 三类互斥周期

每个统计时钟依下列优先级归类，三类相加严格等于总周期：

| 优先级 | 本报告类别 | 观测规则 |
|---|---|---|
| 1 | Hash 运行 | 任一 lane 的 sponge `lane_state==RUN`，实际执行 Keccak 轮计算；两 lane 同时运行只计一拍 |
| 2 | 内部交接/装载 | 没有 lane 运行时，存在 recipe 请求或响应握手、context 接收、快块装载或 128 位吸收握手 |
| 3 | 其余组织/控制 | 其余所有统计拍：微码调度、树/链索引、输入构造、路由、输出及启动结束等 |

内部交接/装载是硬件握手事件占用的拍数，**不是 SLOTH 的 MMIO 总线事务**。其余组织/控制也不是纯输入拼接时间。SLOTH 报告的“哈希输入构建”同样包含树遍历、内存访问和其他 CPU 工作，本文将其称为“剩余 CPU/组织周期”。

观察器同时统计两条 lane 的活动拍、同时活动拍以及 recipe `START/STREAM` 状态驻留。存在重叠时，主表优先归为 Hash；附表保留重叠信息。宽组合拼接可能与其他工作同拍完成，不能据此称其面积、时序成本为零。

## 3. 18 项周期构成实测

| 参数集/操作 | 总周期 | 其余组织/控制 | 占比 | 内部交接/装载 | 占比 | Hash 运行 | 占比 |
|---|---:|---:|---:|---:|---:|---:|---:|''']
    for p in ORDER:
        for op in ('keygen', 'sign', 'verify'):
            r = rows[f'slh_{p}_{op}']
            text.append(f'| {p} {op} | {num(r["total"])} | {num(r["other"])} | {pct(r["other"],r["total"])} | {num(r["transfer"])} | {pct(r["transfer"],r["total"])} | {num(r["hash"])} | {pct(r["hash"],r["total"])} |')
    text.append('''
## 4. 双 lane 利用情况与输入准备重叠

U2 每次 Keccak 置换实际推进 12 个时钟。两 lane 活动拍之和必须等于 `12×置换次数`；Hash 运行并集满足 `lane0＋lane1－同时运行`。18 项均检查通过。Hash 次数按完成的逻辑 Hash 计数，链内多次 Hash 也计入，不与早期版本的 context 请求数混用。

“双 lane 平均利用率”＝`(lane0活动拍＋lane1活动拍)/(2×总周期)`；它与“至少一条 lane 在运行”的占比不同。树依赖、单 lane 配方和双任务长短差异都可能限制同时利用率。

| 参数集/操作 | Hash 次数 | 置换次数 | lane0 活动拍 | lane1 活动拍 | 同时运行拍 | 双 lane 平均利用率 |
|---|---:|---:|---:|---:|---:|---:|''')
    for p in ORDER:
        for op in ('keygen', 'sign', 'verify'):
            r = rows[f'slh_{p}_{op}']
            text.append(f'| {p} {op} | {num(r["hashes"])} | {num(r["permutations"])} | {num(r["lane0"])} | {num(r["lane1"])} | {num(r["both"])} | {pct(r["lane0"]+r["lane1"],2*r["total"])} |')
    text.append('''
输入准备状态的观测采用 recipe `START/STREAM` 任一 lane 的并集。它包括准备、上下文启动和吸收背压等待，并不等于纯组合消息构造的独立耗时；这些拍已计入主表，不可再加到总周期。

| 参数集/Sign | START/STREAM 驻留 | 与 Hash 运行重叠 | 未与 Hash 运行重叠 |
|---|---:|---:|---:|''')
    for p in ORDER:
        r = rows[f'slh_{p}_sign']
        text.append(f'| {p} SG | {num(r["prepare"])} | {num(r["overlap"])} | {num(r["prepare"]-r["overlap"])} |')
    text.append('''
## 5. 主控制状态：调度与 Hash 服务等待

这张表是另一种分解，按主控制器 state 统计，同一行各组互斥并覆盖总周期；不能与第 3 节的类别相加。尤其 `HASH_WAIT` 同时覆盖 recipe 构造、吸收、置换和结果返回，不能把它整体当成 Keccak 运行时间。

| 参数集/Sign | 微码调度 | 树/链管理 | Hash 发射/等待/结果 | 路由/转换/输出 | 输入/启停及其他 |
|---|---:|---:|---:|---:|---:|''')
    for p in ORDER:
        r = rows[f'slh_{p}_sign']
        st = {int(k): int(v) for k, v in r['states'].items()}
        groups = [[3, 4, 5], [6, 7, 8, 10, 11, 14, 15, 16, 17, 18, 19, 20, 21], [22, 23, 24], [25, 26, 27, 28, 29]]
        counts = [sum(st.get(i, 0) for i in group) for group in groups]
        counts.append(r['total'] - sum(counts))
        text.append('| '+p+' SG | '+' | '.join(num(x) for x in counts)+' |')
    r = rows['slh_128f_sign']
    lower = ((r['permutations'] + 1) // 2) * 12
    text.append(f'''
以 128f Sign 为例：

- 主控制 `HASH_WAIT` 驻留 **{num(int(r['states']['23']))} 拍**，其中真正至少一条 lane 推进 Keccak 的并集为 **{num(r['hash'])} 拍**。
- 非置换拍共 **{num(r['total']-r['hash'])}**，占 **{pct(r['total']-r['hash'],r['total'])}**，包含交接/装载和其余组织控制。
- 忽略算法依赖、假设所有置换可在两 lane 均匀分配的理想下界为 `ceil({r['permutations']}/2)×12`＝**{num(lower)} 拍**。实测总周期为 **{num(r['total'])} 拍**，比这个理想下界多 **{num(r['total']-lower)} 拍**。
- 这部分差值包含 lane 不均衡和算法依赖；不能全部归因于消息构造或微码解释。

## 6. 与 SLOTH 参考报告对照

### 6.1 六参数 Sign

“非置换”在 mHBS 为内部交接与其余控制之和，在 SLOTH 为非 Hash MMIO 与剩余 CPU 工作之和。两者都采用 Hash 优先分类，但 Hash 活动条件并非完全相同：本次 mHBS 只计轮运算，SLOTH 参考报告还包括其内部链迭代活动。下表不构成严格同实现的因果消融。

| 参数集/Sign | SLOTH 总周期 | mHBS 总周期 | 快照周期比 SLOTH/mHBS | SLOTH Hash 占比 | mHBS Hash 占比 | SLOTH 非 Hash 周期 | mHBS 非置换周期 |
|---|---:|---:|---:|---:|---:|---:|---:|''')
    for p in ORDER:
        a, b = sloth[p + '_sign'], rows['slh_' + p + '_sign']
        text.append(f'| {p} SG | {num(a["total"])} | {num(b["total"])} | {a["total"]/b["total"]:.2f}× | {pct(a["hash"],a["total"])} | {pct(b["hash"],b["total"])} | {num(a["total"]-a["hash"])} | {num(b["total"]-b["hash"])} |')
    text.append('''
### 6.2 Keygen 与 Verify

| 参数集 | SLOTH KG 周期 | mHBS KG 周期 | SLOTH Verify 周期 | mHBS Verify 周期 |
|---|---:|---:|---:|---:|''')
    for p in ORDER:
        values = [sloth[p+'_keygen']['total'], rows['slh_'+p+'_keygen']['total'], sloth[p+'_verify']['total'], rows['slh_'+p+'_verify']['total']]
        text.append('| '+p+' | '+' | '.join(num(v) for v in values)+' |')
    sign_rows = [rows['slh_'+p+'_sign'] for p in ORDER]
    text.append(f'''
本次六参数 mHBS Sign 的 Hash 运行占比为 **{min(100*r['hash']/r['total'] for r in sign_rows):.2f}%–{max(100*r['hash']/r['total'] for r in sign_rows):.2f}%**。SLOTH 参考数据的 Sign 中，“剩余 CPU/组织工作”占 40.93%–61.77%，非 Hash MMIO 占 5.36%–10.10%。这说明值得优化的部分不仅是 MMIO 传输，还包括构造、地址处理、树遍历及调用调度。

不过，现有差异同时受以下因素影响：

1. mHBS 为双 lane、每拍两轮；本地未掩码 SLOTH 是单 Keccak 轮数据通路。
2. Sign/Verify 消息为 1 B 对 33 B，密钥、随机数与签名也未对齐；Verify 链长受向量影响。
3. SLOTH Sign 会从已生成签名恢复 FORS/XMSS 根，mHBS 的生成与复用调度不同，Hash/置换总次数不能假定相同。
4. SLOTH 包含软件随机数处理，mHBS 接收 Job 给定随机量；函数边界与复位至完成边界不同。
5. 周期比不是频率对齐后的时间加速比；本次没有新增时序签核。

因此不能将快照周期比称为“微码单独带来的加速”，也不能宣称宽输入装载产生零成本。

## 7. 高效组织 Hash 输入的具体机制

### 7.1 宏操作摊薄调度成本

Program 的 RUN/LOOP 与 Template 指定宏类型、descriptor 和路由。Sequencer 一次发出一个宏，等待宏完成；双 lane 调度位于宏内部。CPU 无需逐 Hash 执行地址计算、驱动调用和 MMIO 搬运。收益来自微码与宏执行器联合设计，不能用指令字数直接代替周期收益。

### 7.2 短输入宽并行构造

recipe lane 对适用的短 Hash 组合 seed、ADRS 和节点，生成已填充的 1,088 位 rate block，通过 fast-block 接口装载；无需 CPU 逐个 32 位字写入状态。该组合路径的代价体现为逻辑面积及潜在关键路径，需与频率共同评估。

### 7.3 长输入分块构造

消息和节点列表等长输入采用流式路径。当前 producer 每个接受的 STREAM 拍构造 8 B，两个半拍组成 128 位吸收数据；136 B rate block 的末拍只使用低 64 位。地址、源选择、节点列表游标和 padding 在硬件中组织。吸收背压和跨块置换等待仍有实际周期成本。

### 7.4 链值局部反馈

链中间值保留在 sponge/lane 内，用于下一次带更新地址的 Hash；避免每一步返回通用处理器和主 RAM。SLOTH 本身也有 WOTS 链内加速，因此相对它的新增收益必须区分链外输入构造、其他 recipe、调度和跨操作结果复用。

### 7.5 结果与后续输入衔接

根、端点和结果路由由宏执行器直接管理；签名结果按节点输出，减少软件从结果缓冲回读并重建后续输入的工作。但“更少 Hash 重算”的算法调度收益应与“同一次 Hash 的消息准备更快”分开报告。

## 8. 建议的论文贡献表述与补充实验

### 8.1 当前证据支持的表述

> 提出一种面向 Hash 输入组织的微码与专用数据通路协同架构。该架构以宏操作和循环描述计算流程，在硬件中完成地址生成、输入选择、填充、分块吸收和链值反馈，使控制调度与数据供给适应 Hash 数据通路。六参数 K2U2 签名仿真显示，大部分执行周期内至少一条 Keccak lane 正在推进轮运算。

对比结论可表述为：相较现有 RISC-V＋Hash 软件调度快照，该设计表现出更低的非置换周期占比；其可归因于输入组织机制的独立收益，将通过同 K/U、同向量和同 Hash 调度的实验量化。

### 8.2 最小补充实验

| 问题 | 对照 | 测量 |
|---|---|---|
| 微码是否减少控制开销 | RISC-V 与微码驱动同一 recipe/Hash 数据通路 | 指令/宏数量、启动间隔、等待周期 |
| 宽快装是否提高输入准备效率 | fast-block 与逐字装载，保持 Hash 次数一致 | 每个输入块的准备、传输拍数，LUT/FF/频率 |
| 链反馈有多少增量收益 | 同样支持链加速的基线；额外提供逐步往返消融 | RAM/MMIO 字节、链步间气泡 |
| 改进是否主要来自并行度 | 相同 K/U 或分别扫描 K/U | 置换数、lane 利用率、延迟和 ATP |
| 是否减少重复计算 | 固定同一算法任务图，另列优化任务图 | Hash/置换数及每类输入数量 |
| 输入工作是否真正被隐藏 | 记录构造活动与 Hash 活动交集 | 重叠拍、未重叠拍、供数停顿 |

优先对齐 128f Sign 的消息、密钥、随机量及输出，再扩展六参数 KG/Sign/Verify。对 SLOTH 的“剩余 CPU”进一步按函数或基本块拆分，区分 ADRS、填充、普通内存、树遍历、随机数和调度，才能将“输入 message 组织”与其他开销分离。

## 9. 证据与复现

- [18 项机器可读结果]({evidence}/results.json)
- [冻结输入与工具信息]({evidence}/inputs.json)
- [证据哈希]({evidence}/SHA256.json)
- [本次使用的 SLOTH 报告副本]({evidence}/SLOTH_SHAKE_CYCLE_REPORT.md)
- [观察器与仿真脚本](../../scripts/profile_mhbs_cycles.py)
- [报告生成脚本](../../scripts/report_mhbs_cycles.py)
- [相关存储分析](Memory_Architecture_and_Contribution.md)

每项的 `cases/<参数集>_<操作>/` 保存编译命令、日志和结果；`source/` 保存冻结 RTL、带观察器的测试平台、镜像及向量。证据保存在 manifests，删除 build 后仍可审计；可执行文件需重建。脚本跳过已完成且保存结果的任务，不修改生产 RTL。

```bash
python3 scripts/profile_mhbs_cycles.py --tag {args.tag} --jobs 3
python3 scripts/report_mhbs_cycles.py --tag {args.tag}
```

分类检查包括：三类周期和等于总周期、主状态驻留和等于总周期、两 lane 活动和等于 12 倍置换次数、活动并集恒等式、与冻结基线周期一致。完整原始数据保留在 JSON 中，可据此复算表格百分比。
''')
    k1archive = ROOT / 'manifests/analysis' / args.k1_tag
    if (k1archive / 'results.json').exists():
        k1 = json.loads((k1archive / 'results.json').read_text())
        assert k1['passed'] and len(k1['cases']) == 18, 'K1U1 requires all 18 cases'
        one = k1['cases']
        k1evidence = f'../../manifests/analysis/{args.k1_tag}'
        text[0] = text[0].replace('配置：K2U2，六种', '主表配置：K2U2；第 10 节追加独立 K1U1 实验，均覆盖六种')
        text.append(f'''
## 10. 追加 K1U1 实验：单 lane、每拍一轮

### 10.1 源码与验收边界

本组由第 1–9 节 K2U2 实验的冻结源码派生，使用相同 Program16 镜像、密钥、消息、随机量和参考输出，补测六参数 KG/Sign/Verify 共 18 项。K1U1 是 **一条实际实例化的 Hash lane，每拍执行一轮 Keccak，每次置换 24 拍**。不是将 K2U2 周期乘以比例得到的估计值，也不是将两条物理 lane 的周期相加。

生产核固定 K2U2，因此只在独立实验副本中调整：

- 将批任务掩码限制为单 lane；WOTS 游标每次前进 1，FORS 叶节点逐个生成，Verify 逐链输入和执行。
- 保留原控制器的两槽声明，但未使用槽的 lane 输出固定为零；只实例化 `lanes[0].lane`。
- 使用已有存储模块的通用写银行模式，使单 lane 的端点写入支持奇、偶地址；不改变存储读写拍数。
- 将只读观察器和列表/路由检查适配到单 lane，完成置换判据改为 24 轮的最后一轮。

18 项正常仿真均通过；Keygen/Sign 输出逐字节符合相同软件参考，Verify 接受相同正确签名。**Hash 和置换次数逐项与 K2U2 完全一致；周期按 K1U1 实测记录。**本组未进行综合、布线及完整异常回归，不替换生产 RTL，也不宣称 K1U1 的面积或可达频率。测试时钟同为 10 ns。

### 10.2 K1U1 的 18 项周期构成

分类定义与第 2 节一致，三类互斥相加等于总周期。对单 lane，Hash 运行周期严格等于 `24×置换次数`，18 项均检查通过。

| 参数集/操作 | 总周期 | 其余组织/控制 | 占比 | 内部交接/装载 | 占比 | Hash 运行 | 占比 |
|---|---:|---:|---:|---:|---:|---:|---:|''')
        for p in ORDER:
            for op in ('keygen', 'sign', 'verify'):
                r = one[f'slh_{p}_{op}']
                assert r['hash'] == 24*r['permutations']
                assert r['hashes'] == rows[f'slh_{p}_{op}']['hashes']
                assert r['permutations'] == rows[f'slh_{p}_{op}']['permutations']
                text.append(f'| {p} {op} | {num(r["total"])} | {num(r["other"])} | {pct(r["other"],r["total"])} | {num(r["transfer"])} | {pct(r["transfer"],r["total"])} | {num(r["hash"])} | {pct(r["hash"],r["total"])} |')
        text.append('''
### 10.3 同向量 K1U1 / K2U2 比较

以下两组的算法输入、正确性参考和 Hash/置换次数一致。周期比反映 lane 并行度、轮展开和批调度的联合变化，不能解释为单独的微码收益。

| 参数集/操作 | K1U1 周期 | K2U2 周期 | K1U1/K2U2 | K1U1 非置换占比 | K2U2 非置换占比 |
|---|---:|---:|---:|---:|---:|''')
        for p in ORDER:
            for op in ('keygen', 'sign', 'verify'):
                a,b=one[f'slh_{p}_{op}'],rows[f'slh_{p}_{op}']
                text.append(f'| {p} {op} | {num(a["total"])} | {num(b["total"])} | {a["total"]/b["total"]:.3f}× | {pct(a["total"]-a["hash"],a["total"])} | {pct(b["total"]-b["hash"],b["total"])} |')
        text.append('''
### 10.4 单 lane U1 与 SLOTH Sign 快照对照

K1U1 去除了此前双 lane、每拍两轮的配置差异，更适合观察消息组织与执行调度。不过 SLOTH 仍使用不同消息/随机量、软件函数边界和根恢复流程，其 Hash 活动分类也不完全相同。下表仍是快照对照，不能将全部差值归因于输入拼接。

| 参数集/Sign | SLOTH 周期 | K1U1 周期 | SLOTH/K1U1 | SLOTH 非 Hash 周期 | K1U1 非置换周期 | K1U1 非置换占比 |
|---|---:|---:|---:|---:|---:|---:|''')
        for p in ORDER:
            a,b=sloth[p+'_sign'],one['slh_'+p+'_sign']
            text.append(f'| {p} SG | {num(a["total"])} | {num(b["total"])} | {a["total"]/b["total"]:.3f}× | {num(a["total"]-a["hash"])} | {num(b["total"]-b["hash"])} | {pct(b["total"]-b["hash"],b["total"])} |')
        r=one['slh_128f_sign']
        active=[100*one['slh_'+p+'_sign']['hash']/one['slh_'+p+'_sign']['total'] for p in ORDER]
        text.append(f'''
K1U1 六参数 Sign 的 Hash 运行占比为 **{min(active):.2f}%–{max(active):.2f}%**。128f Sign 为 **{num(r['total'])} 拍**，其中置换 **{num(r['hash'])} 拍**，非置换 **{num(r['total']-r['hash'])} 拍**，占 **{pct(r['total']-r['hash'],r['total'])}**。

高 Hash 占比也受 U1 每次置换耗时更长影响，因此还应观察非置换绝对拍数、每次 Hash 的准备成本和总延迟；不能仅凭占比升高认定 K1U1 的消息构造器比 K2U2 更高效。

本组进一步支持“即使只有一条 U1 Hash lane，微码与专用数据通路也能以较低非置换开销组织计算”。相对 SLOTH 的贡献定量仍需第 8 节的同向量、同 Hash 任务图对照。

### 10.5 K1U1 证据与复现

- [K1U1 全部结果]({k1evidence}/results.json)
- [配置与冻结源码哈希]({k1evidence}/inputs.json)
- [相对冻结 K2U2 的补丁]({k1evidence}/k1u1.patch)
- [证据哈希]({k1evidence}/SHA256.json)
- [K1U1 仿真脚本](../../scripts/profile_mhbs_k1u1.py)

```bash
python3 scripts/profile_mhbs_k1u1.py --tag {args.k1_tag} --jobs 3
python3 scripts/report_mhbs_cycles.py --tag {args.tag} --k1-tag {args.k1_tag}
```

原始日志、向量、实验 RTL 及测试平台保存在上述 manifests 目录，删除 build 后仍可审计；原 K2U2 结果和生产 RTL 保持不变。
''')
    report = ROOT / 'docs/report/MHBS_SHAKE_CYCLE_REPORT.md'
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text('\n'.join(text) + '\n')
    metadata = dict(report=str(report.relative_to(ROOT)), report_sha256=hashlib.sha256(report.read_bytes()).hexdigest(),
                    renderer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    results_sha256=hashlib.sha256((archive / 'results.json').read_bytes()).hexdigest())
    if (k1archive / 'results.json').exists():
        metadata['k1_results_sha256'] = hashlib.sha256((k1archive / 'results.json').read_bytes()).hexdigest()
    (archive / 'report_provenance.json').write_text(json.dumps(metadata, indent=2)+'\n')
    print(report)


if __name__ == '__main__':
    main()
