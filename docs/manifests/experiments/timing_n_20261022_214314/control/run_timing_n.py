#!/usr/bin/env python3
"""Check an alternative timing candidate, then launch the authorized full matrix.

The 100MHz probes are area/critical-path diagnostics, never frequency sign-off.
All reports refresh at most every 60 seconds and stop when the tasks end.
"""
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
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import run_dual_pu_route_matrix as dual

ROOT = Path(os.environ.get('MHBS_N_WORKSPACE', dual.ROOT)).resolve()
dual.ROOT = dual.archive.ROOT = ROOT
dual.archive.ARCHIVES = ROOT / 'docs/manifests/experiments'
POINTS = (('shake', 4, 1), ('shake', 12, 1),
          ('sha2', 4, 1), ('sha2', 6, 1), ('sha2', 8, 1))
BASE = ROOT / 'build/dual_pu_route_matrix/20261022_164951'
BASE_SHA = '2caa69ccd872dbfe7ae7115624d7fef40317315d6e9c16eb40c0477c04283817'
CONTROLS = ('run_timing_n.py', *dual.CONTROLS, 'diagnose_timing.tcl',
            'validate_p1sha_candidate.py')
read, write, sha, now = dual.read, dual.write, dual.sha, dual.now


class Runner(dual.Runner):
    def __init__(self, run):
        super().__init__(run)
        self.reference_meta = read(self.run / 'REFERENCE_SOURCE.json')
        self.reference = Path(self.reference_meta['source_root'])
        assert sha(self.run / 'REFERENCE_SOURCE.json') == BASE_SHA
        for name, wanted in read(self.run / 'CONTROL_SOURCE.json').items():
            assert sha(self.run / 'control' / name) == wanted
        self.state = dict(schema='mhbs.timing_n.results.v1', pid=os.getpid(),
            source_manifest_sha256=sha(self.run / 'SOURCE.json'), started_at=now(),
            complete=False, functional=dict(status='pending'),
            diagnostics={kind + '/' + dual.route_key(*p): dict(status='pending')
                         for p in POINTS for kind in ('candidate', 'baseline')},
            matrix=dict(status='pending'))

    def reference_unchanged(self):
        return all(sha(self.reference / n) == h for n, h in self.reference_meta['sha256'].items())

    def diagnostic(self, backend, p, u, baseline):
        key = ('baseline' if baseline else 'candidate') + '/' + dual.route_key(backend, p, u)
        output = self.run / 'diagnostics' / key
        source = self.reference if baseline else self.source
        unchanged = self.reference_unchanged if baseline else self.unchanged
        reserved, started = False, time.monotonic()
        try:
            output.mkdir(parents=True, exist_ok=True)
            self.update('diagnostics', key, status='waiting_for_capacity')
            self.capacity_token.worker_marker = str(output)
            self.reserve()
            reserved = True
            assert unchanged(), 'Frozen diagnostic source changed'
            command = [self.meta['vivado'], '-mode', 'batch', '-nolog', '-nojournal', '-notrace',
                '-source', str(self.run / 'control/diagnose_timing.tcl'), '-tclargs',
                str(source), str(p), str(u), str(output), '10.0']
            with (output / 'vivado.log').open('w') as stream:
                process = subprocess.Popen(command, cwd=output, stdin=subprocess.DEVNULL,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True,
                    env=dict(os.environ, HASH_BACKEND=backend))
                self.update('diagnostics', key, status='running', pid=process.pid,
                    command=command, started_at=now())
                while process.poll() is None:
                    try:
                        process.wait(timeout=60)
                    except subprocess.TimeoutExpired:
                        elapsed = time.monotonic() - started
                        self.update('diagnostics', key, elapsed_seconds=elapsed, analysis_deferred=elapsed >= 600)
            assert process.returncode == 0 and 'MHBS_TIMING_DIAGNOSTIC_PASS' in (
                output / 'vivado.log').read_text(errors='replace'), 'Diagnostic synthesis failed'
            assert unchanged(), 'Frozen diagnostic source changed'
            utilization = (output / 'utilization.rpt').read_text()
            memory = re.search(r'\|\s*LUT as Memory\s*\|\s*(\d+)', utilization)
            self.update('diagnostics', key, status='passed',
                area=dual.resources(output / 'utilization.rpt'),
                memory_lut=int(memory[1]) if memory else None,
                checkpoint_sha256=sha(output / 'synthesized.dcp'),
                source_manifest_sha256=BASE_SHA if baseline else sha(self.run / 'SOURCE.json'),
                source_unchanged=True, elapsed_seconds=time.monotonic() - started,
                analysis_deferred=False, finished_at=now())
        except Exception as error:
            self.update('diagnostics', key, status='failed', error=str(error), finished_at=now())
        finally:
            if reserved:
                self.release_capacity()
                with self.capacity_lock:
                    self.reserved -= 1

    def validate(self):
        with self.lock:
            self.state['functional'] = dict(status='running', started_at=now())
        try:
            log = self.run / 'functional_validator.log'
            command = [sys.executable, str(self.source / 'scripts/validate_p1sha_candidate.py'),
                       '--run-root', str(self.run)]
            with log.open('w') as stream:
                process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                with self.lock:
                    self.state['functional'].update(pid=process.pid, log=str(log), command=command)
                process.wait()
            proof = read(self.run / 'functional_validation/VALIDATION.json')
            assert process.returncode == 0 and proof['complete'] and proof['passed'] == 36
            assert proof['total_planned'] == 36 and proof['failed'] == 0 and proof['source_unchanged']
            assert proof['source_manifest_sha256'] == sha(self.run / 'SOURCE.json')
            assert all(t['passed'] and sha(t['log']) == t['log_sha256'] for t in proof['tests'])
            with self.lock:
                self.state['functional'].update(status='passed', summary=proof,
                    summary_sha256=sha(self.run / 'functional_validation/VALIDATION.json'), finished_at=now())
        except Exception as error:
            with self.lock:
                self.state['functional'].update(status='failed', error=str(error), finished_at=now())
        self.publish()

    def _publish(self):
        self.state['updated_at'] = now()
        for base in (self.run, self.out):
            write(base / 'status.json', self.state)
        prefix = self.out / 'reports' / ('Timing_N_' + self.meta['run_id'])
        write(prefix.with_suffix('.json'), dict(source=self.meta, results=self.state))
        lines = ['# N：保留RAM推断的时序优化与全矩阵交接', '',
            '更新时间：' + self.state['updated_at'], '',
            '候选从K2恢复：SHAKE保留完整上下文RAM，仅限制地址标签最大扇出；'
            'SHA2仅tag0共享标量发布预译码与字节使能。两者均保持功能拍数。', '',
            '五点候选/基线配对100MHz common综合用于面积和关键路径诊断，不能证明150/100MHz达标。'
            '36组正常/综合视图功能验证及微测摘要通过、全部诊断通过、每点面积增长不超过2%后，'
            '自动发起当前同源RTL的完整14配置双后端矩阵：28次综合布线与84项完整Sign。'
            '2%是本轮资源筛选策略，非用户新增硬性要求；未通过时不自动发起高成本矩阵。', '',
            '全矩阵U1=150MHz（6.666ns）、U2=100MHz；仅实际setup/hold、完整路由及DRC通过才验收频率。'
            '全局最多12个Vivado，每个2线程，60秒刷新，结束后退出。', '',
            '| 配置 | 基线Slice | 候选Slice | 面积变化% | 基线Memory LUT | 候选Memory LUT | 诊断状态 |',
            '|---|---:|---:|---:|---:|---:|---|']
        for point in POINTS:
            key = dual.route_key(*point)
            old, new = [self.state['diagnostics'][kind + '/' + key] for kind in ('baseline', 'candidate')]
            area = lambda t: t.get('area', {}).get('equivalent_slice')
            ratio = 100 * (area(new) / area(old) - 1) if area(new) and area(old) else None
            fmt = lambda x: '—' if x is None else f'{x:,.3f}'
            lines.append('| ' + ' | '.join([key, fmt(area(old)), fmt(area(new)), fmt(ratio),
                fmt(old.get('memory_lut')), fmt(new.get('memory_lut')),
                old['status'] + '/' + new['status']]) + ' |')
        lines += ['', '功能验证：' + self.state['functional']['status'], '',
                  '总任务：' + json.dumps(self.state['matrix'], ensure_ascii=False), '',
                  '运行目录：' + str(self.run), '', '冻结SOURCE：' + sha(self.run / 'SOURCE.json'), '',
                  '诊断分层/时序/日志与冻结RTL归档；sim/validation明细仅留运行目录。', '']
        dual.archive.atomic(prefix.with_suffix('.md'), '\n'.join(lines))
        for path in (self.run / 'diagnostics').rglob('*') if (self.run / 'diagnostics').exists() else []:
            if path.is_file() and path.suffix in ('.rpt', '.log', '.json', '.txt', '.xdc'):
                identity = (path.stat().st_mtime_ns, path.stat().st_size)
                if self.copied.get(path) != identity:
                    dual.archive.copy_changed(path, self.out / path.relative_to(self.run))
                    self.copied[path] = identity
        for source, target in [(self.run / 'runner.log', self.out / 'runner.log'),
                (self.run / 'functional_validation/VALIDATION.json', self.out / 'supplementary_evidence/functional/SUMMARY.json')]:
            if source.is_file():
                dual.archive.copy_changed(source, target)
        for p in self.out.rglob('*'):
            if p.is_file() and p.name != 'ARTIFACTS.json' and not p.name.endswith('.tmp'):
                identity = (p.stat().st_mtime_ns, p.stat().st_size)
                if self.checksums.get(p, (None,))[0] != identity:
                    self.checksums[p] = (identity, sha(p))
        write(self.out / 'ARTIFACTS.json', dict(complete=self.state['complete'],
            omitted_details=['sim', 'validation'],
            missing={kind + '/' + dual.route_key(*point): [n for n in ('hierarchical.rpt', 'timing.rpt')
                if not (self.out / 'diagnostics' / kind / dual.route_key(*point) / n).is_file()]
                for point in POINTS for kind in ('candidate', 'baseline')},
            sha256={str(p.relative_to(self.out)): v[1] for p, v in self.checksums.items()}))

    def execute(self):
        self.publish(force=True)
        dual.archive.index()
        write(self.run / 'INITIAL_PUBLICATION.json', dict(pid=os.getpid(), at=now()))
        done = threading.Event()
        def monitor():
            while not done.wait(60):
                self.publish()
        thread = threading.Thread(target=monitor, daemon=True)
        thread.start()
        try:
            with ThreadPoolExecutor(max_workers=8) as diag, ThreadPoolExecutor(max_workers=1) as validation:
                jobs = [validation.submit(self.validate)]
                jobs += [diag.submit(self.diagnostic, *point, baseline)
                         for point in POINTS for baseline in (False, True)]
                for f in as_completed(jobs):
                    f.result()
            assert self.unchanged() and self.reference_unchanged(), 'Frozen sources changed'
            assert self.state['functional']['status'] == 'passed', 'Functional validation failed'
            assert all(t['status'] == 'passed' for t in self.state['diagnostics'].values()), 'Diagnostic failed'
            costs = {}
            for point in POINTS:
                key = dual.route_key(*point)
                old, new = [self.state['diagnostics'][kind + '/' + key] for kind in ('baseline', 'candidate')]
                costs[key] = new['area']['equivalent_slice'] / old['area']['equivalent_slice']
                assert costs[key] <= 1.02, f'Area planning gate exceeded: {key} ratio={costs[key]}'
                if point[0] == 'shake':
                    assert old['memory_lut'] and new['memory_lut'] >= .95 * old['memory_lut'], 'SHAKE RAM inference regressed'
            self.state['area_cost_ratios'] = costs
            assert all(sha(ROOT / n) == h for n, h in self.meta['sha256'].items()), 'Working source changed before matrix launch'
            dual.launch(SimpleNamespace(rtl_reference_manifest=self.run / 'SOURCE.json',
                vivado_workers=12, sim_workers=4))
            candidates = []
            for path in (ROOT / 'build/dual_pu_route_matrix').glob('*/SOURCE.json'):
                data = read(path)
                if data.get('selected_rtl_source', {}).get('manifest_sha256') == sha(self.run / 'SOURCE.json'):
                    candidates.append(path.parent)
            assert len(candidates) == 1, 'Full matrix handoff not uniquely identified'
            self.state['matrix'] = dict(status='launched', **read(candidates[0] / 'LAUNCH.json'))
            write(self.run / 'MATRIX_LAUNCH.json', self.state['matrix'])
        except Exception as error:
            self.state['matrix'] = dict(status='not_launched', error=str(error))
        finally:
            self.state.update(complete=True, finished_at=now(), source_unchanged=self.unchanged())
            self.publish(force=True)
            dual.archive.index()
            done.set()
            thread.join(timeout=5)
        return int(self.state['matrix']['status'] != 'launched')


