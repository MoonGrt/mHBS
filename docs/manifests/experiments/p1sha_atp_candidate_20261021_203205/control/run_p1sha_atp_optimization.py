#!/usr/bin/env python3
"""Freeze focused P1/SHA candidates; diagnose at 100 MHz, route only explicitly.

The baseline reuses only source-checked, already executed complete Sign tests and
physical jobs from the 20261021_193612 dual matrix. Relaxed-clock synthesis is
performed again for a like-for-like diagnostic comparison. Routing requires a
separate --route-existing command after all candidate Sign and synthesis pass.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime
import hashlib
import json
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

import experiment_archive as archive
import run_dual_pu_route_matrix as dual
from report_timing_focus import timing
from run_pu_route_matrix import live_vivado, resources, route_status

ROOT = Path(os.environ.get('MHBS_P1SHA_WORKSPACE', Path(__file__).resolve().parents[1])).resolve()
archive.ROOT = dual.ROOT = ROOT
archive.ARCHIVES = ROOT / 'docs/manifests/experiments'
MATRIX = ROOT / 'build/dual_pu_route_matrix/20261021_193612'
BASELINE = ROOT / 'build/p1sha_atp_optimization/baseline_20261021_202753'
BASELINE_MANIFEST = '4fe3963885ffb04b710a3475285fba269f654d7ca7c009f0ae94bcff5c75e185'
CONFIGS = ('shake/P1U1', 'shake/P1U2', 'sha2/P1U1', 'sha2/P1U2',
           'sha2/P4U1', 'sha2/P4U2', 'sha2/P12U1')
ROUTE_CONFIGS = CONFIGS[:-1]
PROFILES = dual.PROFILES
CONTROLS = ('run_p1sha_atp_optimization.py', 'run_dual_pu_route_matrix.py',
            'experiment_archive.py', 'run_pu_route_matrix.py', 'report_timing_focus.py',
            'diagnose_timing.tcl', 'route_common_target.tcl')


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def now():
    return datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds')


sha, read, write = dual.sha, dual.read, dual.write


def parts(config):
    match = re.fullmatch(r'(shake|sha2)/P(\d+)U(\d+)', config)
    require(match is not None, 'Invalid configuration: ' + config)
    backend, p, u = match.groups()
    return backend, int(p), int(u)


def unchanged(meta):
    source = Path(meta['source_root'])
    return all((source / name).is_file() and sha(source / name) == value
               for name, value in meta['sha256'].items())


def import_matrix(meta, configs):
    """Import measured records, verifying RTL, harness, vector and raw-log SHA."""
    original = read(MATRIX / 'SOURCE.json')
    state = read(MATRIX / 'status.json')
    matrix_sha = sha(MATRIX / 'SOURCE.json')
    source = Path(original['source_root'])
    require(unchanged(original), 'Matrix frozen source has changed')
    for name in meta['rtl_files'] + ['sources.txt', 'tb/tb_fast.sv', 'tb/fast_main.cpp',
                                     'scripts/simulate_fast.sh']:
        require(meta['sha256'].get(name) == original['sha256'].get(name),
                'Baseline differs from executed matrix: ' + name)
    tests, routes, artifacts = {}, {}, {}
    for config in configs:
        backend, p, u = parts(config)
        for profile in PROFILES:
            key = config + '/' + profile
            test = deepcopy(state['tests'][key])
            require(test.get('status') == 'passed' and test.get('source_unchanged') is True
                    and test.get('source_manifest_sha256') == matrix_sha
                    and test.get('output_and_signature_cache_checked_bytewise') is True,
                    'Incomplete or unbound Sign evidence: ' + key)
            for field in ('log', 'raw_log'):
                log = Path(test[field])
                require(log.is_file() and sha(log) == test[field + '_sha256'],
                        'Missing/changed Sign log: ' + key + '/' + field)
            vectors = source / 'tb/vectors'
            if backend == 'sha2':
                vectors /= 'sha2'
            vectors /= profile + '/sign'
            expected = {str(f.relative_to(source)): sha(f) for f in sorted(vectors.glob('*.mem'))}
            require(test['vectors_sha256'] == expected, 'Matrix vector manifest changed: ' + key)
            require(all(meta['sha256'].get(n) == h for n, h in expected.items()),
                    'Baseline vectors differ: ' + key)
            hashes = [int(n, 16) for n in (vectors / 'meta.mem').read_text().split()]
            require(test['hashes'] == hashes[1] and test['permutations'] == hashes[2],
                    'Matrix workload counts differ: ' + key)
            measured = re.search(rf'STATEFUL_PASS P{p}U{u} op=1 cycles=(\d+) total=(\d+) '
                                 r'hashes=(\d+) permutations=(\d+)',
                                 Path(test['log']).read_text(errors='replace'))
            require(measured is not None and all(test[n] == int(measured[i]) for i, n in
                    enumerate(('cycles', 'total_cycles', 'hashes', 'permutations'), 1)),
                    'Sign log values differ: ' + key)
            test.update(reused_from=str(MATRIX), reused_source_manifest_sha256=matrix_sha)
            tests[key] = test
        route = deepcopy(state['routes'][config])
        require(route['status'] in ('passed', 'target_not_met') and route.get('source_unchanged'),
                'Physical evidence not complete: ' + config)
        directory = MATRIX / 'jobs' / config
        require(route['synth_area'] == resources(directory / 'synth/utilization.rpt')
                and route['routed_area'] == resources(directory / 'route/utilization.rpt')
                and route['route_status'] == route_status(directory / 'route/route_status.rpt'),
                'Matrix physical values differ from reports: ' + config)
        for name in ('synth/synthesized.dcp', 'route/routed.dcp'):
            field = 'synthesized_checkpoint_sha256' if name.startswith('synth') else 'routed_checkpoint_sha256'
            require(sha(directory / name) == route[field], 'Matrix checkpoint changed: ' + config)
        route.update(reused_from=str(directory), reused_source_manifest_sha256=matrix_sha)
        routes[config] = route
        for f in directory.rglob('*'):
            if f.is_file() and f.suffix in ('.rpt', '.log', '.txt', '.xdc', '.json'):
                artifacts[str(f)] = sha(f)
    return dict(checked_at=now(), matrix_run=str(MATRIX), source_manifest_sha256=matrix_sha,
                rtl_harness_vectors_match=True, logs_and_reports_checked=True,
                tests=tests, routing=routes, artifacts_sha256=artifacts)


def freeze_controls(run, out):
    for name in CONTROLS:
        require((ROOT / 'scripts' / name).is_file(), 'Missing control: ' + name)
        for destination in (run, out):
            archive.copy_changed(ROOT / 'scripts' / name, destination / 'control' / name)
    checks = {n: sha(run / 'control' / n) for n in CONTROLS}
    for destination in (run, out):
        write(destination / 'CONTROL_SOURCE.json', checks)


def pack_support(source, out, checks):
    names = sorted(n for n in checks if not n.startswith('rtl/') and n != 'sources.txt')
    with tarfile.open(out / 'support.tar.gz', 'w:gz') as tar:
        for name in names:
            require(sha(source / name) == checks[name], 'Support changed: ' + name)
            tar.add(source / name, arcname=name, recursive=False)
    write(out / 'SUPPORT_SOURCE.json', {n: checks[n] for n in names})


def tool_settings():
    tools = {name: shutil.which(os.environ.get(name.upper(), name)) for name in ('vivado', 'verilator')}
    require(all(tools.values()), 'Vivado and Verilator required')
    return dict(**tools, tool_versions={n: subprocess.check_output([p,
        '-version' if n == 'vivado' else '--version'], text=True, timeout=30).strip()
        for n, p in tools.items()}, vivado_workers=12, threads_per_vivado=2,
        simultaneous_measurement_jobs=3, simulation_workers=4, part='xc7a200tffg1156-3',
        top='common', synthesis_period_ns=10.0, targets_mhz={'1': 150, '2': 100},
        new_timing_exceptions=False, h20_full_keygen_sign_run=False)


class Runner(dual.Runner):
    def __init__(self, run, routes_only=False):
        self.run = Path(run).resolve()
        self.meta = dict(read(self.run / 'SOURCE.json'), **read(self.run / 'EXPERIMENT.json'))
        self.source = Path(self.meta['source_root'])
        self.out = Path(self.meta['archive_directory'])
        self.lock, self.capacity_lock = threading.RLock(), threading.Lock()
        self.reserved, self.copied, self.checksums = 0, {}, {}
        self.base = read(self.run / 'MATRIX_EVIDENCE.json')
        self.configs = self.meta['configs']
        self.routes_only = routes_only
        if routes_only:
            self.state = read(self.run / 'status.json')
            require(self.state['complete'] and self.validated(), 'Routes require all focused Sign and diagnostics pass')
            self.state.update(complete=False, routing_started_at=now(), pid=os.getpid())
            request = read(self.run / 'ROUTE_REQUEST.json')
            require(request['source_manifest_sha256'] == sha(self.run / 'SOURCE.json'), 'Route request source differs')
            for config in request['configs']:
                self.state['routing'][config] = dict(status='pending')
            self.route_configs = request['configs']
        else:
            reused = self.meta['kind'] == 'baseline'
            self.state = dict(schema='mhbs.p1sha_atp.results.v1', label=self.meta['label'],
                pid=os.getpid(), started_at=now(), complete=False, source_manifest_sha256=sha(self.run / 'SOURCE.json'),
                tests=deepcopy(self.base['tests']) if reused else {
                    config + '/' + profile: dict(status='pending') for config in self.configs for profile in PROFILES},
                synthesis={config: dict(status='pending') for config in self.configs},
                routing=deepcopy(self.base['routing']) if reused else {})

    def validated(self):
        return (self.unchanged() and all(t['status'] == 'passed' for t in self.state['tests'].values())
                and all(t['status'] == 'passed' for t in self.state['synthesis'].values())
                and all(row.get('workload_equal') for row in self.rows()))

    def synthesize(self, config):
        backend, p, u = parts(config)
        output = self.run / 'synth' / config
        output.mkdir(parents=True, exist_ok=True)
        self.update('synthesis', config, status='waiting_for_capacity')
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
                self.update('synthesis', config, status='running', pid=process.pid, started_at=now(), command=command)
                while process.poll() is None:
                    try:
                        process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        elapsed = time.monotonic() - started
                        self.update('synthesis', config, elapsed_seconds=elapsed, analysis_deferred=elapsed >= 600)
            require(not process.returncode and f'MHBS_TIMING_DIAGNOSTIC_PASS P{p}U{u}' in
                    (output / 'vivado.log').read_text(errors='replace'), 'Diagnostic synthesis failed: ' + config)
            require(self.unchanged(), 'Frozen source changed')
            self.update('synthesis', config, status='passed', area=resources(output / 'utilization.rpt'),
                timing=timing(output / 'critical_paths.rpt'), source_unchanged=True,
                source_manifest_sha256=self.state['source_manifest_sha256'],
                reports_sha256={f.name: sha(f) for f in output.iterdir()
                    if f.is_file() and f.suffix in ('.rpt', '.log', '.txt', '.xdc')},
                checkpoint_sha256=sha(output / 'synthesized.dcp'),
                elapsed_seconds=time.monotonic()-started, analysis_deferred=False, finished_at=now())
        except Exception as error:
            self.update('synthesis', config, status='failed', error=str(error), finished_at=now())
        finally:
            with self.capacity_lock:
                self.reserved -= 1

    def route(self, backend, p, u):
        # The inherited implementation writes the "routes" group. Alias only
        # while this explicitly invoked physical phase is active.
        return super().route(backend, p, u)

    def update(self, group, key, **values):
        return super().update('routing' if group == 'routes' else group, key, **values)

    def rows(self):
        rows = []
        baseline_status = read(BASELINE / 'status.json') if (BASELINE / 'status.json').exists() else {}
        for config in self.configs:
            _, p, u = parts(config)
            syn = self.state['synthesis'][config]
            physical = self.state['routing'].get(config, {})
            for profile in PROFILES:
                key = config + '/' + profile
                test, old = self.state['tests'][key], self.base['tests'][key]
                row = dict(config=config, profile=profile, status=test['status'],
                    cycles=test.get('cycles'), baseline_cycles=old['cycles'], hashes=test.get('hashes'),
                    permutations=test.get('permutations'), target_mhz=150 if u == 1 else 100,
                    workload_equal=None, diagnostic_equivalent_slice=None, diagnostic_atp=None,
                    baseline_diagnostic_equivalent_slice=None, diagnostic_atp_change_pct=None,
                    routed_atp=None, routed_frequency_mhz=None, routed_time_ms=None)
                if test['status'] == 'passed':
                    row.update(workload_equal=all(test.get(n) == old[n] for n in
                        ('hashes', 'permutations', 'vectors_sha256')),
                        cycles_change_pct=100*(test['cycles']/old['cycles']-1),
                        assumed_target_time_ms=test['cycles']/(row['target_mhz']*1000))
                    if syn['status'] == 'passed':
                        area = syn['area']['equivalent_slice']
                        row.update(diagnostic_equivalent_slice=area,
                            diagnostic_atp=area*test['cycles']/(row['target_mhz']*1000))
                        old_syn = baseline_status.get('synthesis', {}).get(config, {})
                        if old_syn.get('status') == 'passed':
                            old_area = old_syn['area']['equivalent_slice']
                            row.update(baseline_diagnostic_equivalent_slice=old_area,
                                diagnostic_area_change_pct=100*(area/old_area-1),
                                diagnostic_atp_change_pct=100*(area*test['cycles']/(old_area*old['cycles'])-1))
                    if physical.get('meets_target') and physical.get('source_unchanged'):
                        period = physical['result']['actual_period_ns']
                        row.update(routed_frequency_mhz=1000/period,
                            routed_time_ms=test['cycles']*period/1e6,
                            routed_atp=physical['routed_area']['equivalent_slice']*test['cycles']*period/1e6)
                rows.append(row)
        return rows

    def publish(self):
        self.state['updated_at'] = now()
        self.state['counts'] = {g: {s: sum(t['status'] == s for t in self.state[g].values())
            for s in sorted({t['status'] for t in self.state[g].values()})}
            for g in ('tests', 'synthesis', 'routing')}
        self.state['rows'] = self.rows()
        self.state['validation_passed'] = self.validated()
        for base in (self.run, self.out):
            write(base / 'status.json', self.state)
        write(self.out / 'VALIDATION_SUMMARY.json', dict(complete=self.state['complete'],
            source_manifest_sha256=self.state['source_manifest_sha256'],
            counts=self.state['counts']['tests'], tests=self.state['tests'],
            h20_full_keygen_sign_run=False, detailed_logs_archived=False))
        prefix = self.out / 'reports' / ('P1_SHA_ATP_' + self.meta['run_id'])
        write(prefix.with_suffix('.json'), dict(source=self.meta, results=self.state))
        fmt = lambda v: '—' if v is None else f'{v:,.3f}'
        lines = ['# P1／SHA 面积、延迟与 ATP 优化', '',
            f'候选：{self.meta["label"]}；更新时间：{self.state["updated_at"]}；状态：'
            f'{"已结束" if self.state["complete"] else "后台运行"}。', '',
            f'任务：`{json.dumps(self.state["counts"], ensure_ascii=False)}`。', '',
            '基线与20261021_193612矩阵逐文件核对，完整Sign和已完成物理证据复用实测数据；'
            '本轮基线和候选另做相同100MHz common OOC综合，xc7a200tffg1156-3、Vivado2025.2、'
            '默认时序驱动、每进程2线程、全机最多12个Vivado。本控制器最多并发3个，保留旧矩阵后台任务。', '',
            '100MHz综合用于面积与关键路径诊断，不是最终频率证据。假设ATP用U1=150MHz、U2=100MHz；'
            '仅指定频率的路由、DRC、setup与hold全部通过才给出布线ATP。'
            '150MHz周期量化到6.667ns时按实际149.9925MHz计算。没有频率搜索、自动降频或新增时序例外。', '',
            '等效Slice=LUT/4+FF/8+232.4×BRAM36+102.4×DSP，面积均为相同配置的common；'
            '完整Sign逐字节核对输出和签名缓存、Hash与置换/压缩计数。h20完整Keygen/Sign不运行。'
            '超过10分钟只标analysis_deferred，任务继续。', '', '## 100MHz诊断面积', '']
        for backend in ('shake', 'sha2'):
            lines += [f'### {backend.upper()}', '',
                '| 配置 | LUT | FF | BRAM36 | 等效Slice | 基线Slice | 路径ns | 逻辑级数 | 状态 |',
                '|---|---:|---:|---:|---:|---:|---:|---:|---|']
            for config in self.configs:
                if not config.startswith(backend + '/'):
                    continue
                item = self.state['synthesis'][config]
                area, path = item.get('area', {}), item.get('timing', {})
                row = next(r for r in self.state['rows'] if r['config'] == config)
                lines.append('| ' + ' | '.join([config.split('/')[1],
                    *[fmt(area.get(n)) for n in ('lut', 'ff', 'bram36', 'equivalent_slice')],
                    fmt(row['baseline_diagnostic_equivalent_slice']), fmt(path.get('data_path_ns')),
                    fmt(path.get('logic_levels')), item['status'] +
                    ('；分析延后，后台继续' if item.get('analysis_deferred') else '')]) + ' |')
            lines.append('')
        for profile in PROFILES:
            lines += [f'## {profile} 完整Sign', '',
                '| 后端／配置 | 周期 | 基线周期 | 变化% | 假设时间ms | 假设ATP Slice·ms | ATP变化% | 工作量一致 | 状态 |',
                '|---|---:|---:|---:|---:|---:|---:|---|---|']
            for row in self.state['rows']:
                if row['profile'] != profile:
                    continue
                lines.append('| ' + ' | '.join([row['config'], fmt(row['cycles']), fmt(row['baseline_cycles']),
                    fmt(row.get('cycles_change_pct')), fmt(row.get('assumed_target_time_ms')),
                    fmt(row['diagnostic_atp']), fmt(row['diagnostic_atp_change_pct']),
                    '是' if row['workload_equal'] else '—', row['status']]) + ' |')
            lines.append('')
        lines += ['## 指定频率物理验收', '',
            '| 后端／配置 | 目标MHz | 布线Slice | WNS ns | WHS ns | 状态 |',
            '|---|---:|---:|---:|---:|---|']
        for config, item in self.state['routing'].items():
            result = item.get('result', {})
            lines.append('| ' + ' | '.join([config, fmt(item.get('target_frequency_mhz')),
                fmt(item.get('routed_area', {}).get('equivalent_slice')), fmt(result.get('wns_ns')),
                fmt(result.get('whs_ns')), item['status']]) + ' |')
        if not self.state['routing']:
            lines += ['| — | — | — | — | — | 尚未请求布线 |']
        closed = [row for row in self.state['rows'] if row['routed_atp'] is not None]
        if closed:
            lines += ['', '| 后端／配置 | Sign | 实际MHz | 布线时间ms | 布线ATP Slice·ms |',
                '|---|---|---:|---:|---:|']
            lines += ['| ' + ' | '.join([r['config'], r['profile'], fmt(r['routed_frequency_mhz']),
                fmt(r['routed_time_ms']), fmt(r['routed_atp'])]) + ' |' for r in closed]
        for group in ('tests', 'synthesis', 'routing'):
            lines += ['', *[f'错误 `{group}/{k}`：{v["error"]}' for k, v in self.state[group].items() if v.get('error')]]
        lines += [f'运行目录：`{self.run}`。', '',
            f'冻结源码SHA256：`{self.state["source_manifest_sha256"]}`。', '',
            'RTL和支持文件压缩包、控制器校验、验证摘要、分层/时序及Vivado日志归档；'
            '详细仿真日志和DCP留在运行目录。尚缺证据在ARTIFACTS.json显式列出。共同核结果不代表板级I/O时序。', '']
        archive.atomic(prefix.with_suffix('.md'), '\n'.join(lines))
        for directory in ('synth', 'jobs'):
            for path in (self.run / directory).rglob('*') if (self.run / directory).exists() else []:
                if path.is_file() and path.suffix in ('.rpt', '.log', '.json', '.txt', '.xdc'):
                    signature = (path.stat().st_mtime_ns, path.stat().st_size)
                    if self.copied.get(path) != signature:
                        archive.copy_changed(path, self.out / path.relative_to(self.run))
                        self.copied[path] = signature
        if (self.run / 'runner.log').is_file():
            archive.copy_changed(self.run / 'runner.log', self.out / 'runner.log')
        missing = {config: [n for n in ('hierarchical.rpt', 'timing.rpt', 'critical_paths.rpt')
            if not (self.out / 'synth' / config / n).is_file()] for config in self.configs}
        for path in self.out.rglob('*'):
            if not path.is_file() or path.name == 'ARTIFACTS.json' or path.name.endswith('.tmp'):
                continue
            identity = (path.stat().st_mtime_ns, path.stat().st_size)
            if path not in self.checksums or self.checksums[path][0] != identity:
                self.checksums[path] = (identity, sha(path))
        write(self.out / 'ARTIFACTS.json', dict(complete=self.state['complete'], missing=missing,
            omitted_details=['sim', 'validation'], sha256={str(p.relative_to(self.out)): v[1]
                for p, v in self.checksums.items()}))

    def execute(self):
        self.publish()
        archive.index()
        write(self.run / 'INITIAL_PUBLICATION.json', dict(pid=os.getpid(), at=now()))
        with ThreadPoolExecutor(max_workers=3) as physical_pool, ThreadPoolExecutor(max_workers=4) as sim_pool:
            jobs = []
            if self.routes_only:
                jobs += [physical_pool.submit(self.route, *parts(config)) for config in self.route_configs]
            else:
                jobs += [physical_pool.submit(self.synthesize, config) for config in self.configs]
                if self.meta['kind'] != 'baseline':
                    jobs += [sim_pool.submit(self.simulate, *parts(config)) for config in self.configs]
            for future in as_completed(jobs):
                future.result()
        with self.lock:
            self.state.update(complete=True, finished_at=now(), source_unchanged=self.unchanged())
            self.publish()
            archive.index()
        return int(not self.validated())


def detach(run, routes_only=False):
    log = run / ('route_runner.log' if routes_only else 'runner.log')
    command = [sys.executable, str(run / 'control/run_p1sha_atp_optimization.py'), '--run-root', str(run)]
    if routes_only:
        command += ['--routes-only']
    with log.open('w') as stream:
        process = subprocess.Popen(command, cwd=ROOT, env=dict(os.environ, MHBS_P1SHA_WORKSPACE=str(ROOT)),
            stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
    deadline = time.monotonic() + 30
    while not (run / 'status.json').exists() or read(run / 'status.json').get('pid') != process.pid:
        require(process.poll() is None and time.monotonic() < deadline, 'Initial publication failed: ' + str(log))
        time.sleep(.1)
    meta = dict(read(run / 'SOURCE.json'), **read(run / 'EXPERIMENT.json'))
    result = dict(pid=process.pid, root=str(run), routes_only=routes_only,
        report=str(Path(meta['archive_directory']) / 'reports' / ('P1_SHA_ATP_' + meta['run_id'] + '.md')),
        source_manifest_sha256=sha(run / 'SOURCE.json'), configurations=meta['configs'])
    write(run / ('ROUTE_LAUNCH.json' if routes_only else 'LAUNCH.json'), result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def prepare_baseline():
    require(sha(BASELINE / 'SOURCE.json') == BASELINE_MANIFEST, 'Wrong initially frozen baseline')
    require(not (BASELINE / 'EXPERIMENT.json').exists(), 'Baseline already prepared')
    meta = read(BASELINE / 'SOURCE.json')
    require(unchanged(meta), 'Baseline frozen source changed')
    out = Path(meta['archive_directory'])
    evidence = import_matrix(meta, CONFIGS)
    settings = dict(tool_settings(), label='B0_frozen_current_design', kind='baseline', configs=CONFIGS)
    for base in (BASELINE, out):
        write(base / 'EXPERIMENT.json', settings)
        write(base / 'MATRIX_EVIDENCE.json', evidence)
    for name, checksum in evidence['artifacts_sha256'].items():
        path = Path(name)
        require(sha(path) == checksum, 'Matrix physical file changed during archive')
        archive.copy_changed(path, out / 'baseline_matrix' / path.relative_to(MATRIX))
    freeze_controls(BASELINE, out)
    pack_support(Path(meta['source_root']), out, meta['sha256'])
    detach(BASELINE)


def launch_candidate(args):
    require(sha(BASELINE / 'SOURCE.json') == BASELINE_MANIFEST, 'Wrong baseline')
    require((BASELINE / 'MATRIX_EVIDENCE.json').is_file(), 'Prepare baseline first')
    stamp = datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y%m%d_%H%M%S')
    run = ROOT / 'build/p1sha_atp_optimization' / ('candidate_' + stamp)
    out = archive.ARCHIVES / ('p1sha_atp_candidate_' + stamp)
    require(not run.exists() and not out.exists(), 'Candidate already exists')
    checks = dual.frozen_snapshot(ROOT, run / 'source')
    rtl = [n for n in (run / 'source/sources.txt').read_text().splitlines() if n.strip()]
    meta = dict(schema='mhbs.p1sha_atp.source.v1', kind='candidate', run_id=stamp,
        label=args.label, started_at=now(), source_root=str(run / 'source'), sha256=checks,
        rtl_files=rtl, archive_directory=str(out), baseline_run=str(BASELINE),
        baseline_source_manifest_sha256=BASELINE_MANIFEST)
    settings = dict(tool_settings(), configs=list(args.configs or CONFIGS))
    evidence = read(BASELINE / 'MATRIX_EVIDENCE.json')
    for base in (run, out):
        write(base / 'SOURCE.json', meta)
        write(base / 'EXPERIMENT.json', settings)
        write(base / 'MATRIX_EVIDENCE.json', evidence)
    freeze_controls(run, out)
    archive.pack_rtl(run / 'source', out / 'rtl.tar.gz', checks)
    pack_support(run / 'source', out, checks)
    diff = subprocess.run(['diff', '-ru', str(BASELINE / 'source/rtl'), str(run / 'source/rtl')],
                          text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    require(diff.returncode in (0, 1), 'Could not record RTL lineage')
    archive.atomic(out / 'lineage/from_B0.patch', diff.stdout)
    write(out / 'lineage/LINEAGE.json', dict(baseline_manifest_sha256=BASELINE_MANIFEST,
        candidate_manifest_sha256=sha(run / 'SOURCE.json'), patch_sha256=sha(out / 'lineage/from_B0.patch')))
    detach(run)


def route_existing(args):
    run = args.route_existing.resolve()
    state = read(run / 'status.json')
    require(state.get('complete') and state.get('validation_passed'), 'Candidate Sign/diagnostics not all passed')
    require(not (run / 'ROUTE_LAUNCH.json').exists(), 'Route phase already launched')
    configs = list(args.configs or ROUTE_CONFIGS)
    meta = dict(read(run / 'SOURCE.json'), **read(run / 'EXPERIMENT.json'))
    require(all(n in meta['configs'] for n in configs), 'Unmeasured configuration requested for routing')
    require(unchanged(meta), 'Frozen source changed')
    request = dict(requested_at=now(), source_manifest_sha256=sha(run / 'SOURCE.json'), configs=configs,
        explicit_user_authorization=True, target_mhz={'1': 150, '2': 100}, frequency_search=False)
    for base in (run, Path(meta['archive_directory'])):
        write(base / 'ROUTE_REQUEST.json', request)
    detach(run, routes_only=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare-baseline', action='store_true')
    mode.add_argument('--launch-candidate', action='store_true')
    mode.add_argument('--route-existing', type=Path)
    mode.add_argument('--run-root', type=Path)
    mode.add_argument('--refresh-run', type=Path)
    parser.add_argument('--routes-only', action='store_true')
    parser.add_argument('--label', default='candidate')
    parser.add_argument('--configs', nargs='+', choices=CONFIGS)
    args = parser.parse_args()
    if args.prepare_baseline:
        prepare_baseline()
    elif args.launch_candidate:
        launch_candidate(args)
    elif args.route_existing:
        route_existing(args)
    elif args.refresh_run:
        Runner(args.refresh_run).publish()
    else:
        sys.exit(Runner(args.run_root, args.routes_only).execute())
