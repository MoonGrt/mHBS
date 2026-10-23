#!/usr/bin/env python3
"""Aggregate frozen S4-based timing candidates; never launch hardware or edit RTL.

    python3 scripts/report_s4_timing_optimization.py --watch --interval 60

The default output stays in the T1 archive as later candidates appear. Reports
remain volatile until at least three candidates and their validations finish.
"""
import argparse
import json
import os
from pathlib import Path
import time

import report_c2_timing_optimization as common
import run_s4_timing_optimization as measurement

ROOT = measurement.ROOT
RUN_ROOT = ROOT / 'build/s4_timing_optimization'
T1_ARCHIVE = ROOT / 'docs/manifests/experiments/s4_timing_optimization_20261020_115725'
CONFIGS, PROFILES = common.CONFIGS, common.PROFILES
read, write, sha, now = common.read, common.write, common.sha, common.now
fmt, delta, compact = common.fmt, common.delta, common.compact


def evidence_mismatches(path, meta, state):
    """Check completed job files as well as their source-manifest claims."""
    errors, manifest_sha = [], sha(path)
    for key, item in state.get('tests', {}).items():
        if item.get('status') != 'passed':
            continue
        log = Path(item.get('log', ''))
        if (item.get('source_manifest_sha256') != manifest_sha
                or item.get('source_unchanged') is not True or not log.is_file()
                or sha(log) != item.get('log_sha256')
                or item.get('output_and_signature_cache_checked_bytewise') is not True):
            errors.append(f'tests/{key}')
    for key, item in state.get('synthesis', {}).items():
        if item.get('status') != 'passed':
            continue
        folder = path.parent / 'synth' / key
        reports = item.get('reports_sha256', {})
        if (item.get('source_manifest_sha256') != manifest_sha or item.get('source_unchanged') is not True
                or not reports or any(not (folder / name).is_file() or sha(folder / name) != digest
                                      for name, digest in reports.items())):
            errors.append(f'synthesis/{key}')
    for key, item in state.get('routing', {}).items():
        if item.get('status') not in ('passed', 'target_not_met'):
            continue
        folder = path.parent / 'route' / key
        try:
            ok = (item.get('source_manifest_sha256') == manifest_sha
                and item.get('source_unchanged') is True
                and item.get('result') == read(folder / 'result.json')
                and item.get('route_status') == measurement.core.route_status(folder / 'route/route_status.rpt')
                and item.get('area') == measurement.core.utilization(folder / 'route/utilization.rpt')
                and item.get('timing') == measurement.core.timing(folder / 'route/timing.rpt')
                and item.get('routed_checkpoint_sha256') == sha(folder / 'route/routed.dcp'))
        except (OSError, ValueError, KeyError):
            ok = False
        if not ok:
            errors.append(f'routing/{key}')
    return errors


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
            source, evidence_path = Path(meta['source_root']), path.parent / 'S4_BASELINE_EVIDENCE.json'
            mismatches = [name for name, digest in meta['sha256'].items()
                          if not (source / name).is_file() or sha(source / name) != digest]
            mismatches.extend(evidence_mismatches(path, meta, state))
            evidence = read(evidence_path)
            bound = (not mismatches and len([k for k in meta['sha256'] if k.startswith('rtl/')]) == 10
                and meta.get('baseline_manifest_sha256') == measurement.BASELINE_SHA
                and evidence.get('manifest_sha256') == measurement.BASELINE_SHA
                and evidence_path.is_file() and sha(evidence_path) == meta.get('baseline_evidence_sha256')
                and meta.get('hash_backend') == 'shake' and meta.get('top') == 'common'
                and meta.get('part') == 'xc7a200tffg1156-3' and meta.get('synthesis_period_ns') == 10.0
                and meta.get('threads_per_vivado') == 2 and meta.get('new_timing_exceptions') is False)
            runs.append(dict(stage=f'T{len(runs)+1}', name=path.parent.name, label=meta['label'], reference=False,
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


def validations(run_root, runs):
    values, by_manifest = [], {r['source_manifest_sha256']: r for r in runs}
    for path in sorted(run_root.glob('validation_t*/VALIDATION.json')):
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


def workspace_units(run_root, runs):
    """Discover compact workspace/unit summaries, never copy detailed logs."""
    summaries = set(run_root.glob('*workspace*.json')) | set(run_root.glob('*unit*.json'))
    summaries.update(run_root.glob('validation_t*/**/WORKSPACE_VALIDATION.json'))
    for run in runs:
        archive = Path(run['archive_directory'])
        for folder in ('validation_summary', 'workspace_validation_summary'):
            summaries.update(path for path in (archive / folder).rglob('*.json')
                             if 'workspace' in str(path.relative_to(archive)).lower()
                             and path.name != 'SHA256.json')
    values, seen = [], set()
    for path in sorted(summaries):
        data = read(path)
        digest = sha(path)
        if digest in seen:
            continue
        seen.add(digest)
        rtl = data.get('rtl_sha256', data.get('source_sha256'))
        manifest_sha = data.get('source_manifest_sha256')
        matches = [run for run in runs if run['source_bound']
                   and manifest_sha == run['source_manifest_sha256']
                   and isinstance(rtl, dict) and rtl == run['frozen_rtl_sha256']
                   and data.get('source_unchanged') is True]
        tests = data.get('tests', [])
        passed = sum(test.get('passed') is True for test in tests) if isinstance(data.get('passed'), bool) else data.get('passed')
        failed = sum(test.get('passed') is False for test in tests) if isinstance(data.get('passed'), bool) else data.get('failed')
        values.append(dict(path=str(path), summary_sha256=digest, stages=[run['stage'] for run in matches],
            source_bound=bool(matches), complete=data.get('complete', data.get('passed') is True),
            status=data.get('status', 'passed' if data.get('passed') is True else None),
            passed=passed, failed=failed,
            planned=data.get('total_planned', len(tests)), scope=data.get('scope')))
    return values


def render(run_root, prefix, minimum_candidates):
    baseline = from_evidence(measurement.checked_baseline(), 'S4', 'S4：P12U1@139.997200MHz、P4U1@149.992500MHz 实际 STA 闭合')
    candidates, errors = discover(run_root)
    runs = [baseline, *candidates]
    sims = common.sim_rows(runs, baseline)
    for row in sims:
        row['baseline_cycles'] = row.pop('c2_cycles')
        if row.get('workload_equal') is not True:
            for key in ('assumed_100mhz_time_ms', 'diagnostic_assumed_100mhz_atp_slice_ms', 'diagnostic_atp_change_pct'):
                row.pop(key, None)
    routes, _ = common.route_rows(runs, sims)
    actual = common.sta_actual_rows(routes, sims)
    for item in actual:
        prior = [row for row in actual if row['stage'] == 'S4'
                 and row['configuration'] == item['configuration'] and row['profile'] == item['profile']]
        old = min(prior, key=lambda row: row['routed_atp_slice_ms']) if prior else None
        if old:
            item['baseline_task'] = old['task']
            item['baseline_actual_frequency_mhz'] = old['sta_closed_actual_frequency_mhz']
            item['relative_s4_best_closed_atp_pct'] = delta(old['routed_atp_slice_ms'], item['routed_atp_slice_ms'])
    validation = validations(run_root, runs)
    units = workspace_units(run_root, runs)
    routes_requested = any(run['routing'] for run in candidates)
    finished = (len(candidates) >= minimum_candidates and routes_requested and not errors
        and all(r['complete'] and r['archive_complete'] for r in candidates)
        and all(r['source_bound'] for r in runs)
        and all(any(v['run'] == r['name'] and v['source_bound'] and v['complete']
                    for v in validation) for r in candidates)
        and all(v['complete'] for v in validation)
        and all(v['complete'] for v in units if v['source_bound']))
    current = {name: sha(ROOT / name) if (ROOT / name).is_file() else None
               for name in baseline['frozen_rtl_sha256']}
    matches = [run['stage'] for run in runs if current == run['frozen_rtl_sha256']]
    data = dict(schema='mhbs.s4_timing.progress.v1', updated_at=now(), baseline='S4',
        baseline_manifest_sha256=measurement.BASELINE_SHA, all_measurements_complete=finished,
        minimum_expected_candidates=minimum_candidates, diagnostic_period_ns=10.0,
        no_wns_derived_frequency=True, detailed_simulation_logs_archived=False,
        baseline_selection_reason='Frozen S4 (110957) is the selected design. Compare each P/U against its '
            'own independently STA-closed minimum ATP: P12U1 at actual 139.997200 MHz and P4U1 at '
            'actual 149.992500 MHz. Exact nominal target failure due only to clock quantization '
            'does not suppress actual closed frequency or ATP.',
        workspace_matches=matches, runs=[{k:v for k,v in r.items() if k != 'tests'} for r in runs],
        comparisons=sims, routes=routes, STA_closed_actual_rows=actual,
        validation_summaries=validation, workspace_unit_summaries=units, discovery_errors=errors,
        candidate_routes_requested=routes_requested,
        policy_selftest=common.policy_selftest(),
        nominal_clock_rounding_note='Positive setup/hold, DRC=0 and complete routing permit actual '
            '1000/period reporting even when Vivado quantization misses a strict nominal target. '
            'Negative WNS never yields an inferred passed frequency.')
    row_text = lambda values: '| ' + ' | '.join(str(v) for v in values) + ' |'
    lines = ['# S4 基础 SHAKE 时序优化进展', '',
        f'更新时间：{data["updated_at"]}；' + ('已发现测量全部结束。' if finished else '后台测量继续。'), '',
        '本轮唯一比较基线为冻结 S4（20261020_110957），聚焦 P12U1／P4U1。'
        '基线按各自最佳实测闭合 ATP 比较：P12U1 为139.997200 MHz，P4U1 为149.992500 MHz。'
        '精确名义目标因时钟量化未满足，与实际 STA 闭合分开记录；P12U1 的150MHz负 WNS不计ATP。', '',
        'common OOC、xc7a200tffg1156-3、通用 Keccak、SYNTHESIS 统计裁剪、默认时序驱动；'
        '100 MHz 综合仅诊断面积和关键路径。每个 Vivado 两线程，全机最多十二个；'
        '异常综合只延后分析，后台继续，不新增时序例外。h20 完整 Keygen／Sign 保持停止。', '',
        '工作区当前匹配冻结 RTL：' + ('、'.join(matches) or '无完全匹配版本') + '。'
        '报告归档固定在 T1，不因后续候选迁移。', '',
        '| 阶段 | 候选 | Sign通过 | 额外验证 | 源码绑定 | 状态 |', '|---|---|---:|---|---|---|']
    for run in runs:
        extra = [v for v in validation if v['run'] == run['name']]
        extra_text = '、'.join(f'{v["passed"]}/{v["planned"]}（{v["status"]}）' for v in extra) or '—'
        lines.append(row_text([run['stage'], run['label'], f'{run["counts"].get("passed", 0)}/6', extra_text,
            '匹配' if run['source_bound'] else '未匹配', '完成' if run['complete'] else '后台运行']))
    lines += ['', '## 100 MHz 综合面积及路径诊断', '',
        '| 阶段 | 配置 | LUT | FF | BRAM36 | Slice | 相对S4面积 % | 路径 ns | 级数 | 耗时 s | 状态 |',
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
            '| 阶段 | 配置 | 周期 | 相对S4周期 % | 假设100MHz时间 ms | 假设ATP Slice·ms | 相对S4假设ATP % | Hash／置换 | 工作量相同 | 状态 |',
            '|---|---|---:|---:|---:|---:|---:|---|---|---|']
        for row in sims:
            if row['profile'] == profile:
                equal = '—' if row['workload_equal'] is None else ('是' if row['workload_equal'] else '否')
                lines.append(row_text([row['stage'], row['configuration'], fmt(row['cycles'], 0),
                    fmt(row['cycles_change_pct'], 6), fmt(row.get('assumed_100mhz_time_ms'), 6),
                    fmt(row.get('diagnostic_assumed_100mhz_atp_slice_ms'), 6),
                    fmt(row.get('diagnostic_atp_change_pct'), 6),
                    f'{fmt(row["hashes"],0)}／{fmt(row["permutations"],0)}', equal, row['status']]))
    lines += ['', '输出和签名缓存逐字节核对，Hash／置换次数及向量 SHA 与 S4 比较。'
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
        '| 阶段 | 配置 | 算法 | 名义目标 MHz | 实际STA频率 MHz | 严格目标达到 | 布线 Slice | 时间 ms | ATP Slice·ms | 相对S4各自最佳闭合 % |',
        '|---|---|---|---:|---:|---|---:|---:|---:|---:|']
    for row in actual:
        lines.append(row_text([row['stage'], row['configuration'], row['profile'], fmt(row['nominal_target_mhz']),
            fmt(row['sta_closed_actual_frequency_mhz'], 4), boolean(row['strict_target_met']),
            fmt(row['equivalent_slice']), fmt(row['routed_time_ms'], 6), fmt(row['routed_atp_slice_ms'], 6),
            fmt(row.get('relative_s4_best_closed_atp_pct'), 6)]))
    lines += ['', '## 验证与源码证据', '']
    for v in validation:
        lines.append(f'- {v["stage"] or "未匹配候选"}：{v["passed"]}/{v["planned"]}（{v["status"]}）；'
            f'冻结源码绑定：{"匹配" if v["source_bound"] else "未匹配"}。{v["scope"] or ""}')
    for v in units:
        lines.append(f'- 工作区单元验证：{v["passed"]}/{v["planned"]}（{v["status"]}）；'
            f'冻结源码绑定：{"、".join(v["stages"]) or "未匹配"}。`{v["path"]}`；{v["scope"] or ""}')
    for run in runs:
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
    tool = out / 'analysis_tools/report_s4_timing_optimization.py'
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
    parser.add_argument('--output-prefix', type=Path, default=T1_ARCHIVE / 'reports/S4_Timing_Progress_20261020')
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--interval', type=float, default=60)
    parser.add_argument('--minimum-candidates', type=int, default=3)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(common.policy_selftest(), ensure_ascii=False, indent=2))
        return 0
    if not 0 < args.interval <= 60 or args.minimum_candidates < 1:
        parser.error('Interval must be in (0,60]; minimum candidates must be positive')
    prefix, run_root = args.output_prefix.resolve(), args.run_root.resolve()
    candidates, _ = discover(run_root)
    owner = next((run for run in candidates if prefix.is_relative_to(Path(run['archive_directory']))), None)
    if owner is None:
        parser.error('Output must lie in a discovered candidate archive')
    out = Path(owner['archive_directory'])
    common.archive.copy_changed(Path(__file__).resolve(), out / 'analysis_tools/report_s4_timing_optimization.py')
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
