#!/usr/bin/env python3
"""Freeze one generic K candidate; diagnose, validate, then route focused points.

Only --launch starts hardware. All work uses the same immutable snapshot and
ends naturally; report polling is globally limited to once every 60 seconds.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
from zoneinfo import ZoneInfo

import run_dual_pu_route_matrix as dual

ROOT = Path(os.environ.get('MHBS_K_WORKSPACE', dual.ROOT)).resolve()
dual.ROOT = dual.archive.ROOT = ROOT
dual.archive.ARCHIVES = ROOT / 'docs/manifests/experiments'
dual.CONFIGS = [(1, 1), (4, 1), (12, 1), (4, 2)]
dual.BACKENDS = ('shake', 'sha2')
dual.REPORT_REFRESH_SECONDS = 60
CONFIGS = tuple(dual.route_key(b, p, u) for p, u in dual.CONFIGS for b in dual.BACKENDS)
CONTROLS = ('run_shake_p1_timing_k.py', *dual.CONTROLS,
            'diagnose_timing.tcl', 'validate_p1sha_candidate.py')
BASELINES = (
    ('build/dual_pu_route_matrix/20261022_153940',
     'cc56b2557f0f5027d6c3cea53e2b4b9bff468a15efa50df664f51689d7ff3c68'),
    ('build/atp_j/candidate_20261022_132749',
     'e59fee9453346d684880b1e0e2ac2ec45a815d0ef764263f36642905ec85a7c7'),
)
read, write, sha, now = dual.read, dual.write, dual.sha, dual.now


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def reference_evidence():
    """Use completed native tests only; never substitute another P/U's area."""
    evidence = dict(tests={}, routes={}, sources=[])
    for name, expected in BASELINES:
        native = ROOT / name
        require(sha(native / 'SOURCE.json') == expected, 'Baseline SOURCE changed: ' + name)
        meta, state = read(native / 'SOURCE.json'), read(native / 'status.json')
        require(all(sha(Path(meta['source_root']) / n) == h for n, h in meta['sha256'].items()),
                'Baseline frozen files changed: ' + name)
        evidence['sources'].append(dict(run=str(native), source_manifest_sha256=expected,
                                       label=meta.get('label', native.name)))
        physical = read(native / 'PHYSICAL_STATUS.json').get('routes', {}) if (
            native / 'PHYSICAL_STATUS.json').exists() else state.get('routes', {})
        for config in CONFIGS:
            if config not in evidence['routes'] and config in physical:
                route = deepcopy(physical[config])
                if route.get('status') in ('passed', 'target_not_met'):
                    route.update(native_run=str(native), native_source_manifest_sha256=expected)
                    evidence['routes'][config] = route
            for profile in dual.PROFILES:
                key = config + '/' + profile
                test = deepcopy(state['tests'].get(key, {}))
                if key in evidence['tests'] or test.get('status') != 'passed':
                    continue
                require(test.get('source_unchanged') and test['source_manifest_sha256'] == expected
                        and test.get('output_and_signature_cache_checked_bytewise'),
                        'Unbound baseline Sign: ' + key)
                for field in ('log', 'raw_log'):
                    require(sha(test[field]) == test[field + '_sha256'], 'Baseline log changed: ' + key)
                require(all(meta['sha256'][n] == h == sha(Path(meta['source_root']) / n)
                            for n, h in test['vectors_sha256'].items()), 'Baseline vector changed: ' + key)
                test.update(native_run=str(native), native_source_manifest_sha256=expected)
                evidence['tests'][key] = test
    return evidence


def timing(path):
    text = path.read_text(errors='replace')
    result = {}
    for key, pattern, cast in (
        ('data_path_ns', r'Data Path Delay:\s+([\d.]+)ns', float),
        ('logic_levels', r'Logic Levels:\s+(\d+)', int),
        ('source', r'^  Source:\s+(.+)$', str),
        ('destination', r'^  Destination:\s+(.+)$', str),
    ):
        match = re.search(pattern, text, re.M)
        if match:
            result[key] = cast(match[1])
    return result


def closed(route, u):
    result = route.get('result', {})
    return bool(route.get('status') == 'passed' and route.get('source_unchanged')
                and result.get('setup_hold_met') and result.get('drc_errors') == 0
                and route.get('route_status', {}).get('passed')
                and result.get('actual_period_ns', float('inf')) <= 1000 / (150 if u == 1 else 100))


