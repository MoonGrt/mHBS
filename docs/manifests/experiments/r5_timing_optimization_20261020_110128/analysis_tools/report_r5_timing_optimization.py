#!/usr/bin/env python3
"""Aggregate frozen R5-based timing candidates; never launch hardware or edit RTL.

    python3 scripts/report_r5_timing_optimization.py --watch --interval 30

The default output stays in the S1 archive as later candidates appear. Reports
remain volatile until at least two candidates and their validations finish.
"""
import argparse
import json
import os
from pathlib import Path
import time

import report_c2_timing_optimization as common
import run_r5_timing_optimization as measurement

ROOT = measurement.ROOT
RUN_ROOT = ROOT / 'build/r5_timing_optimization'
S1_ARCHIVE = ROOT / 'docs/manifests/experiments/r5_timing_optimization_20261020_110128'
HISTORY_RUN = ROOT / 'build/c2_timing_optimization/candidate_20261020_095359'
HISTORY_SHA = '1e2849cdec2ab4934ecdbd6156822deba9af04a17ba481d77af956e62e6c052b'
CONFIGS, PROFILES = common.CONFIGS, common.PROFILES
read, write, sha, now = common.read, common.write, common.sha, common.now
fmt, delta, compact = common.fmt, common.delta, common.compact


def from_evidence(evidence, stage, label):
    meta, state = evidence['source'], evidence['results']
    return dict(stage=stage, name=Path(evidence['run_root']).name, label=label, reference=True,
        directory=evidence['run_root'], archive_directory=meta['archive_directory'],
        source_manifest=str(Path(evidence['run_root']) / 'SOURCE.json'),
        source_manifest_sha256=evidence['manifest_sha256'], source_bound=True,
        frozen_rtl_sha256={k: v for k, v in meta['sha256'].items() if k.startswith('rtl/')},
        complete=True, archive_complete=True, counts=state['counts'], tests=state['tests'],
        synthesis=state['synthesis'], routing=state['routing'])


def discover(run_root):
    runs, errors = [], []
    for path in sorted(run_root.glob('candidate_*/SOURCE.json')):
        try:
            meta, state = read(path), read(path.parent / 'status.json')
            if meta.get('schema') != measurement.SCHEMA:
                continue
            source, evidence_path = Path(meta['source_root']), path.parent / 'R5_BASELINE_EVIDENCE.json'
            mismatches = [name for name, digest in meta['sha256'].items()
                          if not (source / name).is_file() or sha(source / name) != digest]
            evidence = read(evidence_path)
            bound = (not mismatches and len([k for k in meta['sha256'] if k.startswith('rtl/')]) == 10
                and meta.get('baseline_manifest_sha256') == measurement.BASELINE_SHA
                and evidence.get('manifest_sha256') == measurement.BASELINE_SHA
                and evidence_path.is_file() and sha(evidence_path) == meta.get('baseline_evidence_sha256')
                and meta.get('hash_backend') == 'shake' and meta.get('top') == 'common'
                and meta.get('part') == 'xc7a200tffg1156-3' and meta.get('synthesis_period_ns') == 10.0
                and meta.get('threads_per_vivado') == 2 and meta.get('new_timing_exceptions') is False)
            runs.append(dict(stage=f'S{len(runs)+1}', name=path.parent.name, label=meta['label'], reference=False,
                directory=str(path.parent), archive_directory=meta['archive_directory'],
                source_manifest=str(path), source_manifest_sha256=sha(path), source_bound=bound,
                source_mismatches=mismatches,
                frozen_rtl_sha256={k: v for k, v in meta['sha256'].items() if k.startswith('rtl/')},
                complete=state.get('complete', False), archive_complete=read(Path(meta['archive_directory']) /
                'ARTIFACTS.json').get('complete', False), counts=state.get('counts', {}),
                tests=state.get('tests', {}), synthesis=state.get('synthesis', {}), routing=state.get('routing', {})))
        except (OSError, ValueError, KeyError) as error:
            errors.append(dict(path=str(path), error=str(error)))
    return runs, errors


def historical_r1():
    measurement.require(sha(HISTORY_RUN / 'SOURCE.json') == HISTORY_SHA, 'Historical R1 source manifest changed')
    evidence = measurement.core.checked_evidence(HISTORY_RUN)
    run = from_evidence(evidence, 'R1历史', '旧 R1：仅 P4U1@130MHz 闭合')
    for name, item in run['routing'].items():
        folder = HISTORY_RUN / 'route' / name
        measurement.require(item.get('source_manifest_sha256') == HISTORY_SHA
            and item.get('source_unchanged') is True and item['result'] == read(folder / 'result.json')
            and item['route_status'] == measurement.core.route_status(folder / 'route/route_status.rpt')
            and item['area'] == measurement.core.utilization(folder / 'route/utilization.rpt')
            and sha(folder / 'route/routed.dcp') == item['routed_checkpoint_sha256'],
            f'Unbound historical R1 route: {name}')
    return run


