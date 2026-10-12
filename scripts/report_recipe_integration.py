#!/usr/bin/env python3
"""Compare a frozen 14-point recipe integration with its exact baseline."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import time
from experiment_archive import archive_run, canonical_report

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ('slh_128f', 'xmss_h10', 'lms_h10')


def read_run(stamp):
    folder = ROOT / 'build/pu_sign_matrix' / stamp
    archive_run(folder)
    return json.loads((folder / 'status.json').read_text()), folder


def change(new, old):
    return 100 * (new / old - 1) if new is not None and old else None


def num(value, digits=3):
    return '—' if value is None else f'{value:,.{digits}f}'


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(content)
    temporary.replace(path)


def report(args):
    args.output = canonical_report(args.output)
    baseline, base_folder = read_run(args.baseline)
    candidate, folder = read_run(args.candidate)
    old = {(r['configuration'], r['profile']): r for r in baseline['results']}
    rows = []
    for item in candidate['results']:
        key = item['configuration'], item['profile']
        previous = old[key]
        measured = previous['simulation_status'] == item['simulation_status'] == 'passed'
        row = dict(item)
        for field in ('cycles', 'total_cycles', 'hashes', 'permutations',
                      'common_equivalent_slice', 'atp_slice_ms'):
            row['baseline_' + field] = previous.get(field)
        row['cycles_unchanged'] = (all(item[k] == previous[k] for k in ('cycles', 'total_cycles'))
                                   if measured else None)
        row['workload_unchanged'] = (all(item[k] == previous[k] for k in ('hashes', 'permutations'))
                                     if measured else None)
        row['area_change_pct'] = change(item.get('common_equivalent_slice'),
                                        previous.get('common_equivalent_slice'))
        row['atp_change_pct'] = change(item.get('atp_slice_ms'), previous.get('atp_slice_ms'))
        rows.append(row)
    areas = [r for r in rows if r['profile'] == PROFILES[0]]
    comparable = [r for r in areas if r['area_change_pct'] is not None]
    source_names = (folder / 'source/sources.txt').read_text().splitlines()
    hashes = {name: hashlib.sha256((folder / 'source' / name).read_bytes()).hexdigest()
              for name in source_names}
    matches = all((ROOT / name).exists() and hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha
                  for name, sha in hashes.items())
    validation_path = folder / 'source/validation/FINAL_VALIDATION.json'
    validation = json.loads(validation_path.read_text()) if validation_path.exists() else None
    stages = []
    for spec in args.experiment:
        label, stamp = spec.split('=', 1)
        state, run = read_run(stamp)
        stages.append(dict(label=label, run_id=stamp, tasks=state['tasks'], source=str(run / 'SOURCE.json')))
    summary = dict(comparable_area_points=len(comparable), expected_area_points=len(areas),
                   smaller=sum(r['area_change_pct'] < 0 for r in comparable),
                   equal=sum(r['area_change_pct'] == 0 for r in comparable),
                   larger=sum(r['area_change_pct'] > 0 for r in comparable),
                   measured_sign_cases=sum(r['cycles_unchanged'] is not None for r in rows),
                   expected_sign_cases=len(rows),
                   all_cycles_unchanged=all(r['cycles_unchanged'] is True for r in rows),
                   all_workloads_unchanged=all(r['workload_unchanged'] is True for r in rows))
    data = dict(updated_at=datetime.now().astimezone().isoformat(timespec='seconds'),
                baseline_run=args.baseline, candidate_run=args.candidate, summary=summary,
                area_top='common', routed_sta=False, candidate_matches_worktree=matches,
                candidate_source_sha256=hashes, rows=rows, experiments=stages, validation=validation)
    write(args.output.with_suffix('.json'), json.dumps(data, indent=2) + '\n')
    lines = ['# Recipe 合并与 14 点面积优化', '',
             f'更新时间：{data["updated_at"]}。基线 `{args.baseline}`，候选 `{args.candidate}`。', '',
             f'完成周期对照 {summary["measured_sign_cases"]}/{len(rows)}；'
             f'全部周期不变：{summary["all_cycles_unchanged"]}；'
             f'Hash/置换数不变：{summary["all_workloads_unchanged"]}。'
             f'工作区生产 RTL 与候选一致：{matches}。', '',
             f'面积可比 {len(comparable)}/{len(areas)} 点：下降 {summary["smaller"]}，'
             f'持平 {summary["equal"]}，增加 {summary["larger"]}。'
             '未完成配置留空，异常综合继续后台运行，不能用部分结果声称全部配置通过面积验收。', '',
             '同器件 xc7a200tffg1156-3、Vivado 2025.2、common OOC、通用 Keccak、'
             'SYNTHESIS 宏、6.666667 ns、默认时序驱动，每次综合 2 线程。'
             '等效 Slice = LUT/4 + FF/8 + 232.4×BRAM36 + 102.4×DSP。'
             '共同核不含外部 ROM 和签名缓存。ATP 按 U1=150 MHz、U2=110 MHz 假定频率计算，未新增布线 STA。', '',
             '## common 面积', '',
             '| P/U | 基线 LUT/FF | 候选 LUT/FF | BRAM36/DSP | 基线 Slice | 候选 Slice | 变化 | 基线/候选综合状态 |',
             '|---|---:|---:|---:|---:|---:|---:|---|']
    for row in areas:
        previous = old[row['configuration'], row['profile']]
        pair = lambda r, keys: '/'.join(num(r.get(k), 0) for k in keys)
        lines.append(f'| {row["configuration"]} | {pair(previous, ("common_lut", "common_ff"))} | '
                     f'{pair(row, ("common_lut", "common_ff"))} | {pair(row, ("common_bram36", "common_dsp"))} | '
                     f'{num(row["baseline_common_equivalent_slice"])} | {num(row["common_equivalent_slice"])} | '
                     f'{num(row["area_change_pct"])}% | {previous["common_status"]}/{row["common_status"]} |')
    for profile in PROFILES:
        lines += ['', f'## {profile} Sign', '',
                  '| 排名 | P/U | 基线周期 | 候选周期 | 周期相同 | 时间 ms | ATP Slice·ms | ATP 变化 |',
                  '|---:|---|---:|---:|---|---:|---:|---:|']
        for row in rows:
            if row['profile'] != profile:
                continue
            lines.append(f'| {num(row["atp_rank"], 0)} | {row["configuration"]} | '
                         f'{num(row["baseline_cycles"], 0)} | {num(row["cycles"], 0)} | '
                         f'{row["cycles_unchanged"]} | {num(row["time_ms"], 6)} | '
                         f'{num(row["atp_slice_ms"])} | {num(row["atp_change_pct"])}% |')
    if stages:
        lines += ['', '## 冻结实验面积', '',
                  '| 实验 | P/U | 等效 Slice | 综合秒数 | 状态 |', '|---|---|---:|---:|---|']
        for stage in stages:
            for name, task in stage['tasks'].items():
                if not name.startswith('synth/'):
                    continue
                status = task['status'] + ('（后台继续，跳过分析）' if task.get('analysis_deferred') else '')
                lines.append(f'| {stage["label"]} ({stage["run_id"]}) | {name.split("/")[1]} | '
                             f'{num(task.get("area", {}).get("equivalent_slice"))} | '
                             f'{num(task.get("seconds"), 1)} | {status} |')
    notes = args.output.parent / (args.output.name + '_Notes.md')
    if notes.exists():
        lines += ['', notes.read_text().strip()]
    lines += ['', '## 验证证据', '',
              f'- [基线源码]({base_folder / "SOURCE.json"})；[候选源码]({folder / "SOURCE.json"})。',
              f'- [扩展验证]({validation_path})：' +
              (f'通过={validation["passed"]}，完成={validation["complete"]}，记录={len(validation["results"])}。'
               if validation else '尚未完成。'),
              '- h20 完整 Keygen/Sign 保持停止；历史报告保留。', '']
    write(args.output.with_suffix('.md'), '\n'.join(lines))
    print(json.dumps(summary), flush=True)
    return baseline['complete'] and candidate['complete'] and all(
        read_run(spec.split('=', 1)[1])[0]['complete'] for spec in args.experiment)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--experiment', action='append', default=[], metavar='LABEL=RUN_ID')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    while True:
        complete = report(args)
        if complete or not args.watch:
            break
        time.sleep(30)


if __name__ == '__main__':
    main()