class Runner(dual.Runner):
    def __init__(self, run):
        super().__init__(run)
        self.reference = read(self.run / 'REFERENCE_EVIDENCE.json')
        self.state.update(schema='mhbs.shake_p1_timing_k.results.v1',
                          synthesis={c: dict(status='pending') for c in CONFIGS},
                          functional=dict(status='pending'))
        self.changed = threading.Condition(self.lock)

    def update(self, group, key, **values):
        # Apply workload equality before exposing a passed test to route gates.
        old = self.reference['tests'].get(key) if group == 'tests' else None
        if old and values.get('status') == 'passed':
            equal = all(values.get(n) == old[n] for n in ('hashes', 'permutations', 'vectors_sha256'))
            values['baseline_workload_equal'] = equal
            if not equal:
                values.update(status='failed', error='Native baseline Hash/compression/vector workload differs')
        with self.changed:
            super().update(group, key, **values)
            self.changed.notify_all()

    def synthesize(self, backend, p, u):
        config = dual.route_key(backend, p, u)
        output = self.run / 'synth' / config
        output.mkdir(parents=True, exist_ok=True)
        self.update('synthesis', config, status='waiting_for_capacity')
        self.capacity_token.worker_marker = str(output)
        self.reserve()
        started = time.monotonic()
        try:
            command = [self.meta['vivado'], '-mode', 'batch', '-nolog', '-nojournal', '-notrace',
                       '-source', str(self.run / 'control/diagnose_timing.tcl'), '-tclargs',
                       str(self.source), str(p), str(u), str(output), '10.0']
            with (output / 'vivado.log').open('w') as stream:
                process = subprocess.Popen(command, cwd=output, stdin=subprocess.DEVNULL,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True,
                    env=dict(os.environ, HASH_BACKEND=backend))
                self.update('synthesis', config, status='running', pid=process.pid,
                            started_at=now(), command=command, log=str(output / 'vivado.log'))
                while process.poll() is None:
                    try:
                        process.wait(timeout=60)
                    except subprocess.TimeoutExpired:
                        elapsed = time.monotonic() - started
                        self.update('synthesis', config, elapsed_seconds=elapsed, analysis_deferred=elapsed >= 600)
            require(process.returncode == 0 and f'MHBS_TIMING_DIAGNOSTIC_PASS P{p}U{u}' in
                    (output / 'vivado.log').read_text(errors='replace'), 'Diagnostic synthesis failed')
            require(self.unchanged(), 'Frozen source changed')
            self.update('synthesis', config, status='passed', source_unchanged=True,
                source_manifest_sha256=self.state['source_manifest_sha256'],
                area=dual.resources(output / 'utilization.rpt'), timing=timing(output / 'critical_paths.rpt'),
                reports_sha256={f.name: sha(f) for f in output.iterdir()
                               if f.is_file() and f.suffix in ('.rpt', '.log', '.txt', '.xdc')},
                checkpoint_sha256=sha(output / 'synthesized.dcp'), analysis_deferred=False,
                elapsed_seconds=time.monotonic()-started, finished_at=now())
        except Exception as error:
            self.update('synthesis', config, status='failed', error=str(error), finished_at=now())
        finally:
            self.release_capacity()
            with self.capacity_lock:
                self.reserved -= 1

    def validate(self):
        log = self.run / 'functional_validator.log'
        self.state['functional'] = dict(status='running', started_at=now(), log=str(log))
        try:
            command = [sys.executable, str(self.source / 'scripts/validate_p1sha_candidate.py'),
                       '--run-root', str(self.run)]
            with log.open('w') as stream:
                process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                with self.lock:
                    self.state['functional'].update(pid=process.pid, command=command)
                process.wait()
            proof = read(self.run / 'functional_validation/VALIDATION.json')
            require(process.returncode == 0 and proof.get('complete') and proof.get('total_planned') == 36
                    and proof.get('passed') == 36 and proof.get('failed') == 0 and proof.get('source_unchanged'),
                    'Functional 36-group validation failed')
            require(proof['source_manifest_sha256'] == self.state['source_manifest_sha256'],
                    'Functional source identity differs')
            require(sha(self.run / 'functional_validation/validator.py') == proof['validator_sha256'],
                    'Validator identity differs')
            for test in proof['tests']:
                require(test['passed'] and sha(test['log']) == test['log_sha256'], 'Functional log changed')
            with self.changed:
                self.state['functional'].update(status='passed', summary=proof, finished_at=now())
                self.changed.notify_all()
        except Exception as error:
            with self.changed:
                self.state['functional'].update(status='failed', error=str(error), finished_at=now())
                self.changed.notify_all()
        self.publish()

    def route(self, backend, p, u):
        config = dual.route_key(backend, p, u)
        with self.changed:
            while True:
                jobs = [self.state['synthesis'][config], self.state['functional']]
                jobs += [self.state['tests'][config + '/' + profile] for profile in dual.PROFILES]
                if any(t['status'] in ('failed', 'error') for t in jobs):
                    self.update('routes', config, status='validation_failed')
                    return
                if all(t['status'] == 'passed' for t in jobs):
                    break
                self.update('routes', config, status='waiting_for_validation')
                self.changed.wait(timeout=60)
        try:
            require(self.unchanged(), 'Frozen candidate changed before route')
            diagnostic = self.state['synthesis'][config]
            for name, wanted in diagnostic['reports_sha256'].items():
                require(sha(self.run / 'synth' / config / name) == wanted, 'Diagnostic report changed')
            require(sha(self.run / 'synth' / config / 'synthesized.dcp') == diagnostic['checkpoint_sha256'],
                    'Diagnostic checkpoint changed')
            for profile in dual.PROFILES:
                test = self.state['tests'][config + '/' + profile]
                for name in ('log', 'raw_log'):
                    require(sha(test[name]) == test[name + '_sha256'], 'Sign log changed')
            super().route(backend, p, u)
            item = self.state['routes'][config]
            if 'result' in item:
                strict = closed(item, u)
                self.update('routes', config, status='passed' if strict else 'target_not_met', meets_target=strict)
        except Exception as error:
            self.update('routes', config, status='validation_failed', error=str(error))

    def rows(self):
        rows = super().rows()
        for row in rows:
            config = row['hash_backend'] + '/' + row['configuration']
            old = self.reference['tests'].get(config + '/' + row['profile'], {})
            route = self.reference['routes'].get(config, {})
            row.update(baseline_cycles=old.get('cycles'), cycles_change_pct=None,
                       baseline_workload_equal=None, baseline_routed_atp=None, routed_atp_change_pct=None)
            if old and row['cycles'] is not None:
                row['cycles_change_pct'] = 100 * (row['cycles'] / old['cycles'] - 1)
                test = self.state['tests'][config + '/' + row['profile']]
                row['baseline_workload_equal'] = all(test.get(n) == old[n]
                    for n in ('hashes', 'permutations', 'vectors_sha256'))
                u = int(row['configuration'].split('U')[1])
                if closed(route, u):
                    row['baseline_routed_atp'] = (route['routed_area']['equivalent_slice']
                        * old['cycles'] * route['result']['actual_period_ns'] / 1e6)
                    if row['routed_atp_slice_ms'] is not None:
                        row['routed_atp_change_pct'] = 100 * (row['routed_atp_slice_ms'] / row['baseline_routed_atp'] - 1)
            diagnostic = self.state['synthesis'][config]
            row['diagnostic_assumed_atp'] = (diagnostic['area']['equivalent_slice'] * row['target_time_ms']
                if diagnostic['status'] == 'passed' and row['target_time_ms'] is not None else None)
        return rows

    def _publish(self):
        # Parent writes the area/three algorithm tables, provenance and inventory.
        super()._publish()
        prefix = self.out / 'reports' / ('Dual_PU_Route_Matrix_' + self.meta['run_id'])
        target = self.out / 'reports' / ('SHAKE_P1_Timing_K_' + self.meta['run_id'])
        text = prefix.with_suffix('.md').read_text()
        text = text.replace('# SHAKE／SHA2：14点P/U面积、周期与固定频率布线', '# K：SHAKE P1时序与共享控制优化')
        text = text.replace('两个后端各14个common核，28次指定频率重新综合与布局布线；',
                            '两个后端各4个common核，8次100MHz诊断及8次指定频率重新综合与布局布线；')
        text = text.replace('完整Sign共84项。', '完整Sign共24项。')
        fmt = lambda value: '—' if value is None else f'{value:,.3f}'
        lines = ['', '## 100MHz common诊断与验证', '',
                 '100MHz只用于面积/关键路径诊断，不作为Fmax或最终频率验收。'
                 '每点自身诊断和三个Sign、全局36组功能验证通过后独立启动布线，不等待其他异常点。', '',
                 '| 配置 | LUT | FF | BRAM36 | 等效Slice | 路径ns | 级数 | 状态 |',
                 '|---|---:|---:|---:|---:|---:|---:|---|']
        for config, job in self.state['synthesis'].items():
            area, path = job.get('area', {}), job.get('timing', {})
            lines.append('| ' + ' | '.join([config, *[fmt(area.get(n)) for n in
                ('lut', 'ff', 'bram36', 'equivalent_slice')], fmt(path.get('data_path_ns')),
                fmt(path.get('logic_levels')), job['status'] + ('；analysis_deferred' if job.get('analysis_deferred') else '')]) + ' |')
        proof = self.state['functional'].get('summary', {})
        lines += ['', f'全局36组功能验证：{self.state["functional"]["status"]}；{proof.get("passed", 0)}/36。', '',
                  '## 同配置基线对照', '',
                  '优先采用153940失败矩阵中已通过的原生Sign，其次J1；仅比较同后端同P/U同算法的实测数据。'
                  '基线未闭合时不填写实际ATP。原生SOURCE校验及原始日志路径见REFERENCE_EVIDENCE.json。', '',
                  '| 后端/配置 | 算法 | 基线周期 | 周期变化% | 工作量相同 | 基线布线ATP | ATP变化% |',
                  '|---|---|---:|---:|---|---:|---:|']
        for row in self.state['results']:
            lines.append('| ' + ' | '.join([row['hash_backend'] + '/' + row['configuration'], row['profile'],
                fmt(row['baseline_cycles']), fmt(row['cycles_change_pct']), str(row['baseline_workload_equal']),
                fmt(row['baseline_routed_atp']), fmt(row['routed_atp_change_pct'])]) + ' |')
        dual.archive.atomic(target.with_suffix('.md'), text + '\n'.join(lines) + '\n')
        write(target.with_suffix('.json'), dict(source=self.meta, results=self.state,
                                               reference=self.reference, diagnostic_is_not_fmax=True))
        prefix.with_suffix('.md').unlink()
        prefix.with_suffix('.json').unlink()
        for folder in ('synth',):
            for path in (self.run / folder).rglob('*') if (self.run / folder).exists() else []:
                if path.is_file() and path.suffix in ('.rpt', '.log', '.json', '.txt', '.xdc'):
                    dual.archive.copy_changed(path, self.out / path.relative_to(self.run))
        summary = self.run / 'functional_validation/VALIDATION.json'
        if summary.exists():
            dual.archive.copy_changed(summary, self.out / 'supplementary_evidence/functional/SUMMARY.json')
        artifact = read(self.out / 'ARTIFACTS.json')
        artifact.update(missing_diagnostic_reports={c: [n for n in ('hierarchical.rpt', 'timing.rpt')
            if not (self.out / 'synth' / c / n).exists()] for c in CONFIGS},
            sha256={str(p.relative_to(self.out)): sha(p) for p in self.out.rglob('*')
                    if p.is_file() and p.name != 'ARTIFACTS.json' and not p.name.endswith('.tmp')})
        write(self.out / 'ARTIFACTS.json', artifact)

    def execute(self):
        self.publish(force=True)
        dual.archive.index()
        write(self.run / 'INITIAL_PUBLICATION.json', dict(pid=os.getpid(), at=now()))
        finished = threading.Event()

        def refresh():
            while not finished.wait(60):
                self.publish()

        monitor = threading.Thread(target=refresh, name='report-60s', daemon=True)
        monitor.start()
        try:
            with ThreadPoolExecutor(max_workers=8) as diagnostics, ThreadPoolExecutor(max_workers=4) as simulations, \
                    ThreadPoolExecutor(max_workers=8) as routes, ThreadPoolExecutor(max_workers=1) as validation:
                jobs = [validation.submit(self.validate)]
                for p, u in dual.CONFIGS:
                    for backend in dual.BACKENDS:
                        jobs += [diagnostics.submit(self.synthesize, backend, p, u),
                                 simulations.submit(self.simulate, backend, p, u),
                                 routes.submit(self.route, backend, p, u)]
                for future in as_completed(jobs):
                    future.result()
            with self.lock:
                self.state.update(complete=True, finished_at=now(), source_unchanged=self.unchanged())
                self.publish(force=True)
            dual.archive.index()
            return int(not self.state['source_unchanged'] or self.state['functional']['status'] != 'passed'
                or any(t['status'] != 'passed' for group in ('synthesis', 'tests', 'routes') for t in self.state[group].values()))
        finally:
            finished.set()
            monitor.join(timeout=5)


