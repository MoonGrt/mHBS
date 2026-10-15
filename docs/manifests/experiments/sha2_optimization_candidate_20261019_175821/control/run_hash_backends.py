#!/usr/bin/env python3
"""Freeze both backends; run full non-h20 regression and 100 MHz synthesis."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import hashlib
import json
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
from report_timing_focus import timing
from run_pu_sign_matrix import utilization
from run_pu_route_matrix import live_vivado

ROOT = Path(os.environ.get('MHBS_BACKEND_WORKSPACE', Path(__file__).resolve().parents[1])).resolve()
archive.ROOT = ROOT
archive.ARCHIVES = ROOT / 'docs/manifests/experiments'
SHA2 = ('slh_128f', 'slh_128s', 'xmss_h10', 'xmss_h16', 'lms_h10', 'lms_h15')
SHAKE = ('slh_128f', 'slh_128s', 'slh_192f', 'slh_192s', 'slh_256f', 'slh_256s',
         'xmss_h10', 'xmss_h16', 'lms_h10', 'lms_h15')
TARGETS = ('slh_128f', 'xmss_h10', 'lms_h10')


def now():
    return datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    archive.atomic(Path(path), json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def cases():
    rows = [(variant, backend, 4, 1, profile, op)
            for variant, backend, profiles in (('candidate', 'sha2', SHA2),
                                               ('candidate', 'shake', SHAKE),
                                               ('baseline', 'shake', SHAKE))
            for profile in profiles for op in ('keygen', 'sign', 'verify')]
    rows += [('candidate', 'sha2', p, u, profile, 'sign')
             for p, u in ((1, 1), (4, 2), (12, 1)) for profile in TARGETS]
    return rows


def case_key(case):
    variant, backend, p, u, profile, op = case
    return f'{variant}/{backend}/P{p}U{u}/{profile}/{op}'


def snapshot(source, destination, expected=None):
    names = set((source / 'sources.txt').read_text().splitlines()) | {'sources.txt'}
    for directory, suffixes in [('model', ('.py', '.json')), ('scripts', ('.py', '.sh', '.tcl', '.xdc', '.c')),
                                ('tb', ('.sv', '.cpp', '.mem', '.json'))]:
        names.update(str(p.relative_to(source)) for p in (source / directory).rglob('*')
                     if p.is_file() and p.suffix in suffixes and '__pycache__' not in p.parts)
    checks = {}
    for name in sorted(names):
        before = sha(source / name)
        if expected is not None and expected.get(name) != before:
            raise ValueError(f'Baseline source manifest mismatch: {name}')
        archive.copy_changed(source / name, destination / name)
        if sha(destination / name) != before or sha(source / name) != before:
            raise ValueError(f'Source changed while freezing: {name}')
        checks[name] = before
    return dict(source_root=str(destination), sha256=checks)


class Runner:
    def __init__(self, run):
        self.run = run
        self.meta = json.loads((run / 'SOURCE.json').read_text())
        self.out = Path(self.meta['archive_directory'])
        self.lock = threading.Lock()
        self.capacity_lock = threading.Lock()
        self.reserved = 0
        self.state = dict(started_at=now(), complete=False, source_unchanged=None, tests={}, synthesis={})
        for case in cases():
            self.state['tests'][case_key(case)] = dict(status='pending')
        for backend in ('shake', 'sha2'):
            for p in (1, 4, 12):
                self.state['synthesis'][f'{backend}/P{p}U1'] = dict(status='pending')

    def unchanged(self, variant):
        spec = self.meta['variants'][variant]
        source = Path(spec['source_root'])
        return all(sha(source / name) == checksum for name, checksum in spec['sha256'].items())

    def publish(self):
        self.state['updated_at'] = now()
        comparisons = {}
        for profile in SHAKE:
            for op in ('keygen', 'sign', 'verify'):
                key = f'shake/P4U1/{profile}/{op}'
                a, b = (self.state['tests'][v + '/' + key] for v in ('baseline', 'candidate'))
                if a['status'] == b['status'] == 'passed':
                    comparisons[f'{profile}/{op}'] = all(a[k] == b[k] for k in
                        ('cycles', 'total_cycles', 'hashes', 'permutations', 'vectors_sha256'))
        self.state['shake_baseline_comparisons'] = comparisons
        self.state['counts'] = {s: sum(t['status'] == s for t in self.state['tests'].values())
                                for s in ('pending', 'running', 'passed', 'failed')}
        summary = json.loads(json.dumps(self.state))
        for item in summary['tests'].values():
            item.pop('command', None)
        write(self.run / 'status.json', self.state)
        write(self.out / 'VALIDATION_SUMMARY.json', summary)
        prefix = self.out / 'reports' / ('Hash_Backends_' + self.meta['run_id'])
        write(prefix.with_suffix('.json'), dict(source=self.meta, results=summary))
        lines = ['# SHAKE／SHA2 双后端完整回归与面积', '',
                 f'更新时间：{now()}；状态：' + ('完成' if self.state['complete'] else '后台运行') + '。', '',
                 'SHA2：P4U1 六个非 h20 配置三操作 18 项，以及 P1U1/P4U2/P12U1 三目标 Sign 9 项。'
                 'SHAKE：十个非 h20 配置三操作 30 项，并对迁移前冻结 RTL 实跑相同 30 项作为周期基线。'
                 'h20 完整树任务不执行。每项均由测试台逐字节核对输出、签名缓存、Hash 与压缩/置换计数。', '',
                 f"仿真：{self.state['counts']}；已完成 SHAKE 同工作量比较 {len(comparisons)}/30，"
                 f"不一致 {sum(not v for v in comparisons.values())}。", '',
                 '面积采用同配置 common、100 MHz、OOC、统计裁剪、默认时序驱动综合；每个 Vivado 两线程，'
                 '全机最多 12 个主任务。超过 10 分钟仅延后分析，进程继续。未进行布局布线；下列时序仅为综合诊断。', '',
                 '| 后端 | 配置 | LUT | FF | BRAM36 | Slice | WNS ns | 最差路径 ns | 状态 |',
                 '|---|---|---:|---:|---:|---:|---:|---:|---|']
        def fmt(value): return '—' if value is None else f'{value:,.3f}'
        for key, result in self.state['synthesis'].items():
            backend, config = key.split('/')
            a, t = result.get('area', {}), result.get('timing', {})
            status = result['status'] + ('；分析延后' if result.get('analysis_deferred') else '')
            lines.append('| ' + ' | '.join([backend, config, fmt(a.get('lut')), fmt(a.get('ff')),
                fmt(a.get('bram36')), fmt(a.get('equivalent_slice')), fmt(t.get('wns_ns')),
                fmt(t.get('data_path_ns')), status]) + ' |')
        lines += ['', '| 版本/后端/配置/参数/操作 | 周期 | Hash | 压缩/置换 | 仿真秒 | 状态 |',
                  '|---|---:|---:|---:|---:|---|']
        for key, result in self.state['tests'].items():
            lines.append('| ' + ' | '.join([key, fmt(result.get('cycles')), fmt(result.get('hashes')),
                fmt(result.get('permutations')), fmt(result.get('simulation_seconds')), result['status']]) + ' |')
        lines += ['', f'原始日志与编译缓存：`{self.run}`。每项结果保存源码清单与向量校验；归档省略仿真明细日志。', '']
        archive.atomic(prefix.with_suffix('.md'), '\n'.join(lines))
        for path in (self.run / 'synth').rglob('*'):
            if path.is_file() and path.suffix in ('.rpt', '.log', '.json', '.txt', '.xdc'):
                archive.copy_changed(path, self.out / path.relative_to(self.run))
        write(self.out / 'ARTIFACTS.json', dict(complete=self.state['complete'], omitted_details=['sim', 'validation'],
            missing_synthesis=[key for key, row in self.state['synthesis'].items() if row['status'] != 'passed'],
            sha256={str(p.relative_to(self.out)): sha(p) for p in self.out.rglob('*')
                    if p.is_file() and p.name != 'ARTIFACTS.json' and not p.name.endswith('.tmp')}))
        archive.index()

    def update(self, group, key, **values):
        with self.lock:
            self.state[group][key].update(values)
            self.publish()

    def simulate(self, case):
        variant, backend, p, u, profile, op = case
        key = case_key(case)
        source = Path(self.meta['variants'][variant]['source_root'])
        vector = source / 'tb/vectors'
        if backend == 'sha2': vector /= 'sha2'
        vector /= f'{profile}/{op}'
        log = self.run / 'sim' / (key + '.log')
        log.parent.mkdir(parents=True, exist_ok=True)
        start = time.monotonic()
        self.update('tests', key, status='running', started_at=now(), log=str(log))
        try:
            env = dict(os.environ, HASH_BACKEND=backend, SIM_SYNTHESIS='0', SIM_FAST_OPT_SLOW='-O1',
                       VECTORS_DIR=str(vector.parent.parent), VERILATOR=self.meta['verilator'])
            env.pop('PROFILE_ENABLE', None)
            command = ['bash', 'scripts/simulate_fast.sh', profile, op, str(p), str(u)]
            with log.open('w') as stream:
                result = subprocess.run(command, cwd=source, env=env, stdin=subprocess.DEVNULL,
                                        stdout=stream, stderr=subprocess.STDOUT)
            match = re.search(r'STATEFUL_PASS P(\d+)U(\d+) op=(\d+) cycles=(\d+) total=(\d+) '
                              r'hashes=(\d+) permutations=(\d+).*?seconds=([\d.e+]+)', log.read_text())
            if result.returncode or not match: raise RuntimeError(f'Simulation failed; see {log}')
            if not self.unchanged(variant): raise RuntimeError('Frozen source changed during simulation')
            v = match.groups()
            self.update('tests', key, status='passed', cycles=int(v[3]), total_cycles=int(v[4]),
                hashes=int(v[5]), permutations=int(v[6]), simulation_seconds=float(v[7]),
                wall_seconds=time.monotonic()-start, finished_at=now(), command=command,
                source_unchanged=True, source_manifest_sha256=self.meta['variant_manifest_sha256'][variant],
                vectors_sha256={f.name: sha(f) for f in vector.glob('*.mem')}, log_sha256=sha(log))
        except Exception as error:
            self.update('tests', key, status='failed', error=str(error), finished_at=now())

    def synthesize(self, backend, p):
        key = f'{backend}/P{p}U1'
        output = self.run / 'synth' / key
        output.mkdir(parents=True, exist_ok=True)
        while True:
            with self.capacity_lock:
                live = live_vivado()
                outside = sum(str(self.run) not in item for item in live)
                if len(live) < 12 and outside + self.reserved < 12:
                    self.reserved += 1
                    break
            time.sleep(3)
        source = Path(self.meta['variants']['candidate']['source_root'])
        started = time.monotonic()
        self.update('synthesis', key, status='running', started_at=now())
        try:
            command = [self.meta['vivado'], '-mode', 'batch', '-nolog', '-nojournal', '-notrace',
                '-source', str(source / 'scripts/diagnose_timing.tcl'), '-tclargs', str(source), str(p), '1', str(output), '10.0']
            with (output / 'vivado.log').open('w') as log:
                proc = subprocess.Popen(command, cwd=output, env=dict(os.environ, HASH_BACKEND=backend),
                    stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
                self.update('synthesis', key, pid=proc.pid)
                while proc.poll() is None:
                    try: proc.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        self.update('synthesis', key, seconds=time.monotonic()-started,
                                    analysis_deferred=time.monotonic()-started >= 600)
            if proc.returncode or f'MHBS_TIMING_DIAGNOSTIC_PASS P{p}U1 period_ns=10.0' not in (output / 'vivado.log').read_text():
                raise RuntimeError(f'Synthesis failed; see {output / "vivado.log"}')
            if not self.unchanged('candidate'): raise RuntimeError('Frozen synthesis source changed')
            self.update('synthesis', key, status='passed', area=utilization(output / 'utilization.rpt'),
                timing=timing(output / 'timing.rpt'), finished_at=now(), seconds=time.monotonic()-started,
                source_unchanged=True, analysis_deferred=False,
                source_manifest_sha256=self.meta['variant_manifest_sha256']['candidate'],
                reports_sha256={f.name: sha(f) for f in output.iterdir() if f.suffix in ('.rpt', '.log', '.txt', '.xdc')})
        except Exception as error:
            self.update('synthesis', key, status='failed', error=str(error), finished_at=now())
        finally:
            with self.capacity_lock: self.reserved -= 1

    def execute(self):
        with self.lock: self.publish()
        write(self.run / 'INITIAL_PUBLICATION.json', dict(pid=os.getpid(), started_at=now()))
        with ThreadPoolExecutor(max_workers=4) as sim_pool, ThreadPoolExecutor(max_workers=6) as synth_pool:
            jobs = [sim_pool.submit(self.simulate, case) for case in cases()]
            jobs += [synth_pool.submit(self.synthesize, backend, p) for backend in ('shake', 'sha2') for p in (1, 4, 12)]
            for future in as_completed(jobs): future.result()
        with self.lock:
            self.state.update(complete=True, finished_at=now(), source_unchanged=all(self.unchanged(v) for v in ('baseline', 'candidate')))
            self.publish()
        return int(self.state['counts']['failed'] != 0 or not all(self.state['shake_baseline_comparisons'].values())
                   or not self.state['source_unchanged'] or any(r['status'] != 'passed' for r in self.state['synthesis'].values()))


def launch(args):
    gate = json.loads(args.gate.read_text())
    rtl = (ROOT / 'sources.txt').read_text().splitlines()
    if not gate.get('passed') or gate.get('failed', 0): raise ValueError('Prerequisite validation gate has not passed')
    if gate.get('rtl_sha256') != {name: sha(ROOT / name) for name in rtl}:
        raise ValueError('Prerequisite validation gate does not bind current RTL')
    for name, checksum in gate.get('unit_logs', {}).items():
        if sha(ROOT/name) != checksum: raise ValueError(f'Prerequisite log changed: {name}')
    manifest = json.loads((args.baseline / 'SOURCE.json').read_text())
    baseline = Path(manifest['source_root'])
    for variant, backend, p, u, profile, op in cases():
        source = ROOT if variant == 'candidate' else baseline
        vector = source / 'tb/vectors' / ('sha2/' if backend == 'sha2' else '') / profile / op
        if not (vector / 'meta.mem').is_file(): raise ValueError(f'Missing complete vector: {vector}')
    stamp = datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y%m%d_%H%M%S')
    run = ROOT / 'build/hash_backends' / stamp
    out = archive.ARCHIVES / ('hash_backends_' + stamp)
    variants = {name: snapshot(source, run / name / 'source', expected)
                for name, source, expected in (('baseline', baseline, manifest['sha256']), ('candidate', ROOT, None))}
    tools = {name: shutil.which(os.environ.get(name.upper(), name)) for name in ('vivado', 'verilator')}
    if not all(tools.values()): raise ValueError('Vivado and Verilator are required')
    for variant, spec in variants.items():
        write(run / variant / 'SOURCE.json', spec)
        write(out / variant / 'SOURCE.json', spec)
        archive.pack_rtl(Path(spec['source_root']), out / variant / 'rtl.tar.gz', spec['sha256'])
    versions = {name: subprocess.check_output([path, '--version' if name=='verilator' else '-version'], text=True, timeout=30).strip() for name,path in tools.items()}
    meta = dict(tool_versions=versions, run_id=stamp, started_at=now(), archive_directory=str(out), variants=variants, **tools,
        baseline_git_commit=manifest.get('git_commit'), h20_full_tasks=False, period_ns=10.0, synthesis_top='common',
        variant_manifest_sha256={name: sha(run / name / 'SOURCE.json') for name in variants},
        gate=str(args.gate.resolve()), gate_sha256=sha(args.gate))
    for base in (run, out):
        write(base / 'SOURCE.json', meta)
        write(base / 'PREREQUISITE_VALIDATION.json', gate)
    for key in ('primitive_report','primitive_synthesis_report','model_report'):
        if gate.get(key):
            evidence=ROOT/gate[key]
            if not evidence.is_file():raise ValueError(f'Missing prerequisite summary: {evidence}')
            archive.copy_changed(evidence,out/'prerequisites'/(key+'.json'))
    for name in ('run_hash_backends.py', 'experiment_archive.py', 'run_pu_sign_matrix.py', 'report_timing_focus.py', 'run_pu_route_matrix.py'):
        archive.copy_changed(ROOT / 'scripts' / name, run / 'control' / name)
        archive.copy_changed(ROOT / 'scripts' / name, out / 'control' / name)
    controls={p.name:sha(p) for p in (run/'control').iterdir() if p.is_file()}
    write(run/'CONTROL_SOURCE.json',controls)
    write(out/'CONTROL_SOURCE.json',controls)
    with (run / 'runner.log').open('w') as log:
        proc = subprocess.Popen([sys.executable, str(run / 'control/run_hash_backends.py'), '--run-root', str(run)],
            cwd=ROOT, env=dict(os.environ, MHBS_BACKEND_WORKSPACE=str(ROOT)), stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    deadline = time.monotonic() + 30
    while not (run / 'INITIAL_PUBLICATION.json').exists():
        if proc.poll() is not None or time.monotonic() > deadline: raise RuntimeError(f'Runner startup failed; see {run / "runner.log"}')
        time.sleep(.1)
    result = dict(pid=proc.pid, root=str(run), report=str(out / 'reports' / ('Hash_Backends_' + stamp + '.md')))
    write(run / 'LAUNCH.json', result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--launch', action='store_true')
    group.add_argument('--run-root', type=Path)
    parser.add_argument('--gate', type=Path)
    parser.add_argument('--baseline', type=Path, default=ROOT / 'build/sha2_migration_baseline')
    args = parser.parse_args()
    if args.launch:
        if args.gate is None: parser.error('--launch requires --gate')
        launch(args)
    else:
        sys.exit(Runner(args.run_root.resolve()).execute())
