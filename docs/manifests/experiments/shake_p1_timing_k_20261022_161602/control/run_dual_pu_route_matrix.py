#!/usr/bin/env python3
"""Freeze both hash backends and detach 28 fixed-clock routes plus 84 Sign tests."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import fcntl
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
from run_pu_route_matrix import resources, route_status

ROOT = Path(os.environ.get('MHBS_DUAL_MATRIX_WORKSPACE', Path(__file__).resolve().parents[1])).resolve()
archive.ROOT = ROOT
archive.ARCHIVES = ROOT / 'docs/manifests/experiments'
CONFIGS = [(p, 1) for p in (1, 2, 3, 4, 6, 8, 12, 24)] + [(p, 2) for p in (1, 2, 3, 4, 6, 12)]
BACKENDS = ('shake', 'sha2')
PROFILES = ('slh_128f', 'xmss_h10', 'lms_h10')
CONTROLS = ('run_dual_pu_route_matrix.py', 'route_common_target.tcl',
            'experiment_archive.py', 'run_pu_route_matrix.py')
REPORT_REFRESH_SECONDS = 60


def now():
    return datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    archive.atomic(Path(path), json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def route_key(backend, p, u):
    return f'{backend}/P{p}U{u}'


def live_top_jobs():
    """Count each batch job once; internal synthesis workers are not jobs."""
    output = subprocess.check_output(['ps', '-eo', 'pid,comm,args'], text=True)
    jobs = {}
    for line in output.splitlines():
        fields = line.split(None, 2)
        if (len(fields) != 3 or fields[1] != 'vivado' or '-mode batch' not in fields[2]
                or 'SYNTH_DESIGN_PARENT' in fields[2]):
            continue
        command = fields[2]
        identity = command.split('-tclargs', 1)[-1].strip()
        jobs.setdefault(identity, dict(command=command, pids=[]))['pids'].append(int(fields[0]))
    return list(jobs.values())


def rtl_reference(path):
    """Verify the selected RTL identity without changing the default source."""
    path = Path(path).resolve()
    reference = read(path)
    names = [n for n in (ROOT / 'sources.txt').read_text().splitlines() if n.strip()]
    expected = reference['sha256']
    for name in [*names, 'sources.txt']:
        if name not in expected or sha(ROOT / name) != expected[name]:
            raise ValueError(f'Working RTL differs from selected source: {name}')
    return dict(manifest=str(path), manifest_sha256=sha(path),
                label=reference.get('label', path.parent.name), rtl_files_checked=names,
                sources_txt_checked=True)


def frozen_snapshot(source, destination):
    names = set((source / 'sources.txt').read_text().splitlines()) | {'sources.txt'}
    for directory, suffixes in [('model', ('.py', '.json')), ('scripts', ('.py', '.sh', '.tcl', '.xdc', '.c')),
                                ('tb', ('.sv', '.cpp', '.mem', '.json'))]:
        names.update(str(p.relative_to(source)) for p in (source / directory).rglob('*')
                     if p.is_file() and p.suffix in suffixes and '__pycache__' not in p.parts)
    checks = {}
    for name in sorted(names):
        before = sha(source / name)
        archive.copy_changed(source / name, destination / name)
        if sha(source / name) != before or sha(destination / name) != before:
            raise ValueError(f'Source changed while freezing: {name}')
        checks[name] = before
    if any(sha(source / name) != checksum for name, checksum in checks.items()):
        raise ValueError('Working tree changed during freezing')
    return checks


def rank_rows(rows):
    """Only source-bound, successful Sign and closed physical results are ranked."""
    for row in rows:
        row['rank'] = None
    for backend in BACKENDS:
        for profile in PROFILES:
            eligible = sorted((r for r in rows if r['hash_backend'] == backend and r['profile'] == profile
                               and r['routed_atp_slice_ms'] is not None), key=lambda r: r['routed_atp_slice_ms'])
            previous, rank = None, None
            for position, row in enumerate(eligible, 1):
                if row['routed_atp_slice_ms'] != previous:
                    rank = position
                row['rank'], previous = rank, row['routed_atp_slice_ms']


class Runner:
    def __init__(self, run):
        self.run = Path(run)
        self.meta = read(self.run / 'SOURCE.json')
        self.source = self.run / 'source'
        self.out = Path(self.meta['archive_directory'])
        self.lock = threading.RLock()
        self.capacity_lock = threading.Lock()
        self.capacity_token = threading.local()
        self.reserved = 0
        self.copied = {}
        self.checksums = {}
        self.last_publication = None
        self.state = dict(schema='mhbs.dual_pu_route_matrix.results.v1', pid=os.getpid(),
            started_at=now(), complete=False, source_manifest_sha256=sha(self.run / 'SOURCE.json'),
            routes={route_key(b, p, u): dict(status='pending', target_frequency_mhz=150 if u == 1 else 100)
                    for p, u in CONFIGS for b in BACKENDS},
            tests={route_key(b, p, u) + '/' + profile: dict(status='pending')
                   for p, u in CONFIGS for b in BACKENDS for profile in PROFILES})

    def unchanged(self, names=None):
        checks = self.meta['sha256']
        return all(sha(self.source / name) == checks[name] for name in (names or checks))

    def update(self, group, key, **values):
        with self.lock:
            self.state[group][key].update(values)
            self.publish()
        print(now(), group, key, values.get('status', ''), values.get('error', ''), flush=True)

    def reserve(self):
        """Share admission with other controllers, including pending wrappers."""
        capacity = ROOT / 'build/p1sha_atp_optimization/CAPACITY.json'
        lockfile = capacity.with_suffix('.lock')
        lockfile.parent.mkdir(parents=True, exist_ok=True)
        while True:
            with lockfile.open('a+') as stream:
                fcntl.flock(stream, fcntl.LOCK_EX)
                records = read(capacity) if capacity.exists() else []
                def alive(item):
                    try:
                        os.kill(item['owner_pid'], 0)
                        return True
                    except ProcessLookupError:
                        return False
                records = [record for record in records if alive(record)]
                live = live_top_jobs()
                pending = [record for record in records if not any(
                    record['worker_marker'] in job['command'] for job in live)]
                ours = sum(record['owner_pid'] == os.getpid() for record in records)
                if len(live) + len(pending) < 12 and ours < self.meta['vivado_workers']:
                    token = f'{os.getpid()}_{threading.get_ident()}_{time.monotonic_ns()}'
                    records.append(dict(token=token, owner_pid=os.getpid(), run=str(self.run),
                        worker_marker=self.capacity_token.worker_marker))
                    write(capacity, records)
                    self.capacity_token.value = token
                    with self.capacity_lock:
                        self.reserved += 1
                    return
                write(capacity, records)
            time.sleep(3)

    def release_capacity(self):
        capacity = ROOT / 'build/p1sha_atp_optimization/CAPACITY.json'
        with capacity.with_suffix('.lock').open('a+') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            records = read(capacity) if capacity.exists() else []
            write(capacity, [record for record in records
                if record['token'] != getattr(self.capacity_token, 'value', None)])

    def route(self, backend, p, u):
        key = route_key(backend, p, u)
        output = self.run / 'jobs' / key
        output.mkdir(parents=True, exist_ok=True)
        self.update('routes', key, status='waiting_for_capacity')
        self.capacity_token.worker_marker = str(output)
        self.reserve()
        started = time.monotonic()
        frequency = 150 if u == 1 else 100
        try:
            command = [self.meta['vivado'], '-mode', 'batch', '-nolog', '-nojournal', '-notrace',
                '-source', str(self.run / 'control/route_common_target.tcl'), '-tclargs',
                str(self.source), str(p), str(u), str(output), str(frequency), '2']
            with (output / 'vivado.log').open('w') as stream:
                process = subprocess.Popen(command, cwd=output, stdin=subprocess.DEVNULL,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True,
                    env=dict(os.environ, HASH_BACKEND=backend))
                self.update('routes', key, status='synthesis', started_at=now(), pid=process.pid,
                            command=command, log=str(output / 'vivado.log'))
                while process.poll() is None:
                    try:
                        process.wait(timeout=REPORT_REFRESH_SECONDS)
                    except subprocess.TimeoutExpired:
                        stage = read(output / 'stage.json')['stage'] if (output / 'stage.json').is_file() else 'synthesis'
                        values = dict(status=stage, elapsed_seconds=time.monotonic()-started,
                            analysis_deferred=stage == 'synthesis' and time.monotonic()-started >= 600)
                        if (output / 'synth/utilization.rpt').is_file():
                            values['synth_area'] = resources(output / 'synth/utilization.rpt')
                        self.update('routes', key, **values)
            if process.returncode or 'COMMON_TARGET_PASS' not in (output / 'vivado.log').read_text(errors='replace'):
                raise RuntimeError(f'Vivado exit={process.returncode}; see {output / "vivado.log"}')
            if not self.unchanged(self.meta['rtl_files'] + ['sources.txt']):
                raise RuntimeError('Frozen RTL changed')
            result = read(output / 'result.json')
            routing = route_status(output / 'route/route_status.rpt')
            physical_pass = result['setup_hold_met'] and result['drc_errors'] == 0 and routing['passed']
            result['actual_frequency_mhz'] = 1000 / result['actual_period_ns']
            closed = bool(physical_pass and result['actual_period_ns'] <= 1000/frequency + 1e-6)
            result['strict_frequency_target_met'] = closed
            self.update('routes', key, status='passed' if closed else 'target_not_met', meets_target=closed,
                result=result, route_status=routing, synth_area=resources(output / 'synth/utilization.rpt'),
                routed_area=resources(output / 'route/utilization.rpt'), source_unchanged=True,
                analysis_deferred=False, elapsed_seconds=time.monotonic()-started, finished_at=now(),
                synthesized_checkpoint_sha256=sha(output / 'synth/synthesized.dcp'),
                routed_checkpoint_sha256=sha(output / 'route/routed.dcp'))
        except Exception as error:
            self.update('routes', key, status='error', error=str(error), finished_at=now(),
                        elapsed_seconds=time.monotonic()-started, analysis_deferred=False)
        finally:
            self.release_capacity()
            with self.capacity_lock:
                self.reserved -= 1

    def simulate(self, backend, p, u):
        config = route_key(backend, p, u)
        vectors = self.source / 'tb/vectors'
        if backend == 'sha2':
            vectors /= 'sha2'
        env = dict(os.environ, HASH_BACKEND=backend, VERILATOR=self.meta['verilator'],
                   SIM_SYNTHESIS='0', SIM_FAST_OPT_SLOW='-O1', VECTORS_DIR=str(vectors))
        env.pop('PROFILE_ENABLE', None)
        env.pop('SIM_COMPILE_ONLY', None)
        for profile in PROFILES:
            key = config + '/' + profile
            output = self.run / 'sim' / config
            output.mkdir(parents=True, exist_ok=True)
            log = output / (profile + '_sign.log')
            vector = vectors / profile / 'sign'
            before = {str(f.relative_to(self.source)): sha(f) for f in sorted(vector.glob('*.mem'))}
            started = time.monotonic()
            try:
                command = ['nice', '-n', '10', 'bash', 'scripts/simulate_fast.sh', profile, 'sign', str(p), str(u)]
                with log.open('w') as stream:
                    process = subprocess.Popen(command, cwd=self.source, env=env, stdin=subprocess.DEVNULL,
                        stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                    self.update('tests', key, status='running', pid=process.pid, started_at=now(),
                                command=command, log=str(log))
                    while True:
                        try:
                            code = process.wait(timeout=REPORT_REFRESH_SECONDS)
                            break
                        except subprocess.TimeoutExpired:
                            self.update('tests', key, status='running', elapsed_seconds=time.monotonic()-started)
                match = re.search(rf'STATEFUL_PASS P{p}U{u} op=1 cycles=(\d+) total=(\d+) '
                                  r'hashes=(\d+) permutations=(\d+).*?seconds=([\d.e+]+)', log.read_text(errors='replace'))
                if code or not match:
                    raise RuntimeError(f'Simulation exit={code}; see {log} and frozen source/build/sim compile.log')
                names = self.meta['rtl_files'] + ['sources.txt', 'tb/tb_fast.sv', 'tb/fast_main.cpp', 'scripts/simulate_fast.sh'] + list(before)
                if not self.unchanged(names) or any(sha(self.source / n) != h for n, h in before.items()):
                    raise RuntimeError('Frozen simulation RTL/tools/vectors changed')
                values = match.groups()
                raw = self.source / f'build/sim/P{p}U{u}_fast_o3_synthesis0_slow_O1'
                if backend == 'sha2':
                    raw = raw.with_name(raw.name + '_sha2')
                raw /= profile + '_sign.log'
                copied = output / (profile + '_raw.log')
                archive.copy_changed(raw, copied)
                self.update('tests', key, status='passed', cycles=int(values[0]), total_cycles=int(values[1]),
                    hashes=int(values[2]), permutations=int(values[3]), simulation_seconds=float(values[4]),
                    elapsed_seconds=time.monotonic()-started, finished_at=now(), source_unchanged=True,
                    source_manifest_sha256=self.state['source_manifest_sha256'], log_sha256=sha(log),
                    raw_log=str(copied), raw_log_sha256=sha(copied), vectors_sha256=before,
                    verified_output_bytes=int((vector / 'meta.mem').read_text().splitlines()[0], 16),
                    output_and_signature_cache_checked_bytewise=True)
            except Exception as error:
                self.update('tests', key, status='failed', error=str(error), finished_at=now(),
                            elapsed_seconds=time.monotonic()-started)

    def rows(self):
        rows = []
        for backend in BACKENDS:
            for p, u in CONFIGS:
                config = route_key(backend, p, u)
                physical = self.state['routes'][config]
                for profile in PROFILES:
                    sim = self.state['tests'][config + '/' + profile]
                    row = dict(hash_backend=backend, configuration=f'P{p}U{u}', profile=profile,
                        cycles=sim.get('cycles'), hashes=sim.get('hashes'), permutations=sim.get('permutations'),
                        simulation_status=sim['status'], physical_status=physical['status'],
                        target_frequency_mhz=150 if u == 1 else 100, actual_closed_frequency_mhz=None,
                        target_time_ms=None, routed_time_ms=None, routed_atp_slice_ms=None,
                        assumed_synthesis_atp_slice_ms=None)
                    if sim['status'] == 'passed':
                        row['target_time_ms'] = sim['cycles'] / (row['target_frequency_mhz'] * 1000)
                        if 'synth_area' in physical:
                            row['assumed_synthesis_atp_slice_ms'] = physical['synth_area']['equivalent_slice'] * row['target_time_ms']
                        if physical.get('meets_target') and physical.get('source_unchanged'):
                            row['actual_closed_frequency_mhz'] = physical['result']['actual_frequency_mhz']
                            row['routed_time_ms'] = sim['cycles'] * physical['result']['actual_period_ns'] / 1e6
                            row['routed_atp_slice_ms'] = physical['routed_area']['equivalent_slice'] * row['routed_time_ms']
                    rows.append(row)
        rank_rows(rows)
        return rows

    def publish(self, *, force=False):
        """Throttle all workers together; initial and final snapshots are forced."""
        with self.lock:
            if (not force and self.last_publication is not None
                    and time.monotonic() - self.last_publication < REPORT_REFRESH_SECONDS):
                return False
            self._publish()
            self.last_publication = time.monotonic()
            return True

    def _publish(self):
        self.state['updated_at'] = now()
        self.state['counts'] = {group: {status: sum(t['status'] == status for t in self.state[group].values())
            for status in sorted({t['status'] for t in self.state[group].values()})} for group in ('routes', 'tests')}
        self.state['results'] = self.rows()
        write(self.run / 'status.json', self.state)
        write(self.out / 'status.json', self.state)
        write(self.out / 'VALIDATION_SUMMARY.json', dict(complete=self.state['complete'],
            source_manifest_sha256=self.state['source_manifest_sha256'], counts=self.state['counts']['tests'],
            tests={k: {n: v for n, v in t.items() if n != 'command'} for k, t in self.state['tests'].items()},
            h20_full_keygen_sign_run=False))
        prefix = self.out / 'reports' / ('Dual_PU_Route_Matrix_' + self.meta['run_id'])
        write(prefix.with_suffix('.json'), dict(source=self.meta, results=self.state))
        fmt = lambda v: '—' if v is None else f'{v:,.3f}'
        state_label = '用户要求重跑，旧轮未完成任务已停止' if self.state.get('superseded_by_user') else (
            '任务全部结束' if self.state['complete'] else '后台运行')
        lines = ['# SHAKE／SHA2：14点P/U面积、周期与固定频率布线', '',
            f'更新时间：{self.state["updated_at"]}；状态：{state_label}。', '',
            f'任务状态：`{json.dumps(self.state["counts"], ensure_ascii=False)}`。', '',
            '当前源码一次冻结；两个后端各14个common核，28次指定频率重新综合与布局布线；'
            'SLH-DSA 128f、XMSS h10、LMS h10完整Sign共84项。U1=150MHz，U2=100MHz。'
            '不搜索频率，不自动降频，不新增false-path/multicycle。器件xc7a200tffg1156-3，'
            '默认时序驱动、OOC、SYNTHESIS统计裁剪、通用Keccak；每Vivado两线程，全机批处理最多12个。', '',
            'common面积不含外部ROM与可选签名缓存；三个算法共用同后端同P/U面积。'
            '等效Slice=LUT/4+FF/8+232.4×BRAM36+102.4×DSP，资源项在JSON完整列出。'
            '仿真逐字节核对输出、签名缓存及64位Hash/置换或压缩计数；认证路径完整重算，不执行h20。', '',
            '指定时钟的完整路由、DRC及内部setup/hold均通过后才填写布线ATP并排名。'
            '频率严格按实际时钟周期判定：实际周期须不大于1000/目标MHz+0.000001ns，'
            '不采用标称频率的周期量化容忍；ATP始终使用实际时钟周期。未闭合点仍显示周期和目标频率时间，'
            '不借用其他配置面积或频率。排名按后端、算法分别计算，使用未舍入ATP；任务未全完时为暂定排名。', '',
            '综合单点超过600秒只标记analysis_deferred，进程继续；该阈值不停止仿真或布线。', '',
            '后台报告与归档全局每60秒最多刷新一次；初始与最终结果立即发布，任务结束后自动退出。', '',
            '## common面积与布线STA', '']
        for backend in BACKENDS:
            lines += [f'### {backend.upper()}', '',
                '| P/U | 目标MHz | 综合LUT | 综合FF | 综合BRAM36 | 综合Slice | 布线LUT | 布线FF | 布线BRAM36 | 布线Slice | WNS ns | WHS ns | 状态 |',
                '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|']
            for p, u in CONFIGS:
                config = f'P{p}U{u}'
                task = self.state['routes'][route_key(backend, p, u)]
                a, b, timing = task.get('synth_area', {}), task.get('routed_area', {}), task.get('result', {})
                label = task['status'] + ('；分析延后，综合继续' if task.get('analysis_deferred') else '')
                lines.append('| ' + ' | '.join([config, fmt(task['target_frequency_mhz']),
                    *[fmt(a.get(n)) for n in ('lut', 'ff', 'bram36', 'equivalent_slice')],
                    *[fmt(b.get(n)) for n in ('lut', 'ff', 'bram36', 'equivalent_slice')],
                    fmt(timing.get('wns_ns')), fmt(timing.get('whs_ns')), label]) + ' |')
            lines.append('')
        titles = dict(slh_128f='SLH-DSA 128f Sign', xmss_h10='XMSS h10 Sign', lms_h10='LMS h10 Sign')
        for profile in PROFILES:
            lines += ['', f'## {titles[profile]}', '',
                '| 后端 | ATP排名 | P/U | Sign周期 | Hash | 置换/压缩 | 目标时间ms | 闭合MHz | 布线时间ms | 布线ATP Slice·ms | 仿真/物理 |',
                '|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---|']
            for row in sorted((r for r in self.state['results'] if r['profile'] == profile), key=lambda r:
                              (BACKENDS.index(r['hash_backend']), r['rank'] is None, r['rank'] or 100)):
                lines.append('| ' + ' | '.join([row['hash_backend'], fmt(row['rank']), row['configuration'],
                    *[fmt(row[n]) for n in ('cycles', 'hashes', 'permutations', 'target_time_ms',
                      'actual_closed_frequency_mhz', 'routed_time_ms', 'routed_atp_slice_ms')],
                    row['simulation_status'] + '/' + row['physical_status']]) + ' |')
        for group in ('routes', 'tests'):
            for key, task in self.state[group].items():
                if task.get('error'):
                    lines += ['', f'错误 `{group}/{key}`：{task["error"]}']
        lines += ['', f'运行目录：`{self.run}`；冻结源码校验：`{self.state["source_manifest_sha256"]}`。', '',
            '冻结RTL、控制脚本、验证摘要、完整Vivado日志与综合/布线分层、时序、DRC、路由报告归档；'
            'DCP和仿真明细日志保留运行目录。缺项在ARTIFACTS.json列明。共同核结果不代表板级或顶层I/O时序。', '']
        archive.atomic(prefix.with_suffix('.md'), '\n'.join(lines))
        for path in (self.run / 'jobs').rglob('*') if (self.run / 'jobs').exists() else []:
            if not path.is_file() or path.suffix not in ('.rpt', '.log', '.json', '.txt', '.xdc'):
                continue
            stat = path.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
            if self.copied.get(path) != signature:
                archive.copy_changed(path, self.out / path.relative_to(self.run))
                self.copied[path] = signature
        if (self.run / 'runner.log').is_file():
            archive.copy_changed(self.run / 'runner.log', self.out / 'runner.log')
        missing = {}
        for key in self.state['routes']:
            folder = self.out / 'jobs' / key
            required = ('synth/hierarchical.rpt', 'synth/timing.rpt', 'route/hierarchical.rpt',
                        'route/timing.rpt', 'route/route_status.rpt', 'route/drc.rpt', 'result.json')
            missing[key] = [n for n in required if not (folder / n).is_file()]
        for path in self.out.rglob('*'):
            if not path.is_file() or path.name == 'ARTIFACTS.json' or path.name.endswith('.tmp'):
                continue
            stat = path.stat()
            identity = (stat.st_mtime_ns, stat.st_size)
            if path not in self.checksums or self.checksums[path][0] != identity:
                self.checksums[path] = (identity, sha(path))
        write(self.out / 'ARTIFACTS.json', dict(complete=self.state['complete'], missing=missing,
            omitted_details=['sim', 'validation'], sha256={str(p.relative_to(self.out)): value[1]
                for p, value in self.checksums.items()}))

    def execute(self):
        self.publish(force=True)
        archive.index()
        write(self.run / 'INITIAL_PUBLICATION.json', dict(pid=os.getpid(), at=now()))
        with ThreadPoolExecutor(max_workers=self.meta['vivado_workers']) as physical_pool, \
                ThreadPoolExecutor(max_workers=self.meta['simulation_workers']) as sim_pool:
            jobs = []
            for p, u in CONFIGS:
                for backend in BACKENDS:
                    jobs.append(physical_pool.submit(self.route, backend, p, u))
                    jobs.append(sim_pool.submit(self.simulate, backend, p, u))
            for future in as_completed(jobs):
                future.result()
        with self.lock:
            self.state.update(complete=True, finished_at=now(), source_unchanged=self.unchanged())
            self.publish(force=True)
            archive.index()
        return int(not self.state['source_unchanged'] or
                   any(t['status'] != 'passed' for t in self.state['tests'].values()) or
                   any(t['status'] != 'passed' for t in self.state['routes'].values()))


def launch(args):
    tools = {name: shutil.which(os.environ.get(name.upper(), name)) for name in ('vivado', 'verilator')}
    if not all(tools.values()):
        raise ValueError('Vivado and Verilator are required')
    selected_rtl = rtl_reference(args.rtl_reference_manifest) if args.rtl_reference_manifest else None
    required = {'descriptor.mem', 'expected.mem', 'job.mem', 'message.mem', 'meta.mem', 'nodes.mem', 'program.mem', 'template.mem'}
    for backend in BACKENDS:
        for profile in PROFILES:
            vector = ROOT / 'tb/vectors' / ('sha2' if backend == 'sha2' else '') / profile / 'sign'
            if not all((vector / n).is_file() for n in required):
                raise ValueError(f'Missing complete Sign vector: {vector}')
    stamp = datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y%m%d_%H%M%S')
    run = ROOT / 'build/dual_pu_route_matrix' / stamp
    out = archive.ARCHIVES / ('dual_pu_route_matrix_' + stamp)
    if run.exists() or out.exists():
        raise ValueError('Run already exists')
    checks = frozen_snapshot(ROOT, run / 'source')
    meta = dict(schema='mhbs.dual_pu_route_matrix.source.v1', run_id=stamp, started_at=now(),
        source_root=str(run / 'source'), sha256=checks, archive_directory=str(out), **tools,
        rtl_files=[n for n in (ROOT / 'sources.txt').read_text().splitlines() if n.strip()],
        tool_versions={n: subprocess.check_output([p, '-version' if n == 'vivado' else '--version'],
                      text=True, timeout=30).strip() for n, p in tools.items()},
        base_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        backends=BACKENDS, configs=CONFIGS, profiles=PROFILES, operation='sign', top='common',
        part='xc7a200tffg1156-3', target_frequency_mhz_by_unroll={'1': 150, '2': 100},
        vivado_workers=args.vivado_workers, threads_per_vivado=2, simulation_workers=args.sim_workers,
        analysis_defer_seconds=600, report_refresh_seconds=REPORT_REFRESH_SECONDS,
        strict_actual_frequency_required=True, actual_period_tolerance_ns=1e-6,
        explicit_user_authorization=True, frequency_search=False,
        automatic_frequency_fallback=False, new_timing_exceptions=False, h20_full_keygen_sign_run=False)
    if selected_rtl:
        # Recheck after freezing to close the validation-to-snapshot race.
        if selected_rtl != rtl_reference(args.rtl_reference_manifest):
            raise ValueError('Selected RTL reference changed during freezing')
        if any(checks[name] != read(args.rtl_reference_manifest)['sha256'][name]
               for name in [*meta['rtl_files'], 'sources.txt']):
            raise ValueError('Frozen RTL differs from selected source')
        meta['selected_rtl_source'] = selected_rtl
    for base in (run, out):
        write(base / 'SOURCE.json', meta)
        for name in CONTROLS:
            archive.copy_changed(ROOT / 'scripts' / name, base / 'control' / name)
        write(base / 'CONTROL_SOURCE.json', {name: sha(base / 'control' / name) for name in CONTROLS})
    archive.pack_rtl(run / 'source', out / 'rtl.tar.gz', checks)
    with (run / 'runner.log').open('w') as stream:
        process = subprocess.Popen([sys.executable, str(run / 'control/run_dual_pu_route_matrix.py'),
            '--run-root', str(run)], cwd=ROOT, env=dict(os.environ, MHBS_DUAL_MATRIX_WORKSPACE=str(ROOT)),
            stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
    deadline = time.monotonic() + 30
    while not (run / 'INITIAL_PUBLICATION.json').is_file():
        if process.poll() is not None or time.monotonic() > deadline:
            raise RuntimeError(f'Initial publication failed: {run / "runner.log"}')
        time.sleep(.1)
    result = dict(pid=process.pid, root=str(run), report=str(out / 'reports' / ('Dual_PU_Route_Matrix_' + stamp + '.md')),
                  configurations=14, backends=2, complete_sign_tests=84, fixed_target_routes=28,
                  max_total_vivado=args.vivado_workers, threads_per_vivado=2)
    write(run / 'LAUNCH.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--launch', action='store_true')
    mode.add_argument('--run-root', type=Path)
    parser.add_argument('--vivado-workers', type=int, default=12, choices=range(1, 13))
    parser.add_argument('--sim-workers', type=int, default=4, choices=range(1, 5))
    parser.add_argument('--rtl-reference-manifest', type=Path,
                        help='Require current RTL to match this frozen SOURCE.json')
    options = parser.parse_args()
    if options.launch:
        launch(options)
    else:
        sys.exit(Runner(options.run_root.resolve()).execute())