def launch(label):
    tools = {n: shutil.which(os.environ.get(n.upper(), n)) for n in ('vivado', 'verilator')}
    require(all(tools.values()), 'Vivado and Verilator are required')
    reference = reference_evidence()
    stamp = datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y%m%d_%H%M%S')
    run = ROOT / 'build/shake_p1_timing_k' / stamp
    out = dual.archive.ARCHIVES / ('shake_p1_timing_k_' + stamp)
    require(not run.exists() and not out.exists(), 'Run already exists')
    checks = dual.frozen_snapshot(ROOT, run / 'source')
    meta = dict(schema='mhbs.p1sha_atp.source.v1', experiment_family='shake_p1_timing_k',
        kind='candidate', label=label, run_id=stamp, started_at=now(), source_root=str(run / 'source'),
        archive_directory=str(out), sha256=checks, **tools,
        rtl_files=[n for n in (ROOT / 'sources.txt').read_text().splitlines() if n.strip()],
        tool_versions={n: subprocess.check_output([p, '-version' if n == 'vivado' else '--version'],
                       text=True, timeout=30).strip() for n, p in tools.items()},
        base_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        configs=CONFIGS, backends=dual.BACKENDS, profiles=dual.PROFILES, top='common', operation='sign',
        part='xc7a200tffg1156-3', vivado_workers=12, threads_per_vivado=2, simulation_workers=4,
        synthesis_period_ns=10.0, targets_mhz={'1': 150, '2': 100}, report_refresh_seconds=60,
        analysis_defer_seconds=600, explicit_user_authorization=True,
        frequency_search=False, automatic_frequency_fallback=False,
        new_timing_exceptions=False, h20_full_keygen_sign_run=False)
    for base in (run, out):
        write(base / 'SOURCE.json', meta)
        write(base / 'REFERENCE_EVIDENCE.json', reference)
        for name in CONTROLS:
            dual.archive.copy_changed(ROOT / 'scripts' / name, base / 'control' / name)
        write(base / 'CONTROL_SOURCE.json', {name: sha(base / 'control' / name) for name in CONTROLS})
    dual.archive.pack_rtl(run / 'source', out / 'rtl.tar.gz', checks)
    support = {n: h for n, h in checks.items() if not n.startswith('rtl/') and n != 'sources.txt'}
    with tarfile.open(out / 'support.tar.gz', 'w:gz') as tar:
        for name, wanted in support.items():
            require(sha(run / 'source' / name) == wanted, 'Frozen support changed')
            tar.add(run / 'source' / name, arcname=name, recursive=False)
    write(out / 'SUPPORT_SOURCE.json', support)
    with (run / 'runner.log').open('w') as stream:
        process = subprocess.Popen([sys.executable, str(run / 'control/run_shake_p1_timing_k.py'),
            '--run-root', str(run)], cwd=ROOT,
            env=dict(os.environ, MHBS_K_WORKSPACE=str(ROOT), MHBS_DUAL_MATRIX_WORKSPACE=str(ROOT)),
            stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
    deadline = time.monotonic() + 30
    while not (run / 'INITIAL_PUBLICATION.json').exists():
        require(process.poll() is None and time.monotonic() < deadline, 'Initial publication failed: ' + str(run / 'runner.log'))
        time.sleep(.1)
    result = dict(pid=process.pid, run_root=str(run), source_manifest_sha256=sha(run / 'SOURCE.json'),
        report=str(out / 'reports' / ('SHAKE_P1_Timing_K_' + stamp + '.md')),
        diagnostic_common=8, complete_sign=24, functional_groups=36, fixed_target_routes=8,
        report_refresh_seconds=60, max_total_vivado=12, threads_per_vivado=2)
    write(run / 'LAUNCH.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--launch', action='store_true')
    mode.add_argument('--run-root', type=Path)
    parser.add_argument('--label', default='K1')
    args = parser.parse_args()
    if args.launch:
        import json
        print(json.dumps(launch(args.label), ensure_ascii=False, indent=2))
    else:
        raise SystemExit(Runner(args.run_root).execute())
