#!/usr/bin/env python3
"""Measure SHA2 formatter changes at P1/P4/P12 without waiting for large trees."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
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
from run_hash_backends import snapshot, sha
from run_pu_sign_matrix import utilization
from report_timing_focus import timing
from run_pu_route_matrix import live_vivado

ROOT = Path(os.environ.get('MHBS_SHA2_OPTIMIZATION_WORKSPACE', Path(__file__).resolve().parents[1])).resolve()
archive.ROOT = ROOT
archive.ARCHIVES = ROOT / 'docs/manifests/experiments'
CONFIGS = (1, 4, 12)
# Short Sign cases run first, independently of the full h16/h15 regressions.
PROFILES = ('slh_128f', 'lms_h10', 'xmss_h10')
CONTROLS = ('run_sha2_optimization.py', 'run_hash_backends.py', 'experiment_archive.py',
            'run_pu_sign_matrix.py', 'report_timing_focus.py', 'run_pu_route_matrix.py')


def now(): return datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds')


def write(path, data): archive.atomic(Path(path), json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def read(path): return json.loads(Path(path).read_text())


def vector_checks(source, profile):
    return {p.name: sha(p) for p in (source / 'tb/vectors/sha2' / profile / 'sign').glob('*.mem')}


def unchanged(spec):
    return all(sha(Path(spec['source_root']) / name) == digest for name, digest in spec['sha256'].items())


def archive_source(source, out, spec):
    archive.pack_rtl(source, out / 'rtl.tar.gz', spec['sha256'])
    names = [n for n in spec['sha256'] if n.startswith(('model/', 'scripts/', 'tb/'))]
    with tarfile.open(out / 'support_source.tar.gz', 'w:gz') as tar:
        for name in names: tar.add(source / name, arcname=name, recursive=False)
    write(out / 'SUPPORT_SOURCE.json', dict(files={n: spec['sha256'][n] for n in names},
                                         archive_sha256=sha(out / 'support_source.tar.gz')))


def reusable_results(previous_run, previous_spec, frozen):
    """Reuse only artifacts whose own frozen RTL, settings and logs still match."""
    state, meta = read(previous_run / 'status.json'), read(previous_run / 'SOURCE.json')
    if meta.get('period_ns') != 10.0 or not unchanged(previous_spec):
        raise ValueError('Baseline source/period mismatch')
    if frozen['sha256'] != previous_spec['sha256']:
        raise ValueError('Refrozen baseline differs from the measured source')
    sim, synth = {}, {}
    for p in CONFIGS:
        row = state['synthesis'][f'sha2/P{p}U1']
        if row.get('status') != 'passed' or not row.get('source_unchanged'):
            raise ValueError(f'Baseline SHA2 P{p}U1 synthesis is incomplete')
        folder = previous_run / 'synth/sha2' / f'P{p}U1'
        if not all(sha(folder / name) == h for name, h in row['reports_sha256'].items()):
            raise ValueError('Baseline synthesis report checksum mismatch')
        settings = dict(line.split('=', 1) for line in (folder / 'settings.txt').read_text().splitlines() if '=' in line)
        for key, value in {'hash_backend': 'sha2', 'PIPELINE': str(p), 'UNROLL': '1', 'threads': '2',
                           'part': 'xc7a200tffg1156-3', 'mode': 'out_of_context',
                           'timing_driven': 'default', 'new_timing_exceptions': 'none'}.items():
            if settings.get(key) != value: raise ValueError(f'Baseline settings mismatch: {key}')
        if float(settings['period_ns']) != 10.0: raise ValueError('Baseline was not synthesized at 100 MHz')
        synth[f'P{p}U1'] = dict(row, reused=True, reuse_source=str(previous_run), evidence_directory=str(folder))
        for profile in PROFILES:
            key = f'candidate/sha2/P{p}U1/{profile}/sign'
            measured = state['tests'].get(key, {})
            if measured.get('status') != 'passed': continue
            if not measured.get('source_unchanged') or sha(Path(measured['log'])) != measured.get('log_sha256'):
                raise ValueError('Baseline simulation evidence changed')
            if measured['vectors_sha256'] != vector_checks(Path(frozen['source_root']), profile):
                raise ValueError('Baseline vector identity changed')
            sim[f'P{p}U1/{profile}'] = dict(measured, reused=True, reuse_source=str(previous_run), reuse_task=key)
    return sim, synth


class Runner:
    def __init__(self, run):
        self.run = run
        self.meta = read(run / 'SOURCE.json')
        self.source = Path(self.meta['source_root'])
        self.out = Path(self.meta['archive_directory'])
        self.lock = threading.RLock()
        self.capacity_lock = threading.Lock()
        self.reserved = 0
        self.state = dict(started_at=now(), complete=False, phase=self.meta['phase'], hash_backend='sha2',
            tests={f'P{p}U1/{profile}': dict(status='pending') for p in CONFIGS for profile in PROFILES},
            synthesis={f'P{p}U1': dict(status='pending') for p in CONFIGS})
        reuse = read(run / 'REUSE.json')
        self.state['tests'].update(reuse['sim'])
        self.state['synthesis'].update(reuse['synth'])

    def publish(self):
        self.state['updated_at'] = now()
        self.state['counts'] = {s: sum(v['status'] == s for v in self.state['tests'].values())
                                for s in ('pending', 'running', 'passed', 'failed')}
        baseline = read(Path(self.meta['baseline_run']) / 'status.json') if self.meta.get('baseline_run') else None
        comparisons = []
        for key, sim in self.state['tests'].items():
            config, profile = key.split('/')
            synth = self.state['synthesis'][config]
            row = dict(configuration=config, profile=profile, status=sim['status'], cycles=sim.get('cycles'))
            if sim['status'] == synth['status'] == 'passed':
                area, cycles, path = synth['area']['equivalent_slice'], sim['cycles'], synth['timing'].get('data_path_ns')
                row.update(equivalent_slice=area, assumed_frequency_mhz=100.0,
                    time_ms_at_100mhz=cycles / 100000,
                    atp_slice_ms_at_100mhz=area * cycles / 100000,
                    synthesized_path_delay_ns=path,
                    area_cycles_path_delay=area * cycles * path if path is not None else None)
            if baseline:
                old, old_synth = baseline['tests'][key], baseline['synthesis'][config]
                if old['status'] == sim['status'] == old_synth['status'] == synth['status'] == 'passed':
                    oa, oc, op = old_synth['area']['equivalent_slice'], old['cycles'], old_synth['timing'].get('data_path_ns')
                    row.update(baseline_cycles=oc, baseline_equivalent_slice=oa,
                        workload_equal=all(sim.get(f) == old.get(f) for f in ('hashes', 'permutations', 'vectors_sha256')),
                        area_change_pct=100*(area/oa-1), cycles_change_pct=100*(cycles/oc-1),
                        assumed_atp_change_pct=100*((area*cycles)/(oa*oc)-1),
                        diagnostic_score_change_pct=100*((area*cycles*path)/(oa*oc*op)-1) if path and op else None)
            comparisons.append(row)
        self.state['comparisons'] = comparisons
        write(self.run / 'status.json', self.state)
        write(self.out / 'VALIDATION_SUMMARY.json', self.state)
        prefix = self.out / 'reports' / ('SHA2_Optimization_' + self.meta['run_id'])
        write(prefix.with_suffix('.json'), dict(source=self.meta, results=self.state))
        fmt = lambda x: '—' if x is None else f'{x:,.3f}'
        lines = ['# SHA2 formatter 三点面积／周期／时序诊断', '',
                 f'阶段：{self.meta["phase"]}；更新时间：{now()}；状态：' + ('完成' if self.state['complete'] else '后台运行') + '。', '',
                 '测量P1U1/P4U1/P12U1与SLH128f、XMSS h10、LMS h10完整Sign。短任务优先，'
                 '不排入h16/h15大树；此前后台任务继续运行。面积取同配置common，100MHz、OOC、默认时序驱动、统计裁剪，'
                 '每Vivado两线程，全机主任务最多12个；无布局布线。', '',
                 'ATP以假设100MHz计算；面积×cycles×综合路径时延仅为诊断指标（单位Slice·cycle·ns），'
                 '不是布线ATP或实测最高频率，综合WNS通过也不等于布线闭合。', '',
                 f'完整Sign状态：{self.state["counts"]}。', '',
                 '| 配置 | LUT | FF | BRAM36 | Slice | WNS ns | 综合路径 ns | 逻辑级数 | 状态 |',
                 '|---|---:|---:|---:|---:|---:|---:|---:|---|']
        for config, result in self.state['synthesis'].items():
            area, paths = result.get('area', {}), result.get('timing', {})
            status = result['status'] + ('／复用已核验实测' if result.get('reused') else '')
            if result.get('analysis_deferred'): status += '／分析延后，进程继续'
            lines.append('| ' + ' | '.join([config, fmt(area.get('lut')), fmt(area.get('ff')), fmt(area.get('bram36')),
                fmt(area.get('equivalent_slice')), fmt(paths.get('wns_ns')), fmt(paths.get('data_path_ns')),
                fmt(paths.get('logic_levels')), status]) + ' |')
        for profile in PROFILES:
            lines += ['', f'## {profile} Sign', '',
                '| 配置 | 周期 | 假设100MHz时间 ms | 假设ATP Slice·ms | 面积×周期×综合路径 | 面积变化 % | 周期变化 % | 假设ATP变化 % | 诊断指标变化 % | 状态 |',
                '|---|---:|---:|---:|---:|---:|---:|---:|---:|---|']
            for row in comparisons:
                if row['profile'] == profile:
                    lines.append('| ' + ' | '.join([row['configuration'], fmt(row.get('cycles')),
                        fmt(row.get('time_ms_at_100mhz')), fmt(row.get('atp_slice_ms_at_100mhz')),
                        fmt(row.get('area_cycles_path_delay')), fmt(row.get('area_change_pct')),
                        fmt(row.get('cycles_change_pct')), fmt(row.get('assumed_atp_change_pct')),
                        fmt(row.get('diagnostic_score_change_pct')), row['status']]) + ' |')
        lines += ['', '每项核对完整输出、签名缓存与Hash／压缩次数，保存冻结源码清单、向量和日志SHA。'
                  '基线复用还核对原始源码、报告及100MHz设置；未完成数据留空。', '',
                  f'运行目录：`{self.run}`；详细仿真日志留运行目录。', '']
        archive.atomic(prefix.with_suffix('.md'), '\n'.join(lines))
        for config, result in self.state['synthesis'].items():
            folder = Path(result.get('evidence_directory', self.run / 'synth' / config))
            for path in folder.rglob('*') if folder.exists() else []:
                if path.is_file() and path.suffix in ('.rpt', '.log', '.txt', '.xdc', '.json'):
                    archive.copy_changed(path, self.out / 'synth' / config / path.relative_to(folder))
        write(self.out / 'ARTIFACTS.json', dict(complete=self.state['complete'], omitted_details=['sim', 'validation'],
            missing_synthesis=[k for k, v in self.state['synthesis'].items() if v['status'] != 'passed'],
            sha256={str(p.relative_to(self.out)): sha(p) for p in self.out.rglob('*')
                    if p.is_file() and p.name != 'ARTIFACTS.json' and not p.name.endswith('.tmp')}))
        archive.index()

    def update(self, group, key, **values):
        with self.lock:
            self.state[group][key].update(values)
            self.publish()

    def simulate(self, p, profile):
        key = f'P{p}U1/{profile}'
        log = self.run / 'sim' / f'P{p}U1' / f'{profile}_sign.log'
        log.parent.mkdir(parents=True, exist_ok=True)
        start = time.monotonic()
        self.update('tests', key, status='running', started_at=now(), log=str(log))
        try:
            env = dict(os.environ, HASH_BACKEND='sha2', SIM_SYNTHESIS='0', SIM_FAST_OPT_SLOW='-O1',
                       VECTORS_DIR=str(self.source / 'tb/vectors/sha2'), VERILATOR=self.meta['verilator'])
            env.pop('PROFILE_ENABLE', None)
            env.pop('SIM_COMPILE_ONLY', None)
            command = ['bash', 'scripts/simulate_fast.sh', profile, 'sign', str(p), '1']
            with log.open('w') as stream:
                proc = subprocess.run(command, cwd=self.source, env=env, stdin=subprocess.DEVNULL,
                                      stdout=stream, stderr=subprocess.STDOUT)
            match = re.search(r'STATEFUL_PASS P(\d+)U1 op=1 cycles=(\d+) total=(\d+) '
                              r'hashes=(\d+) permutations=(\d+).*?seconds=([\d.e+]+)', log.read_text())
            if proc.returncode or not match or int(match[1]) != p: raise RuntimeError(f'Simulation failed: {log}')
            if not unchanged(self.meta): raise RuntimeError('Frozen source changed')
            self.update('tests', key, status='passed', cycles=int(match[2]), total_cycles=int(match[3]),
                hashes=int(match[4]), permutations=int(match[5]), simulation_seconds=float(match[6]),
                elapsed_seconds=time.monotonic()-start, finished_at=now(), source_unchanged=True,
                source_manifest_sha256=sha(self.run / 'SOURCE.json'), vectors_sha256=vector_checks(self.source, profile),
                log_sha256=sha(log), command=command)
        except Exception as error:
            self.update('tests', key, status='failed', error=str(error), finished_at=now())

    def synthesize(self, p):
        config = f'P{p}U1'
        output = self.run / 'synth' / config
        output.mkdir(parents=True, exist_ok=True)
        while True:
            with self.capacity_lock:
                processes = live_vivado()
                outside = sum(str(self.run) not in command for command in processes)
                if len(processes) < 12 and outside + self.reserved < 12:
                    self.reserved += 1
                    break
            time.sleep(3)
        start = time.monotonic()
        self.update('synthesis', config, status='running', started_at=now())
        try:
            command = [self.meta['vivado'], '-mode', 'batch', '-nolog', '-nojournal', '-notrace',
                '-source', str(self.source / 'scripts/diagnose_timing.tcl'), '-tclargs',
                str(self.source), str(p), '1', str(output), '10.0']
            with (output / 'vivado.log').open('w') as log:
                proc = subprocess.Popen(command, cwd=output, env=dict(os.environ, HASH_BACKEND='sha2'),
                    stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
                self.update('synthesis', config, pid=proc.pid)
                while proc.poll() is None:
                    try: proc.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        self.update('synthesis', config, elapsed_seconds=time.monotonic()-start,
                                    analysis_deferred=time.monotonic()-start >= 600)
            if proc.returncode or f'MHBS_TIMING_DIAGNOSTIC_PASS P{p}U1 period_ns=10.0' not in (output / 'vivado.log').read_text():
                raise RuntimeError(f'Synthesis failed: {output / "vivado.log"}')
            if not unchanged(self.meta): raise RuntimeError('Frozen source changed')
            self.update('synthesis', config, status='passed', area=utilization(output / 'utilization.rpt'),
                timing=timing(output / 'timing.rpt'), elapsed_seconds=time.monotonic()-start,
                finished_at=now(), source_unchanged=True, analysis_deferred=False,
                source_manifest_sha256=sha(self.run / 'SOURCE.json'),
                reports_sha256={f.name: sha(f) for f in output.iterdir() if f.suffix in ('.rpt', '.txt', '.log', '.xdc')})
        except Exception as error:
            self.update('synthesis', config, status='failed', error=str(error), finished_at=now())
        finally:
            with self.capacity_lock: self.reserved -= 1

    def execute(self):
        with self.lock: self.publish()
        write(self.run / 'INITIAL_PUBLICATION.json', dict(pid=os.getpid(), started_at=now()))
        with ThreadPoolExecutor(max_workers=3) as sim_pool, ThreadPoolExecutor(max_workers=3) as synth_pool:
            futures = [sim_pool.submit(self.simulate, p, profile) for profile in PROFILES for p in (12, 4, 1)
                       if self.state['tests'][f'P{p}U1/{profile}']['status'] == 'pending']
            futures += [synth_pool.submit(self.synthesize, p) for p in CONFIGS
                        if self.state['synthesis'][f'P{p}U1']['status'] == 'pending']
            for future in as_completed(futures): future.result()
        with self.lock:
            self.state.update(complete=True, finished_at=now(), source_unchanged=unchanged(self.meta))
            self.publish()
        return int(not self.state['source_unchanged'] or self.state['counts']['failed'] != 0
                   or any(v['status'] != 'passed' for v in self.state['synthesis'].values()))


def launch(args):
    phase = 'baseline' if args.launch_baseline else 'candidate'
    stamp = datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y%m%d_%H%M%S')
    run = ROOT / 'build/sha2_optimization' / f'{phase}_{stamp}'
    out = archive.ARCHIVES / f'sha2_optimization_{phase}_{stamp}'
    if phase == 'baseline':
        old_run = args.previous_run.resolve()
        old_meta = read(old_run / 'SOURCE.json')
        old_spec = old_meta['variants']['candidate']
        spec = snapshot(Path(old_spec['source_root']), run / 'source', old_spec['sha256'])
        sim, synth = reusable_results(old_run, old_spec, spec)
        baseline_run = None
        gate = None
        provenance = dict(previous_run=str(old_run), previous_manifest_sha256=sha(old_run / 'SOURCE.json'),
                          previous_candidate_manifest_sha256=sha(old_run / 'candidate/SOURCE.json'))
    else:
        if args.gate is None or args.baseline_run is None: raise ValueError('Candidate requires --gate and --baseline-run')
        baseline_run = args.baseline_run.resolve()
        baseline_meta = read(baseline_run / 'SOURCE.json')
        if baseline_meta['phase'] != 'baseline': raise ValueError('Expected dedicated baseline run')
        gate = read(args.gate)
        rtl = (ROOT / 'sources.txt').read_text().splitlines()
        if not gate.get('passed') or gate.get('failed', 0) or gate.get('rtl_sha256') != {n: sha(ROOT / n) for n in rtl}:
            raise ValueError('Candidate validation gate must pass and bind every current RTL file')
        for name in ('rtl/hash/shake-recipe.sv', 'rtl/hash/keccak.sv'):
            if sha(ROOT / name) != baseline_meta['sha256'][name]: raise ValueError('SHAKE must remain unchanged')
        for profile in PROFILES:
            if vector_checks(ROOT, profile) != vector_checks(Path(baseline_meta['source_root']), profile):
                raise ValueError('Candidate Sign vectors differ from baseline')
        spec = snapshot(ROOT, run / 'source')
        sim, synth = {}, {}
        provenance = dict(baseline_manifest_sha256=sha(baseline_run / 'SOURCE.json'),
                          gate_sha256=sha(args.gate), gate_source=str(args.gate.resolve()))
    tools = {name: shutil.which(os.environ.get(name.upper(), name)) for name in ('vivado', 'verilator')}
    if not all(tools.values()): raise ValueError('Vivado and Verilator are required')
    meta = dict(spec, **tools, **provenance, run_id=stamp, phase=phase, hash_backend='sha2',
                started_at=now(), baseline_run=str(baseline_run) if baseline_run else None,
                archive_directory=str(out), configurations=CONFIGS, profiles=PROFILES, period_ns=10.0,
                max_vivado_threads=2, max_total_vivado=12, synthesis_only=True)
    for base in (run, out):
        write(base / 'SOURCE.json', meta)
        write(base / 'REUSE.json', dict(sim=sim, synth=synth))
        if gate is not None: write(base / 'PREREQUISITE_VALIDATION.json', gate)
    archive_source(run / 'source', out, spec)
    for name in CONTROLS:
        archive.copy_changed(ROOT / 'scripts' / name, run / 'control' / name)
        archive.copy_changed(ROOT / 'scripts' / name, out / 'control' / name)
    checks = {p.name: sha(p) for p in (run / 'control').iterdir() if p.is_file()}
    write(run / 'CONTROL_SOURCE.json', checks)
    write(out / 'CONTROL_SOURCE.json', checks)
    with (run / 'runner.log').open('w') as log:
        proc = subprocess.Popen([sys.executable, str(run / 'control/run_sha2_optimization.py'), '--run-root', str(run)],
            cwd=ROOT, env=dict(os.environ, MHBS_SHA2_OPTIMIZATION_WORKSPACE=str(ROOT), MHBS_BACKEND_WORKSPACE=str(ROOT)),
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    deadline = time.monotonic() + 30
    while not (run / 'INITIAL_PUBLICATION.json').exists():
        if proc.poll() is not None or time.monotonic() > deadline: raise RuntimeError(f'Runner startup failed: {run / "runner.log"}')
        time.sleep(.1)
    result = dict(pid=proc.pid, root=str(run), report=str(out / 'reports' / f'SHA2_Optimization_{stamp}.md'),
                  reused_simulations=len(sim), reused_synthesis=len(synth))
    write(run / 'LAUNCH.json', result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--launch-baseline', action='store_true')
    group.add_argument('--launch-candidate', action='store_true')
    group.add_argument('--run-root', type=Path)
    parser.add_argument('--previous-run', type=Path, default=ROOT / 'build/hash_backends/20261019_172456')
    parser.add_argument('--baseline-run', type=Path)
    parser.add_argument('--gate', type=Path)
    args = parser.parse_args()
    if args.run_root: sys.exit(Runner(args.run_root.resolve()).execute())
    launch(args)