def validations(run_root, runs):
    values, by_manifest = [], {r['source_manifest_sha256']: r for r in runs}
    for path in sorted(run_root.glob('validation_s*/VALIDATION.json')):
        data = read(path)
        run = by_manifest.get(data.get('source_manifest_sha256'))
        bound = bool(run and Path(data.get('source_manifest', '')).resolve() == Path(run['source_manifest']).resolve()
            and data.get('rtl_sha256') == run['frozen_rtl_sha256'] and run['source_bound']
            and data.get('source_unchanged') is True)
        values.append(dict(path=str(path), summary_sha256=sha(path), source_bound=bound,
            stage=run['stage'] if run else None, run=run['name'] if run else None,
            complete=data.get('complete', False), passed=data.get('passed'), failed=data.get('failed'),
            planned=data.get('total_planned'), status=data.get('status'), scope=data.get('scope')))
    return values


def render(run_root, prefix, minimum_candidates):
    baseline = from_evidence(measurement.checked_baseline(), 'R5', 'R5：两配置 130MHz 布线通过的选定起点')
    candidates, errors = discover(run_root)
    history = historical_r1()
    runs = [baseline, *candidates]
    sims = common.sim_rows([*runs, history], baseline)
    for row in sims:
        row['baseline_cycles'] = row.pop('c2_cycles')
        if row.get('workload_equal') is not True:
            for key in ('assumed_100mhz_time_ms', 'diagnostic_assumed_100mhz_atp_slice_ms', 'diagnostic_atp_change_pct'):
                row.pop(key, None)
    routes, _ = common.route_rows([*runs, history], sims)
    actual = common.sta_actual_rows(routes, sims)
    for row in actual:
        old = next((r for r in actual if r['stage'] == 'R5' and r['configuration'] == row['configuration']
            and r['profile'] == row['profile'] and r['nominal_target_mhz'] == 130), None)
        if old:
            row['relative_r5_130mhz_atp_pct'] = delta(old['routed_atp_slice_ms'], row['routed_atp_slice_ms'])
    validation = validations(run_root, runs)
    finished = (len(candidates) >= minimum_candidates and not errors
        and all(r['complete'] and r['archive_complete'] for r in candidates)
        and all(v['complete'] for v in validation))
    current = {name: sha(ROOT / name) if (ROOT / name).is_file() else None
               for name in baseline['frozen_rtl_sha256']}
    matches = [run['stage'] for run in runs if current == run['frozen_rtl_sha256']]
    data = dict(schema='mhbs.r5_timing.progress.v1', updated_at=now(), baseline='R5',
        baseline_manifest_sha256=measurement.BASELINE_SHA, all_measurements_complete=finished,
        minimum_expected_candidates=minimum_candidates, diagnostic_period_ns=10.0,
        no_wns_derived_frequency=True, detailed_simulation_logs_archived=False,
        baseline_selection_reason='R5 closes P12U1 and P4U1 at 130 MHz; historical R1 has lower P4U1 ATP '
            'at 130 MHz but does not close P12U1 at 130 MHz. R5 is the selected common timing baseline.',
        workspace_matches=matches, runs=[{k:v for k,v in r.items() if k != 'tests'} for r in runs],
        historical_r1={k:v for k,v in history.items() if k not in ('tests', 'synthesis')},
        comparisons=sims, routes=routes, STA_closed_actual_rows=actual,
        validation_summaries=validation, discovery_errors=errors,
        policy_selftest=common.policy_selftest(),
        nominal_clock_rounding_note='Positive setup/hold, DRC=0 and complete routing permit actual '
            '1000/period reporting even when Vivado quantization misses a strict nominal target. '
            'Negative WNS never yields an inferred passed frequency.')
    row_text = lambda values: '| ' + ' | '.join(str(v) for v in values) + ' |'
    lines = ['# R5 基础 SHAKE 时序优化进展', '',
        f'更新时间：{data["updated_at"]}；' + ('已发现测量全部结束。' if finished else '后台测量继续。'), '',
        '本轮唯一比较基线为冻结 R5（20261020_100441），聚焦 P12U1／P4U1。'
        'R5 在两配置均通过 130 MHz 布线，因此选为共同优化起点；旧 R1 的 P4U1@130MHz '
        '面积和 ATP 更低，但其 P12U1@130MHz 未闭合。选定 R5 不代表每个配置的 ATP 都优于 R1。', '',
        'common OOC、xc7a200tffg1156-3、通用 Keccak、SYNTHESIS 统计裁剪、默认时序驱动；'
        '100 MHz 综合仅诊断面积和关键路径。每个 Vivado 两线程，全机最多十二个；'
        '异常综合只延后分析，后台继续，不新增时序例外。h20 完整 Keygen／Sign 保持停止。', '',
        '工作区当前匹配冻结 RTL：' + ('、'.join(matches) or '无完全匹配版本') + '。'
        '报告归档固定在 S1，不因后续候选迁移。', '',
        '| 阶段 | 候选 | Sign通过 | 额外验证 | 源码绑定 | 状态 |', '|---|---|---:|---|---|---|']
    for run in runs:
        extra = [v for v in validation if v['run'] == run['name']]
        extra_text = '、'.join(f'{v["passed"]}/{v["planned"]}（{v["status"]}）' for v in extra) or '—'
        lines.append(row_text([run['stage'], run['label'], f'{run["counts"].get("passed", 0)}/6', extra_text,
            '匹配' if run['source_bound'] else '未匹配', '完成' if run['complete'] else '后台运行']))
    lines += ['', '## 100 MHz 综合面积及路径诊断', '',
        '| 阶段 | 配置 | LUT | FF | BRAM36 | Slice | 相对R5面积 % | 路径 ns | 级数 | 耗时 s | 状态 |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|']
    for run in runs:
        for config in CONFIGS:
            item = run['synthesis'].get(config, {})
            area, path = item.get('area', {}), item.get('timing', {})
            status = item.get('status', 'pending') + ('／分析延后，后台继续' if item.get('analysis_deferred') else '')
            lines.append(row_text([run['stage'], config, *[fmt(area.get(k), 0) for k in ('lut', 'ff')],
                fmt(area.get('bram36')), fmt(area.get('equivalent_slice')),
                fmt(delta(baseline['synthesis'][config]['area']['equivalent_slice'], area.get('equivalent_slice'))),
                fmt(path.get('data_path_ns')), fmt(path.get('logic_levels'), 0), fmt(item.get('elapsed_seconds')), status]))
    for profile in PROFILES:
        lines += ['', f'## {profile} 完整 Sign', '',
            '| 阶段 | 配置 | 周期 | 相对R5周期 % | 假设100MHz时间 ms | 假设ATP Slice·ms | 相对R5假设ATP % | Hash／置换 | 工作量相同 | 状态 |',
            '|---|---|---:|---:|---:|---:|---:|---|---|---|']
        for row in sims:
            if row['profile'] == profile and row['stage'] != 'R1历史':
                equal = '—' if row['workload_equal'] is None else ('是' if row['workload_equal'] else '否')
                lines.append(row_text([row['stage'], row['configuration'], fmt(row['cycles'], 0),
                    fmt(row['cycles_change_pct'], 6), fmt(row.get('assumed_100mhz_time_ms'), 6),
                    fmt(row.get('diagnostic_assumed_100mhz_atp_slice_ms'), 6),
                    fmt(row.get('diagnostic_atp_change_pct'), 6),
                    f'{fmt(row["hashes"],0)}／{fmt(row["permutations"],0)}', equal, row['status']]))
    lines += ['', '输出和签名缓存逐字节核对，Hash／置换次数及向量 SHA 与 R5 比较。'
        '以上 100 MHz ATP 是固定假设频率的诊断值，不代表布线收益。', '',
        '## 布线 STA', '',
        '| 阶段 | 配置 | 名义目标 MHz | 实际周期 ns | WNS ns | WHS ns | 布通 | DRC错误 | 严格目标达到 | 状态 |',
        '|---|---|---:|---:|---:|---:|---|---:|---|---|']
    boolean = lambda v: '—' if v is None else ('是' if v else '否')
    for route in routes:
        lines.append(row_text([route['stage'], route['configuration'], fmt(route['target_frequency_mhz']),
            fmt(route['actual_constraint_period_ns']), fmt(route['wns_ns']), fmt(route['whs_ns']),
            boolean(route['complete_routing']), fmt(route['drc_errors'], 0),
            boolean(route['target_verdict']), route['status']]))
    lines += ['', '## 按实际约束闭合的频率及 ATP', '',
        '只有源码／工作量绑定、完整布通、DRC=0、setup／hold 全通过才填写本表。'
        '名义 150 MHz 若被 Vivado 量化为 6.667 ns，实际闭合频率为约 149.9925 MHz，'
        '保留该实测值且严格目标列保持“否”。负 WNS 不外推较低频率。', '',
        '| 阶段 | 配置 | 算法 | 名义目标 MHz | 实际STA频率 MHz | 严格目标达到 | 布线 Slice | 时间 ms | ATP Slice·ms | 相对R5@130MHz % |',
        '|---|---|---|---:|---:|---|---:|---:|---:|---:|']
    for row in actual:
        lines.append(row_text([row['stage'], row['configuration'], row['profile'], fmt(row['nominal_target_mhz']),
            fmt(row['sta_closed_actual_frequency_mhz'], 4), boolean(row['strict_target_met']),
            fmt(row['equivalent_slice']), fmt(row['routed_time_ms'], 6), fmt(row['routed_atp_slice_ms'], 6),
            fmt(row.get('relative_r5_130mhz_atp_pct'), 6)]))
    lines += ['', '## 验证与源码证据', '']
    for v in validation:
        lines.append(f'- {v["stage"] or "未匹配候选"}：{v["passed"]}/{v["planned"]}（{v["status"]}）；'
            f'冻结源码绑定：{"匹配" if v["source_bound"] else "未匹配"}。{v["scope"] or ""}')
    for run in [*runs, history]:
        lines.append(f'- {run["stage"]}：`{run["directory"]}`；SOURCE SHA `{run["source_manifest_sha256"]}`。')
    for error in errors:
        lines.append(f'- 发现错误：`{error["path"]}`：{error["error"]}')
    lines += ['', '归档仅保存 MD／JSON、冻结 RTL、源码校验、综合／布线报告及验证摘要；仿真明细留 build。'
        '全部测量及额外验证结束前，本进展报告列为 volatile；不可变原始证据的哈希不会被重写。', '']
    write(prefix.with_suffix('.json'), data)
    common.archive.atomic(prefix.with_suffix('.md'), '\n'.join(lines))
    return data


