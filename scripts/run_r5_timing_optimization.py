#!/usr/bin/env python3
"""Freeze SHAKE timing candidates and compare only with the measured frozen R5.

Diagnose first (six full Sign tests and two common/100-MHz syntheses)::

    python3 scripts/run_r5_timing_optimization.py --launch-candidate --label NAME

After inspecting that frozen candidate, explicitly request its routes::

    python3 scripts/run_r5_timing_optimization.py --route-existing RUN \
        --route-mhz 150 140 135

Execution, simulation, capacity limits and routing reuse the C2 controller. This
controller changes the baseline and reporting, never the hardware or constraints.
It does not start h20 full-tree tests, terminate slow jobs or update INDEX.md.
"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from zoneinfo import ZoneInfo

import run_c2_timing_optimization as core

ROOT = Path(os.environ.get('MHBS_R5_TIMING_WORKSPACE', core.ROOT)).resolve()
core.archive.ROOT = ROOT
core.archive.ARCHIVES = ROOT / 'docs/manifests/experiments'
SCHEMA = 'r5_shake_timing_optimization_v1'
BASELINE_RUN = ROOT / 'build/c2_timing_optimization/candidate_20261020_100441'
BASELINE_SHA = 'fdc3f8f41e11b400e26e869741a79fb7974b4a6087f9d9bf529f9911b0fe5b4e'
CONTROLS = ('run_r5_timing_optimization.py', *core.CONTROLS)
CONFIGS, PROFILES = core.CONFIGS, core.PROFILES
read, write, require, sha, now = core.read, core.write, core.require, core.sha, core.now


def checked_baseline():
    """Check real R5 Sign, synthesis and both successful/failed routing evidence."""
    require(sha(BASELINE_RUN / 'SOURCE.json') == BASELINE_SHA,
            'Only frozen R5/20261020_100441 is accepted as the comparison baseline')
    evidence = core.checked_evidence(BASELINE_RUN)
    evidence.update(label='R5', comparison_parent_baselines_ignored=True)
    routes = evidence['results']['routing']
    report_hashes = {}
    for p in CONFIGS:
        for frequency in (130, 150):
            name = core.route_name(p, frequency)
            item = routes[name]
            folder = BASELINE_RUN / 'route' / name
            result = read(folder / 'result.json')
            require(item.get('source_manifest_sha256') == BASELINE_SHA
                    and item.get('source_unchanged') is True
                    and item['result'] == result
                    and item['route_status'] == core.route_status(folder / 'route/route_status.rpt')
                    and item['area'] == core.utilization(folder / 'route/utilization.rpt')
                    and item['timing'] == core.timing(folder / 'route/timing.rpt')
                    and sha(folder / 'route/routed.dcp') == item['routed_checkpoint_sha256'],
                    f'Changed or unbound R5 routed evidence: {name}')
            expected = 'passed' if frequency == 130 else 'target_not_met'
            require(item['status'] == expected and item['meets_target'] is (frequency == 130)
                    and result['setup_hold_met'] is (frequency == 130)
                    and (result['wns_ns'] >= 0) is (frequency == 130)
                    and result['whs_ns'] >= 0 and result['drc_errors'] == 0
                    and item['route_status']['passed'] is True,
                    f'R5 route no longer matches measured 130-MHz pass/150-MHz failure: {name}')
            settings = (folder / 'settings.txt').read_text().splitlines()
            for setting in (f'PIPELINE={p}', 'UNROLL=1', 'top=common',
                            f'frequency_mhz={frequency}.0', 'hash_backend=shake', 'threads=2',
                            'part=xc7a200tffg1156-3', 'mode=out_of_context',
                            'keccak=generic', 'timing_driven=default',
                            'new_timing_exceptions=none', 'frequency_search=none'):
                require(setting in settings, f'R5 route setting mismatch: {name}/{setting}')
            for file in ('result.json', 'settings.txt', 'target_clock.xdc', 'vivado.log',
                         'route/hierarchical.rpt', 'route/timing.rpt', 'route/critical_paths.rpt',
                         'route/utilization.rpt', 'route/route_status.rpt', 'route/drc.rpt'):
                require((folder / file).is_file(), f'Missing R5 route evidence: {name}/{file}')
                report_hashes[f'{name}/{file}'] = sha(folder / file)
    evidence.update(routed_reports_sha256=report_hashes,
                    route_evidence_validated=True, checked_at=now())
    return evidence


class Runner(core.Runner):
    """Use the shared measured-job engine with an R5-only comparison surface."""
    def __init__(self, run, routes_only=False):
        self.run = Path(run).resolve()
        self.meta = read(self.run / 'SOURCE.json')
        require(self.meta.get('schema') == SCHEMA and self.meta.get('hash_backend') == 'shake',
                'Not an R5 timing optimization run')
        self.source, self.out = Path(self.meta['source_root']), Path(self.meta['archive_directory'])
        self.baseline = read(self.run / 'R5_BASELINE_EVIDENCE.json')
        require(self.baseline['manifest_sha256'] == BASELINE_SHA
                and sha(self.run / 'R5_BASELINE_EVIDENCE.json') == self.meta['baseline_evidence_sha256'],
                'R5 baseline evidence changed')
        self.lock, self.capacity_lock, self.reserved = threading.RLock(), threading.Lock(), 0
        self.routes_only = routes_only
        if routes_only:
            self.state = read(self.run / 'status.json')
            require(self.state.get('complete') and self.validated(),
                    'Routes require completed same-workload Sign and diagnostic synthesis')
            request = read(self.run / 'ROUTE_REQUEST.json')
            require(request['source_manifest_sha256'] == sha(self.run / 'SOURCE.json'),
                    'Routing is not bound to this frozen candidate')
            self.state.update(complete=False, pid=os.getpid(), routing_started_at=now())
            self.targets = request['frequencies_mhz']
        else:
            self.targets = self.meta['route_frequencies_mhz'] if self.meta['route_requested'] else []
            self.state = dict(schema=SCHEMA, label=self.meta['label'], hash_backend='shake',
                baseline_label='R5', baseline_manifest_sha256=BASELINE_SHA, pid=os.getpid(),
                started_at=now(), complete=False, source_unchanged=None,
                tests={f'P{p}U1/{profile}': dict(status='pending') for p in CONFIGS for profile in PROFILES},
                synthesis={f'P{p}U1': dict(status='pending') for p in CONFIGS}, routing={})
        self.state['routing'].update({core.route_name(p, f): dict(status='pending',
            configuration=f'P{p}U1', target_frequency_mhz=f) for p in CONFIGS for f in self.targets})

    def comparisons(self):
        # The shared arithmetic is baseline-agnostic; expose R5 names to consumers.
        rows = super().comparisons()
        for row in rows:
            row['baseline_label'] = 'R5'
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
        for name, route in self.state['routing'].items():
            if route['status'] != 'passed' or route.get('meets_target') is not True:
                continue
            config, period = route['configuration'], route['result']['actual_period_ns']
            old = self.baseline['results']['routing'][f'{config}_130MHz']
            for row in self.state['comparisons']:
                if row['configuration'] != config or row.get('workload_equal') is not True:
                    continue
                atp = route['area']['equivalent_slice'] * row['cycles'] * period / 1e6
                old_cycles = self.baseline['results']['tests'][f'{config}/{row["profile"]}']['cycles']
                old_atp = old['area']['equivalent_slice'] * old_cycles * old['result']['actual_period_ns'] / 1e6
                closed.append(dict(task=name, configuration=config, profile=row['profile'],
                    routed_equivalent_slice=route['area']['equivalent_slice'], cycles=row['cycles'],
                    closed_frequency_mhz=1000 / period, routed_time_ms=row['cycles'] * period / 1e6,
                    routed_atp_slice_ms=atp, baseline_task=f'{config}_130MHz',
                    baseline_routed_atp_slice_ms=old_atp, routed_atp_change_pct=100 * (atp / old_atp - 1)))
        self.state['closed_routed_atp'] = closed
        write(self.run / 'status.json', self.state)
        write(self.out / 'VALIDATION_SUMMARY.json', self.state)
        prefix = self.out / 'reports' / ('R5_Timing_Optimization_' + self.meta['run_id'])
        write(prefix.with_suffix('.json'), dict(source=self.meta, results=self.state))
        fmt = lambda v: '—' if v is None else f'{v:,.3f}'
        table_row = lambda values: '| ' + ' | '.join(str(v) for v in values) + ' |'
        lines = ['# R5 基础 SHAKE P12U1／P4U1 时序优化', '',
            f'候选：{self.meta["label"]}；更新时间：{self.state["updated_at"]}；'
            f'状态：{"完成" if self.state["complete"] else "后台运行"}。', '',
            '唯一基线为冻结 R5（20261020_100441）。六项完整 Sign、两项 100 MHz 综合、'
            '两项 130 MHz 布线通过和两项 150 MHz setup 失败证据均已核对源码和报告。'
            'C2 及更早设计不参与本轮周期、面积或 ATP 比较。', '',
            'common OOC、xc7a200tffg1156-3、通用 Keccak、SYNTHESIS 裁剪统计，默认时序驱动；'
            '每个 Vivado 两线程，全机最多十二个。100 MHz 综合仅用于面积与关键路径诊断；'
            '十分钟异常只延后分析，任务保留后台。h20 完整 Keygen／Sign 保持停止。', '',
            '| 配置 | LUT | FF | BRAM36 | Slice | R5 Slice | 路径 ns | R5 路径 ns | 逻辑级数 | 状态 |',
            '|---|---:|---:|---:|---:|---:|---:|---:|---:|---|']
        for config, item in self.state['synthesis'].items():
            area, path = item.get('area', {}), item.get('timing', {})
            old = self.baseline['results']['synthesis'][config]
            lines.append(table_row([config, *[fmt(area.get(k)) for k in ('lut', 'ff', 'bram36', 'equivalent_slice')],
                fmt(old['area']['equivalent_slice']), fmt(path.get('data_path_ns')),
                fmt(old['timing']['data_path_ns']), fmt(path.get('logic_levels')),
                item['status'] + ('／分析延后，后台继续' if item.get('analysis_deferred') else '')]))
        for profile in PROFILES:
            lines += ['', f'## {profile} 完整 Sign', '',
                '| 配置 | 周期 | R5 周期 | 周期变化 % | 面积变化 % | 假设100MHz时间 ms | 假设ATP Slice·ms | 假设ATP变化 % | 工作量相同 | 状态 |',
                '|---|---:|---:|---:|---:|---:|---:|---:|---|---|']
            for row in self.state['comparisons']:
                if row['profile'] == profile:
                    keys = ('cycles', 'baseline_cycles', 'cycles_change_pct', 'area_change_pct',
                            'diagnostic_time_ms_at_100mhz', 'diagnostic_atp_slice_ms_at_100mhz',
                            'diagnostic_atp_change_pct')
                    equal = '—' if 'workload_equal' not in row else ('是' if row['workload_equal'] else '否')
                    lines.append(table_row([row['configuration'], *[fmt(row.get(k)) for k in keys], equal, row['status']]))
        lines += ['', '## 布线证据', '',
            '只有显式请求才启动同一冻结候选的布线，且六项 Sign、工作量与诊断综合全部通过。'
            '不搜索频率，不新增时序例外；完整布线、DRC、setup／hold 及目标周期全部满足才计算 ATP。', '',
            '| 设计／目标 | 布线 Slice | WNS ns | WHS ns | 状态 |', '|---|---:|---:|---:|---|']
        for design, routes in (('R5', self.baseline['results']['routing']), ('候选', self.state['routing'])):
            for name, item in routes.items():
                result = item.get('result', {})
                lines.append(table_row([f'{design} {name}', fmt(item.get('area', {}).get('equivalent_slice')),
                    fmt(result.get('wns_ns')), fmt(result.get('whs_ns')), item['status']]))
        lines += ['', '| 闭合任务 | 算法 | 受约束频率 MHz | 时间 ms | ATP Slice·ms | 相对R5@130MHz % |',
                  '|---|---|---:|---:|---:|---:|']
        for row in closed:
            lines.append(table_row([row['task'], row['profile'], *[fmt(row[k]) for k in
                ('closed_frequency_mhz', 'routed_time_ms', 'routed_atp_slice_ms', 'routed_atp_change_pct')]]))
        errors = [(f'{group}/{key}', item['error']) for group in ('tests', 'synthesis', 'routing')
                  for key, item in self.state[group].items() if item.get('error')]
        if errors:
            lines += ['', '## 未通过项目', ''] + [f'- `{key}`：{error}' for key, error in errors]
        lines += ['', f'运行目录：`{self.run}`。仿真明细只留运行目录；归档保留验证摘要、'
            '冻结源码与 SHA、综合／布线分层面积和时序报告及日志。索引由调用方按时间追加。', '']
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
        process = subprocess.Popen([sys.executable, str(run / 'control/run_r5_timing_optimization.py'),
            '--run-routes-only' if routes_only else '--run-root', str(run)], cwd=ROOT,
            env=dict(os.environ, MHBS_R5_TIMING_WORKSPACE=str(ROOT), MHBS_C2_TIMING_WORKSPACE=str(ROOT),
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
    require(versions == baseline['source']['tool_versions'], 'Tool versions differ from R5')
    for profile in PROFILES:
        require(core.previous.vectors(source, profile) == core.previous.vectors(Path(baseline['source']['source_root']), profile),
                f'Candidate vectors differ from R5: {profile}')
    for name in ('scripts/diagnose_timing.tcl', 'scripts/route_common_target.tcl'):
        require(sha(source / name) == baseline['source']['sha256'][name], f'R5 tool-setting script changed: {name}')
    targets = core.frequencies(args.route_mhz) if args.route else []
    stamp = datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y%m%d_%H%M%S')
    run = ROOT / 'build/r5_timing_optimization' / f'candidate_{stamp}'
    out = core.archive.ARCHIVES / f'r5_timing_optimization_{stamp}'
    require(not run.exists() and not out.exists(), f'Run exists; retry next second: {run}')
    spec = core.snapshot(source, run / 'source')
    for base in (run, out):
        write(base / 'R5_BASELINE_EVIDENCE.json', baseline)
    meta = dict(spec, schema=SCHEMA, run_id=stamp, label=args.label, phase='candidate', hash_backend='shake',
        **tools, tool_versions=versions, started_at=now(), archive_directory=str(out), configurations=CONFIGS,
        profiles=PROFILES, top='common', part='xc7a200tffg1156-3', synthesis_period_ns=10.0,
        threads_per_vivado=2, max_total_vivado=12, route_requested=bool(args.route),
        route_frequencies_mhz=targets, frequency_search=False, new_timing_exceptions=False,
        h20_full_keygen_sign_run=False, baseline_label='R5', baseline_run=str(BASELINE_RUN),
        baseline_manifest_sha256=BASELINE_SHA,
        baseline_evidence_sha256=sha(run / 'R5_BASELINE_EVIDENCE.json'), reuse_evidence=False)
    for base in (run, out):
        write(base / 'SOURCE.json', meta)
        for name in CONTROLS:
            core.archive.copy_changed(ROOT / 'scripts' / name, base / 'control' / name)
        write(base / 'CONTROL_SOURCE.json', {name: sha(base / 'control' / name) for name in CONTROLS})
    core.previous.archive_source(meta, out)
    result = dict(pid=background(run), root=str(run),
        report=str(out / 'reports' / f'R5_Timing_Optimization_{stamp}.md'), baseline='R5',
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
    parser.add_argument('--label', default='R5-based candidate')
    parser.add_argument('--route', action='store_true', help='Explicitly route only after all diagnostic checks pass')
    parser.add_argument('--route-mhz', nargs='+', type=float, default=[150.0, 140.0, 135.0])
    args = parser.parse_args()
    if args.inspect_baseline:
        evidence = checked_baseline()
        print(json.dumps(dict(baseline='R5', validated=True, manifest_sha256=evidence['manifest_sha256'],
            measured_sign_cases=6, diagnostic_syntheses=2,
            routes={name: item['status'] for name, item in evidence['results']['routing'].items()}), indent=2))
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