def launch():
    assert sha(BASE / 'SOURCE.json') == BASE_SHA
    micro = {}
    for name, rtl, checksum in (
        ('build/n_shake_address_fanout_20261022/SUMMARY.json', 'rtl/hash/shake-recipe.sv', 'sha256'),
        ('build/n_sha2_timing/SUMMARY.json', 'rtl/hash/sha2-recipe.sv', 'source_sha256')):
        proof = read(ROOT / name)
        assert proof[checksum] == sha(ROOT / rtl), 'Microtest source differs'
        for test in proof['tests']:
            assert test.get('passed') is True or test.get('status') == 'pass', 'Microtest failed'
            current = sha(ROOT / test['log'])
            assert current == test.get('log_sha256', current), 'Microtest log changed'
            test['log_sha256'] = current
        micro[Path(name).parent.name] = proof
    tools = {n: shutil.which(os.environ.get(n.upper(), n)) for n in ('vivado', 'verilator')}
    assert all(tools.values())
    stamp = datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y%m%d_%H%M%S')
    run, out = ROOT / 'build/timing_n' / stamp, dual.archive.ARCHIVES / ('timing_n_' + stamp)
    checks = dual.frozen_snapshot(ROOT, run / 'source')
    meta = dict(schema='mhbs.p1sha_atp.source.v1', experiment_family='timing_n', run_id=stamp,
        label='N1_preserve_RAM_limit_tag_fanout_scalar_only_publication', started_at=now(),
        source_root=str(run / 'source'), archive_directory=str(out), sha256=checks, **tools,
        rtl_files=[n for n in (ROOT / 'sources.txt').read_text().splitlines() if n.strip()],
        base_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        tool_versions={n: subprocess.check_output([p, '-version' if n == 'vivado' else '--version'],
            text=True, timeout=30).strip() for n, p in tools.items()},
        vivado_workers=12, threads_per_vivado=2, diagnostic_points=POINTS,
        synthesis_period_ns=10.0, report_refresh_seconds=60, automatic_authorized_full_matrix=True,
        area_growth_planning_limit=.02, planning_limit_is_user_hard_constraint=False,
        h20_full_keygen_sign_run=False)
    for base in (run, out):
        write(base / 'SOURCE.json', meta)
        dual.archive.copy_changed(BASE / 'SOURCE.json', base / 'REFERENCE_SOURCE.json')
        for n in CONTROLS:
            dual.archive.copy_changed(run / 'source/scripts' / n, base / 'control' / n)
        write(base / 'CONTROL_SOURCE.json', {n: sha(base / 'control' / n) for n in CONTROLS})
    dual.archive.pack_rtl(run / 'source', out / 'rtl.tar.gz', checks)
    reference = read(run / 'REFERENCE_SOURCE.json')
    dual.archive.pack_rtl(Path(reference['source_root']), out / 'reference_rtl.tar.gz', reference['sha256'])
    with tarfile.open(out / 'support.tar.gz', 'w:gz') as tar:
        for n in checks:
            if not n.startswith('rtl/') and n != 'sources.txt':
                tar.add(run / 'source' / n, arcname=n, recursive=False)
    for name, summary in micro.items():
        write(out / 'supplementary_evidence' / (name + '.json'), summary)
    with (run / 'runner.log').open('w') as stream:
        proc = subprocess.Popen([sys.executable, str(run / 'control/run_timing_n.py'), '--run-root', str(run)],
            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
            start_new_session=True, env=dict(os.environ, MHBS_N_WORKSPACE=str(ROOT)))
    deadline = time.monotonic() + 30
    while not (run / 'INITIAL_PUBLICATION.json').exists():
        assert proc.poll() is None and time.monotonic() < deadline, 'Initial publication failed'
        time.sleep(.1)
    result = dict(pid=proc.pid, run_root=str(run), report=str(out / 'reports' / ('Timing_N_' + stamp + '.md')))
    write(run / 'LAUNCH.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--launch', action='store_true')
    mode.add_argument('--run-root', type=Path)
    args = parser.parse_args()
    if args.launch:
        launch()
    else:
        raise SystemExit(Runner(args.run_root).execute())
