#!/usr/bin/env python3
"""Measure SHAKE timing candidates against the frozen C2 design, never old B0.

Freeze and measure (6 full Sign tests and 2 common/100-MHz syntheses)::

    python3 scripts/run_c2_timing_optimization.py --launch-candidate \
        --source-root PATH --label context_read_pipeline

Only after examining that run's diagnostics, explicitly start four routes::

    python3 scripts/run_c2_timing_optimization.py --route-existing RUN \
        --route-mhz 150 130

Alternatively --route can explicitly request those routes at launch. All jobs use
the same frozen candidate. No frequency search, termination of slow jobs, INDEX
update, CSV report, or h20 Keygen/Sign is performed by this controller.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
from zoneinfo import ZoneInfo

import experiment_archive as archive
import run_shake_timing_optimization as previous
from report_timing_focus import timing
from run_hash_backends import sha, snapshot
from run_pu_route_matrix import route_status
from run_pu_sign_matrix import utilization

ROOT = Path(os.environ.get('MHBS_C2_TIMING_WORKSPACE', Path(__file__).resolve().parents[1])).resolve()
archive.ROOT = ROOT
archive.ARCHIVES = ROOT / 'docs/manifests/experiments'
SCHEMA = 'c2_shake_timing_optimization_v1'
C2_RUN = ROOT / 'build/shake_timing_optimization/candidate_20261019_211601'
C2_MANIFEST_SHA = '295a41c168fc65b5f1561f89f702943d0b25595b9c424805f1cbbf1795a219d9'
CONFIGS = (12, 4)
PROFILES = ('slh_128f', 'lms_h10', 'xmss_h10')
CONTROLS = ('run_c2_timing_optimization.py', *previous.CONTROLS)
PASS = re.compile(r'STATEFUL_PASS P(\d+)U1 op=1 cycles=(\d+) total=(\d+) '
                  r'hashes=(\d+) permutations=(\d+).*?seconds=([\d.e+]+)')


def now():
    return datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds')


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    archive.atomic(Path(path), json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def source_keys(meta):
    """All snapshotted inputs bind reuse, including model, vectors and harness."""
    return meta['sha256']


def require(condition, message):
    if not condition:
        raise ValueError(message)


def checked_evidence(run, c2=False):
    """Validate measured evidence before importing it; do not follow its B0 link."""
    run = Path(run).resolve()
    manifest, status = run / 'SOURCE.json', run / 'status.json'
    meta, state = read(manifest), read(status)
    if c2:
        require(sha(manifest) == C2_MANIFEST_SHA,
                'Baseline must be the exact frozen C2 (211601) manifest; B0 is not accepted')
    require(meta.get('hash_backend') == 'shake' and meta.get('top') == 'common'
            and meta.get('part') == 'xc7a200tffg1156-3'
            and meta.get('synthesis_period_ns') == 10.0
            and meta.get('threads_per_vivado') == 2,
            'Evidence uses different backend, top, device, diagnostic clock or thread settings')
    require(state.get('complete') and state.get('source_unchanged') is True
            and previous.unchanged(meta), 'Evidence is incomplete or frozen source changed')
    require(len([p for p in source_keys(meta) if p.startswith('rtl/')]) == 10,
            'Expected complete frozen ten-file RTL source list')
    source = Path(meta['source_root'])
    for p in CONFIGS:
        config = f'P{p}U1'
        for profile in PROFILES:
            key = f'{config}/{profile}'
            test = state['tests'][key]
            log = Path(test.get('log', ''))
            require(test.get('status') == 'passed' and test.get('source_unchanged') is True
                    and test.get('source_manifest_sha256') == sha(manifest),
                    f'Unbound or failed Sign evidence: {key}')
            require(log.is_file() and sha(log) == test.get('log_sha256'),
                    f'Missing or changed measured Sign log: {key}')
            match = PASS.search(log.read_text(errors='replace'))
            require(match is not None and int(match[1]) == p, f'No measured Sign PASS: {key}')
            for name, group in (('cycles', 2), ('total_cycles', 3), ('hashes', 4), ('permutations', 5)):
                require(test.get(name) == int(match[group]), f'Measured {name} mismatch: {key}')
            wanted = previous.vectors(source, profile)
            require(test.get('vectors_sha256') == wanted, f'Changed vectors: {key}')
            expected = [int(v, 16) for v in (source / 'tb/vectors' / profile / 'sign/meta.mem').read_text().split()]
            require(test['hashes'] == expected[1] and test['permutations'] == expected[2],
                    f'Wrong hash/permutation workload: {key}')
        syn = state['synthesis'][config]
        require(syn.get('status') == 'passed' and syn.get('source_unchanged') is True
                and syn.get('source_manifest_sha256') == sha(manifest),
                f'Unbound or failed synthesis evidence: {config}')
        folder = run / 'synth' / config
        settings = (folder / 'settings.txt').read_text()
        for value in ('diagnostic_only=1', 'top=common', f'PIPELINE={p}', 'UNROLL=1',
                      'period_ns=10.0', 'hash_backend=shake', 'part=xc7a200tffg1156-3',
                      'threads=2', 'mode=out_of_context', 'keccak=generic',
                      'timing_driven=default', 'new_timing_exceptions=none'):
            require(value in settings.splitlines(), f'Diagnostic setting mismatch {config}: {value}')
        for name in ('hierarchical.rpt', 'timing.rpt', 'utilization.rpt', 'settings.txt', 'vivado.log'):
            require((folder / name).is_file() and sha(folder / name) == syn['reports_sha256'].get(name),
                    f'Missing or changed synthesis evidence: {config}/{name}')
        require(syn['area'] == utilization(folder / 'utilization.rpt')
                and syn['timing'] == timing(folder / 'timing.rpt'),
                f'Parsed synthesis report differs from recorded results: {config}')
    return dict(run_root=str(run), label='C2' if c2 else 'reused_candidate',
                manifest_sha256=sha(manifest), status_sha256=sha(status),
                source=meta, results=state, checked_at=now(),
                legacy_parent_baseline_ignored=True, full_source_checksums_validated=True,
                measured_logs_and_synthesis_reports_validated=True)


def frequencies(values):
    require(values and all(math.isfinite(v) and v > 0 for v in values),
            'Route frequencies must be positive and finite')
    require(len(values) == len(set(values)), 'Duplicate route frequencies')
    return values


def route_name(p, frequency):
    return f'P{p}U1_{frequency:g}MHz'


class Runner(previous.Runner):
    """Reuse existing simulation/capacity code; comparison and archives are C2-only."""
    def __init__(self, run, routes_only=False):
        self.run = Path(run).resolve()
        self.meta = read(self.run / 'SOURCE.json')
        require(self.meta.get('schema') == SCHEMA and self.meta.get('hash_backend') == 'shake',
                'Not a C2 timing optimization run')
        self.source, self.out = Path(self.meta['source_root']), Path(self.meta['archive_directory'])
        self.baseline = read(self.run / 'C2_BASELINE_EVIDENCE.json')
        require(self.baseline['manifest_sha256'] == C2_MANIFEST_SHA, 'Wrong C2 baseline evidence')
        require(sha(self.run / 'C2_BASELINE_EVIDENCE.json') == self.meta['baseline_evidence_sha256'],
                'Frozen C2 evidence was changed')
        self.lock, self.capacity_lock, self.reserved = threading.RLock(), threading.Lock(), 0
        self.routes_only = routes_only
        if routes_only:
            self.state = read(self.run / 'status.json')
            require(self.state.get('complete') and self.validated(),
                    'Routes require completed, same-workload Sign and diagnostic synthesis')
            self.state.update(complete=False, pid=os.getpid(), routing_started_at=now())
            request = read(self.run / 'ROUTE_REQUEST.json')
            require(request['source_manifest_sha256'] == sha(self.run / 'SOURCE.json'),
                    'Route request is not bound to this frozen source')
            self.targets = request['frequencies_mhz']
        else:
            self.targets = self.meta['route_frequencies_mhz'] if self.meta['route_requested'] else []
            self.state = dict(schema=SCHEMA, label=self.meta['label'], hash_backend='shake',
                baseline_label='C2', baseline_manifest_sha256=C2_MANIFEST_SHA,
                pid=os.getpid(), started_at=now(), complete=False, source_unchanged=None,
                tests={f'P{p}U1/{profile}': dict(status='pending') for p in CONFIGS for profile in PROFILES},
                synthesis={f'P{p}U1': dict(status='pending') for p in CONFIGS}, routing={})
        self.state['routing'].update({route_name(p, f): dict(status='pending', configuration=f'P{p}U1',
            target_frequency_mhz=f) for p in CONFIGS for f in self.targets})

    def comparisons(self):
        rows = []
        baseline = self.baseline['results']
        for key, test in self.state['tests'].items():
            config, profile = key.split('/')
            old = baseline['tests'][key]
            syn, old_syn = self.state['synthesis'][config], baseline['synthesis'][config]
            row = dict(configuration=config, profile=profile, status=test['status'],
                       cycles=test.get('cycles'), baseline_label='C2', c2_cycles=old['cycles'])
            if test['status'] == 'passed':
                checks = {k: test.get(k) == old[k] for k in ('hashes', 'permutations', 'vectors_sha256')}
                row.update(workload_checks=checks, workload_equal=all(checks.values()),
                    cycles_change_pct=100 * (test['cycles'] / old['cycles'] - 1))
                if syn['status'] == 'passed':
                    area, old_area = syn['area']['equivalent_slice'], old_syn['area']['equivalent_slice']
                    row.update(equivalent_slice=area, c2_equivalent_slice=old_area,
                        area_change_pct=100 * (area / old_area - 1),
                        diagnostic_time_ms_at_100mhz=test['cycles'] / 100000,
                        diagnostic_atp_slice_ms_at_100mhz=area * test['cycles'] / 100000,
                        diagnostic_atp_change_pct=100 * (area * test['cycles'] / (old_area * old['cycles']) - 1))
            rows.append(row)
        return rows

    def validated(self):
        return (previous.unchanged(self.meta)
            and all(t['status'] == 'passed' for t in self.state['tests'].values())
            and all(t['status'] == 'passed' for t in self.state['synthesis'].values())
            and all(r.get('workload_equal') is True for r in self.comparisons()))

    def publish(self):
        self.state['updated_at'] = now()
        self.state['counts'] = {s: sum(t['status'] == s for t in self.state['tests'].values())
                                for s in ('pending', 'running', 'passed', 'failed')}
        self.state['comparisons'] = self.comparisons()
        self.state['validation_passed'] = self.validated()
        closed = []
        for name, route in self.state['routing'].items():
            if route['status'] != 'passed' or route.get('meets_target') is not True:
                continue
            result = route['result']
            for row in self.state['comparisons']:
                if row['configuration'] == route['configuration'] and row.get('workload_equal') is True:
                    period = result['actual_period_ns']
                    area = route['area']['equivalent_slice']
                    closed.append(dict(task=name, configuration=row['configuration'], profile=row['profile'],
                        routed_equivalent_slice=area, closed_frequency_mhz=1000 / period,
                        cycles=row['cycles'], routed_time_ms=row['cycles'] * period / 1e6,
                        routed_atp_slice_ms=area * row['cycles'] * period / 1e6))
        self.state['closed_routed_atp'] = closed
        write(self.run / 'status.json', self.state)
        write(self.out / 'VALIDATION_SUMMARY.json', self.state)
        prefix = self.out / 'reports' / ('C2_Timing_Optimization_' + self.meta['run_id'])
        write(prefix.with_suffix('.json'), dict(source=self.meta, results=self.state))
        fmt = lambda v: '—' if v is None else f'{v:,.3f}'
        lines = ['# C2 基础 SHAKE P12U1／P4U1 时序优化', '',
            f'候选：{self.meta["label"]}；更新时间：{self.state["updated_at"]}；'
            f'状态：{"完成" if self.state["complete"] else "后台运行"}。', '',
            '唯一比较基线为冻结 C2（20261019_211601），复用其已核验的六项完整 Sign 和两项 100 MHz 综合。'
            'C2 旧报告中的 B0 关系不参与本轮周期、面积或 ATP 比较。', '',
            'common OOC、xc7a200tffg1156-3、通用 Keccak、SYNTHESIS 裁剪统计、默认时序驱动；'
            '每个 Vivado 两线程，全机最多十二个。100 MHz 综合仅用于面积和关键路径诊断，'
            '不代表实际频率。异常综合超过十分钟仅延后分析，进程继续运行；h20 完整 Keygen／Sign 不运行。', '',
            '| 配置 | LUT | FF | BRAM36 | 等效 Slice | C2 Slice | 路径 ns | C2 路径 ns | 逻辑级数 | 状态 |',
            '|---|---:|---:|---:|---:|---:|---:|---:|---:|---|']
        for config, item in self.state['synthesis'].items():
            area, path = item.get('area', {}), item.get('timing', {})
            old = self.baseline['results']['synthesis'][config]
            status = item['status'] + ('／分析延后，后台继续' if item.get('analysis_deferred') else '')
            lines += ['| ' + ' | '.join([config, fmt(area.get('lut')), fmt(area.get('ff')),
                fmt(area.get('bram36')), fmt(area.get('equivalent_slice')),
                fmt(old['area']['equivalent_slice']), fmt(path.get('data_path_ns')),
                fmt(old['timing']['data_path_ns']), fmt(path.get('logic_levels')), status]) + ' |']
        for profile in PROFILES:
            lines += ['', f'## {profile} 完整 Sign', '',
                '| 配置 | 周期 | C2 周期 | 周期变化 % | 面积变化 % | 假设100MHz时间 ms | 假设ATP Slice·ms | 假设ATP变化 % | 工作量相同 | 状态 |',
                '|---|---:|---:|---:|---:|---:|---:|---:|---|---|']
            for row in self.state['comparisons']:
                if row['profile'] != profile:
                    continue
                equal = '—' if 'workload_equal' not in row else ('是' if row['workload_equal'] else '否')
                lines += ['| ' + ' | '.join([row['configuration'], fmt(row.get('cycles')),
                    fmt(row['c2_cycles']), fmt(row.get('cycles_change_pct')), fmt(row.get('area_change_pct')),
                    fmt(row.get('diagnostic_time_ms_at_100mhz')), fmt(row.get('diagnostic_atp_slice_ms_at_100mhz')),
                    fmt(row.get('diagnostic_atp_change_pct')), equal, row['status']]) + ' |']
        lines += ['', '## 显式请求的布线', '',
            '只有 `--route` 或 `--route-existing` 明确请求后才启动，同一冻结 RTL 的六项 Sign、'
            '工作量与 100 MHz 综合全部通过后执行。不搜索频率、不新增时序例外。'
            '完整布线、DRC、setup／hold 全通过且实际周期满足目标，才记闭合和计算布线 ATP。', '',
            '| 配置／目标 | 布线 Slice | WNS ns | WHS ns | 状态 |', '|---|---:|---:|---:|---|']
        for name, item in self.state['routing'].items():
            result = item.get('result', {})
            lines += ['| ' + ' | '.join([name, fmt(item.get('area', {}).get('equivalent_slice')),
                fmt(result.get('wns_ns')), fmt(result.get('whs_ns')), item['status']]) + ' |']
        if not self.state['routing']:
            lines += ['| 未请求 | — | — | — | not_requested |']
        lines += ['', '| 闭合任务 | 算法 | 实际受约束频率 MHz | 时间 ms | ATP Slice·ms |',
                  '|---|---|---:|---:|---:|']
        for row in closed:
            lines += ['| ' + ' | '.join([row['task'], row['profile'], fmt(row['closed_frequency_mhz']),
                fmt(row['routed_time_ms']), fmt(row['routed_atp_slice_ms'])]) + ' |']
        errors = [(f'{group}/{key}', item['error']) for group in ('tests', 'synthesis', 'routing')
                  for key, item in self.state[group].items() if item.get('error')]
        if errors:
            lines += ['', '## 未通过项目', ''] + [f'- `{key}`：{error}' for key, error in errors]
        lines += ['', f'运行目录：`{self.run}`。仿真明细留运行目录，归档保留验证摘要、冻结源码与 SHA、'
            '综合／布线分层面积和时序报告及日志。索引由调用方按时间追加。', '']
        archive.atomic(prefix.with_suffix('.md'), '\n'.join(lines))
        missing = {}
        for group, keys in (('synth', self.state['synthesis']), ('route', self.state['routing'])):
            for name in keys:
                folder = self.run / group / name
                for path in folder.rglob('*') if folder.exists() else []:
                    if path.is_file() and path.suffix in ('.rpt', '.log', '.txt', '.xdc', '.json'):
                        archive.copy_changed(path, self.out / group / name / path.relative_to(folder))
                wanted = (['hierarchical.rpt', 'timing.rpt'] if group == 'synth' else
                    ['route/hierarchical.rpt', 'route/timing.rpt', 'route/route_status.rpt', 'route/drc.rpt', 'result.json'])
                missing[f'{group}/{name}'] = [n for n in wanted if not (self.out / group / name / n).is_file()]
        write(self.out / 'ARTIFACTS.json', dict(complete=self.state['complete'], missing=missing,
            omitted_details=['sim', 'validation'], sha256={str(p.relative_to(self.out)): sha(p)
                for p in self.out.rglob('*') if p.is_file() and p.name != 'ARTIFACTS.json'
                and not p.name.endswith('.tmp')}))

    def route(self, p, frequency):
        name = route_name(p, frequency)
        output = self.run / 'route' / name
        output.mkdir(parents=True, exist_ok=True)
        self.update('routing', name, status='waiting_for_capacity')
        self.reserve()
        started = time.monotonic()
        try:
            command = [self.meta['vivado'], '-mode', 'batch', '-nolog', '-nojournal', '-notrace',
                '-source', str(self.source / 'scripts/route_common_target.tcl'), '-tclargs',
                str(self.source), str(p), '1', str(output), str(frequency), '2']
            with (output / 'vivado.log').open('w') as stream:
                process = subprocess.Popen(command, cwd=output, env=dict(os.environ, HASH_BACKEND='shake'),
                    stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                self.update('routing', name, status='running', pid=process.pid, started_at=now(), command=command)
                while process.poll() is None:
                    try:
                        process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        stage_file = output / 'stage.json'
                        stage = read(stage_file).get('stage', 'synthesis') if stage_file.exists() else 'synthesis'
                        self.update('routing', name, elapsed_seconds=time.monotonic() - started, stage=stage,
                            analysis_deferred=stage == 'synthesis' and time.monotonic() - started >= 600)
            require(process.returncode == 0 and 'COMMON_TARGET_PASS' in (output / 'vivado.log').read_text(),
                    f'Vivado failed; see {output / "vivado.log"}')
            require(previous.unchanged(self.meta), 'Frozen source changed')
            result = read(output / 'result.json')
            routing = route_status(output / 'route/route_status.rpt')
            met = (result.get('setup_hold_met') is True and result.get('drc_errors') == 0
                and result.get('wns_ns', -1) >= 0 and result.get('whs_ns', -1) >= 0
                and routing.get('passed') is True and result.get('actual_period_ns', math.inf) > 0
                and result['actual_period_ns'] <= 1000 / frequency + 1e-6)
            self.update('routing', name, status='passed' if met else 'target_not_met', meets_target=met,
                result=result, route_status=routing, area=utilization(output / 'route/utilization.rpt'),
                timing=timing(output / 'route/timing.rpt'), analysis_deferred=False,
                elapsed_seconds=time.monotonic() - started, finished_at=now(), source_unchanged=True,
                source_manifest_sha256=sha(self.run / 'SOURCE.json'),
                routed_checkpoint_sha256=sha(output / 'route/routed.dcp'))
        except Exception as error:
            self.update('routing', name, status='failed', error=str(error), finished_at=now())
        finally:
            with self.capacity_lock:
                self.reserved -= 1

    def execute(self):
        self.publish()
        write(self.run / ('ROUTE_INITIAL_PUBLICATION.json' if self.routes_only else 'INITIAL_PUBLICATION.json'),
              dict(pid=os.getpid(), at=now()))
        if not self.routes_only:
            if self.meta.get('reuse_evidence'):
                evidence = read(self.run / 'REUSE_EVIDENCE.json')
                require(sha(self.run / 'REUSE_EVIDENCE.json') == self.meta['reuse_evidence_sha256'],
                        'Reuse evidence was changed')
                require(source_keys(evidence['source']) == source_keys(self.meta),
                        'Reused evidence source must match every candidate source input')
                self.state['tests'] = deepcopy(evidence['results']['tests'])
                self.state['synthesis'] = deepcopy(evidence['results']['synthesis'])
                for group in ('tests', 'synthesis'):
                    for item in self.state[group].values():
                        item.update(reused_from_run=evidence['run_root'],
                            original_source_manifest_sha256=item['source_manifest_sha256'],
                            source_manifest_sha256=sha(self.run / 'SOURCE.json'))
                for config in self.state['synthesis']:
                    folder = Path(evidence['run_root']) / 'synth' / config
                    for path in folder.rglob('*'):
                        if path.is_file() and path.suffix in ('.rpt', '.log', '.txt', '.xdc', '.json'):
                            archive.copy_changed(path, self.run / 'synth' / config / path.relative_to(folder))
                self.publish()
            else:
                with ThreadPoolExecutor(max_workers=2) as sims, ThreadPoolExecutor(max_workers=2) as synths:
                    futures = [sims.submit(self.simulate_configuration, p) for p in CONFIGS]
                    futures += [synths.submit(self.vivado, p) for p in CONFIGS]
                    for future in as_completed(futures):
                        future.result()
        if self.targets:
            if self.validated():
                with ThreadPoolExecutor(max_workers=4) as pool:
                    for future in as_completed([pool.submit(self.route, p, f) for p in CONFIGS for f in self.targets]):
                        future.result()
            else:
                for name in self.state['routing']:
                    self.update('routing', name, status='blocked_validation',
                                error='Full Sign, frozen-source, same-workload or synthesis validation failed')
        self.state.update(complete=True, finished_at=now(), source_unchanged=previous.unchanged(self.meta))
        self.publish()
        return int(not (self.validated() and all(t['status'] == 'passed' for t in self.state['routing'].values())))


def background(run, routes_only=False):
    runner = run / 'control/run_c2_timing_optimization.py'
    marker = run / ('ROUTE_INITIAL_PUBLICATION.json' if routes_only else 'INITIAL_PUBLICATION.json')
    require(not marker.exists(), 'Worker was already started; refusing duplicate jobs')
    with (run / ('route_runner.log' if routes_only else 'runner.log')).open('w') as stream:
        process = subprocess.Popen([sys.executable, str(runner),
            '--run-routes-only' if routes_only else '--run-root', str(run)], cwd=ROOT,
            env=dict(os.environ, MHBS_C2_TIMING_WORKSPACE=str(ROOT), MHBS_SHAKE_TIMING_WORKSPACE=str(ROOT),
                     MHBS_BACKEND_WORKSPACE=str(ROOT)), stdin=subprocess.DEVNULL,
            stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
    deadline = time.monotonic() + 30
    while not marker.exists():
        if process.poll() is not None or time.monotonic() > deadline:
            raise RuntimeError(f'Initial publication failed; see {run}')
        time.sleep(.1)
    return process.pid


def launch(args):
    baseline = checked_evidence(args.baseline_run.resolve(), c2=True)
    source = (args.source_root or ROOT).resolve()
    tools = {name: shutil.which(os.environ.get(name.upper(), name)) for name in ('vivado', 'verilator')}
    require(all(tools.values()), 'Vivado and Verilator are required')
    versions = {name: subprocess.check_output([path, '-version' if name == 'vivado' else '--version'],
        text=True, timeout=30).strip() for name, path in tools.items()}
    require(versions == baseline['source']['tool_versions'], 'Tool versions differ from C2')
    for profile in PROFILES:
        require(previous.vectors(source, profile) == previous.vectors(Path(baseline['source']['source_root']), profile),
                f'Candidate vectors differ from C2: {profile}')
    # Preserve diagnostic/route settings exactly; change RTL freely, not timing constraints.
    for name in ('scripts/diagnose_timing.tcl', 'scripts/route_common_target.tcl'):
        require(sha(source / name) == baseline['source']['sha256'][name], f'C2 tool-setting script changed: {name}')
    targets = frequencies(args.route_mhz) if args.route else []
    stamp = datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y%m%d_%H%M%S')
    run = ROOT / 'build/c2_timing_optimization' / f'candidate_{stamp}'
    out = archive.ARCHIVES / f'c2_timing_optimization_{stamp}'
    require(not run.exists() and not out.exists(), f'Run exists; retry next second: {run}')
    spec = snapshot(source, run / 'source')
    for base in (run, out):
        write(base / 'C2_BASELINE_EVIDENCE.json', baseline)
    meta = dict(spec, schema=SCHEMA, run_id=stamp, label=args.label, phase='candidate', hash_backend='shake',
        **tools, tool_versions=versions, started_at=now(), archive_directory=str(out),
        configurations=CONFIGS, profiles=PROFILES, top='common', part='xc7a200tffg1156-3',
        synthesis_period_ns=10.0, threads_per_vivado=2, max_total_vivado=12,
        route_requested=bool(args.route), route_frequencies_mhz=targets, frequency_search=False,
        new_timing_exceptions=False, h20_full_keygen_sign_run=False,
        baseline_label='C2', baseline_run=baseline['run_root'], baseline_manifest_sha256=C2_MANIFEST_SHA,
        baseline_evidence_sha256=sha(run / 'C2_BASELINE_EVIDENCE.json'), reuse_evidence=bool(args.reuse_evidence_run))
    if args.reuse_evidence_run:
        evidence = checked_evidence(args.reuse_evidence_run.resolve())
        require(source_keys(evidence['source']) == source_keys(meta),
                'Evidence reuse requires exact checksums of all source, model, script, harness and vector files')
        require(evidence['source']['tool_versions'] == versions, 'Reused evidence tools differ')
        for base in (run, out):
            write(base / 'REUSE_EVIDENCE.json', evidence)
        meta['reuse_evidence_sha256'] = sha(run / 'REUSE_EVIDENCE.json')
    for base in (run, out):
        write(base / 'SOURCE.json', meta)
        for name in CONTROLS:
            archive.copy_changed(ROOT / 'scripts' / name, base / 'control' / name)
        write(base / 'CONTROL_SOURCE.json', {name: sha(base / 'control' / name) for name in CONTROLS})
    previous.archive_source(meta, out)
    pid = background(run)
    report = out / 'reports' / f'C2_Timing_Optimization_{stamp}.md'
    result = dict(pid=pid, root=str(run), report=str(report), baseline='C2',
        simulation_cases=0 if args.reuse_evidence_run else 6,
        reused_simulation_cases=6 if args.reuse_evidence_run else 0,
        diagnostic_syntheses=0 if args.reuse_evidence_run else 2,
        reused_diagnostic_syntheses=2 if args.reuse_evidence_run else 0,
        route_jobs=2 * len(targets))
    write(run / 'LAUNCH.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def request_routes(args):
    run = args.route_existing.resolve()
    runner = Runner(run)
    runner.state = read(run / 'status.json')
    require(runner.state.get('complete') and runner.validated(), 'Existing candidate diagnostics must finish and pass')
    require(not runner.state.get('routing') and not (run / 'ROUTE_REQUEST.json').exists(),
            'Routing already requested; refusing duplicate jobs')
    request = dict(requested_at=now(), frequencies_mhz=frequencies(args.route_mhz),
                   source_manifest_sha256=sha(run / 'SOURCE.json'), explicitly_requested=True)
    for base in (run, runner.out):
        write(base / 'ROUTE_REQUEST.json', request)
    print(json.dumps(dict(pid=background(run, routes_only=True), root=str(run),
                         route_jobs=2 * len(request['frequencies_mhz'])), indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--launch-candidate', action='store_true')
    group.add_argument('--route-existing', type=Path)
    group.add_argument('--inspect-baseline', action='store_true', help='Validate C2 evidence; start no jobs')
    group.add_argument('--run-root', type=Path, help=argparse.SUPPRESS)
    group.add_argument('--run-routes-only', type=Path, help=argparse.SUPPRESS)
    group.add_argument('--refresh-run', type=Path, help='Republish completed evidence; start no jobs')
    parser.add_argument('--baseline-run', type=Path, default=C2_RUN, help='Exact C2/211601 only; no B0 baseline')
    parser.add_argument('--source-root', type=Path)
    parser.add_argument('--label', default='C2-based candidate')
    parser.add_argument('--reuse-evidence-run', type=Path,
                        help='Optional unchanged-source measured evidence; every source and tool checksum must match')
    parser.add_argument('--route', action='store_true', help='Explicitly request routes after all validation passes')
    parser.add_argument('--route-mhz', nargs='+', type=float, default=[150.0, 130.0])
    args = parser.parse_args()
    if args.inspect_baseline:
        evidence = checked_evidence(args.baseline_run, c2=True)
        print(json.dumps(dict(baseline='C2', validated=True, manifest_sha256=evidence['manifest_sha256'],
            measured_sign_cases=6, diagnostic_syntheses=2,
            cycles={k: v['cycles'] for k, v in evidence['results']['tests'].items()}), indent=2))
        return 0
    if args.refresh_run:
        runner = Runner(args.refresh_run.resolve())
        runner.state = read(runner.run / 'status.json')
        require(runner.state.get('complete'), 'Active worker owns its files; refresh requires completion')
        require(previous.unchanged(runner.meta), 'Frozen candidate source changed')
        runner.publish()
        return 0
    if args.route_existing:
        request_routes(args)
        return 0
    if args.run_root or args.run_routes_only:
        return Runner(args.run_routes_only or args.run_root, routes_only=bool(args.run_routes_only)).execute()
    launch(args)
    return 0


if __name__ == '__main__':
    sys.exit(main())
