#!/usr/bin/env python3
"""Compare frozen common-area / Sign runs without mixing RTL candidates."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from experiment_archive import archive_run, canonical_report

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = ('P12U1', 'P4U1', 'P1U1')
PROFILES = ('slh_128f', 'xmss_h10', 'lms_h10')


def rtl_tokens(path):
    """Ignore layout/comments while preserving identifiers and quoted strings."""
    pattern = r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|[A-Za-z_$][\w$]*|\\\S+|\d+|\S'
    return [token for token in re.findall(pattern, path.read_text(), re.S)
            if not token.startswith(('//', '/*'))]


def read_run(stamp):
    run = ROOT / 'build/pu_sign_matrix' / stamp
    archive_run(run)
    state = json.loads((run / 'status.json').read_text())
    state['root'] = str(run)
    return state


def change(new, old):
    return (new / old - 1) * 100 if new is not None and old else None


def number(value, digits=3):
    return '—' if value is None else f'{value:,.{digits}f}'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--experiment', action='append', default=[], metavar='LABEL=RUN_ID')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output = canonical_report(args.output)
    baseline, candidate = map(read_run, (args.baseline, args.candidate))
    old = {(r['configuration'], r['profile']): r for r in baseline['results']}
    new = {(r['configuration'], r['profile']): r for r in candidate['results']}
    rows = []
    for config in CONFIGS:
        for profile in PROFILES:
            a, b = old.get((config, profile), {}), new.get((config, profile), {})
            workload_equal = (a.get('simulation_status') == b.get('simulation_status') == 'passed'
                              and all(a[k] == b[k] for k in ('hashes', 'permutations')))
            row = dict(configuration=config, profile=profile,
                       baseline_cycles=a.get('cycles'), cycles=b.get('cycles'),
                       cycles_change_pct=change(b.get('cycles'), a.get('cycles')),
                       baseline_area=a.get('common_equivalent_slice'),
                       area=b.get('common_equivalent_slice'),
                       area_change_pct=change(b.get('common_equivalent_slice'),
                                              a.get('common_equivalent_slice')),
                       baseline_atp=a.get('atp_slice_ms'), atp=b.get('atp_slice_ms'),
                       atp_change_pct=change(b.get('atp_slice_ms'), a.get('atp_slice_ms')),
                       time_ms=b.get('time_ms'), assumed_mhz=150,
                       hashes=b.get('hashes'), permutations=b.get('permutations'),
                       workload_equal=workload_equal, rank=b.get('atp_rank'),
                       simulation_status=b.get('simulation_status'),
                       synthesis_status=b.get('common_status'))
            rows.append(row)
    validation_path = Path(candidate['root']) / 'source/validation/FINAL_VALIDATION.json'
    validation = json.loads(validation_path.read_text()) if validation_path.exists() else None
    complete = all(r['atp_change_pct'] is not None for r in rows)
    all_points_improved = (all(r['atp_change_pct'] < 0 and r['area_change_pct'] < 0
                              and r['cycles_change_pct'] < 0 and r['workload_equal'] for r in rows)
                          if complete else None)
    best = []
    if complete:
        for profile in PROFILES:
            cases = [r for r in rows if r['profile'] == profile]
            a = min(cases, key=lambda r: r['baseline_atp'])
            b = min(cases, key=lambda r: r['atp'])
            best.append(dict(profile=profile, baseline_configuration=a['configuration'],
                             configuration=b['configuration'], baseline_atp=a['baseline_atp'],
                             atp=b['atp'], change_pct=change(b['atp'], a['baseline_atp'])))
    accepted = (all(r['change_pct'] < 0 for r in best)
                and all(r['workload_equal'] for r in rows)) if complete else None
    experiments = []
    for spec in args.experiment:
        label, stamp = spec.split('=', 1)
        state = read_run(stamp)
        experiments.append(dict(label=label, run_id=stamp, tasks=state['tasks'],
                                source_manifest=state['source_manifest']))
    source = Path(candidate['root']) / 'source'
    files = (source / 'sources.txt').read_text().splitlines()
    source_hashes = {p: hashlib.sha256((source / p).read_bytes()).hexdigest() for p in files}
    matches_worktree = all(hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == h
                          for p, h in source_hashes.items())
    matches_tokens = all(rtl_tokens(ROOT / p) == rtl_tokens(source / p) for p in files)
    data = dict(baseline_run=args.baseline, candidate_run=args.candidate,
                complete=complete, measured_best_targets_improved=accepted,
                all_points_area_cycles_atp_improved=all_points_improved, best=best,
                candidate_matches_worktree=matches_worktree,
                candidate_matches_worktree_tokens=matches_tokens,
                candidate_source_sha256=source_hashes,
                baseline_source_manifest=baseline['source_manifest'],
                candidate_source_manifest=candidate['source_manifest'],
                validation=validation, routed_sta=False, rows=rows, experiments=experiments)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix('.json').write_text(json.dumps(data, indent=2) + '\n')
    lines = ['# P12U1 / P4U1 / P1U1 Sign 面积、周期与 ATP 优化', '',
             f'基线 `{args.baseline}`；候选 `{args.candidate}`。'
             f'三点九项完成：{complete}；三个算法最佳ATP均下降：{accepted}；'
             f'工作区RTL与候选源码字节一致：{matches_worktree}；词法一致：{matches_tokens}。', '',
             '基线为所列冻结源码对应的综合和实测结果，候选使用自身源码对应的面积与周期。'
             '每个P/U共用一个完整标准算法common核，三种算法按Job互斥执行。'
             '节点、认证路径、签名输出及Hash/置换工作量保持一致，未增加Hash lane或按P/U特化。', '',
             '沿用此前“允许个别P/U点回退，三个算法最佳ATP均不回退”的取舍规则，'
             '本轮比较范围按用户要求缩为P12U1/P4U1/P1U1。单点回退在下表保留。', '',
             '器件 xc7a200tffg1156-3，Vivado 2025.2，通用Keccak，OOC，'
             'SYNTHESIS宏裁剪诊断，6.666667ns约束、默认时序驱动，每次综合2线程。'
             'common不含外部ROM和签名缓存。等效Slice=LUT/4+FF/8+232.4×BRAM36+102.4×DSP。'
             '本表为综合面积，ATP按假定150MHz折算，不代表布线时序闭合。', '',
             '## 面积', '',
             '| P/U | 基线LUT/FF | 候选LUT/FF | BRAM36 | 基线等效Slice | 候选等效Slice | 变化 |',
             '|---|---:|---:|---:|---:|---:|---:|']
    for config in CONFIGS:
        a, b = old.get((config, PROFILES[0]), {}), new.get((config, PROFILES[0]), {})
        pair = lambda r: '/'.join(number(r.get('common_' + k), 0) for k in ('lut', 'ff'))
        lines.append(f'| {config} | {pair(a)} | {pair(b)} | {number(b.get("common_bram36"))} | '
                     f'{number(a.get("common_equivalent_slice"))} | {number(b.get("common_equivalent_slice"))} | '
                     f'{number(change(b.get("common_equivalent_slice"), a.get("common_equivalent_slice")))}% |')
    for profile in PROFILES:
        lines.extend(['', f'## {profile} Sign', '',
                      '| 排名 | P/U | 基线周期 | 候选周期 | 周期变化 | 时间ms | 基线ATP | 候选ATP | ATP变化 |',
                      '|---:|---|---:|---:|---:|---:|---:|---:|---:|'])
        for r in rows:
            if r['profile'] != profile:
                continue
            lines.append(f'| {number(r["rank"], 0)} | {r["configuration"]} | '
                         f'{number(r["baseline_cycles"], 0)} | {number(r["cycles"], 0)} | '
                         f'{number(r["cycles_change_pct"])}% | {number(r["time_ms"], 6)} | '
                         f'{number(r["baseline_atp"])} | {number(r["atp"])} | {number(r["atp_change_pct"])}% |')
    lines.extend(['', '三个算法在本轮三点范围内的最佳ATP变化：', ''])
    for r in best:
        lines.append(f'- {r["profile"]}：{r["baseline_configuration"]} → {r["configuration"]}，'
                     f'{number(r["baseline_atp"])} → {number(r["atp"])} Slice·ms，'
                     f'{number(r["change_pct"])}%。')
    lines.extend(['', '## 逐项实验', '',
                  '各行面积属于该行独立冻结RTL，不跨候选拼接面积与周期。'
                  '异常耗时综合继续后台运行，未完成的结果留空。', '',
                  '| 阶段 | P/U | 等效Slice | 综合秒数 | 状态 |', '|---|---|---:|---:|---|'])
    for exp in experiments:
        for config in CONFIGS:
            task = exp['tasks'].get(f'synth/{config}/common')
            if task:
                status = task['status'] + ('（跳过分析，后台继续）' if task.get('analysis_deferred') else '')
                lines.append(f'| {exp["label"]} ({exp["run_id"]}) | {config} | '
                             f'{number(task.get("area", {}).get("equivalent_slice"))} | '
                             f'{number(task.get("seconds"), 1)} | {status} |')
    notes = args.output.parent / (args.output.name + '_Notes.md')
    if notes.exists():
        lines.extend(['', notes.read_text().strip()])
    lines.extend(['', '## 剩余周期开销', '',
                  '下界只计算实际置换的24轮工作量，忽略相关性、填充输入和控制开销：'
                  '理论下界=ceil(24×实测置换数/P)。这是下界，不是另一种实现的周期预测。', '',
                  '| 算法 | P/U | 实测周期 | 置换吞吐下界 | 超出下界的周期 | 占实测周期 |',
                  '|---|---|---:|---:|---:|---:|'])
    for r in rows:
        if r['cycles'] is not None and r['permutations'] is not None:
            p = int(r['configuration'].split('U')[0][1:])
            lower = (24 * r['permutations'] + p - 1) // p
            overhead = r['cycles'] - lower
            lines.append(f'| {r["profile"]} | {r["configuration"]} | {r["cycles"]:,} | '
                         f'{lower:,} | {overhead:,} | {100 * overhead / r["cycles"]:.3f}% |')
    lines.extend(['', '## 验证与归档', '',
                  f'九项Sign逐字节与签名缓存核对，Hash/置换工作量一致：{all(r["workload_equal"] for r in rows)}。',
                  f'补充验证日志：[FINAL_VALIDATION.json]({validation_path})。'
                  + (f' 完成={validation.get("complete")}，通过={validation.get("passed")}，'
                     f'记录={len(validation.get("results", []))}。' if validation else ' 尚未生成。'), '',
                  f'- 基线源码、工具版本与日志：[基线SOURCE.json]({baseline["source_manifest"]})。',
                  f'- 候选源码、工具版本与日志：[候选SOURCE.json]({candidate["source_manifest"]})。',
                  '- XMSS/LMS h20完整Keygen、Sign保持停止，仅包含Verify/地址边界检查。', ''])
    args.output.with_suffix('.md').write_text('\n'.join(lines))
    print(json.dumps(dict(complete=complete, accepted=accepted, matches_worktree=matches_worktree)))


if __name__ == '__main__':
    main()
