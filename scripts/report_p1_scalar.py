#!/usr/bin/env python3
"""Compare the P1 scalar implementation with the frozen context-engine baseline."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import time
from zoneinfo import ZoneInfo
from experiment_archive import archive_run, canonical_report, report_prefix

ROOT = Path(__file__).resolve().parents[1]


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(content)
    temporary.replace(path)


def number(value, digits=3):
    return '—' if value is None else f'{value:,.{digits}f}'


def report(args):
    args.output = canonical_report(args.output)
    folder = ROOT / 'build/pu_sign_matrix' / args.candidate
    baseline = json.loads((ROOT / 'build/pu_sign_matrix' / args.baseline / 'status.json').read_text())
    candidate = json.loads((folder / 'status.json').read_text())
    archive_run(folder)
    old = {(r['configuration'], r['profile']): r for r in baseline['results']}
    rows = []
    for item in candidate['results']:
        row = dict(item)
        previous = old[row['configuration'], row['profile']]
        for field in ('cycles', 'hashes', 'permutations', 'common_equivalent_slice', 'atp_slice_ms'):
            row['baseline_' + field] = previous[field]
        for name, field in (('area', 'common_equivalent_slice'), ('cycles', 'cycles'), ('atp', 'atp_slice_ms')):
            row[name + '_change_pct'] = (100 * (row[field] / previous[field] - 1)
                                         if row[field] is not None and previous[field] else None)
        measured = row['simulation_status'] == previous['simulation_status'] == 'passed'
        row['workload_equal'] = (all(row[k] == previous[k] for k in ('hashes', 'permutations'))
                                 if measured else None)
        rows.append(row)
    source = json.loads((folder / 'SOURCE.json').read_text())
    rtl = (folder / 'source/sources.txt').read_text().splitlines()
    matches = all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == source['sha256'][name] for name in rtl)
    validation_path = folder / 'source/validation/p1_scalar/VALIDATION.json'
    validation = json.loads(validation_path.read_text()) if validation_path.exists() else None
    data = dict(updated_at=datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds'),
                baseline_run=args.baseline, candidate_run=args.candidate, source_matches_worktree=matches,
                area_top='common', routed_sta=False, rows=rows, validation=validation,
                candidate_complete=candidate['complete'], tasks=candidate['tasks'])
    write(args.output.with_suffix('.json'), json.dumps(data, indent=2) + '\n')
    lines = ['# P1 标量执行路径', '',
             f'更新时间：{data["updated_at"]}。基线 `{args.baseline}`；候选 `{args.candidate}`。', '',
             'P1 使用标量固定块、链反馈和流式吸收；P>1 保留 recipe 内的统一上下文执行。'
             '本次按用户后续要求改变 P1 执行结构，周期重新实测。', '',
             '面积为 xc7a200tffg1156-3 / Vivado 2025.2 / common OOC / 通用 Keccak / '
             '6.666667 ns 默认时序驱动综合，每任务 2 线程。等效 Slice=LUT/4+FF/8+232.4×BRAM36+102.4×DSP。'
             'ATP 使用假定 U1=150 MHz、U2=110 MHz；本次没有布线 STA。', '',
             '## common 面积', '',
             '| P/U | LUT | FF | BRAM36/DSP | 原 Slice | 标量候选 Slice | 变化 | 状态 |',
             '|---|---:|---:|---:|---:|---:|---:|---|']
    for r in rows:
        if r['profile'] == 'slh_128f':
            lines.append(f'| {r["configuration"]} | {number(r["common_lut"],0)} | {number(r["common_ff"],0)} | '
                         f'{number(r["common_bram36"],0)}/{number(r["common_dsp"],0)} | '
                         f'{number(r["baseline_common_equivalent_slice"])} | {number(r["common_equivalent_slice"])} | '
                         f'{number(r["area_change_pct"])}% | {r["common_status"]} |')
    for profile in ('slh_128f', 'xmss_h10', 'lms_h10'):
        lines += ['', f'## {profile} Sign', '',
                  '| 排名 | P/U | 原周期 | 新周期 | 周期变化 | 时间 ms | ATP Slice·ms | ATP变化 | 工作量一致 |',
                  '|---:|---|---:|---:|---:|---:|---:|---:|---|']
        for r in rows:
            if r['profile'] == profile:
                lines.append(f'| {number(r["atp_rank"],0)} | {r["configuration"]} | '
                             f'{number(r["baseline_cycles"],0)} | {number(r["cycles"],0)} | '
                             f'{number(r["cycles_change_pct"])}% | {number(r["time_ms"],6)} | '
                             f'{number(r["atp_slice_ms"])} | {number(r["atp_change_pct"])}% | {r["workload_equal"]} |')
    notes = args.output.parent / (args.output.name + '_Notes.md')
    if notes.exists():
        lines += ['', notes.read_text().strip()]
    lines += ['', '## 验证与证据', '', f'工作区生产源码与候选一致：{matches}。', '',
              f'- [冻结源码]({folder / "SOURCE.json"})；[完整任务状态]({folder / "status.json"})。',
              f'- [扩展验证]({validation_path})：' + (f'{len(validation["results"])}/{validation["expected_records"]}，'
              f'完成={validation["complete"]}，通过={validation["passed"]}。' if validation else '待完成。'),
              '- XMSS/LMS h20 完整 Keygen、Sign 保持停止；异常综合继续后台运行。', '']
    write(args.output.with_suffix('.md'), '\n'.join(lines))
    print(json.dumps(dict(candidate=args.candidate, counts=candidate['counts'], source_matches=matches)), flush=True)
    return candidate['complete'] and validation is not None and validation['complete']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default='20261014_143751')
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--output', type=Path, default=report_prefix('P1_Scalar_20261014'))
    parser.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    while True:
        complete = report(args)
        if complete or not args.watch:
            break
        time.sleep(30)


if __name__ == '__main__':
    main()
