#!/usr/bin/env python3
"""Publish source-bound V-numbered U5 comparisons; launch no hardware jobs."""
import argparse
import json
import os
from pathlib import Path
import re
import time

import run_u5_atp_optimization as measure
import report_t2_atp_optimization as shared

# Reuse the existing read-only, source/log/report-bound candidate validator.
# Its old publish() entry point is never called, and old reports are untouched.
shared.measure = measure
ROOT = measure.ROOT
read, write, sha, require = measure.read, measure.write, measure.sha, measure.require


def discover_runs():
    runs = {}
    for path in sorted((ROOT / 'build/u5_atp_optimization').glob('candidate_*')):
        if (path / 'LAUNCH_FAILED.json').is_file():
            continue
        if not (path / 'SOURCE.json').is_file():
            continue
        meta = read(path / 'SOURCE.json')
        match = re.match(r'(V[1-9]\d*)_', meta.get('label', ''))
        if match and meta.get('schema') == measure.SCHEMA:
            require(match[1] not in runs, f'Duplicate candidate label: {match[1]}')
            runs[match[1]] = path
    return dict(sorted(runs.items(), key=lambda pair: int(pair[0][1:])))


def publish(expected_candidates=0):
    baseline, runs = measure.checked_baseline(), discover_runs()
    require(runs, 'Launch a frozen candidate before publishing')
    first = min(runs.values())
    out = Path(read(first / 'SOURCE.json')['archive_directory'])
    prefix = out / 'reports/U5_ATP_Progress_20261020'
    data = dict(schema='mhbs.u5_atp_progress.v1', updated_at=measure.now(),
        baseline_manifest_sha256=measure.BASELINE_SHA, baseline_run=str(measure.BASELINE_RUN),
        assumed_frequency_mhz=100.0, diagnostic_only=True, measured_candidate_frequency_mhz=None,
        candidate_routing_requested=False, candidates={}, evidence_errors={},
        baseline_synthesis=baseline['results']['synthesis'], baseline_sign=baseline['results']['tests'])
    for label, run in runs.items():
        if not (run / 'status.json').is_file():
            data['candidates'][label] = dict(label=label, run=str(run), status='not_started')
            continue
        try:
            meta = read(run / 'SOURCE.json')
            require(meta.get('route_requested') is False and not meta.get('route_frequencies_mhz'),
                    f'Unexpected routing request: {label}')
            require(not read(run / 'status.json').get('routing'), f'Unexpected routing results: {label}')
            data['candidates'][label] = shared.candidate(label, run, baseline)
        except Exception as error:
            data['evidence_errors'][label] = str(error)
            data['candidates'][label] = dict(label=label, run=str(run), status='evidence_rejected')
    data['complete'] = (len(runs) >= max(1, expected_candidates) and not data['evidence_errors']
        and all(v.get('complete') and (v.get('validation') or {}).get('complete')
                for v in data['candidates'].values()))
    data['totals'] = dict(candidates=len(runs),
        measured_sign_passed=sum(t.get('status') == 'passed' for value in data['candidates'].values()
                                 for t in value.get('tests', {}).values()),
        supplemental_validation_passed=sum((value.get('validation') or {}).get('passed', 0)
                                           for value in data['candidates'].values()),
        diagnostic_synthesis_passed=sum(t.get('status') == 'passed' for value in data['candidates'].values()
                                        for t in value.get('synthesis', {}).values()),
        routing_jobs=0)
    best = {}
    for p in measure.CONFIGS:
        config = f'P{p}U1'
        best[config] = {}
        for profile in measure.PROFILES:
            old = baseline['results']['tests'][f'{config}/{profile}']
            old_area = baseline['results']['synthesis'][config]['area']['equivalent_slice']
            eligible = [dict(label='U5', atp_slice_ms=old_area * old['cycles'] / 100000)]
            for label, value in data['candidates'].items():
                validation = value.get('validation') or {}
                if validation.get('passed') != 76 or validation.get('failed') != 0:
                    continue
                eligible += [dict(label=label, atp_slice_ms=item['diagnostic_atp_slice_ms_at_100mhz'])
                    for item in value.get('comparisons', []) if item['configuration'] == config
                    and item['profile'] == profile and 'diagnostic_atp_slice_ms_at_100mhz' in item]
            best[config][profile] = min(eligible, key=lambda item: item['atp_slice_ms'])
    data['diagnostic_atp_best_at_assumed_100mhz'] = best
    selection_file = ROOT / 'build/u5_atp_optimization/WORKSPACE_SELECTION.json'
    if selection_file.is_file():
        selection = read(selection_file)
        require(sha(Path(selection['candidate_run']) / 'SOURCE.json') == selection['source_manifest_sha256'],
                'Unbound workspace selection')
        data.update(workspace_selection=selection, workspace_selection_record_sha256=sha(selection_file),
            workspace_matches_selected_rtl=all(sha(ROOT / name) == digest
                for name, digest in selection['rtl_sha256'].items()))
    write(prefix.with_suffix('.json'), data)
    fmt = lambda value: '—' if value is None else f'{value:,.3f}'
    row = lambda values: '| ' + ' | '.join(map(str, values)) + ' |'
    lines = ['# U5 基础面积与延迟优化进展', '', f'更新时间：{data["updated_at"]}。', '',
        '统一比较冻结U5（20261020_140547）。面积取对应P/U的common OOC、100 MHz综合，'
        '器件xc7a200tffg1156-3、通用Keccak、默认时序驱动、无新增时序例外。'
        '完整Sign实测并逐字节核对输出／签名缓存，核对Hash、置换和向量校验。', '',
        '**本轮未进行布线。U5也没有物理频率证据，实际频率与布线ATP均未知。**'
        '以下ATP全部假设100 MHz，仅为辅助比较；综合关键路径不能证明实际频率提高。'
        '慢综合留在后台，超过10分钟仅延后分析。', '',
        '| 候选 | 配置 | LUT | FF | BRAM36 | 等效Slice | 对U5面积% | 诊断路径ns | 级数 | 综合耗时s | 补充验证 | 状态 |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|']
    values = [('U5', dict(synthesis=baseline['results']['synthesis']))] + list(data['candidates'].items())
    for label, value in values:
        validation = value.get('validation') or {}
        valid = '历史76/76' if label == 'U5' else (f'{validation.get("passed", 0)}/76' if validation else '—')
        for p in measure.CONFIGS:
            config = f'P{p}U1'
            item = value.get('synthesis', {}).get(config, {})
            area, path = item.get('area', {}), item.get('timing', {})
            old = baseline['results']['synthesis'][config]['area']['equivalent_slice']
            delta = 100 * (area['equivalent_slice'] / old - 1) if area else None
            status = item.get('status', value.get('status', 'pending'))
            if item.get('analysis_deferred'):
                status += '／分析延后，后台继续'
            lines.append(row([label, config, *[fmt(area.get(k)) for k in ('lut', 'ff', 'bram36', 'equivalent_slice')],
                fmt(delta), fmt(path.get('data_path_ns')), fmt(path.get('logic_levels')),
                fmt(item.get('elapsed_seconds')), valid, status]))
    for profile in ('slh_128f', 'xmss_h10', 'lms_h10'):
        lines += ['', f'## {profile} 完整 Sign', '',
            '| 候选 | 配置 | 周期 | 对U5周期% | 假设100MHz时间ms | 假设ATP Slice·ms | 对U5 ATP% | 本轮布线ATP | 状态 |',
            '|---|---|---:|---:|---:|---:|---:|---:|---|']
        for p in measure.CONFIGS:
            config = f'P{p}U1'
            old = baseline['results']['tests'][f'{config}/{profile}']
            area = baseline['results']['synthesis'][config]['area']['equivalent_slice']
            lines.append(row(['U5', config, old['cycles'], '0.000', fmt(old['cycles'] / 100000),
                fmt(area * old['cycles'] / 100000), '0.000', '—', 'passed']))
        for label, value in data['candidates'].items():
            for p in measure.CONFIGS:
                config = f'P{p}U1'
                item = next((v for v in value.get('comparisons', [])
                    if v['configuration'] == config and v['profile'] == profile), {})
                test = value.get('tests', {}).get(f'{config}/{profile}', {})
                lines.append(row([label, config, item.get('cycles', '—'), fmt(item.get('cycles_change_pct')),
                    fmt(item.get('diagnostic_time_ms_at_100mhz')), fmt(item.get('diagnostic_atp_slice_ms_at_100mhz')),
                    fmt(item.get('diagnostic_atp_change_pct')), '—', test.get('status', value.get('status', 'pending'))]))
    lines += ['', '每候选补充执行76组冻结源码验证，覆盖正常/SYNTHESIS配方及批次、P1/P2/P6兼容、'
        '六组SLH Verify、停顿/乱序/重放/复位/截断/篡改/故障、SHA2兼容及已有h20 Verify。'
        'h20完整Keygen/Sign保持停止；详细仿真日志仅留build，归档保留摘要及SHA。', '',
        '通过、失败或回退候选均保留。已完成且验证通过的假设100 MHz最低ATP项：', '']
    for config, items in best.items():
        lines.append(f'- {config}：' + '；'.join(f'{profile}={item["label"]}' for profile, item in items.items()) + '。')
    if data.get('workspace_selection'):
        selection = data['workspace_selection']
        lines += ['', f'工作区选择`{selection["candidate"]}`，与冻结RTL一致：'
            f'{data["workspace_matches_selected_rtl"]}；物理频率尚未验证。', '']
        selected = data['candidates'].get(selection['candidate'].split('_', 1)[0], {})
        for config, item in selected.get('synthesis', {}).items():
            old_path = baseline['results']['synthesis'][config]['timing']['data_path_ns']
            path = item.get('timing', {}).get('data_path_ns')
            if path is not None:
                change = 100 * (path / old_path - 1)
                lines.append(f'- {config}综合诊断路径：{old_path:.3f}→{path:.3f} ns（{change:+.2f}%）。')
        if 'V2' in data['candidates']:
            lines += ['', 'V2单独保留为P4U1假设100 MHz ATP较低的源码对照；所选候选的'
                'P12U1／P4U1结果均采用同一份冻结RTL。P4诊断路径回退保留为限制；'
                '综合路径不能证明实际频率，实际频率及布线ATP仍未知。', '']
    totals = data['totals']
    lines += ['', f'本轮有效候选{totals["candidates"]}个：主测完整Sign通过'
        f'{totals["measured_sign_passed"]}项，补充验证通过{totals["supplemental_validation_passed"]}组，'
        f'100 MHz综合通过{totals["diagnostic_synthesis_passed"]}项；布线任务0。', '']
    lines.append('')
    for label, run in runs.items():
        archive = Path(read(run / 'SOURCE.json')['archive_directory'])
        target = os.path.relpath(archive / 'reports' / ('U5_ATP_Optimization_' + run.name.removeprefix('candidate_') + '.md'), prefix.parent)
        lines.append(f'- {label}：[测量报告]({target})。')
    for label, error in data['evidence_errors'].items():
        lines.append(f'- **{label}证据拒绝**：{error}。候选数值留空。')
    measure.core.archive.atomic(prefix.with_suffix('.md'), '\n'.join(lines) + '\n')
    tools = out / 'analysis_tools'
    for tool in (Path(__file__), Path(shared.__file__)):
        measure.core.archive.copy_changed(tool, tools / tool.name)
    write(tools / 'REPORT_TOOL_SOURCE.json', dict(scripts={tool.name: sha(tool)
        for tool in (Path(__file__), Path(shared.__file__))}, baseline_manifest_sha256=measure.BASELINE_SHA,
        candidate_source_manifests={k: v.get('source_manifest_sha256') for k, v in data['candidates'].items()}))
    artifacts = out / 'ARTIFACTS.json'
    if artifacts.is_file():
        archived = read(artifacts)
        archived['sha256'] = {str(p.relative_to(out)): sha(p) for p in out.rglob('*')
            if p.is_file() and p.name != 'ARTIFACTS.json' and not p.name.endswith('.tmp')}
        write(artifacts, archived)
    return dict(data, report=str(prefix.with_suffix('.md')))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--interval', type=float, default=30)
    parser.add_argument('--expected-candidates', type=int, default=0)
    args = parser.parse_args()
    require(args.interval >= 5, 'Refresh interval must be at least five seconds')
    while True:
        data = publish(args.expected_candidates)
        print(json.dumps({k: data[k] for k in ('updated_at', 'complete', 'evidence_errors', 'report')}), flush=True)
        if not args.watch or data['complete']:
            return int(bool(data['evidence_errors']))
        time.sleep(args.interval)


if __name__ == '__main__':
    raise SystemExit(main())
