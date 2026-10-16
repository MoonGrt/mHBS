#!/usr/bin/env python3
"""Measure new SHAKE candidates against the exact frozen S4, without job changes.

First use --launch-candidate (six full Sign tests and two 100-MHz common
syntheses). After examining those results, explicitly use --route-existing RUN
--route-mhz 150 155 160. No routing, frequency search, process termination, h20
full-tree tests or INDEX edits are implicit. --inspect-baseline is read-only.

The shared C2 job engine supplies source freezing, bytewise Sign checks, two
threads per Vivado and the twelve-process capacity limit. STA closure at Vivado's
actual clock and strict satisfaction of the requested frequency are separate:
6.667 ns may pass STA while missing an exact 150-MHz request. Only actual STA
closure qualifies for routed ATP; its actual clock, never the requested clock or
a frequency inferred from slack, is used.
"""
import argparse
from datetime import datetime
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from zoneinfo import ZoneInfo

import run_c2_timing_optimization as core

ROOT = Path(os.environ.get('MHBS_S4_TIMING_WORKSPACE', core.ROOT)).resolve()
core.archive.ROOT = ROOT
core.archive.ARCHIVES = ROOT / 'docs/manifests/experiments'
SCHEMA = 's4_shake_timing_optimization_v1'
BASELINE_RUN = ROOT / 'build/r5_timing_optimization/candidate_20261020_110957'
BASELINE_SHA = 'ba124444f1084d76ee7db167121a0d52f21138a3bc2f5f7c425bd05c596bdfe4'
BASELINE_ROUTES = {
    # actual period, setup slack, hold slack, routed equivalent Slice
    'P12U1_150MHz': (6.667, -0.063, 0.119, 16068.625),
    'P12U1_140MHz': (7.143, 0.078, 0.130, 16051.250),
    'P12U1_135MHz': (7.407, 0.123, 0.094, 16052.000),
    'P4U1_150MHz': (6.667, 0.014, 0.096, 9989.750),
    'P4U1_140MHz': (7.143, 0.134, 0.094, 9967.750),
    'P4U1_135MHz': (7.407, 0.180, 0.068, 9964.625),
}
CONTROLS = ('run_s4_timing_optimization.py', *core.CONTROLS)
CONFIGS, PROFILES = core.CONFIGS, core.PROFILES
read, write, require, sha, now = core.read, core.write, core.require, core.sha, core.now


def route_assessment(item):
    """Preserve exact-target status while recognizing real, source-bound closure."""
    result = item.get('result', {})
    period = result.get('actual_period_ns')
    closed = (item.get('source_unchanged') is True
        and item.get('source_manifest_sha256') is not None
        and result.get('setup_hold_met') is True and result.get('drc_errors') == 0
        and result.get('wns_ns', -1) >= 0 and result.get('whs_ns', -1) >= 0
        and item.get('route_status', {}).get('passed') is True
        and isinstance(period, (int, float)) and math.isfinite(period) and period > 0)
    target = item.get('target_frequency_mhz')
    strict = bool(closed and target and period <= 1000 / target + 1e-6)
    return dict(sta_closed=bool(closed), strict_target_met=strict,
        actual_clock_frequency_mhz=1000 / period if closed else None,
        quantization_only_target_miss=bool(closed and not strict
            and 0 < period - 1000 / target <= 0.000500001))


def best_closed(routes, config):
    eligible = [(name, item) for name, item in routes.items()
                if item.get('configuration') == config and route_assessment(item)['sta_closed']]
    require(eligible, f'No actual STA-closed baseline for {config}')
    return min(eligible, key=lambda pair: pair[1]['area']['equivalent_slice']
               * pair[1]['result']['actual_period_ns'])