def update_artifacts(out, prefix, finished):
    path = out / 'ARTIFACTS.json'
    value = read(path)
    if not value:
        return dict(updated=False, reason='Measurement archive not yet published')
    owned = [str(p.relative_to(out)) for p in (prefix.with_suffix('.md'), prefix.with_suffix('.json'))]
    indexed, errors = dict(value.get('sha256', {})), []
    if value.get('complete'):
        for name, digest in indexed.items():
            if name in owned or name in value.get('volatile_artifacts', []):
                continue
            if not (out / name).is_file() or sha(out / name) != digest:
                errors.append(name)
    for name in owned:
        indexed.pop(name, None)
    tool = out / 'analysis_tools/report_r5_timing_optimization.py'
    indexed[str(tool.relative_to(out))] = sha(tool)
    finalized = bool(finished and value.get('complete') and not errors)
    if finalized:
        indexed.update({name: sha(out / name) for name in owned})
        value['volatile_artifacts'] = [n for n in value.get('volatile_artifacts', []) if n not in owned]
    else:
        value['volatile_artifacts'] = sorted(set(value.get('volatile_artifacts', [])) | set(owned))
    value.update(sha256=indexed, comparison_report_status='finalized' if finalized else
        ('immutable_evidence_mismatch' if errors else 'live'), comparison_report_index_updated_at=now(),
        comparison_immutable_checksum_errors=errors)
    write(path, value)
    return dict(updated=True, finalized=finalized, immutable_checksum_errors=errors)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--run-root', type=Path, default=RUN_ROOT)
    parser.add_argument('--output-prefix', type=Path, default=S1_ARCHIVE / 'reports/R5_Timing_Progress_20261020')
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--interval', type=float, default=30)
    parser.add_argument('--minimum-candidates', type=int, default=2)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(common.policy_selftest(), ensure_ascii=False, indent=2))
        return 0
    if not 0 < args.interval <= 30 or args.minimum_candidates < 1:
        parser.error('Interval must be in (0,30]; minimum candidates must be positive')
    prefix, run_root = args.output_prefix.resolve(), args.run_root.resolve()
    candidates, _ = discover(run_root)
    owner = next((run for run in candidates if prefix.is_relative_to(Path(run['archive_directory']))), None)
    if owner is None:
        parser.error('Output must lie in a discovered candidate archive')
    out = Path(owner['archive_directory'])
    common.archive.copy_changed(Path(__file__).resolve(), out / 'analysis_tools/report_r5_timing_optimization.py')
    while True:
        data = render(run_root, prefix, args.minimum_candidates)
        artifacts = update_artifacts(out, prefix, data['all_measurements_complete'])
        if not args.watch or data['all_measurements_complete']:
            print(json.dumps(dict(report=str(prefix.with_suffix('.md')),
                all_measurements_complete=data['all_measurements_complete'], artifacts=artifacts),
                ensure_ascii=False, indent=2))
            return int(bool(artifacts.get('immutable_checksum_errors')))
        time.sleep(args.interval)


if __name__ == '__main__':
    raise SystemExit(main())
