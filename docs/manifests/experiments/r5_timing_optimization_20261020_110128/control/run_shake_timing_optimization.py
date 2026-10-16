#!/usr/bin/env python3
"""Freeze SHAKE timing candidates, measure Sign/100-MHz synthesis, optionally route.

Examples::

    python3 scripts/run_shake_timing_optimization.py --launch-baseline
    python3 scripts/run_shake_timing_optimization.py --launch-candidate \
        --baseline-run build/shake_timing_optimization/baseline_YYYYMMDD_HHMMSS
    python3 scripts/run_shake_timing_optimization.py --launch-candidate \
        --baseline-run BASELINE --route --route-mhz 150

Launch returns after initial publication; subprocesses continue in the background.
The chronological experiment INDEX is deliberately not modified by this runner.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json
import math
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
from report_timing_focus import timing
from run_hash_backends import snapshot, sha
from run_pu_route_matrix import live_vivado, route_status
from run_pu_sign_matrix import utilization

ROOT = Path(os.environ.get('MHBS_SHAKE_TIMING_WORKSPACE', Path(__file__).resolve().parents[1])).resolve()
archive.ROOT = ROOT
archive.ARCHIVES = ROOT / 'docs/manifests/experiments'
CONFIGS = (12, 4)
PROFILES = ('slh_128f', 'lms_h10', 'xmss_h10')
SCHEMA = 'shake_timing_optimization_v1'
CONTROLS = ('run_shake_timing_optimization.py', 'experiment_archive.py', 'report_timing_focus.py',
            'run_hash_backends.py', 'run_pu_route_matrix.py', 'run_pu_sign_matrix.py')


def now():
    return datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds')


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    archive.atomic(Path(path), json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def unchanged(meta):
    source = Path(meta['source_root'])
    return all((source / name).is_file() and sha(source / name) == digest
               for name, digest in meta['sha256'].items())


def vectors(source, profile):
    folder = Path(source) / 'tb/vectors' / profile / 'sign'
    result = {p.name: sha(p) for p in sorted(folder.glob('*.mem'))}
    if not result:
        raise ValueError(f'Missing Sign vectors: {folder}')
    return result


def archive_source(meta, out):
    source = Path(meta['source_root'])
    archive.pack_rtl(source, out / 'rtl.tar.gz', meta['sha256'])
    support = {n: h for n, h in meta['sha256'].items() if n.startswith(('model/', 'scripts/', 'tb/'))}
    with tarfile.open(out / 'support_source.tar.gz', 'w:gz') as tar:
        for name in support:
            tar.add(source / name, arcname=name, recursive=False)
    write(out / 'SUPPORT_SOURCE.json', dict(files=support,
          archive_sha256=sha(out / 'support_source.tar.gz')))


class Runner:
    def __init__(self, run):
        self.run = run
        self.meta = read(run / 'SOURCE.json')
        if self.meta.get('schema') != SCHEMA or self.meta.get('hash_backend') != 'shake':
            raise ValueError('Not a SHAKE timing optimization run')
        self.source = Path(self.meta['source_root'])
        self.out = Path(self.meta['archive_directory'])
        self.lock = threading.RLock()
        self.capacity_lock = threading.Lock()
        self.reserved = 0
        self.state = dict(schema=SCHEMA, phase=self.meta['phase'], hash_backend='shake',
            pid=os.getpid(), started_at=now(), complete=False, source_unchanged=None,
            tests={f'P{p}U1/{profile}': dict(status='pending') for p in CONFIGS for profile in PROFILES},
            synthesis={f'P{p}U1': dict(status='pending') for p in CONFIGS},
            routing={f'P{p}U1': dict(status='pending' if self.meta['route_requested'] else 'not_requested',
                target_frequency_mhz=self.meta['route_frequency_mhz']) for p in CONFIGS})

    def compare(self):
        baseline = read(Path(self.meta['baseline_run']) / 'status.json') if self.meta.get('baseline_run') else None
        rows = []
        for key, sim in self.state['tests'].items():
            config, profile = key.split('/')
            syn, routed = self.state['synthesis'][config], self.state['routing'][config]
            row = dict(configuration=config, profile=profile, status=sim['status'], cycles=sim.get('cycles'))
            if sim['status'] == syn['status'] == 'passed':
                area, cycles = syn['area']['equivalent_slice'], sim['cycles']
                row.update(equivalent_slice=area, assumed_frequency_mhz=100.0,
                    diagnostic_time_ms_at_100mhz=cycles / 100000,
                    diagnostic_atp_slice_ms_at_100mhz=area * cycles / 100000)
            if sim['status'] == routed['status'] == 'passed':
                frequency = 1000 / routed['result']['actual_period_ns']
                row.update(routed_frequency_mhz=frequency,
                    routed_time_ms=sim['cycles'] / (frequency * 1000),
                    routed_atp_slice_ms=routed['area']['equivalent_slice'] * sim['cycles'] / (frequency * 1000))
            if baseline:
                old = baseline['tests'][key]
                old_syn = baseline['synthesis'][config]
                if old['status'] == sim['status'] == 'passed':
                    row.update(baseline_cycles=old['cycles'],
                        cycles_change_pct=100 * (sim['cycles'] / old['cycles'] - 1),
                        workload_equal=all(sim.get(k) == old.get(k) for k in ('hashes', 'permutations', 'vectors_sha256')))
                    if old_syn['status'] == syn['status'] == 'passed':
                        old_area = old_syn['area']['equivalent_slice']
                        row.update(baseline_equivalent_slice=old_area,
                            area_change_pct=100 * (area / old_area - 1),
                            diagnostic_atp_change_pct=100 * (area * cycles / (old_area * old['cycles']) - 1))
                old_route = baseline.get('routing', {}).get(config, {})
                if old_route.get('status') == routed['status'] == 'passed' and 'routed_atp_slice_ms' in row:
                    old_frequency = 1000 / old_route['result']['actual_period_ns']
                    old_atp = old_route['area']['equivalent_slice'] * old['cycles'] / (old_frequency * 1000)
                    row.update(baseline_routed_atp_slice_ms=old_atp,
                        routed_atp_change_pct=100 * (row['routed_atp_slice_ms'] / old_atp - 1))
            rows.append(row)
        return rows

    def publish(self):
        self.state['updated_at'] = now()
        self.state['counts'] = {s: sum(v['status'] == s for v in self.state['tests'].values())
                                for s in ('pending', 'running', 'passed', 'failed')}
        self.state['comparisons'] = self.compare()
        write(self.run / 'status.json', self.state)
        write(self.out / 'VALIDATION_SUMMARY.json', self.state)
        prefix = self.out / 'reports' / ('SHAKE_Timing_Optimization_' + self.meta['run_id'])
        write(prefix.with_suffix('.json'), dict(source=self.meta, results=self.state))
        fmt = lambda value: '—' if value is None else f'{value:,.3f}'
        lines = ['# SHAKE P12U1／P4U1 时序优化', '',
            f'阶段：{self.meta["phase"]}；更新时间：{self.state["updated_at"]}；'
            f'状态：{"完成" if self.state["complete"] else "后台运行"}。', '',
            'common OOC、xc7a200tffg1156-3、通用 Keccak、默认时序驱动、SYNTHESIS 统计裁剪；'
            '每个 Vivado 两线程，全机最多 12 个。100 MHz 综合仅用于面积及关键路径诊断，'
            '不能作为实际最高频率或布线 ATP 验收证据；不新增 false-path 或 multicycle。', '',
            '完整 Sign 逐字节核对输出和签名缓存，核对 Hash／置换次数。'
            'XMSS h20、LMS h20 完整 Keygen／Sign 不执行。异常综合超过十分钟只延后分析，进程继续运行。', '',
            '| 配置 | LUT | FF | BRAM36 | 等效 Slice | 综合路径 ns | 逻辑级数 | 综合状态 |',
            '|---|---:|---:|---:|---:|---:|---:|---|']
        for config, result in self.state['synthesis'].items():
            area, path = result.get('area', {}), result.get('timing', {})
            status = result['status'] + ('／分析延后，后台继续' if result.get('analysis_deferred') else '')
            lines.append('| ' + ' | '.join([config, fmt(area.get('lut')), fmt(area.get('ff')),
                fmt(area.get('bram36')), fmt(area.get('equivalent_slice')), fmt(path.get('data_path_ns')),
                fmt(path.get('logic_levels')), status]) + ' |')
        for profile in PROFILES:
            lines += ['', f'## {profile} Sign', '',
                '| 配置 | 周期 | 假设100MHz时间 ms | 假设ATP Slice·ms | 周期变化 % | 面积变化 % | 工作量相同 | 状态 |',
                '|---|---:|---:|---:|---:|---:|---|---|']
            for row in self.state['comparisons']:
                if row['profile'] != profile:
                    continue
                equal = '—' if 'workload_equal' not in row else ('是' if row['workload_equal'] else '否')
                lines.append('| ' + ' | '.join([row['configuration'], fmt(row.get('cycles')),
                    fmt(row.get('diagnostic_time_ms_at_100mhz')), fmt(row.get('diagnostic_atp_slice_ms_at_100mhz')),
                    fmt(row.get('cycles_change_pct')), fmt(row.get('area_change_pct')), equal, row['status']]) + ' |')
        lines += ['', '## 显式请求的布线验证', '',
            '只有启动时给出 `--route` 才进行布线；该配置的三个完整 Sign 必须先通过。'
            '仅测试指定目标，不执行频率搜索。通过要求完整布线、DRC 以及受约束内部 setup／hold 全部通过；'
            '结论适用于 common OOC 内部路径。', '',
            '| 配置 | 目标 MHz | 布线 Slice | WNS ns | WHS ns | 状态 |',
            '|---|---:|---:|---:|---:|---|']
        for config, route in self.state['routing'].items():
            result = route.get('result', {})
            lines.append('| ' + ' | '.join([config, fmt(route.get('target_frequency_mhz')),
                fmt(route.get('area', {}).get('equivalent_slice')), fmt(result.get('wns_ns')),
                fmt(result.get('whs_ns')), route['status']]) + ' |')
        lines += ['', '| 配置 | 算法 | 布线闭合频率 MHz | 时间 ms | ATP Slice·ms | 相对基线 ATP % |',
            '|---|---|---:|---:|---:|---:|']
        for row in self.state['comparisons']:
            lines.append('| ' + ' | '.join([row['configuration'], row['profile'],
                fmt(row.get('routed_frequency_mhz')), fmt(row.get('routed_time_ms')),
                fmt(row.get('routed_atp_slice_ms')), fmt(row.get('routed_atp_change_pct'))]) + ' |')
        errors = [(f'{group}/{key}', item['error']) for group in ('tests', 'synthesis', 'routing')
                  for key, item in self.state[group].items() if item.get('error')]
        if errors:
            lines += ['', '## 未通过项目', ''] + [f'- `{key}`：{error}' for key, error in errors]
        lines += ['', f'运行目录：`{self.run}`。详细仿真日志保留运行目录；'
            '归档保留冻结 RTL／支持源码、源码 SHA、验证摘要及综合／布线报告和 Vivado 日志。'
            '未完成数据留空，任务完成后自动补齐；索引由调用方按实验时间追加。', '']
        archive.atomic(prefix.with_suffix('.md'), '\n'.join(lines))
        missing = {}
        for group in ('synth', 'route'):
            for p in CONFIGS:
                config = f'P{p}U1'
                folder = self.run / group / config
                for path in folder.rglob('*') if folder.exists() else []:
                    if path.is_file() and path.suffix in ('.rpt', '.log', '.txt', '.xdc', '.json'):
                        archive.copy_changed(path, self.out / group / config / path.relative_to(folder))
                required = ['hierarchical.rpt', 'timing.rpt'] if group == 'synth' else (
                    ['route/hierarchical.rpt', 'route/timing.rpt', 'route/route_status.rpt', 'route/drc.rpt', 'result.json']
                    if self.meta['route_requested'] else [])
                missing[f'{group}/{config}'] = [name for name in required if not (self.out / group / config / name).is_file()]
        write(self.out / 'ARTIFACTS.json', dict(complete=self.state['complete'], missing=missing,
            omitted_details=['sim', 'validation'], sha256={str(path.relative_to(self.out)): sha(path)
                for path in self.out.rglob('*') if path.is_file()
                and path.name != 'ARTIFACTS.json' and not path.name.endswith('.tmp')}))

    def update(self, group, key, **values):
        with self.lock:
            self.state[group][key].update(values)
            self.publish()

    def simulate_configuration(self, p):
        for profile in PROFILES:
            key = f'P{p}U1/{profile}'
            log = self.run / 'sim' / f'P{p}U1' / f'{profile}_sign.log'
            log.parent.mkdir(parents=True, exist_ok=True)
            started = time.monotonic()
            self.update('tests', key, status='running', started_at=now(), log=str(log))
            try:
                env = dict(os.environ, HASH_BACKEND='shake', SIM_SYNTHESIS='0', SIM_FAST_OPT_SLOW='-O1',
                    VECTORS_DIR=str(self.source / 'tb/vectors'), VERILATOR=self.meta['verilator'])
                for name in ('PROFILE_ENABLE', 'SIM_COMPILE_ONLY'):
                    env.pop(name, None)
                command = ['bash', 'scripts/simulate_fast.sh', profile, 'sign', str(p), '1']
                with log.open('w') as stream:
                    process = subprocess.run(command, cwd=self.source, env=env, stdin=subprocess.DEVNULL,
                        stdout=stream, stderr=subprocess.STDOUT)
                match = re.search(r'STATEFUL_PASS P(\d+)U1 op=1 cycles=(\d+) total=(\d+) '
                    r'hashes=(\d+) permutations=(\d+).*?seconds=([\d.e+]+)', log.read_text(errors='replace'))
                if process.returncode or not match or int(match[1]) != p:
                    raise RuntimeError(f'Sign failed; see {log}')
                raw_log = (self.source / 'build/sim' / f'P{p}U1_fast_o3_synthesis0_slow_O1'
                           / f'{profile}_sign.log')
                if not raw_log.is_file() or match[0] not in raw_log.read_text(errors='replace'):
                    raise RuntimeError('Original simulator log is missing or differs from the shell result')
                expected = [int(line, 16) for line in
                    (self.source / 'tb/vectors' / profile / 'sign/meta.mem').read_text().split()]
                if int(match[4]) != expected[1] or int(match[5]) != expected[2]:
                    raise RuntimeError('Measured hash/permutation counts differ from the frozen vector')
                if not unchanged(self.meta):
                    raise RuntimeError('Frozen source changed')
                self.update('tests', key, status='passed', cycles=int(match[2]), total_cycles=int(match[3]),
                    hashes=int(match[4]), permutations=int(match[5]), simulation_seconds=float(match[6]),
                    elapsed_seconds=time.monotonic() - started, finished_at=now(),
                    vectors_sha256=vectors(self.source, profile), log_sha256=sha(log),
                    original_log=str(raw_log), original_log_sha256=sha(raw_log),
                    verified_output_bytes=expected[0], output_and_signature_cache_checked_bytewise=True,
                    source_manifest_sha256=sha(self.run / 'SOURCE.json'), source_unchanged=True)
            except Exception as error:
                self.update('tests', key, status='failed', error=str(error), finished_at=now())

    def reserve(self):
        while True:
            with self.capacity_lock:
                outside = sum(str(self.run) not in item['command'] for item in live_vivado())
                if outside + self.reserved < 12:
                    self.reserved += 1
                    return
            time.sleep(3)

    def vivado(self, p, routed=False):
        config, group = f'P{p}U1', 'routing' if routed else 'synthesis'
        output = self.run / ('route' if routed else 'synth') / config
        output.mkdir(parents=True, exist_ok=True)
        self.update(group, config, status='waiting_for_capacity')
        self.reserve()
        started = time.monotonic()
        try:
            script = 'route_common_target.tcl' if routed else 'diagnose_timing.tcl'
            arguments = [str(self.source), str(p), '1', str(output)] + (
                [str(self.meta['route_frequency_mhz']), '2'] if routed else ['10.0'])
            command = [self.meta['vivado'], '-mode', 'batch', '-nolog', '-nojournal', '-notrace',
                '-source', str(self.source / 'scripts' / script), '-tclargs', *arguments]
            with (output / 'vivado.log').open('w') as stream:
                process = subprocess.Popen(command, cwd=output, env=dict(os.environ, HASH_BACKEND='shake'),
                    stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                self.update(group, config, status='running', started_at=now(), pid=process.pid, command=command)
                while process.poll() is None:
                    try:
                        process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        elapsed = time.monotonic() - started
                        stage_file = output / 'stage.json'
                        stage = read(stage_file).get('stage', 'synthesis') if stage_file.exists() else 'synthesis'
                        self.update(group, config, elapsed_seconds=elapsed, stage=stage,
                            analysis_deferred=elapsed >= 600 and (not routed or stage == 'synthesis'))
            marker = 'COMMON_TARGET_PASS' if routed else f'MHBS_TIMING_DIAGNOSTIC_PASS P{p}U1 period_ns=10.0'
            if process.returncode or marker not in (output / 'vivado.log').read_text(errors='replace'):
                raise RuntimeError(f'Vivado failed; see {output / "vivado.log"}')
            if not unchanged(self.meta):
                raise RuntimeError('Frozen source changed')
            values = dict(elapsed_seconds=time.monotonic() - started, finished_at=now(),
                source_unchanged=True, source_manifest_sha256=sha(self.run / 'SOURCE.json'), analysis_deferred=False)
            if routed:
                result = read(output / 'result.json')
                routing = route_status(output / 'route/route_status.rpt')
                met = bool(result['setup_hold_met'] and result['drc_errors'] == 0 and routing['passed']
                    and result['actual_period_ns'] <= 1000 / self.meta['route_frequency_mhz'] + 1e-6)
                values.update(status='passed' if met else 'target_not_met', result=result, route_status=routing,
                    meets_target=met, area=utilization(output / 'route/utilization.rpt'),
                    timing=timing(output / 'route/timing.rpt'),
                    routed_checkpoint_sha256=sha(output / 'route/routed.dcp'))
            else:
                values.update(status='passed', area=utilization(output / 'utilization.rpt'),
                    timing=timing(output / 'timing.rpt'),
                    checkpoint_sha256=sha(output / 'synthesized.dcp'))
            values['reports_sha256'] = {str(path.relative_to(output)): sha(path) for path in output.rglob('*')
                if path.is_file() and path.suffix in ('.rpt', '.log', '.txt', '.xdc', '.json')}
            self.update(group, config, **values)
        except Exception as error:
            self.update(group, config, status='failed', error=str(error), finished_at=now())
        finally:
            with self.capacity_lock:
                self.reserved -= 1

    def execute(self):
        with self.lock:
            self.publish()
            write(self.run / 'INITIAL_PUBLICATION.json', dict(pid=os.getpid(), at=now()))
        with ThreadPoolExecutor(max_workers=2) as sims, ThreadPoolExecutor(max_workers=2) as synths:
            futures = [sims.submit(self.simulate_configuration, p) for p in CONFIGS]
            futures += [synths.submit(self.vivado, p) for p in CONFIGS]
            for future in as_completed(futures):
                future.result()
        if self.meta['route_requested']:
            with ThreadPoolExecutor(max_workers=2) as routes:
                futures = []
                for p in CONFIGS:
                    config = f'P{p}U1'
                    valid = all(self.state['tests'][f'{config}/{profile}']['status'] == 'passed' for profile in PROFILES)
                    valid = valid and self.state['synthesis'][config]['status'] == 'passed' and unchanged(self.meta)
                    comparisons = [r for r in self.state['comparisons'] if r['configuration'] == config]
                    valid = valid and all(r.get('workload_equal', True) for r in comparisons)
                    if valid:
                        futures.append(routes.submit(self.vivado, p, True))
                    else:
                        self.update('routing', config, status='blocked_validation',
                            error='Sign, same-workload comparison, synthesis or frozen-source validation did not pass')
                for future in as_completed(futures):
                    future.result()
        with self.lock:
            self.state.update(complete=True, finished_at=now(), source_unchanged=unchanged(self.meta))
            self.publish()
        passed = self.state['source_unchanged'] and self.state['counts']['passed'] == 6
        passed = passed and all(r['status'] == 'passed' for r in self.state['synthesis'].values())
        passed = passed and all(r.get('workload_equal', True) for r in self.state['comparisons'])
        if self.meta['route_requested']:
            passed = passed and all(r['status'] == 'passed' for r in self.state['routing'].values())
        return int(not passed)


def launch(args):
    phase = 'baseline' if args.launch_baseline else 'candidate'
    if phase == 'candidate' and args.baseline_run is None:
        raise ValueError('Candidate requires --baseline-run from this runner')
    if phase == 'baseline' and args.baseline_run is not None:
        raise ValueError('Baseline cannot refer to another baseline')
    if not math.isfinite(args.route_mhz) or args.route_mhz <= 0:
        raise ValueError('Route frequency must be positive and finite')
    source = (args.source_root or ROOT).resolve()
    baseline_run = args.baseline_run.resolve() if args.baseline_run else None
    old = read(baseline_run / 'SOURCE.json') if baseline_run else None
    if old:
        previous = read(baseline_run / 'status.json')
        if (old.get('schema') != SCHEMA or old.get('phase') != 'baseline' or not unchanged(old)
                or previous.get('counts', {}).get('failed', 0)
                or any(t['status'] == 'failed' for t in previous['synthesis'].values())):
            raise ValueError('Baseline must have unchanged frozen source and no failed measurements')
        for profile in PROFILES:
            if vectors(source, profile) != vectors(Path(old['source_root']), profile):
                raise ValueError(f'Candidate Sign vector identity differs: {profile}')
    tools = {name: shutil.which(os.environ.get(name.upper(), name)) for name in ('vivado', 'verilator')}
    if not all(tools.values()):
        raise ValueError('Vivado and Verilator are required')
    versions = {name: subprocess.check_output([path, '-version' if name == 'vivado' else '--version'],
        text=True, timeout=30).strip() for name, path in tools.items()}
    if old and old['tool_versions'] != versions:
        raise ValueError('Baseline and candidate tool versions differ')
    stamp = datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y%m%d_%H%M%S')
    run = ROOT / 'build/shake_timing_optimization' / f'{phase}_{stamp}'
    if run.exists():
        raise ValueError(f'Run already exists; retry in the next second: {run}')
    out = archive.ARCHIVES / f'shake_timing_optimization_{phase}_{stamp}'
    spec = snapshot(source, run / 'source')
    meta = dict(spec, schema=SCHEMA, run_id=stamp, phase=phase, hash_backend='shake', **tools,
        tool_versions=versions, started_at=now(), archive_directory=str(out), configurations=CONFIGS,
        profiles=PROFILES, synthesis_period_ns=10.0, top='common', part='xc7a200tffg1156-3',
        threads_per_vivado=2, max_total_vivado=12, route_requested=bool(args.route),
        route_frequency_mhz=args.route_mhz if args.route else None, frequency_search=False,
        new_timing_exceptions=False, h20_full_keygen_sign_run=False,
        baseline_run=str(baseline_run) if baseline_run else None,
        baseline_manifest_sha256=sha(baseline_run / 'SOURCE.json') if baseline_run else None,
        baseline_status_sha256=sha(baseline_run / 'status.json') if baseline_run else None)
    for base in (run, out):
        write(base / 'SOURCE.json', meta)
    archive_source(meta, out)
    # Historical source snapshots need not contain the new experiment controller.
    # Freeze the controller separately without modifying those measured sources.
    for base in (run, out):
        for name in CONTROLS:
            archive.copy_changed(ROOT / 'scripts' / name, base / 'control' / name)
        write(base / 'CONTROL_SOURCE.json', {name: sha(base / 'control' / name) for name in CONTROLS})
    runner = run / 'control/run_shake_timing_optimization.py'
    report = out / 'reports' / f'SHAKE_Timing_Optimization_{stamp}.md'
    row = (f'| {out.name} | [{report.stem}]({report.relative_to(archive.ARCHIVES)}) '
           f'| [目录]({out.name}/) |')
    write(out / 'INDEX_ENTRY.json', dict(timestamp=stamp, markdown_row=row, index_updated=False))
    with (run / 'runner.log').open('w') as stream:
        process = subprocess.Popen([sys.executable, str(runner), '--run-root', str(run)], cwd=ROOT,
            env=dict(os.environ, MHBS_SHAKE_TIMING_WORKSPACE=str(ROOT), MHBS_BACKEND_WORKSPACE=str(ROOT)),
            stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
    deadline = time.monotonic() + 30
    while not (run / 'INITIAL_PUBLICATION.json').exists():
        if process.poll() is not None or time.monotonic() > deadline:
            raise RuntimeError(f'Initial publication failed; see {run / "runner.log"}')
        time.sleep(.1)
    result = dict(pid=process.pid, root=str(run), report=str(report), index_row=row,
        simulation_cases=6, diagnostic_syntheses=2, route_jobs=2 if args.route else 0)
    write(run / 'LAUNCH.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--launch-baseline', action='store_true')
    group.add_argument('--launch-candidate', action='store_true')
    group.add_argument('--run-root', type=Path, help='Internal foreground worker for an already frozen run')
    group.add_argument('--refresh-run', type=Path,
        help='Republish completed measurements after a concurrent baseline finishes; starts no tasks')
    parser.add_argument('--baseline-run', type=Path)
    parser.add_argument('--source-root', type=Path, help='Source workspace to freeze; default current repository')
    parser.add_argument('--route', action='store_true', help='Explicitly request two fixed-clock routes after Sign passes')
    parser.add_argument('--route-mhz', type=float, default=150.0)
    args = parser.parse_args()
    if args.refresh_run:
        runner = Runner(args.refresh_run.resolve())
        runner.state = read(runner.run / 'status.json')
        if not runner.state.get('complete'):
            parser.error('--refresh-run requires a completed run; active controllers own their status files')
        if not unchanged(runner.meta):
            parser.error('Frozen source changed; refusing to refresh results')
        runner.publish()
        return 0
    return Runner(args.run_root.resolve()).execute() if args.run_root else launch(args)


if __name__ == '__main__':
    sys.exit(main())