def checked_baseline():
    """Bind six measured Sign, two diagnostics and all six S4 routed reports."""
    require(sha(BASELINE_RUN / 'SOURCE.json') == BASELINE_SHA,
            'Only frozen S4/20261020_110957 is accepted as the comparison baseline')
    evidence = core.checked_evidence(BASELINE_RUN)
    evidence.update(label='S4', comparison_parent_baselines_ignored=True)
    routes, hashes = evidence['results']['routing'], {}
    require(len(routes) == 6, 'S4 must have all six measured routing results')
    for p in CONFIGS:
        for frequency in (150, 140, 135):
            name = core.route_name(p, frequency)
            item, folder = routes[name], BASELINE_RUN / 'route' / name
            result = read(folder / 'result.json')
            require((result['actual_period_ns'], result['wns_ns'], result['whs_ns'],
                item['area']['equivalent_slice']) == BASELINE_ROUTES[name],
                f'S4 baseline measured clock/slack/area changed: {name}')
            require(item.get('source_manifest_sha256') == BASELINE_SHA
                and item.get('source_unchanged') is True and item['result'] == result
                and item['route_status'] == core.route_status(folder / 'route/route_status.rpt')
                and item['area'] == core.utilization(folder / 'route/utilization.rpt')
                and item['timing'] == core.timing(folder / 'route/timing.rpt')
                and sha(folder / 'route/routed.dcp') == item['routed_checkpoint_sha256'],
                f'Changed or unbound S4 routed evidence: {name}')
            assessment = route_assessment(item)
            expected_closed = not (p == 12 and frequency == 150)
            expected_strict = frequency == 135
            require(assessment['sta_closed'] is expected_closed
                and assessment['strict_target_met'] is expected_strict
                and item['meets_target'] is expected_strict
                and item['status'] == ('passed' if expected_strict else 'target_not_met')
                and (result['wns_ns'] >= 0) is expected_closed
                and result['whs_ns'] >= 0 and result['drc_errors'] == 0
                and item['route_status']['passed'] is True,
                f'S4 measured closure/quantization status changed: {name}')
            settings = (folder / 'settings.txt').read_text().splitlines()
            for setting in (f'PIPELINE={p}', 'UNROLL=1', 'top=common',
                    f'frequency_mhz={frequency}.0', 'hash_backend=shake', 'threads=2',
                    'part=xc7a200tffg1156-3', 'mode=out_of_context', 'keccak=generic',
                    'timing_driven=default', 'new_timing_exceptions=none', 'frequency_search=none'):
                require(setting in settings, f'S4 route setting mismatch: {name}/{setting}')
            for file in ('result.json', 'settings.txt', 'target_clock.xdc', 'vivado.log',
                    'route/hierarchical.rpt', 'route/timing.rpt', 'route/critical_paths.rpt',
                    'route/utilization.rpt', 'route/route_status.rpt', 'route/drc.rpt'):
                require((folder / file).is_file(), f'Missing S4 routed evidence: {name}/{file}')
                hashes[f'{name}/{file}'] = sha(folder / file)
            item.update(assessment)
    evidence.update(routed_reports_sha256=hashes, route_evidence_validated=True,
        baseline_best_closed_tasks={f'P{p}U1': best_closed(routes, f'P{p}U1')[0] for p in CONFIGS},
        checked_at=now())
    return evidence


