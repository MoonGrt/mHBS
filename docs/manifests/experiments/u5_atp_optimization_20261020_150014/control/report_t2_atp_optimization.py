#!/usr/bin/env python3
"""Publish source-bound U-numbered comparisons with T2; launch no hardware jobs.

All new ATP numbers use measured common synthesis area and an explicitly assumed
100 MHz. No new routing is requested and no measured candidate clock is inferred
from a synthesis path. --watch only refreshes Markdown/JSON and artifact hashes.
"""
import argparse
import json
import os
from pathlib import Path
import re
import time

import run_t2_atp_optimization as measure

ROOT = measure.ROOT
OUT = ROOT / 'docs/manifests/experiments/t2_atp_optimization_20261020_135654'
PREFIX = OUT / 'reports/T2_ATP_Progress_20261020'
read, write, sha, require = measure.read, measure.write, measure.sha, measure.require


def discover_runs():
    runs = {}
    for path in sorted((ROOT / 'build/t2_atp_optimization').glob('candidate_*')):
        if not (path / 'SOURCE.json').is_file():
            continue
        meta = read(path / 'SOURCE.json')
        match = re.match(r'(U[1-9]\d*)_', meta.get('label', ''))
        if match and meta.get('schema') == measure.SCHEMA:
            label = match[1]
            require(label not in runs, f'Duplicate candidate label: {label}')
            runs[label] = path
    return dict(sorted(runs.items(), key=lambda pair: int(pair[0][1:])))


def candidate(label, run, baseline):
    meta, state = read(run / 'SOURCE.json'), read(run / 'status.json')
    identity = sha(run / 'SOURCE.json')
    require(meta.get('schema') == measure.SCHEMA and meta['label'].startswith(label + '_'),
            f'Unexpected candidate identity: {run}')
    require(meta.get('baseline_manifest_sha256') == measure.BASELINE_SHA
        and meta.get('hash_backend') == 'shake' and meta.get('top') == 'common'
        and meta.get('part') == 'xc7a200tffg1156-3' and meta.get('synthesis_period_ns') == 10.0,
        f'Different baseline or measurement scope: {run}')
    unchanged = measure.core.previous.unchanged(meta)
    value = dict(label=label, run=str(run), source=meta, source_manifest_sha256=identity,
        source_unchanged=unchanged, complete=state.get('complete', False),
        tests={}, synthesis={}, comparisons=[], validation=None,
        measured_candidate_frequency_mhz=None, measured_candidate_routed_atp=None)
    require(unchanged, f'Frozen source changed: {run}')
    for config, item in state['synthesis'].items():
        value['synthesis'][config] = item
        if item['status'] != 'passed':
            continue
        folder = run / 'synth' / config
        require(item.get('source_manifest_sha256') == identity
            and item.get('source_unchanged') is True,
            f'Unbound synthesis: {label}/{config}')
        for name, digest in item['reports_sha256'].items():
            require((folder / name).is_file() and sha(folder / name) == digest,
                    f'Changed synthesis report: {label}/{config}/{name}')
        require(item['area'] == measure.core.utilization(folder / 'utilization.rpt')
            and item['timing'] == measure.core.timing(folder / 'timing.rpt'),
            f'Changed synthesis interpretation: {label}/{config}')
    for key, item in state['tests'].items():
        value['tests'][key] = item
        if item['status'] != 'passed':
            continue
        old = baseline['results']['tests'][key]
        require(item.get('source_manifest_sha256') == identity
            and item.get('source_unchanged') is True
            and item.get('output_and_signature_cache_checked_bytewise') is True
            and Path(item['log']).is_file() and sha(Path(item['log'])) == item['log_sha256'],
            f'Unbound Sign: {label}/{key}')
        match = measure.core.PASS.search(Path(item['log']).read_text(errors='replace'))
        require(match is not None and int(match[2]) == item['cycles'],
                f'Changed measured cycles: {label}/{key}')
        equal = all(item[k] == old[k] for k in ('hashes', 'permutations', 'vectors_sha256'))
        require(equal, f'Changed workload: {label}/{key}')
        config, profile = key.split('/')
        row = dict(label=label, configuration=config, profile=profile, cycles=item['cycles'],
            baseline_cycles=old['cycles'], workload_equal=True, status='passed',
            hashes=item['hashes'], permutations=item['permutations'],
            cycles_change_pct=100 * (item['cycles'] / old['cycles'] - 1),
            assumed_frequency_mhz=100.0, measured_frequency_mhz=None, routed_atp_slice_ms=None)
        row['diagnostic_time_ms_at_100mhz'] = item['cycles'] / 100000
        syn = state['synthesis'][config]
        if syn['status'] == 'passed':
            area = syn['area']['equivalent_slice']
            old_area = baseline['results']['synthesis'][config]['area']['equivalent_slice']
            row.update(equivalent_slice=area, baseline_equivalent_slice=old_area,
                area_change_pct=100 * (area / old_area - 1),
                diagnostic_time_ms_at_100mhz=item['cycles'] / 100000,
                diagnostic_atp_slice_ms_at_100mhz=area * item['cycles'] / 100000,
                diagnostic_atp_change_pct=100 * (area * item['cycles'] / (old_area * old['cycles']) - 1))
        value['comparisons'].append(row)
    validation = run / 'functional_validation/VALIDATION.json'
    if validation.is_file():
        proof = read(validation)
        require(proof.get('source_manifest_sha256') == identity
            and proof.get('source_unchanged') is True
            and proof.get('rtl_sha256') == {k: v for k, v in meta['sha256'].items() if k.startswith('rtl/')},
            f'Unbound supplemental validation: {label}')
        if proof.get('complete'):
            require(proof.get('passed', 0) + proof.get('failed', 0) == 76,
                    f'Incomplete supplemental validation: {label}')
            for test in proof['tests']:
                log = Path(test['log'])
                require(log.is_file() and sha(log) == test['log_sha256'],
                        f'Changed supplemental log: {label}/{test["name"]}')
        value['validation'] = {k: proof.get(k) for k in
            ('status', 'complete', 'passed', 'failed', 'total_planned', 'elapsed_seconds',
             'source_manifest_sha256', 'source_unchanged')}
    return value


