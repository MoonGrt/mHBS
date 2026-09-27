#!/usr/bin/env python3
"""Generate v4.1 comparison tables exclusively from measured manifests."""
import argparse,json,re,tarfile
from autonomous_flow import ROOT,BASE

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--tag',required=True);args=parser.parse_args()
    candidate=BASE/'candidates'/args.tag
    ppa=json.loads((candidate/'ppa.json').read_text())
    rows=[]
    for path in sorted((BASE/'candidates').glob('*/ppa.json')):
        p=json.loads(path.read_text())
        rows.append(f'| {p["tag"]} | {p["stage"]} | {p["frequency_mhz"]:.3f} | {p.get("index_policy","guarded")} | {p["lut"]:,} | {p["ff"]:,} | {p["lutram"]:,} | {p["equivalent_slice"]:,.3f} | {p.get("wns_ns","—")} | {p["worst_ratio"]:.4f} |')
    lines=['# μHBS v4.1：U2 优化与论文对比','',
        '**状态：功能验证与性能验收分别记录；没有 final.json 就不表示性能完成。**','',
        '本轮固定 U2、双 lane、三个独立分布式 ROM、ABI 4。当前执行策略为 `fixed_q_no_guard`：',
        'XMSS/LMS 使用固定 q 和选定认证路径，不提供索引消耗、防复用或提交确认。历史带 guard 数据保留。','',
        '## 已完成的共同硬件候选','',
        '下表面积包含 ROM、Boot、执行器和计数逻辑。post-synth 使用 100 MHz 归一化；post-route 使用该行实测频率。',
        '最差比例为七点签名 ATP 与有效门槛之比的最大值；有效门槛取论文门槛与适用的 V3 上限较小值。','',
        '| 候选 | 阶段 | MHz | 索引策略 | LUT | FF | LUTRAM（已包含于 LUT） | 等效 Slice | WNS/ns | 最差 ATP 比例 |',
        '|---|---|---:|---|---:|---:|---:|---:|---:|---:|',*rows,'',
        '等效面积 = LUT/4 + FF/8 + BRAM36 等效数×232.4 + DSP×102.4。','',
        f'## 比较候选：{args.tag}','',
        f'阶段：`{ppa["stage"]}`。以下面积、周期来自该候选同一源码快照；不代表之后工作树版本。',
        f'共同面积 **{ppa["equivalent_slice"]:,.3f} Slice**；计算频率 **{ppa["frequency_mhz"]:.3f} MHz**，依据 `{ppa.get("frequency_basis","normalized_only")}`。','',
        '| Profile | Boot | Keygen 周期 | Sign 周期 | Keygen ATP | Sign ATP | 论文门槛 | V3 上限 | 数值达标 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---|']
    for name,p in ppa['profiles'].items():
        old='—' if p['v3_ceiling'] is None else f'{p["v3_ceiling"]:,.6f}'
        lines.append(f'| {name} | {p["boot_cycles"]} | {p["keygen_cycles"]:,} | {p["sign_cycles"]:,} | {p["keygen_atp"]:,.3f} | {p["sign_atp"]:,.3f} | {p["paper_threshold"]:,.3f} | {old} | {"是" if p["paper_pass"] and p["v3_pass"] else "否"} |')
    if 'cycle_reference' in ppa:
        reference=json.loads((BASE/'area_baseline.json').read_text())
        lines += ['', '### 面积优先约束：逐点 Sign 增量 ≤5%', '',
            f'比较基线 `{reference["candidate"]}`：9,830.875 等效 Slice、100 MHz，均为 post-route。',
            '下列周期来自完整算法仿真。综合候选面积只能与综合基线直接比较，最终面积收益采用 post-route。', '',
            '| Profile | 基线 Sign | 当前 Sign | 周期增量 | ≤5% |',
            '|---|---:|---:|---:|---|']
        for name,p in ppa['profiles'].items():
            lines.append(f'| {name} | {reference["profiles"][name]["sign_cycles"]:,} | {p["sign_cycles"]:,} | {(p["sign_cycle_ratio"]-1)*100:+.3f}% | {"通过" if p["cycle_limit_pass"] else "失败"} |')
        if ppa['stage']=='post_route':
            lines += ['',f'相对布线基线，面积变化 **{(ppa["equivalent_slice"]/9830.875-1)*100:+.3f}%**；',
                      f'频率变化 **{(ppa["frequency_mhz"]/100-1)*100:+.3f}%**。',
                      '具体优化、淘汰实验与物理镜像格式见 `Area_Optimization.md`。']
    limits={name:min(p['paper_threshold'],p['v3_ceiling'] if p['v3_ceiling'] is not None else float('inf')) for name,p in ppa['profiles'].items()}
    required=max((ppa['equivalent_slice']*p['sign_cycles']/(1000*limits[name]),name) for name,p in ppa['profiles'].items())
    area_at_100=min(limits[name]*100000/p['sign_cycles'] for name,p in ppa['profiles'].items())
    lines += ['', '### 距离验收目标', '',
        f'保持该候选的面积与签名周期，共同频率需要达到约 **{required[0]:.3f} MHz**；约束最紧的参数点为 `{required[1]}`。',
        f'若共同频率为 100 MHz、周期保持不变，面积需降至约 **{area_at_100:,.3f} Slice**。',
        '这些是门槛反算值，不是可实现频率或面积预测。最终仍以 post-route 实测、时序裕量和原严格比较规则验收。']
    with tarfile.open(candidate/'source_snapshot.tar.gz') as snapshot:
        core_path=next(name for name in snapshot.getnames()
                       if name.startswith('rtl/top/') and name.endswith('_hbs.sv'))
        core=snapshot.extractfile(core_path).read().decode()
    enum=re.search(r'typedef enum logic \[5:0\] \{(.*?)\} state_t;',core,re.S)
    states=[n.strip() for n in enum[1].split(',')]
    lines += ['', '## Hash 计数与 Sign 状态驻留', '',
        '状态编号按该候选源码快照解码。HASH_WAIT 是宏 Hash 等待，SIGN_RUN 是独立签名链调度状态；二者不可混作同一利用率。', '',
        '| Profile | Sign Hash | Sign 置换 | HASH_WAIT 周期 | SIGN_RUN 周期 |',
        '|---|---:|---:|---:|---:|']
    for name,row in ppa['profiles'].items():
        path=ROOT/row['simulation'];sim=json.loads(path.read_text())
        residence={states[int(i)]:int(c) for i,c in re.findall(r'RESIDENCY sign state=(\d+) cycles=(\d+)',path.with_suffix('.log').read_text())}
        lines.append(f'| {name} | {sim["sign_hashes"]:,} | {sim["sign_permutations"]:,} | {residence.get("HASH_WAIT",0):,} | {residence.get("SIGN_RUN",0):,} |')
    paper=json.loads((ROOT/'manifests/experiments/unified_hbs_v4/comparison.json').read_text())['rows']
    lines += ['', '## 论文报告值与 108 MHz 重算', '',
        '论文共同资源为 24,184 LUT、13,659 FF、16.5 BRAM36 等效、0 DSP，等效面积 11,587.975 Slice。',
        '下表沿用历史已核对的 Table 5 数据，按周期重算列不替代报告毫秒门槛。', '',
        '| Profile | KG 周期 | Sign 周期 | 报告 KG/ms | 报告 Sign/ms | KG/ms @108 MHz | Sign/ms @108 MHz | Sign ATP @108 MHz |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in paper:
        lines.append(f'| {r["profile"]} | {r["paper_keygen_cycles"]:,} | {r["paper_sign_cycles"]:,} | {r["paper_keygen_ms"]:.3f} | {r["paper_sign_ms"]:.3f} | {r["paper_keygen_cycles"]/108000:.6f} | {r["paper_sign_cycles"]/108000:.6f} | {r["paper_eq_slice"]*r["paper_sign_cycles"]/108000:,.3f} |')
    lines += ['', '数据来源：`manifests/experiments/unified_hbs_v4/comparison.json`；原论文锚点见历史报告。']
    update=json.loads((BASE/'author_update.json').read_text())
    current=ppa['profiles']['slh_128f']
    updated_ms=update['updated_sign_cycles']/(update['assumed_unchanged_frequency_mhz']*1000)
    updated_atp=updated_ms*update['assumed_unchanged_equivalent_slice']
    lines += ['', '## 作者更新：128f 签名周期', '',
        '来源为用户转述的作者更新；未提供更新后的报告毫秒值。以下假设论文频率和面积不变，原验收上限不自动修改。', '',
        f'- 更新周期：**{update["updated_sign_cycles"]:,}**；按 108 MHz 重算 **{updated_ms:.6f} ms**、**{updated_atp:,.3f} Slice·ms**。',
        f'- 当前比较候选周期：**{current["sign_cycles"]:,}**，比更新周期少 **{100*(1-current["sign_cycles"]/update["updated_sign_cycles"]):.2f}%**。',
        '- 既定论文报告值与 V3 不退化门槛继续用于验收；更新周期重算值作为单独对照。']
    lines += ['', 'ATP 单位：Slice·ms。论文门槛采用论文报告毫秒值；108 MHz 重算列仅用于核对计时口径。','',
        '## 移除 guard 的单独增量','',
        '同一 U2 基线移除 guard 后，LUT 42,190→42,162，FF 14,124→14,052，等效面积 12,313→12,297 Slice。',
        '四个 XMSS/LMS 参数点 Sign 均减少 4 周期；Boot、Keygen 和 SLH Sign 周期不变。',
        '这是整机重新综合后的净变化。其余面积下降来自另外的候选结构，不能归因于移除 guard。','',
        '## 比较限制与来源','',
        '- NON_STRICT：SLH-DSA 与论文 SPHINCS+ 版本不同；LMS 使用 SHAKE256/256 研究 profile。',
        '- 本设计使用固定输入、一次启动仅一次签名；XMSS/LMS Keygen 生成选定 q 的认证路径，Sign 复用缓存。',
        '- V3/V4 分别静态综合；v4.1 要求七点共用硬件和频率。当前无 guard，不能据此声称状态保护开销相同。',
        '- 最终验收还须具备 post-route 时序、完整布线、覆盖检查，以及七份仅 ROM INIT 不同的结构证据。',
        f'- 候选来源：`manifests/experiments/unified_hbs_v4.1/candidates/{args.tag}/`，包含源码快照、SHA-256、原始报告及仿真引用。','',
        '```bash',f'python3 scripts/report_autonomous_optimization.py --tag {args.tag}',
        'python3 scripts/reproduce_paper_comparison.py',
        'python3 scripts/reproduce_seven_profiles.py',
        'python3 scripts/reproduce_autonomous.py --allow-incomplete','```','']
    out=ROOT/'docs/v4.1/Unified_HBS_Paper_Comparison.md';out.write_text('\n'.join(lines));print(out)

if __name__=='__main__':main()