class Runner(core.Runner):
    """Keep the measured-job engine; specialize source identity and reporting."""
    def __init__(self, run, routes_only=False):
        self.run = Path(run).resolve()
        self.meta = read(self.run / 'SOURCE.json')
        require(self.meta.get('schema') == SCHEMA and self.meta.get('hash_backend') == 'shake',
                'Not an S4 timing optimization run')
        self.source, self.out = Path(self.meta['source_root']), Path(self.meta['archive_directory'])
        self.baseline = read(self.run / 'S4_BASELINE_EVIDENCE.json')
        require(self.baseline['manifest_sha256'] == BASELINE_SHA
            and sha(self.run / 'S4_BASELINE_EVIDENCE.json') == self.meta['baseline_evidence_sha256'],
            'Frozen S4 baseline evidence changed')
        self.lock, self.capacity_lock, self.reserved = threading.RLock(), threading.Lock(), 0
        self.routes_only = routes_only
        if routes_only:
            self.state = read(self.run / 'status.json')
            require(self.state.get('complete') and self.validated(),
                    'Routes require completed same-workload Sign and diagnostic synthesis')
            request = read(self.run / 'ROUTE_REQUEST.json')
            require(request['source_manifest_sha256'] == sha(self.run / 'SOURCE.json'),
                    'Routing is not bound to this frozen candidate')
            self.targets = request['frequencies_mhz']
            self.state.update(complete=False, pid=os.getpid(), routing_started_at=now())
        else:
            self.targets = self.meta['route_frequencies_mhz'] if self.meta['route_requested'] else []
            self.state = dict(schema=SCHEMA, label=self.meta['label'], hash_backend='shake',
                baseline_label='S4', baseline_manifest_sha256=BASELINE_SHA, pid=os.getpid(),
                started_at=now(), complete=False, source_unchanged=None,
                tests={f'P{p}U1/{profile}': dict(status='pending') for p in CONFIGS for profile in PROFILES},
                synthesis={f'P{p}U1': dict(status='pending') for p in CONFIGS}, routing={})
        self.state['routing'].update({core.route_name(p, f): dict(status='pending',
            configuration=f'P{p}U1', target_frequency_mhz=f) for p in CONFIGS for f in self.targets})

    def comparisons(self):
        rows = super().comparisons()
        for row in rows:
            row['baseline_label'] = 'S4'
            row['baseline_cycles'] = row.pop('c2_cycles')
            if 'c2_equivalent_slice' in row:
                row['baseline_equivalent_slice'] = row.pop('c2_equivalent_slice')
        return rows

    def publish(self):
        self.state.update(updated_at=now(), comparisons=self.comparisons(),
                          validation_passed=self.validated())
        self.state['counts'] = {s: sum(t['status'] == s for t in self.state['tests'].values())
                                for s in ('pending', 'running', 'passed', 'failed')}
        closed = []
        for name, item in self.state['routing'].items():
            item.update(route_assessment(item))
            if not item['sta_closed']:
                continue
            config, period = item['configuration'], item['result']['actual_period_ns']
            old_name, old = best_closed(self.baseline['results']['routing'], config)
            for row in self.state['comparisons']:
                if row['configuration'] != config or row.get('workload_equal') is not True:
                    continue
                atp = item['area']['equivalent_slice'] * row['cycles'] * period / 1e6
                old_cycles = self.baseline['results']['tests'][f'{config}/{row["profile"]}']['cycles']
                old_atp = old['area']['equivalent_slice'] * old_cycles * old['result']['actual_period_ns'] / 1e6
                closed.append(dict(task=name, configuration=config, profile=row['profile'],
                    routed_equivalent_slice=item['area']['equivalent_slice'], cycles=row['cycles'],
                    actual_period_ns=period, closed_frequency_mhz=1000 / period,
                    strict_target_met=item['strict_target_met'], routed_time_ms=row['cycles'] * period / 1e6,
                    routed_atp_slice_ms=atp, baseline_task=old_name,
                    baseline_closed_frequency_mhz=1000 / old['result']['actual_period_ns'],
                    baseline_routed_atp_slice_ms=old_atp, routed_atp_change_pct=100 * (atp / old_atp - 1)))
        self.state['closed_routed_atp'] = closed
        write(self.run / 'status.json', self.state)
        write(self.out / 'VALIDATION_SUMMARY.json', self.state)
        prefix = self.out / 'reports' / ('S4_Timing_Optimization_' + self.meta['run_id'])
        write(prefix.with_suffix('.json'), dict(source=self.meta, results=self.state))
        fmt = lambda v: '—' if v is None else f'{v:,.3f}'
        row = lambda values: '| ' + ' | '.join(str(v) for v in values) + ' |'
        lines = ['# S4 基础 SHAKE P12U1／P4U1 时序优化', '',
            f'候选：{self.meta["label"]}；更新时间：{self.state["updated_at"]}；'
            f'状态：{"完成" if self.state["complete"] else "后台运行"}。', '',
            '唯一比较基线为冻结 S4（20261020_110957）；六项完整 Sign、两项 100 MHz 综合和六项'
            '布线证据已逐项核对源码与报告。基线 P4U1 在实际 6.667 ns（149.992500 MHz）下闭合，'
            'P12U1 在实际 7.143 ns（139.997200 MHz）下闭合；精确 150／140 MHz 目标因时钟量化'
            '未严格满足，与实际 STA 通过分开记录。P12U1@150 的 WNS=-0.063 ns，不能计入闭合 ATP。', '',
            'common OOC、xc7a200tffg1156-3、通用 Keccak、默认时序驱动，无新增时序例外。'
            '100 MHz 综合只用于诊断，不能证明最终频率。每个 Vivado 两线程，全机最多十二个。'
            '异常综合只延后分析，不终止任务；h20 完整 Keygen／Sign 保持停止。', '',
            '| 配置 | LUT | FF | BRAM36 | Slice | S4 Slice | 路径 ns | S4 路径 ns | 级数 | 状态 |',
            '|---|---:|---:|---:|---:|---:|---:|---:|---:|---|']
        for config, item in self.state['synthesis'].items():
            area, path = item.get('area', {}), item.get('timing', {})
            old = self.baseline['results']['synthesis'][config]
            lines.append(row([config, *[fmt(area.get(k)) for k in ('lut', 'ff', 'bram36', 'equivalent_slice')],
                fmt(old['area']['equivalent_slice']), fmt(path.get('data_path_ns')),
                fmt(old['timing']['data_path_ns']), fmt(path.get('logic_levels')),
                item['status'] + ('／分析延后，后台继续' if item.get('analysis_deferred') else '')]))
        for profile in PROFILES:
            lines += ['', f'## {profile} 完整 Sign', '',
                '| 配置 | 周期 | S4 周期 | 周期变化 % | 面积变化 % | 假设100MHz时间 ms | 假设ATP Slice·ms | 假设ATP变化 % | 工作量相同 | 状态 |',
                '|---|---:|---:|---:|---:|---:|---:|---:|---|---|']
            for item in self.state['comparisons']:
                if item['profile'] == profile:
                    keys = ('cycles', 'baseline_cycles', 'cycles_change_pct', 'area_change_pct',
                            'diagnostic_time_ms_at_100mhz', 'diagnostic_atp_slice_ms_at_100mhz',
                            'diagnostic_atp_change_pct')
                    equal = '—' if 'workload_equal' not in item else ('是' if item['workload_equal'] else '否')
                    lines.append(row([item['configuration'], *[fmt(item.get(k)) for k in keys], equal, item['status']]))
        lines += ['', '## 布线证据', '',
            '布线只在显式请求且诊断通过后启动。严格目标状态保留；实际 STA、DRC、布线及源码校验通过'
            '即按实际受约束周期计算 ATP。时钟量化不会抹去已闭合证据；不从 slack 推算 Fmax。', '',
            '| 设计／目标 | 布线 Slice | WNS ns | WHS ns | 实际 MHz | STA闭合 | 精确目标满足 | 严格状态 |',
            '|---|---:|---:|---:|---:|---|---|---|']
        for design, routes in (('S4', self.baseline['results']['routing']), ('候选', self.state['routing'])):
            for name, item in routes.items():
                result, assessment = item.get('result', {}), route_assessment(item)
                complete = bool(result)
                lines.append(row([f'{design} {name}', fmt(item.get('area', {}).get('equivalent_slice')),
                    fmt(result.get('wns_ns')), fmt(result.get('whs_ns')), fmt(assessment['actual_clock_frequency_mhz']),
                    ('通过' if assessment['sta_closed'] else '失败') if complete else '—',
                    ('是' if assessment['strict_target_met'] else '否') if complete else '—', item['status']]))
        lines += ['', '| 闭合任务 | 算法 | 实际 MHz | 时间 ms | ATP Slice·ms | 比较基线任务 | ATP变化 % |',
                  '|---|---|---:|---:|---:|---|---:|']
        for item in closed:
            lines.append(row([item['task'], item['profile'], *[fmt(item[k]) for k in
                ('closed_frequency_mhz', 'routed_time_ms', 'routed_atp_slice_ms')],
                item['baseline_task'], fmt(item['routed_atp_change_pct'])]))
        errors = [(f'{group}/{key}', item['error']) for group in ('tests', 'synthesis', 'routing')
                  for key, item in self.state[group].items() if item.get('error')]
        if errors:
            lines += ['', '## 未通过项目', ''] + [f'- `{key}`：{error}' for key, error in errors]
        lines += ['', f'运行目录：`{self.run}`。仿真明细只保留运行目录；归档保留摘要、冻结源码、SHA、'
            '综合／布线分层面积、时序报告和日志。索引由调用方按时间追加。', '']
        core.archive.atomic(prefix.with_suffix('.md'), '\n'.join(lines))
        missing = {}
        for group, items in (('synth', self.state['synthesis']), ('route', self.state['routing'])):
            for name in items:
                folder = self.run / group / name
                for path in folder.rglob('*') if folder.exists() else []:
                    if path.is_file() and path.suffix in ('.rpt', '.log', '.txt', '.xdc', '.json'):
                        core.archive.copy_changed(path, self.out / group / name / path.relative_to(folder))
                wanted = (['hierarchical.rpt', 'timing.rpt'] if group == 'synth' else
                    ['route/hierarchical.rpt', 'route/timing.rpt', 'route/route_status.rpt', 'route/drc.rpt', 'result.json'])
                missing[f'{group}/{name}'] = [file for file in wanted if not (self.out / group / name / file).is_file()]
        write(self.out / 'ARTIFACTS.json', dict(complete=self.state['complete'], missing=missing,
            omitted_details=['sim', 'validation'], sha256={str(p.relative_to(self.out)): sha(p)
                for p in self.out.rglob('*') if p.is_file() and p.name != 'ARTIFACTS.json'
                and not p.name.endswith('.tmp')}))