def publish(expected_candidates=0):
    baseline = measure.checked_baseline()
    runs = discover_runs()
    data = dict(schema='mhbs.t2_atp_progress.v1', updated_at=measure.now(),
        baseline_manifest_sha256=measure.BASELINE_SHA,
        baseline_run=str(measure.BASELINE_RUN), assumed_frequency_mhz=100.0,
        diagnostic_only=True, measured_candidate_frequency_mhz=None,
        candidate_routing_requested=False, candidates={}, evidence_errors={})
    data['baseline_synthesis'] = baseline['results']['synthesis']
    data['baseline_sign'] = baseline['results']['tests']
    for label, run in runs.items():
        if not (run / 'SOURCE.json').is_file() or not (run / 'status.json').is_file():
            data['candidates'][label] = dict(label=label, run=str(run), status='not_started')
            continue
        try:
            data['candidates'][label] = candidate(label, run, baseline)
        except Exception as error:
            data['evidence_errors'][label] = str(error)
            data['candidates'][label] = dict(label=label, run=str(run), status='evidence_rejected')
    data['complete'] = (len(data['candidates']) >= max(1, expected_candidates) and not data['evidence_errors']
        and all(v.get('complete') and (v.get('validation') or {}).get('complete')
                for v in data['candidates'].values()))
    best = {}
    for p in measure.CONFIGS:
        config = f'P{p}U1'
        best[config] = {}
        for profile in measure.PROFILES:
            old = baseline['results']['tests'][f'{config}/{profile}']
            old_area = baseline['results']['synthesis'][config]['area']['equivalent_slice']
            eligible = [dict(label='T2', atp_slice_ms=old_area * old['cycles'] / 100000)]
            for label, value in data['candidates'].items():
                validation = value.get('validation') or {}
                if validation.get('passed') != 76 or validation.get('failed') != 0:
                    continue
                for item in value.get('comparisons', []):
                    if (item['configuration'] == config and item['profile'] == profile
                            and 'diagnostic_atp_slice_ms_at_100mhz' in item):
                        eligible.append(dict(label=label,
                            atp_slice_ms=item['diagnostic_atp_slice_ms_at_100mhz']))
            best[config][profile] = min(eligible, key=lambda item: item['atp_slice_ms'])
    data['diagnostic_atp_best_at_assumed_100mhz'] = best
    selection_file = ROOT / 'build/t2_atp_optimization/WORKSPACE_SELECTION.json'
    if selection_file.is_file():
        selection = read(selection_file)
        selected_manifest = Path(selection['candidate_run']) / 'SOURCE.json'
        require(sha(selected_manifest) == selection['source_manifest_sha256'],
                'Workspace selection is not bound to the frozen candidate')
        data['workspace_selection'] = selection
        data['workspace_selection_record_sha256'] = sha(selection_file)
        data['workspace_matches_selected_rtl'] = all(sha(ROOT / name) == digest
            for name, digest in selection['rtl_sha256'].items())
    write(PREFIX.with_suffix('.json'), data)
    fmt = lambda value: '—' if value is None else f'{value:,.3f}'
    row = lambda values: '| ' + ' | '.join(map(str, values)) + ' |'
    lines = ['# T2 基础面积与延迟优化进展', '', f'更新时间：{data["updated_at"]}。', '',
        '统一比较冻结 T2（20261020_115729），全部面积取对应 P/U 的 common OOC、'
        '100 MHz 综合，器件 xc7a200tffg1156-3、通用 Keccak、默认时序驱动、无新增时序例外。'
        '所有周期来自完整 Sign 实测，输出与签名缓存逐字节核对，Hash/置换计数和向量校验一致。', '',
        '**本轮未进行布线。以下 ATP 全部为假设 100 MHz 的辅助指标，不能作为实际频率或布线 ATP 验收。**'
        '关键路径为综合诊断路径，不能据此声称频率提高。T2 历史布线两配置在实际 6.667 ns'
        '（149.992500 MHz）下闭合，但本轮候选的实测频率和布线 ATP 保持空白。', '',
        'U1：提前登记返回路径控制；U2：U1 加执行器平坦写回选择和所有者预计算；'
        'U3：U2 加删除重复 512 位容量寄存器；U4：U3 加提前登记响应优先队首；'
        'U5：U4 加滚动链调度使用已登记活动位，拆开同拍退休到重发的控制环，允许少量周期增加。', '',
        '| 候选 | 配置 | LUT | FF | BRAM36 | 等效 Slice | 对T2面积% | 诊断路径 ns | 级数 | 综合耗时 s | 本轮实测 MHz | 补充验证 | 状态 |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|']
    for config, item in baseline['results']['synthesis'].items():
        area, path = item['area'], item['timing']
        lines.append(row(['T2', config, *[fmt(area.get(k)) for k in ('lut', 'ff', 'bram36', 'equivalent_slice')],
            '0.000', fmt(path.get('data_path_ns')), fmt(path.get('logic_levels')),
            fmt(item.get('elapsed_seconds')), '—', '历史基线', 'passed']))
    for label, value in data['candidates'].items():
        validation = value.get('validation') or {}
        valid = f'{validation.get("passed", 0)}/76' if validation else '—'
        if validation.get('failed'):
            valid += f'，失败{validation["failed"]}'
        for p in measure.CONFIGS:
            config = f'P{p}U1'
            item = value.get('synthesis', {}).get(config, {})
            area, path = item.get('area', {}), item.get('timing', {})
            old_area = baseline['results']['synthesis'][config]['area']['equivalent_slice']
            delta = 100 * (area['equivalent_slice'] / old_area - 1) if area else None
            status = item.get('status', value.get('status', 'pending'))
            if item.get('analysis_deferred'):
                status += '／分析延后，后台继续'
            lines.append(row([label, config, *[fmt(area.get(k)) for k in ('lut', 'ff', 'bram36', 'equivalent_slice')],
                fmt(delta), fmt(path.get('data_path_ns')), fmt(path.get('logic_levels')),
                fmt(item.get('elapsed_seconds')), '—', valid, status]))
    for profile in ('slh_128f', 'xmss_h10', 'lms_h10'):
        lines += ['', f'## {profile} 完整 Sign', '',
            '| 候选 | 配置 | 周期 | 对T2周期% | 假设100MHz时间 ms | 假设100MHz ATP Slice·ms | 对T2 ATP% | 本轮布线ATP | 状态 |',
            '|---|---|---:|---:|---:|---:|---:|---:|---|']
        for p in measure.CONFIGS:
            config = f'P{p}U1'
            old = baseline['results']['tests'][f'{config}/{profile}']
            area = baseline['results']['synthesis'][config]['area']['equivalent_slice']
            lines.append(row(['T2', config, old['cycles'], '0.000', fmt(old['cycles'] / 100000),
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
    lines += ['', '每候选另有 76 组冻结源码验证：正常/SYNTHESIS 配方与批次 KAT、P1/P2/P6兼容、'
        '六组 SLH Verify、三算法停顿/乱序/重放/复位/截断/篡改/故障、SHA2兼容和现有 h20 Verify。'
        '不执行 h20 完整 Keygen/Sign；详细日志保留 build，归档只保存摘要和校验。', '',
        '候选通过、失败或回退均保留。工作区选择由最终源码选择记录说明，汇总脚本不替换 RTL。', '']
    if all(data['candidates'].get(label, {}).get('complete') for label in ('U4', 'U5')):
        lines += ['U4／U5 取舍：U4 保留为 P12U1 固定 100 MHz ATP 对照。U5 的 P12U1'
            '只比 U4 少 6.5 Slice，周期增加使其固定频率 ATP 略高；其诊断路径从 U4 的'
            '6.123 ns 降为 5.259 ns，也低于 T2 的 5.575 ns。P4U1 的 U5 面积、诊断路径和'
            '假定 ATP 同时改善。因此 U5 是兼顾两配置的待布线候选；实际物理闭合基线仍为 T2，'
            '候选物理频率及实际 ATP 尚未验证。', '']
    lines.append('已完成且补充验证通过的固定 100 MHz ATP 最低项（按未舍入数值）：')
    lines.append('')
    for config, items in best.items():
        winners = '；'.join(f'{profile}={item["label"]}' for profile, item in items.items())
        lines.append(f'- {config}：{winners}。')
    lines.append('')
    if data.get('workspace_selection'):
        selection = data['workspace_selection']
        lines += [f'工作区保留 `{selection["candidate"]}`，源码清单 SHA256：'
            f'`{selection["source_manifest_sha256"]}`。这是待布线候选，实际物理频率尚未验证；'
            f'工作区十个 RTL 与冻结选择一致：{data["workspace_matches_selected_rtl"]}。'
            '[选择记录](../analysis_evidence/WORKSPACE_SELECTION.json)。', '']
    for label, run in runs.items():
        archive = ROOT / 'docs/manifests/experiments' / ('t2_atp_optimization_' + run.name.removeprefix('candidate_'))
        target = os.path.relpath(archive / 'reports' / ('T2_ATP_Optimization_' + run.name.removeprefix('candidate_') + '.md'), PREFIX.parent)
        lines.append(f'- {label}：[测量报告]({target})；源码清单 `{archive / "SOURCE.json"}`。')
    for label, error in data['evidence_errors'].items():
        lines.append(f'- **{label} 证据拒绝**：{error}。该候选数值留空。')
    measure.core.archive.atomic(PREFIX.with_suffix('.md'), '\n'.join(lines) + '\n')
    controls = OUT / 'analysis_tools'
    measure.core.archive.copy_changed(Path(__file__), controls / Path(__file__).name)
    write(controls / 'REPORT_TOOL_SOURCE.json', dict(script=Path(__file__).name,
        sha256=sha(Path(__file__)), baseline_manifest_sha256=measure.BASELINE_SHA,
        candidate_source_manifests={k: v.get('source_manifest_sha256') for k, v in data['candidates'].items()}))
    artifacts = OUT / 'ARTIFACTS.json'
    if artifacts.is_file():
        archive_data = read(artifacts)
        archive_data['sha256'] = {str(p.relative_to(OUT)): sha(p)
            for p in OUT.rglob('*') if p.is_file() and p.name != 'ARTIFACTS.json'
            and not p.name.endswith('.tmp')}
        write(artifacts, archive_data)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--interval', type=float, default=30.0)
    parser.add_argument('--expected-candidates', type=int, default=0,
                        help='Keep --watch alive until at least this many candidates exist and finish')
    args = parser.parse_args()
    require(args.interval >= 5, 'Refresh interval must be at least five seconds')
    while True:
        data = publish(args.expected_candidates)
        print(json.dumps(dict(updated_at=data['updated_at'], complete=data['complete'],
            evidence_errors=data['evidence_errors'], report=str(PREFIX.with_suffix('.md')))), flush=True)
        if not args.watch or data['complete']:
            return int(bool(data['evidence_errors']))
        time.sleep(args.interval)


if __name__ == '__main__':
    raise SystemExit(main())
