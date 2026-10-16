#!/usr/bin/env python3
"""Report C2-based timing measurements; never launch or stop hardware jobs.

    python3 scripts/report_c2_timing_optimization.py --watch

Discovers frozen candidates and the C2 reference routes. By default the report
is written to the latest non-reference candidate archive at startup. Later runs
are included in that report automatically. No RTL or INDEX is modified.
"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import time
from zoneinfo import ZoneInfo

import experiment_archive as archive
import run_c2_timing_optimization as measurement
from run_hash_backends import sha

ROOT = Path(os.environ.get('MHBS_C2_TIMING_WORKSPACE', Path(__file__).resolve().parents[1])).resolve()
CONFIGS = ('P12U1', 'P4U1')
PROFILES = ('slh_128f', 'xmss_h10', 'lms_h10')


def now():
    return datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds')


def read(path):
    path = Path(path)
    return json.loads(path.read_text()) if path.is_file() else {}


def write(path, value):
    archive.atomic(Path(path), json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def fmt(value, digits=3):
    return '—' if value is None else f'{value:,.{digits}f}'


def delta(old, new):
    return None if old is None or new is None or old <= 0 else 100 * (new / old - 1)


def compact(item, fields):
    return {name: item[name] for name in fields if name in item}


def discover(run_root):
    runs, errors = [], []
    for path in sorted(run_root.glob('candidate_*/SOURCE.json')):
        try:
            meta, state = read(path), read(path.parent / 'status.json')
            if meta.get('schema') != measurement.SCHEMA:
                continue
            source = Path(meta['source_root'])
            mismatches = [name for name, digest in meta.get('sha256', {}).items()
                          if not (source / name).is_file() or sha(source / name) != digest]
            evidence = path.parent / 'C2_BASELINE_EVIDENCE.json'
            baseline = read(evidence)
            settings_ok = (meta.get('hash_backend') == 'shake' and meta.get('top') == 'common'
                and meta.get('part') == 'xc7a200tffg1156-3' and meta.get('synthesis_period_ns') == 10.0
                and meta.get('threads_per_vivado') == 2 and meta.get('new_timing_exceptions') is False)
            baseline_ok = (meta.get('baseline_manifest_sha256') == measurement.C2_MANIFEST_SHA
                and baseline.get('manifest_sha256') == measurement.C2_MANIFEST_SHA
                and evidence.is_file() and sha(evidence) == meta.get('baseline_evidence_sha256'))
            rtl = {name: digest for name, digest in meta.get('sha256', {}).items() if name.startswith('rtl/')}
            bound = not mismatches and bool(meta.get('sha256')) and len(rtl) == 10 and settings_ok and baseline_ok
            tests = {key: compact(item, ('status', 'cycles', 'total_cycles', 'hashes', 'permutations',
                'simulation_seconds', 'vectors_sha256', 'source_manifest_sha256', 'source_unchanged',
                'output_and_signature_cache_checked_bytewise', 'reused_from_run', 'error'))
                for key, item in state.get('tests', {}).items()}
            synthesis = {key: compact(item, ('status', 'area', 'timing', 'elapsed_seconds',
                'analysis_deferred', 'stage', 'source_manifest_sha256', 'source_unchanged',
                'reused_from_run', 'error')) for key, item in state.get('synthesis', {}).items()}
            routing = {key: compact(item, ('configuration', 'status', 'target_frequency_mhz', 'result',
                'area', 'timing', 'route_status', 'meets_target', 'elapsed_seconds', 'analysis_deferred',
                'stage', 'source_manifest_sha256', 'source_unchanged', 'error'))
                for key, item in state.get('routing', {}).items()}
            runs.append(dict(name=path.parent.name, label=meta.get('label', path.parent.name),
                reference=str(meta.get('label', '')).startswith('C2_reference'),
                directory=str(path.parent), archive_directory=meta['archive_directory'],
                source_manifest=str(path), source_manifest_sha256=sha(path),
                source_bound=bound, settings_bound=settings_ok, baseline_bound=baseline_ok,
                source_mismatches=mismatches, frozen_rtl_sha256=rtl,
                started_at=meta.get('started_at'), updated_at=state.get('updated_at'),
                complete=state.get('complete', False), archive_complete=read(Path(meta['archive_directory']) /
                'ARTIFACTS.json').get('complete', False), counts=state.get('counts', {}),
                tests=tests, synthesis=synthesis, routing=routing,
                synthesis_period_ns=meta['synthesis_period_ns'],
                route_requested_at_launch=meta.get('route_requested'),
                route_request=read(path.parent / 'ROUTE_REQUEST.json')))
        except (OSError, ValueError, KeyError) as error:
            errors.append(dict(path=str(path), error=str(error)))
    number = 0
    for run in runs:
        if run['reference']:
            run['stage'] = 'C2-ref'
        else:
            number += 1
            run['stage'] = f'R{number}'
    return runs, errors


def baseline_run():
    evidence = measurement.checked_evidence(measurement.C2_RUN, c2=True)
    meta, state = evidence['source'], evidence['results']
    return dict(stage='C2', name=Path(evidence['run_root']).name, label='原始 C2（211601）', reference=True,
        directory=evidence['run_root'], archive_directory=meta['archive_directory'],
        source_manifest=str(Path(evidence['run_root']) / 'SOURCE.json'),
        source_manifest_sha256=measurement.C2_MANIFEST_SHA, source_bound=True,
        settings_bound=True, baseline_bound=True, source_mismatches=[],
        frozen_rtl_sha256={k: v for k, v in meta['sha256'].items() if k.startswith('rtl/')},
        complete=True, archive_complete=True, counts=state['counts'],
        tests=state['tests'], synthesis=state['synthesis'], routing=state['routing'],
        synthesis_period_ns=10.0, evidence_validation=evidence['checked_at'])


def sim_rows(runs, baseline):
    rows = []
    for run in runs:
        for config in CONFIGS:
            syn, old_syn = run['synthesis'].get(config, {}), baseline['synthesis'][config]
            for profile in PROFILES:
                key = f'{config}/{profile}'
                test, old = run['tests'].get(key, {}), baseline['tests'][key]
                measured = test.get('status') == 'passed'
                bound = (run['source_bound'] and test.get('source_unchanged') is True
                    and test.get('source_manifest_sha256') == run['source_manifest_sha256'])
                checks = {field: test.get(field) == old[field]
                          for field in ('hashes', 'permutations', 'vectors_sha256')} if measured else {}
                equal = bound and all(checks.values()) if checks else None
                row = dict(stage=run['stage'], run=run['name'], reference=run['reference'],
                    configuration=config, profile=profile, status=test.get('status', 'pending'),
                    cycles=test.get('cycles'), c2_cycles=old['cycles'], hashes=test.get('hashes'),
                    permutations=test.get('permutations'), source_bound=bound,
                    workload_checks=checks, workload_equal=equal,
                    cycles_change_pct=delta(old['cycles'], test.get('cycles')) if measured else None)
                if measured and syn.get('status') == 'passed':
                    area, old_area = syn['area']['equivalent_slice'], old_syn['area']['equivalent_slice']
                    row.update(equivalent_slice=area, area_change_pct=delta(old_area, area),
                        assumed_100mhz_time_ms=test['cycles'] / 100000,
                        diagnostic_assumed_100mhz_atp_slice_ms=area * test['cycles'] / 100000,
                        diagnostic_atp_change_pct=100 * (area * test['cycles'] / (old_area * old['cycles']) - 1))
                rows.append(row)
    return rows


def route_rows(runs, rows):
    routes, closed = [], []
    for run in runs:
        for name, task in run['routing'].items():
            config = task.get('configuration', name.split('_')[0])
            result = task.get('result', {})
            target, period = task.get('target_frequency_mhz'), result.get('actual_period_ns')
            bound = (run['source_bound'] and task.get('source_unchanged') is True
                and task.get('source_manifest_sha256') == run['source_manifest_sha256'])
            verified = [row for row in rows if row['run'] == run['name'] and row['configuration'] == config]
            sign_validated = len(verified) == len(PROFILES) and all(row['workload_equal'] is True for row in verified)
            sta_closed = (bound and sign_validated and task.get('status') in ('passed', 'target_not_met')
                and task.get('route_status', {}).get('passed') is True
                and result.get('setup_hold_met') is True and result.get('drc_errors') == 0
                and result.get('wns_ns', -1) >= 0 and result.get('whs_ns', -1) >= 0
                and isinstance(period, (int, float)) and period > 0)
            accepted = (sta_closed and task.get('status') == 'passed' and task.get('meets_target') is True
                and isinstance(target, (int, float)) and target > 0 and period <= 1000 / target + 1e-6)
            route = dict(stage=run['stage'], run=run['name'], configuration=config, task=name,
                target_frequency_mhz=target, requested_period_ns=1000 / target if target else None,
                actual_constraint_period_ns=period, source_bound=bound, accepted=accepted,
                sta_closed_at_actual_constraint=sta_closed,
                sta_closed_actual_frequency_mhz=1000 / period if sta_closed else None,
                target_verdict=accepted if task.get('status') in ('passed', 'target_not_met') else None,
                status=task.get('status', 'pending'), stage_detail=task.get('stage'),
                analysis_deferred=task.get('analysis_deferred', False),
                equivalent_slice=task.get('area', {}).get('equivalent_slice'),
                wns_ns=result.get('wns_ns'), whs_ns=result.get('whs_ns'),
                drc_errors=result.get('drc_errors'), complete_routing=task.get('route_status', {}).get('passed'),
                measured_closed_frequency_mhz=1000 / period if accepted else None)
            routes.append(route)
            if accepted and route['equivalent_slice'] is not None:
                for sim in rows:
                    if sim['run'] == run['name'] and sim['configuration'] == config and sim['workload_equal'] is True:
                        closed.append(dict(stage=run['stage'], run=run['name'], task=name, configuration=config,
                            profile=sim['profile'], target_frequency_mhz=target, actual_constraint_period_ns=period,
                            measured_closed_frequency_mhz=1000 / period, cycles=sim['cycles'],
                            equivalent_slice=route['equivalent_slice'], routed_time_ms=sim['cycles'] * period / 1e6,
                            routed_atp_slice_ms=route['equivalent_slice'] * sim['cycles'] * period / 1e6))
    # Compare only with independently closed C2 at the same target, not a failed WNS-derived clock.
    for row in closed:
        old = next((r for r in closed if r['stage'].startswith('C2') and r['configuration'] == row['configuration']
            and r['profile'] == row['profile'] and r['target_frequency_mhz'] == row['target_frequency_mhz']), None)
        if old:
            row['same_target_c2_routed_atp_change_pct'] = delta(old['routed_atp_slice_ms'], row['routed_atp_slice_ms'])
    return routes, closed


def sta_actual_rows(routes, sims):
    """Actual STA closure is distinct from passing the strict nominal target."""
    rows = []
    for route in routes:
        if not route['sta_closed_at_actual_constraint'] or route['equivalent_slice'] is None:
            continue
        period, area = route['actual_constraint_period_ns'], route['equivalent_slice']
        for sim in sims:
            if (sim['run'] == route['run'] and sim['configuration'] == route['configuration']
                    and sim['workload_equal'] is True):
                rows.append(dict(stage=route['stage'], run=route['run'], task=route['task'],
                    configuration=route['configuration'], profile=sim['profile'],
                    nominal_target_mhz=route['target_frequency_mhz'], strict_target_met=route['accepted'],
                    sta_closed=True, actual_constraint_period_ns=period,
                    sta_closed_actual_frequency_mhz=1000 / period,
                    cycles=sim['cycles'], equivalent_slice=area,
                    routed_time_ms=sim['cycles'] * period / 1e6,
                    routed_atp_slice_ms=area * sim['cycles'] * period / 1e6))
    return rows


def policy_selftest():
    """Synthetic policy cases, not hardware measurements or extra Vivado jobs."""
    from copy import deepcopy
    task = dict(configuration='P12U1', source_unchanged=True, source_manifest_sha256='source',
        status='target_not_met', meets_target=False, target_frequency_mhz=150,
        route_status=dict(passed=True), area=dict(equivalent_slice=10),
        result=dict(actual_period_ns=6.667, wns_ns=0.1, whs_ns=0.05, setup_hold_met=True, drc_errors=0))
    run = dict(stage='TEST', name='synthetic', source_bound=True, source_manifest_sha256='source',
        routing={'P12U1_150MHz': task})
    sims = [dict(run='synthetic', configuration='P12U1', profile=profile, workload_equal=True, cycles=100)
            for profile in PROFILES]
    tests = []
    routes, strict = route_rows([run], sims)
    actual = sta_actual_rows(routes, sims)
    assert not strict and len(actual) == 3 and actual[0]['strict_target_met'] is False
    assert abs(actual[0]['sta_closed_actual_frequency_mhz'] - 149.99250037498125) < 1e-9
    tests.append(dict(name='positive_STA_quantized_period_strict_target_false', passed=True,
        actual_frequency_mhz=actual[0]['sta_closed_actual_frequency_mhz'], strict_target_met=False))
    for name, field, value in (('negative_WNS', 'wns_ns', -0.001),
                               ('negative_hold', 'whs_ns', -0.001), ('DRC_error', 'drc_errors', 1)):
        changed = deepcopy(run)
        changed['routing']['P12U1_150MHz']['result'][field] = value
        routes, strict = route_rows([changed], sims)
        assert not strict and not sta_actual_rows(routes, sims)
        tests.append(dict(name=name, passed=True, actual_frequency_reported=False))
    changed = deepcopy(run)
    changed['source_bound'] = False
    routes, strict = route_rows([changed], sims)
    assert not strict and not sta_actual_rows(routes, sims)
    tests.append(dict(name='unbound_source', passed=True, actual_frequency_reported=False))
    return dict(kind='synthetic_report_policy_selftest', updated_at=now(), complete=True,
                passed=len(tests), failed=0, tests=tests, hardware_jobs_started=0)


def validation_summaries(run_root, runs):
    values = []
    by_manifest = {run['source_manifest_sha256']: run for run in runs}
    for path in sorted(run_root.glob('validation_r*/VALIDATION.json')):
        data = read(path)
        run = by_manifest.get(data.get('source_manifest_sha256'))
        matched = (run is not None and Path(data.get('source_manifest', '')).resolve() ==
            Path(run['source_manifest']).resolve() and data.get('rtl_sha256') == run['frozen_rtl_sha256']
            and run['source_bound'] and data.get('source_unchanged') is True)
        values.append(dict(path=str(path), summary_sha256=sha(path), stage=run['stage'] if run else None,
            run=run['name'] if run else None, source_bound=matched, complete=data.get('complete', False),
            status=data.get('status'), passed=data.get('passed'), failed=data.get('failed'),
            planned=data.get('total_planned', len(data.get('tests', []))), scope=data.get('scope')))
    return values


def selected_candidate(selection_file, runs):
    selection = read(selection_file)
    wanted = selection.get('candidate_run', selection.get('run_root', selection.get('run')))
    match = next((run for run in runs if wanted in (run['name'], run['directory'])), None)
    bound = bool(match and selection.get('source_manifest_sha256') == match['source_manifest_sha256']
                 and match['source_bound'])
    return dict(path=str(selection_file), present=bool(selection), selection=selection,
                source_bound=bound, stage=match['stage'] if match else None)


def render(run_root, prefix, selection_file):
    candidates, errors = discover(run_root)
    baseline = baseline_run()
    runs = [baseline, *candidates]
    rows = sim_rows(runs, baseline)
    routes, closed = route_rows(runs, rows)
    actual_closed = sta_actual_rows(routes, rows)
    validation = validation_summaries(run_root, runs)
    selection = selected_candidate(selection_file, runs)
    all_finished = (bool(candidates) and not errors and all(r['complete'] and r['archive_complete'] for r in candidates)
        and all(v['complete'] for v in validation))
    current = {name: sha(ROOT / name) if (ROOT / name).is_file() else None
               for name in baseline['frozen_rtl_sha256']}
    matches = [run for run in runs if current == run['frozen_rtl_sha256']]
    latest = next((run for run in reversed(candidates) if not run['reference']), None)
    data = dict(schema='mhbs.c2_timing.progress.v1', updated_at=now(), all_measurements_complete=all_finished,
        scope='SHAKE common OOC, xc7a200tffg1156-3; generic Keccak; default timing-driven; 2 threads/Vivado.',
        baseline='C2', baseline_manifest_sha256=measurement.C2_MANIFEST_SHA,
        diagnostic_period_ns=10.0, no_wns_derived_frequency=True, detailed_simulation_logs_archived=False,
        runs=runs, comparisons=rows, routes=routes, closed_routed_atp=closed,
        STA_closed_actual_rows=actual_closed,
        validation_summaries=validation, candidate_selection=selection, discovery_errors=errors,
        workspace_matches=[run['stage'] for run in matches],
        current_workspace_candidate=[dict(stage=run['stage'], label=run['label'], directory=run['directory'],
            source_manifest_sha256=run['source_manifest_sha256']) for run in matches],
        latest_frozen_candidate=compact(latest or {}, ('stage', 'label', 'directory', 'source_manifest_sha256')),
        nominal_clock_rounding_note='Vivado can quantize nominal 150 MHz to 6.667 ns. '
            'After STA closure that period represents 149.9925 MHz, not exactly 150 MHz. '
            'The strict nominal target test is unchanged. Actual STA closure is reported separately '
            'even when quantization misses the nominal target; failed/incomplete STA yields no closed frequency.')
    # Avoid duplicating large controller state and hashes for every model/vector file.
    data['runs'] = [{k: v for k, v in run.items() if k not in ('tests', 'evidence_validation')}
                    for run in runs]
    lines = ['# C2 基础 SHAKE 时序优化进展', '',
        f'更新时间：{data["updated_at"]}；' + ('当前已发现测量全部结束。' if all_finished else '后台测量继续。'), '',
        '唯一基线为 C2（211601）；旧 B0 不参与本轮比较。聚焦 P12U1／P4U1。'
        '100 MHz 综合仅用于面积、组合路径诊断，不转换为实际 Fmax。'
        '150／130 MHz 等显式目标只有完整布线、DRC、setup／hold 全通过才填写已闭合频率和 ATP；'
        '失败 WNS 不能推算成较低频率已通过。', '',
        '口径：common OOC、xc7a200tffg1156-3、通用 Keccak、统计由 SYNTHESIS 裁剪、默认时序驱动。'
        '每个 Vivado 两线程、最多十二个；不新增时序例外、不搜索频率。'
        '综合超过十分钟只延后分析，后台继续；h20 完整 Keygen／Sign 保持停止。', '',
        '当前工作区匹配冻结 RTL：' + ('、'.join(data['workspace_matches']) or '无完全匹配版本') + '。', '',
        '当前开发候选按工作区源码 SHA 确认；最新冻结候选为 '
        + (f'{latest["stage"]}（{latest["label"]}）' if latest else '尚无')
        + '。报告所在归档固定，不随新候选迁移；最终保留选择另列。', '',
        '| 阶段 | 候选 | Sign通过 | 额外验证 | 源码／基线绑定 | 状态 |', '|---|---|---:|---|---|---|']
    for run in runs:
        extra = [v for v in validation if v['run'] == run['name']]
        extra_text = '、'.join(f'{v["passed"]}/{v["planned"]}（{v["status"]}）' for v in extra) or '—'
        lines += [f'| {run["stage"]} | {run["label"]} | {run["counts"].get("passed", 0)}/6 | '
            f'{extra_text} | {"匹配" if run["source_bound"] else "未匹配"} | '
            f'{"完成" if run["complete"] else "后台运行"} |']
    if selection['present']:
        lines += ['', f'显式候选选择：{selection["stage"] or "未匹配版本"}；源码绑定：'
            f'{"匹配" if selection["source_bound"] else "未确认"}。选择记录见 `{selection_file}`。']
    else:
        lines += ['', '尚无绑定冻结源码的最终候选选择记录。报告不自动替换 RTL。']
    lines += ['', '## 100 MHz 面积与路径诊断', '',
        '| 阶段 | 配置 | LUT | FF | BRAM36 | Slice | 相对C2面积 % | 路径 ns | 级数 | 耗时 s | 状态 |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|']
    for run in runs:
        for config in CONFIGS:
            item = run['synthesis'].get(config, {})
            area, path = item.get('area', {}), item.get('timing', {})
            status = item.get('status', 'pending') + ('／分析延后，后台继续' if item.get('analysis_deferred') else '')
            lines += ['| ' + ' | '.join([run['stage'], config, fmt(area.get('lut'), 0), fmt(area.get('ff'), 0),
                fmt(area.get('bram36')), fmt(area.get('equivalent_slice')),
                fmt(delta(baseline['synthesis'][config]['area']['equivalent_slice'], area.get('equivalent_slice'))),
                fmt(path.get('data_path_ns')), fmt(path.get('logic_levels'), 0), fmt(item.get('elapsed_seconds')), status]) + ' |']
    lines += ['', '| 阶段 | 配置 | 综合路径起点 | 综合路径终点 |', '|---|---|---|---|']
    for run in runs:
        for config in CONFIGS:
            path = run['synthesis'].get(config, {}).get('timing', {})
            lines += [f'| {run["stage"]} | {config} | `{path.get("source", "—")}` | `{path.get("destination", "—")}` |']
    for profile in PROFILES:
        lines += ['', f'## {profile} 完整 Sign', '',
            '| 阶段 | 配置 | 周期 | 相对C2 % | Hash | 置换 | 工作量相同 | 状态 |',
            '|---|---|---:|---:|---:|---:|---|---|']
        for row in rows:
            if row['profile'] == profile:
                equal = '—' if row['workload_equal'] is None else ('是' if row['workload_equal'] else '否')
                lines += ['| ' + ' | '.join([row['stage'], row['configuration'], fmt(row['cycles'], 0),
                    fmt(row['cycles_change_pct'], 6), fmt(row['hashes'], 0), fmt(row['permutations'], 0),
                    equal, row['status']]) + ' |']
    lines += ['', '逐字节输出与签名缓存由冻结测试台检查，Hash／置换次数及向量 SHA 另与 C2 比较。'
        'JSON 保留未舍入结果及假定 100 MHz 的诊断 ATP；其不作为频率或 ATP 验收证据。', '',
        '## 显式目标布线', '',
        '150 MHz 是名义请求值；Vivado 若将实际约束记录为 6.667 ns，STA 闭合后对应的实际频率为 '
        '149.9925 MHz，应按该实际值报告。严格 150 MHz 目标判定保持不变；'
        '尚未完成或未通过 STA 时，已闭合频率与 ATP 继续留空。', '',
        '| 阶段 | 配置 | 目标 MHz | 目标周期 ns | 实际约束 ns | 布线 Slice | WNS ns | WHS ns | 布通 | DRC错误 | 达到目标 | 状态 |',
        '|---|---|---:|---:|---:|---:|---:|---:|---|---:|---|---|']
    for route in routes:
        boolean = lambda value: '—' if value is None else ('是' if value else '否')
        lines += ['| ' + ' | '.join([route['stage'], route['configuration'], fmt(route['target_frequency_mhz']),
            fmt(route['requested_period_ns']), fmt(route['actual_constraint_period_ns']), fmt(route['equivalent_slice']),
            fmt(route['wns_ns']), fmt(route['whs_ns']), boolean(route['complete_routing']),
            fmt(route['drc_errors'], 0), boolean(route['target_verdict']), route['status']]) + ' |']
    lines += ['', '| 阶段 | 配置 | 算法 | 已闭合频率 MHz | Sign时间 ms | 布线ATP Slice·ms | 同目标C2 ATP变化 % |',
        '|---|---|---|---:|---:|---:|---:|']
    for row in closed:
        lines += ['| ' + ' | '.join([row['stage'], row['configuration'], row['profile'],
            fmt(row['measured_closed_frequency_mhz']), fmt(row['routed_time_ms'], 6),
            fmt(row['routed_atp_slice_ms'], 6), fmt(row.get('same_target_c2_routed_atp_change_pct'))]) + ' |']
    if not closed:
        lines += ['| — | — | — | — | — | — | — |', '', '尚无通过严格名义目标的项目；实际约束 STA 闭合结果见下表。']
    lines += ['', '## 按实际约束闭合的 STA 结果', '',
        '下表单独接受完整布通、DRC=0、setup／hold 全通过及源码／工作量绑定的实测。'
        '即使实际 6.667 ns 对应约 149.9925 MHz、未达到严格 150 MHz，也保留其实际频率和 ATP；'
        '严格目标达到列保持“否”。负 WNS、负 hold 或尚未完成的项目不进入此表。', '',
        '| 阶段 | 配置 | 算法 | 名义目标 MHz | 实际周期 ns | STA闭合频率 MHz | 严格目标达到 | 时间 ms | ATP Slice·ms |',
        '|---|---|---|---:|---:|---:|---|---:|---:|']
    for row in actual_closed:
        lines += ['| ' + ' | '.join([row['stage'], row['configuration'], row['profile'],
            fmt(row['nominal_target_mhz']), fmt(row['actual_constraint_period_ns']),
            fmt(row['sta_closed_actual_frequency_mhz'], 4), '是' if row['strict_target_met'] else '否',
            fmt(row['routed_time_ms'], 6), fmt(row['routed_atp_slice_ms'], 6)]) + ' |']
    if not actual_closed:
        lines += ['| — | — | — | — | — | — | — | — | — |']
    lines += ['', '## 额外验证与证据', '']
    for item in validation:
        lines += [f'- {item["stage"] or "未匹配候选"}：{item["passed"]}/{item["planned"]}，'
            f'{item["status"]}；冻结源码绑定 {"匹配" if item["source_bound"] else "未确认"}。{item["scope"] or ""}']
    for error in errors:
        lines += [f'- 候选发现错误：`{error["path"]}`：{error["error"]}']
    for run in runs:
        lines += [f'- {run["stage"]}：`{run["directory"]}`；归档 `{run["archive_directory"]}`。']
    lines += ['', '归档保留冻结 RTL、源码校验、综合和布线报告／日志、验证摘要；仿真明细保留 build。'
        '动态进展报告在全部后台测量结束前列为 volatile，不修改原始测量证据。', '']
    write(prefix.with_suffix('.json'), data)
    archive.atomic(prefix.with_suffix('.md'), '\n'.join(lines))
    return data


def update_artifacts(out, prefix, finished):
    """Keep owned live reports volatile; never bless changed raw measurement bytes."""
    path = out / 'ARTIFACTS.json'
    value = read(path)
    if not value:
        return dict(updated=False, reason='Measurement archive manifest unavailable')
    owned = {str(p.relative_to(out)): p for p in (prefix.with_suffix('.md'), prefix.with_suffix('.json'))
             if p.is_relative_to(out)}
    tool = out / 'analysis_tools/report_c2_timing_optimization.py'
    if tool.is_file():
        owned[str(tool.relative_to(out))] = tool
    indexed = dict(value.get('sha256', {}))
    immutable_errors = []
    if value.get('complete'):
        for name, digest in indexed.items():
            if name in owned or name in value.get('volatile_artifacts', []):
                continue
            item = out / name
            if not item.is_file() or sha(item) != digest:
                immutable_errors.append(name)
    for name in owned:
        indexed.pop(name, None)
    report_names = [str(p.relative_to(out)) for p in (prefix.with_suffix('.md'), prefix.with_suffix('.json'))
                    if p.is_relative_to(out)]
    if tool.is_file():
        indexed[str(tool.relative_to(out))] = sha(tool)
    final = bool(finished and value.get('complete') and not immutable_errors)
    if final:
        indexed.update({name: sha(out / name) for name in report_names})
        value['volatile_artifacts'] = [name for name in value.get('volatile_artifacts', []) if name not in report_names]
        value['comparison_report_status'] = 'finalized'
        value['comparison_report_finalized_at'] = now()
    else:
        value['volatile_artifacts'] = sorted(set(value.get('volatile_artifacts', [])) | set(report_names))
        value['comparison_report_status'] = 'live' if not immutable_errors else 'immutable_evidence_mismatch'
    value.update(sha256=indexed, comparison_report_index_updated_at=now(),
                 comparison_immutable_checksum_errors=immutable_errors)
    write(path, value)
    return dict(updated=True, finalized=final, immutable_checksum_errors=immutable_errors)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--run-root', type=Path, default=ROOT / 'build/c2_timing_optimization')
    parser.add_argument('--output-prefix', type=Path)
    parser.add_argument('--selection-file', type=Path)
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--self-test', action='store_true', help='Run synthetic report-policy checks; no hardware jobs')
    parser.add_argument('--interval', type=float, default=30)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(policy_selftest(), ensure_ascii=False, indent=2))
        return 0
    if not 0 < args.interval <= 30:
        parser.error('--interval must be positive and at most 30 seconds')
    run_root = args.run_root.resolve()
    runs, _ = discover(run_root)
    candidates = [run for run in runs if not run['reference']]
    if not candidates:
        parser.error('No C2-based non-reference candidate found')
    out = Path(candidates[-1]['archive_directory'])
    prefix = (args.output_prefix or out / 'reports/C2_Timing_Progress_20261020').resolve()
    if args.output_prefix:
        owner = next((run for run in candidates if prefix.is_relative_to(Path(run['archive_directory']))), None)
        if owner is None:
            parser.error('--output-prefix must be within a discovered non-reference candidate archive')
        out = Path(owner['archive_directory'])
    archive.copy_changed(Path(__file__).resolve(), out / 'analysis_tools/report_c2_timing_optimization.py')
    selection = (args.selection_file or run_root / 'SELECTION.json').resolve()
    while True:
        data = render(run_root, prefix, selection)
        artifacts = update_artifacts(out, prefix, data['all_measurements_complete'])
        if not args.watch or data['all_measurements_complete']:
            print(json.dumps(dict(report=str(prefix.with_suffix('.md')),
                all_measurements_complete=data['all_measurements_complete'], artifacts=artifacts),
                ensure_ascii=False, indent=2))
            return int(bool(artifacts.get('immutable_checksum_errors')))
        time.sleep(args.interval)


if __name__ == '__main__':
    raise SystemExit(main())