def background(run, routes_only=False):
    marker = run / ('ROUTE_INITIAL_PUBLICATION.json' if routes_only else 'INITIAL_PUBLICATION.json')
    require(not marker.exists(), 'Worker already started; refusing duplicate jobs')
    with (run / ('route_runner.log' if routes_only else 'runner.log')).open('w') as stream:
        process = subprocess.Popen([sys.executable, str(run / 'control/run_s4_timing_optimization.py'),
            '--run-routes-only' if routes_only else '--run-root', str(run)], cwd=ROOT,
            env=dict(os.environ, MHBS_S4_TIMING_WORKSPACE=str(ROOT), MHBS_C2_TIMING_WORKSPACE=str(ROOT),
                MHBS_SHAKE_TIMING_WORKSPACE=str(ROOT), MHBS_BACKEND_WORKSPACE=str(ROOT)),
            stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
    deadline = time.monotonic() + 30
    while not marker.exists():
        if process.poll() is not None or time.monotonic() > deadline:
            raise RuntimeError(f'Initial publication failed; see {run}')
        time.sleep(.1)
    return process.pid


def launch(args):
    baseline = checked_baseline()
    source = (args.source_root or ROOT).resolve()
    tools = {name: shutil.which(os.environ.get(name.upper(), name)) for name in ('vivado', 'verilator')}
    require(all(tools.values()), 'Vivado and Verilator are required')
    versions = {name: subprocess.check_output([path, '-version' if name == 'vivado' else '--version'],
        text=True, timeout=30).strip() for name, path in tools.items()}
    require(versions == baseline['source']['tool_versions'], 'Tool versions differ from S4')
    for profile in PROFILES:
        require(core.previous.vectors(source, profile) == core.previous.vectors(Path(baseline['source']['source_root']), profile),
                f'Candidate vectors differ from S4: {profile}')
    for name in ('scripts/diagnose_timing.tcl', 'scripts/route_common_target.tcl'):
        require(sha(source / name) == baseline['source']['sha256'][name], f'S4 tool-setting script changed: {name}')
    targets = core.frequencies(args.route_mhz) if args.route else []
    stamp = datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y%m%d_%H%M%S')
    run = ROOT / 'build/s4_timing_optimization' / f'candidate_{stamp}'
    out = core.archive.ARCHIVES / f's4_timing_optimization_{stamp}'
    require(not run.exists() and not out.exists(), f'Run exists; retry next second: {run}')
    spec = core.snapshot(source, run / 'source')
    for base in (run, out):
        write(base / 'S4_BASELINE_EVIDENCE.json', baseline)
    meta = dict(spec, schema=SCHEMA, run_id=stamp, label=args.label, phase='candidate', hash_backend='shake',
        **tools, tool_versions=versions, started_at=now(), archive_directory=str(out), configurations=CONFIGS,
        profiles=PROFILES, top='common', part='xc7a200tffg1156-3', synthesis_period_ns=10.0,
        threads_per_vivado=2, max_total_vivado=12, route_requested=bool(args.route),
        route_frequencies_mhz=targets, frequency_search=False, new_timing_exceptions=False,
        h20_full_keygen_sign_run=False, baseline_label='S4', baseline_run=str(BASELINE_RUN),
        baseline_manifest_sha256=BASELINE_SHA,
        baseline_evidence_sha256=sha(run / 'S4_BASELINE_EVIDENCE.json'), reuse_evidence=False)
    for base in (run, out):
        write(base / 'SOURCE.json', meta)
        for name in CONTROLS:
            core.archive.copy_changed(ROOT / 'scripts' / name, base / 'control' / name)
        write(base / 'CONTROL_SOURCE.json', {name: sha(base / 'control' / name) for name in CONTROLS})
    core.previous.archive_source(meta, out)
    result = dict(pid=background(run), root=str(run),
        report=str(out / 'reports' / f'S4_Timing_Optimization_{stamp}.md'), baseline='S4',
        simulation_cases=6, diagnostic_syntheses=2, route_jobs=2 * len(targets))
    write(run / 'LAUNCH.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--launch-candidate', action='store_true')
    group.add_argument('--route-existing', type=Path)
    group.add_argument('--inspect-baseline', action='store_true')
    group.add_argument('--run-root', type=Path, help=argparse.SUPPRESS)
    group.add_argument('--run-routes-only', type=Path, help=argparse.SUPPRESS)
    group.add_argument('--refresh-run', type=Path)
    parser.add_argument('--source-root', type=Path)
    parser.add_argument('--label', default='S4-based candidate')
    parser.add_argument('--route', action='store_true', help='Explicitly route after all diagnostic checks pass')
    parser.add_argument('--route-mhz', nargs='+', type=float, default=[150.0, 155.0, 160.0])
    args = parser.parse_args()
    if args.inspect_baseline:
        evidence = checked_baseline()
        print(json.dumps(dict(baseline='S4', validated=True, manifest_sha256=evidence['manifest_sha256'],
            measured_sign_cases=6, diagnostic_syntheses=2,
            best_closed_tasks=evidence['baseline_best_closed_tasks'],
            routes={name: dict(strict_status=item['status'], **route_assessment(item))
                    for name, item in evidence['results']['routing'].items()}), indent=2))
    elif args.refresh_run:
        runner = Runner(args.refresh_run)
        runner.state = read(runner.run / 'status.json')
        require(runner.state.get('complete') and core.previous.unchanged(runner.meta),
                'Only completed unchanged-source runs can be refreshed')
        runner.publish()
    elif args.route_existing:
        runner = Runner(args.route_existing)
        runner.state = read(runner.run / 'status.json')
        require(runner.state.get('complete') and runner.validated(), 'Candidate diagnostics must finish and pass')
        require(not runner.state.get('routing') and not (runner.run / 'ROUTE_REQUEST.json').exists(),
                'Routing already requested; refusing duplicate jobs')
        request = dict(requested_at=now(), frequencies_mhz=core.frequencies(args.route_mhz),
            source_manifest_sha256=sha(runner.run / 'SOURCE.json'), explicitly_requested=True)
        for base in (runner.run, runner.out):
            write(base / 'ROUTE_REQUEST.json', request)
        print(json.dumps(dict(pid=background(runner.run, routes_only=True), root=str(runner.run),
                              route_jobs=2 * len(request['frequencies_mhz'])), indent=2))
    elif args.run_root or args.run_routes_only:
        return Runner(args.run_routes_only or args.run_root, routes_only=bool(args.run_routes_only)).execute()
    else:
        launch(args)
    return 0


if __name__ == '__main__':
    sys.exit(main())
