#!/usr/bin/env python3
"""Freeze the working tree and launch detached Sign simulations and OOC synthesis."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import sys
import threading
import time
from zoneinfo import ZoneInfo
try:
    from .experiment_archive import archive_run, canonical_report, report_prefix
except ImportError:
    from experiment_archive import archive_run, canonical_report, report_prefix

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = [(p, 1) for p in (1, 2, 3, 4, 6, 8, 12, 24)] + [
    (p, 2) for p in (1, 2, 3, 4, 6, 12)]
PROFILES = ('slh_128f', 'xmss_h10', 'lms_h10')
PART = 'xc7a200tffg1156-3'

def now():
    return datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(text)
    temporary.replace(path)


def launch(args):
    slow_opt = os.environ.get('SIM_FAST_OPT_SLOW', '-O3')
    if slow_opt not in ('-O0', '-O1', '-O2', '-O3', '-Os'):
        raise ValueError('SIM_FAST_OPT_SLOW must be -O0, -O1, -O2, -O3 or -Os')
    configs = args.configs or CONFIGS
    stamp = datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y%m%d_%H%M%S')
    run = ROOT / 'build/pu_sign_matrix' / stamp
    snapshot = run / 'source'
    snapshot.mkdir(parents=True)
    report = report_prefix(f'PU_Sign_Matrix_{stamp}')
    source_files = set((ROOT / 'sources.txt').read_text().splitlines())
    source_files.update(['sources.txt', 'scripts/clock.xdc',
                         'scripts/simulate_fast.sh', 'scripts/run_pu_sign_matrix.py',
                         'scripts/synth_pu_sign_matrix.tcl', 'tb/tb_fast.sv',
                         'tb/fast_main.cpp'])
    source_files.update(str(p.relative_to(ROOT)) for p in (ROOT / 'model').rglob('*.py'))
    source_files.update(str(p.relative_to(ROOT)) for p in (ROOT / 'model').rglob('*.json'))
    source_files.update(str(p.relative_to(ROOT)) for p in (ROOT / 'scripts').iterdir()
                        if p.is_file() and p.suffix in ('.py', '.sh', '.tcl', '.xdc', '.c'))
    source_files.update(str(p.relative_to(ROOT)) for p in (ROOT / 'tb').iterdir()
                        if p.is_file() and p.suffix in ('.sv', '.cpp'))
    source_files.update(str(p.relative_to(ROOT)) for p in (ROOT / 'tb/vectors').rglob('*.mem'))
    checksums = {}
    for name in sorted(source_files):
        src, dst = ROOT / name, snapshot / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        before = digest(src)
        shutil.copy2(src, dst)
        if digest(src) != before or digest(dst) != before:
            raise RuntimeError(f'Source changed during freezing: {name}')
        checksums[name] = before
    if any(digest(ROOT / name) != sha for name, sha in checksums.items()):
        raise RuntimeError('Working tree changed during freezing; launch again')
    vivado = shutil.which(os.environ.get('VIVADO', 'vivado'))
    verilator = shutil.which(os.environ.get('VERILATOR', 'verilator'))
    if not vivado or not verilator:
        raise RuntimeError('Vivado and Verilator must be available before launching')
    versions = {}
    for name, command in [('vivado', [vivado, '-version']),
                          ('verilator', [verilator, '--version'])]:
        versions[name] = subprocess.check_output(command, text=True, timeout=30).strip()
    metadata = dict(schema='mhbs.pu_sign_matrix.source.v1', run_id=stamp, hash_backend=args.hash_backend,
                    started_at=now(), source_root=str(snapshot), report=str(report),
                    archive_root=str(ROOT / 'docs/manifests/experiments'),
                    base_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'],
                                                        cwd=ROOT, text=True).strip(),
                    configs=configs, profiles=PROFILES, operations=['sign'], part=PART,
                    area_top='common', area_scope='One shared common core per P/U',
                    vivado_workers=args.vivado_workers, vivado_threads=2,
                    vivado_headroom=args.vivado_headroom,
                    simulation_workers=args.sim_workers, simulation_opt_slow=slow_opt, versions=versions,
                    synthesis_skip_seconds=args.synth_skip_seconds,
                    synthesis_capacity_runs=[str(p.resolve()) for p in args.synth_capacity_run],
                    vivado=vivado, verilator=verilator, sha256=checksums)
    atomic_write(run / 'SOURCE.json', json.dumps(metadata, indent=2) + '\n')
    archive_run(run)
    atomic_write(run / 'source.sha256', ''.join(f'{h}  {p}\n' for p, h in checksums.items()))
    diff = subprocess.check_output(['git', 'diff', '--binary'], cwd=ROOT, text=True)
    atomic_write(run / 'working_tree.patch', diff)
    atomic_write(run / 'working_tree_status.txt', subprocess.check_output(
        ['git', 'status', '--short'], cwd=ROOT, text=True))
    log = run / 'runner.log'
    with log.open('w') as handle:
        child = subprocess.Popen([sys.executable,
                                  str(snapshot / 'scripts/run_pu_sign_matrix.py'),
                                  '--run-root', str(run)], cwd=snapshot,
                                 stdin=subprocess.DEVNULL, stdout=handle,
                                 stderr=subprocess.STDOUT, start_new_session=True,
                                 close_fds=True)
    atomic_write(run / 'runner.pid', str(child.pid) + '\n')
    atomic_write(ROOT / 'build/pu_sign_matrix/latest.json', json.dumps(
        dict(run_id=stamp, pid=child.pid, root=str(run), log=str(log),
             status=str(run / 'status.json'), report=str(report)), indent=2) + '\n')
    # A following launch must be able to reserve this pool immediately. Publishing
    # LAUNCH before the initial status allowed callers to miss an in-flight pool.
    publication_deadline = time.monotonic() + 30
    while not (run / 'status.json').exists():
        if child.poll() is not None:
            raise RuntimeError(f'Matrix runner exited before publishing status; see {log}')
        if time.monotonic() >= publication_deadline:
            raise RuntimeError(f'Matrix runner is still active but status is not published; see {log}')
        time.sleep(0.05)
    print(json.dumps(dict(pid=child.pid, root=str(run), log=str(log),
                          status=str(run / 'status.json'), report=str(report),
                          simulation_cases=len(configs) * len(PROFILES),
                          common_syntheses=len(configs), area_top='common',
                          vivado_workers=args.vivado_workers, vivado_threads=2), indent=2))


def utilization(path):
    values = {}
    text = path.read_text()
    for key, label in [('lut', 'Slice LUTs'), ('ff', 'Slice Registers'),
                       ('bram36', 'Block RAM Tile'), ('dsp', 'DSPs')]:
        match = re.search(r'^\|\s*' + re.escape(label) + r'\*?\s*\|\s*([\d.]+)', text, re.M)
        if not match:
            raise RuntimeError(f'Missing {label}: {path}')
        values[key] = float(match.group(1))
    values['equivalent_slice'] = (values['lut'] / 4 + values['ff'] / 8
                                  + 232.4 * values['bram36'] + 102.4 * values['dsp'])
    return values


def rank_atp(rows):
    """Rank each algorithm separately; use full precision and competition ties."""
    for row in rows:
        row['atp_slice_ms'] = None
        row['atp_rank'] = None
        if (row['simulation_status'] == row['common_status'] == 'passed'
                and row['cycles'] is not None
                and row['common_equivalent_slice'] is not None):
            row['atp_slice_ms'] = (row['common_equivalent_slice'] * row['cycles']
                                     / (row['assumed_frequency_mhz'] * 1000))
    for profile in PROFILES:
        available = sorted((r for r in rows if r['profile'] == profile
                            and r['atp_slice_ms'] is not None),
                           key=lambda r: r['atp_slice_ms'])
        previous = None
        rank = None
        for position, row in enumerate(available, 1):
            if row['atp_slice_ms'] != previous:
                rank = position
            row['atp_rank'] = rank
            previous = row['atp_slice_ms']


class Runner:
    def __init__(self, run):
        self.run = run
        self.meta = json.loads((run / 'SOURCE.json').read_text())
        self.configs = self.meta['configs']
        self.source = Path(self.meta['source_root'])
        self.report = canonical_report(self.meta['report'])
        self.lock = threading.Lock()
        self.capacity_lock = threading.Lock()
        self.active_syntheses = 0
        self.started = time.monotonic()
        self.state = dict(hash_backend=self.meta.get('hash_backend','shake'), schema='mhbs.pu_sign_matrix.results.v1', run_id=self.meta['run_id'],
                          started_at=now(), updated_at=now(), pid=os.getpid(), complete=False,
                          source_unchanged=None, source_manifest=str(run / 'SOURCE.json'),
                          part=PART, vivado_workers=self.meta['vivado_workers'], vivado_threads=2,
                          simulation_synthesis_macro=False, synthesis_synthesis_macro=True,
                          simulation_opt_slow=self.meta.get('simulation_opt_slow', '-O3'),
                          synthesis_mode='OOC, generic Keccak, no DSP', routed_sta=False,
                          clock_period_ns=6.666667, tasks={}, results=[])
        self.state.update(area_top='common', area_scope='One shared common core per P/U')
        for p, u in self.configs:
            config = f'P{p}U{u}'
            for profile in PROFILES:
                self.state['tasks'][f'sim/{config}/{profile}'] = dict(status='pending')
            self.state['tasks'][f'synth/{config}/common'] = dict(status='pending')
        with self.lock:
            self.publish()

    def update(self, key, status, **values):
        with self.lock:
            self.state['tasks'][key].update(status=status, **values)
            self.publish()
        print(now(), status.upper(), key, values.get('error', ''), flush=True)

    def publish(self):
        rows = []
        tasks = self.state['tasks']
        for p, u in self.configs:
            config = f'P{p}U{u}'
            common = tasks[f'synth/{config}/common']
            for profile in PROFILES:
                sim = tasks[f'sim/{config}/{profile}']
                row = dict(configuration=config, pipeline=p, unroll=u, profile=profile,
                           operation='sign', simulation_status=sim['status'],
                           common_status=common['status'])
                for key in ['cycles', 'total_cycles', 'hashes', 'permutations', 'simulation_seconds']:
                    row[key] = sim.get(key)
                frequency = 150 if u == 1 else 110
                row['assumed_frequency_mhz'] = frequency
                row['time_seconds'] = sim['cycles'] / (frequency * 1e6) if 'cycles' in sim else None
                row['time_ms'] = sim['cycles'] / (frequency * 1000) if 'cycles' in sim else None
                for key in ['lut', 'ff', 'bram36', 'dsp', 'equivalent_slice']:
                    row['common_' + key] = common.get('area', {}).get(key)
                rows.append(row)
        rank_atp(rows)
        self.state.update(assumed_frequency_mhz_by_unroll={'1': 150, '2': 110}, atp_unit='Slice*ms',
                          atp_rank_scope='Per algorithm among completed simulation/common pairs',
                          report_generator_sha256=digest(Path(__file__)))
        self.state['updated_at'] = now()
        if not getattr(self, 'report_only', False):
            self.state['elapsed_seconds'] = ((datetime.fromisoformat(self.state['stopped_at']) -
            datetime.fromisoformat(self.state['started_at'])).total_seconds()
            if self.state.get('stopped_by_user') else time.monotonic() - self.started)
        self.state['results'] = rows
        counts = {status: sum(t['status'] == status for t in tasks.values())
                  for status in ['pending', 'running', 'passed', 'failed', 'cancelled', 'skipped']}
        deferred = [key for key, task in tasks.items() if task.get('analysis_deferred')]
        self.state['analysis_excluded_configurations'] = [key.split('/')[1] for key in deferred]
        self.state['analysis_ready'] = all(task['status']=='passed' for key,task in tasks.items()
                                         if key not in deferred)
        self.state['counts'] = counts
        text = json.dumps(self.state, indent=2) + '\n'
        if not getattr(self, 'report_only', False):
            atomic_write(self.run / 'status.json', text)
        atomic_write(self.report.with_suffix('.json'), text)
        finished = self.state['complete']
        label = ('用户已停止，未完成矩阵' if self.state.get('stopped_by_user') else
                 '已完成其余配置，异常配置继续后台综合' if deferred and self.state['analysis_ready'] else
                 '已完成可测项，部分综合跳过' if finished and counts['skipped'] else
                 '全部完成' if finished and not counts['failed'] else
                 '已结束，存在失败项' if finished else '后台执行中')
        lines = ['# 三算法 Sign 的 P/U 周期与综合面积矩阵', '',
                 f'状态：{label}。更新时间：{self.state["updated_at"]}。任务通过 {counts["passed"]}/{len(tasks)}，运行 {counts["running"]}，等待 {counts["pending"]}，失败 {counts["failed"]}，取消 {counts["cancelled"]}。', '',
                 f'Hash 后端：`{self.meta.get("hash_backend", "shake")}`。', '',
                 f'冻结源码：`{self.run / "SOURCE.json"}`。基于提交 `{self.meta["base_commit"]}` 和启动时的工作区改动，后续编辑不会改变本次测量。', '',
                 'P/U：U1=P1/2/3/4/6/8/12/24；U2=P1/2/3/4/6/12。全部使用同一组默认 Sign 输入和已有独立参考向量；XMSS/LMS 均为 h10，完整重算认证路径。每项逐拍执行生产 common，并核对输出字节、签名缓存、Hash及置换计数；周期没有外推。', '',
                 f'综合：{PART}，Vivado版本见源码清单，最多{self.meta["vivado_workers"]}个Vivado并发，每个2线程，统计关闭，通用Keccak，OOC，6.666667 ns约束。面积统一采用对应P/U的common共同核。每个P/U只综合一次，三个算法共用该面积；common含运行时Job/ROM接口，ROM和签名缓存由外部提供。', '',
                 '等效Slice = LUT/4 + FF/8 + 232.4×BRAM36 + 102.4×DSP。面积为综合结果；没有布局布线STA。时间按U1=150MHz、U2=110MHz假定折算，不代表时序闭合。综合保持冻结的6.666667ns共同约束。仿真总周期另含启动开销；签名缓存读回用于验证，不计入Sign周期。', '']
        lines.extend(['时间(ms) = Sign周期 / (假定MHz × 1000)；ATP（Slice·ms）= 对应P/U的common等效Slice × 时间(ms)。U1采用150MHz，U2采用110MHz。三个算法分别按未舍入的ATP从低到高排名，相同ATP并列；仅对仿真与common综合均通过的配置排名。任务执行期间的排名为当前已完成项的暂定排名。', '',
                      '## common综合面积', '',
                      '| P/U | LUT | FF | BRAM36 | DSP | 等效Slice | 综合状态 |',
                      '|---|---:|---:|---:|---:|---:|---|'])
        def value(v):
            if v is None:
                return '—'
            return f'{v:,.3f}'.rstrip('0').rstrip('.') if isinstance(v, float) else f'{v:,}'
        for p, u in self.configs:
            config = f'P{p}U{u}'
            task = tasks[f'synth/{config}/common']
            area = task.get('area', {})
            label = task['status'] + (': ' + task.get('reason', '') if task.get('analysis_deferred') or task['status']=='skipped' else '')
            lines.append('| ' + ' | '.join([config, *[value(area.get(k)) for k in
                          ['lut', 'ff', 'bram36', 'dsp', 'equivalent_slice']], label]) + ' |')
        lines.append('')
        titles = {'slh_128f': 'SLH-DSA 128f Sign',
                  'xmss_h10': 'XMSS h10 Sign', 'lms_h10': 'LMS h10 Sign'}
        for profile in PROFILES:
            lines.extend([f'## {titles[profile]}', '',
                          '| ATP排名 | P/U | MHz（假定） | Sign周期 | 时间 ms | ATP Slice·ms | 仿真/综合 |',
                          '|---:|---|---:|---:|---:|---:|---|'])
            ordered = sorted((r for r in rows if r['profile'] == profile), key=lambda r:
                             (r['atp_slice_ms'] is None,
                              r['atp_slice_ms'] if r['atp_slice_ms'] is not None else 0))
            for row in ordered:
                milliseconds = row['time_ms']
                lines.append('| ' + ' | '.join([value(row['atp_rank']), row['configuration'],
                             value(row['assumed_frequency_mhz']),
                             value(row['cycles']),
                             f'{milliseconds:.6f}' if milliseconds is not None else '—',
                             value(row['atp_slice_ms']),
                             row['simulation_status'] + '/' + row['common_status']]) + ' |')
            lines.append('')
        lines.extend(['', f'原始日志、综合检查点、设置和源码：`{self.run}`。',
                      'JSON含各任务开始/结束状态和错误，报告随任务完成更新；失败项保持空值，不借用历史结果。', ''])
        if self.state.get('stopped_by_user'):
            lines.extend(['用户要求停止后，所有本轮后台子任务均已终止。此前top综合只作为原始归档，不参与本矩阵面积；完成的仿真和common综合结果保留，缺项不补用历史面积。', ''])
        atomic_write(self.report.with_suffix('.md'), '\n'.join(lines))
        archive_run(self.run)

    @classmethod
    def render_existing(cls, run, prefix=None):
        """Read measured status without changing the measuring process or its source."""
        renderer = cls.__new__(cls)
        renderer.run = run
        renderer.meta = json.loads((run / 'SOURCE.json').read_text())
        renderer.configs = renderer.meta['configs']
        renderer.state = json.loads((run / 'status.json').read_text())
        renderer.source = Path(renderer.meta['source_root'])
        renderer.report = canonical_report(prefix or renderer.meta['report'])
        renderer.report_only = True
        renderer.publish()
        return renderer.state

    def reserve_synthesis(self):
        """Reserve future capacity of older, independently running matrices.

        Older runners need not understand this option: their pending tasks
        reserve up to their full worker pool, so they can launch safely too.
        """
        while True:
            with self.capacity_lock:
                reserved = 0
                for path in self.meta.get('synthesis_capacity_runs', []):
                    state = json.loads((Path(path) / 'status.json').read_text())
                    remaining = sum(t['status'] in ('pending', 'running')
                                    for k, t in state['tasks'].items() if k.startswith('synth/'))
                    reserved += min(state['vivado_workers'], remaining)
                # Routing may be running alongside synthesis in an explicitly
                # authorized timing experiment. Include those real processes,
                # and count our reserved slots before their Vivado has spawned.
                live = subprocess.check_output(['ps', '-eo', 'comm=,args='], text=True)
                own_script = str(self.source / 'scripts/synth_pu_sign_matrix.tcl')
                outside = sum(len(fields := line.split(None, 1)) == 2
                              and fields[0] == 'vivado'
                              and '/bin/unwrapped/lnx64.o/vivado -mode batch' in fields[1]
                              and own_script not in fields[1]
                              for line in live.splitlines())
                limit = 12 - self.meta.get('vivado_headroom', 0)
                if (reserved + self.active_syntheses < limit
                        and outside + self.active_syntheses < limit):
                    self.active_syntheses += 1
                    return
            time.sleep(2)

    def synthesize(self, p, u, profile):
        self.reserve_synthesis()
        try:
            self.synthesize_reserved(p, u, profile)
        finally:
            with self.capacity_lock:
                self.active_syntheses -= 1

    def synthesize_reserved(self, p, u, profile):
        key = f'synth/P{p}U{u}/{profile}'
        output = self.run / 'synth' / f'P{p}U{u}' / profile
        output.mkdir(parents=True, exist_ok=True)
        start = time.monotonic()
        self.update(key, 'running', started_at=now(), log=str(output / 'vivado.log'))
        try:
            command = [self.meta['vivado'], '-mode', 'batch', '-nolog', '-nojournal',
                       '-notrace', '-source', str(self.source / 'scripts/synth_pu_sign_matrix.tcl'),
                       '-tclargs', str(p), str(u), profile, str(output), '2', PART]
            with (output / 'vivado.log').open('w') as handle:
                process = subprocess.Popen(command, cwd=output, stdout=handle,
                                           env=dict(os.environ, HASH_BACKEND=self.meta.get('hash_backend','shake')),
                                           stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                           start_new_session=True)
                self.update(key, 'running', pid=process.pid)
                try:
                    code = process.wait(timeout=self.meta.get('synthesis_skip_seconds',600))
                except subprocess.TimeoutExpired:
                    self.update(key, 'running', analysis_deferred=True,
                                reason='综合继续后台运行；当前分析不等待异常耗时配置')
                    code = process.wait()
            text = (output / 'vivado.log').read_text(errors='replace')
            marker = f'MHBS_MATRIX_SYNTH_PASS P{p}U{u} profile={profile}'
            if code or marker not in text:
                raise RuntimeError(f'Vivado exit={code}; see {output / "vivado.log"}')
            self.update(key, 'passed', finished_at=now(),
                        analysis_deferred=False,
                        seconds=time.monotonic() - start,
                        area=utilization(output / 'utilization.rpt'))
        except Exception as error:
            self.update(key, 'failed', finished_at=now(),
                        seconds=time.monotonic() - start, error=str(error))

    def simulate(self, p, u):
        for profile in PROFILES:
            key = f'sim/P{p}U{u}/{profile}'
            output = self.run / 'sim' / f'P{p}U{u}'
            output.mkdir(parents=True, exist_ok=True)
            log = output / f'{profile}_sign.log'
            start = time.monotonic()
            self.update(key, 'running', started_at=now(), log=str(log))
            try:
                command = ['nice', '-n', '10', 'bash', 'scripts/simulate_fast.sh',
                           profile, 'sign', str(p), str(u)]
                env = os.environ.copy()
                env['VERILATOR'] = self.meta['verilator']
                env.pop('PROFILE_ENABLE', None)
                env['SIM_SYNTHESIS']='0'
                slow_opt = self.meta.get('simulation_opt_slow', '-O3')
                env['SIM_FAST_OPT_SLOW'] = slow_opt
                # Always use the frozen vectors, regardless of the launch shell.
                env['HASH_BACKEND'] = self.meta.get('hash_backend', 'shake')
                vector_root = self.source / 'tb/vectors'
                if env['HASH_BACKEND'] == 'sha2': vector_root /= 'sha2'
                env['VECTORS_DIR'] = str(vector_root)
                with log.open('w') as handle:
                    process = subprocess.Popen(command, cwd=self.source, env=env,
                                               stdout=handle, stderr=subprocess.STDOUT,
                                               stdin=subprocess.DEVNULL, start_new_session=True)
                    self.update(key, 'running', pid=process.pid)
                    try:
                        code = process.wait(timeout=21600)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                        raise RuntimeError('Simulation exceeded 6 hours')
                cache_name = f'P{p}U{u}_fast_o3_synthesis0'
                if slow_opt != '-O3':
                    cache_name += '_slow_' + slow_opt.removeprefix('-')
                if self.meta.get('hash_backend','shake') == 'sha2': cache_name += '_sha2'
                raw_log = self.source / 'build/sim' / cache_name / f'{profile}_sign.log'
                if raw_log.exists():
                    shutil.copy2(log, output / f'{profile}_driver.log')
                    shutil.copy2(raw_log, log)
                text = log.read_text(errors='replace')
                match = re.search(rf'STATEFUL_PASS P{p}U{u} op=1 cycles=(\d+) total=(\d+) '
                                  r'hashes=(\d+) permutations=(\d+).*?seconds=([\d.e+]+)', text)
                if code or not match:
                    raise RuntimeError(f'Simulation exit={code}; see {log}; compile log in {raw_log.parent / "compile.log"}')
                values = match.groups()
                self.update(key, 'passed', finished_at=now(),
                            task_seconds=time.monotonic() - start,
                            cycles=int(values[0]), total_cycles=int(values[1]),
                            hashes=int(values[2]), permutations=int(values[3]),
                            simulation_seconds=float(values[4]))
            except Exception as error:
                self.update(key, 'failed', finished_at=now(), error=str(error))

    def execute(self):
        print(now(), 'MATRIX_START', str(self.run), flush=True)
        # Two independent bounded pools: Vivado 12*2; simulation/build default 2 workers.
        with ThreadPoolExecutor(max_workers=self.meta['vivado_workers']) as synth_pool, \
                ThreadPoolExecutor(max_workers=self.meta['simulation_workers']) as sim_pool:
            futures = []
            for p, u in self.configs:
                futures.append(sim_pool.submit(self.simulate, p, u))
                futures.append(synth_pool.submit(self.synthesize, p, u, 'common'))
            for future in as_completed(futures):
                future.result()
        unchanged = all(digest(self.source / name) == sha
                        for name, sha in self.meta['sha256'].items())
        with self.lock:
            self.state.update(complete=True, finished_at=now(), source_unchanged=unchanged)
            self.publish()
        passed = (self.state['counts']['passed'] + self.state['counts']['skipped']
                  == len(self.state['tasks']) and unchanged)
        print(now(), 'PU_SIGN_MATRIX_PASS' if passed else 'PU_SIGN_MATRIX_FAILED',
              json.dumps(self.state['counts']), flush=True)
        return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hash', dest='hash_backend', choices=('shake','sha2'), default='shake')
    parser.add_argument('--launch', action='store_true')
    parser.add_argument('--run-root', type=Path)
    parser.add_argument('--render-root', type=Path, help='Render existing measured results only')
    parser.add_argument('--report-prefix', type=Path)
    parser.add_argument('--watch', action='store_true', help='Refresh an existing report as measurements finish')
    parser.add_argument('--vivado-workers', type=int, default=12)
    parser.add_argument('--vivado-headroom', type=int, default=0,
                        help='Reserve extra process slots when older independent runners are active')
    parser.add_argument('--sim-workers', type=int, default=2)
    parser.add_argument('--synth-capacity-run', action='append', type=Path, default=[],
                        help='Reserve this existing matrix worker pool within the total limit of 12')
    parser.add_argument('--configs', nargs='+', metavar='PxUy',
                        help='Restrict measurement to these P/U points; default is the 14-point matrix')
    parser.add_argument('--synth-defer-seconds', '--synth-skip-seconds',
                        dest='synth_skip_seconds', type=int, default=600,
                        help='After 10 minutes defer analysis; synthesis keeps running')
    args = parser.parse_args()
    if args.configs:
        if not args.launch:
            parser.error('--configs requires --launch; existing runs use their frozen configuration list')
        configs = []
        for name in args.configs:
            match = re.fullmatch(r'P([0-9]+)U([0-9]+)', name, re.I)
            if not match:
                parser.error(f'Invalid configuration: {name}')
            p, u = map(int, match.groups())
            if p < 1 or u < 1 or p * u > 24 or 24 % (p * u):
                parser.error(f'Invalid configuration: {name}')
            if (p, u) not in configs:
                configs.append((p, u))
        args.configs = configs
    if args.synth_capacity_run:
        if not args.launch:
            parser.error('--synth-capacity-run requires --launch')
        if len(set(p.resolve() for p in args.synth_capacity_run)) != len(args.synth_capacity_run):
            parser.error('Duplicate capacity run')
        for path in args.synth_capacity_run:
            if not (path / 'status.json').is_file():
                parser.error(f'Missing capacity-run status: {path}')
    if sum([args.launch, bool(args.run_root), bool(args.render_root)]) != 1:
        parser.error('Choose --launch, --run-root or --render-root')
    if (args.watch or args.report_prefix) and not args.render_root:
        parser.error('--watch/--report-prefix require --render-root')
    if not 1 <= args.vivado_workers <= 12 or not 1 <= args.sim_workers <= 4:
        parser.error('Vivado workers must be 1..12; simulation workers 1..4')
    if not 0 <= args.vivado_headroom < 12:
        parser.error('--vivado-headroom must be 0..11')
    if args.synth_skip_seconds<=0:
        parser.error('--synth-skip-seconds must be positive')
    if args.launch:
        launch(args)
        return 0
    if args.render_root:
        run = args.render_root.resolve()
        prefix = args.report_prefix.resolve() if args.report_prefix else None
        previous = None
        while True:
            version = (run / 'status.json').stat().st_mtime_ns
            if version != previous:
                state = Runner.render_existing(run, prefix)
                previous = version
                print(now(), 'MATRIX_REPORT_UPDATED', state['counts'], flush=True)
            if not args.watch or state.get('complete') or state.get('stopped_by_user'):
                return 0
            time.sleep(60)
    return Runner(args.run_root.resolve()).execute()


if __name__ == '__main__':
    sys.exit(main())
