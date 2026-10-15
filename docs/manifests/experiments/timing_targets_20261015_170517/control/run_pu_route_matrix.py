#!/usr/bin/env python3
"""Explicitly authorized routing of an existing frozen common synthesis matrix."""
import argparse
from concurrent.futures import ThreadPoolExecutor
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

ROOT = Path(os.environ.get('MHBS_ROUTE_WORKSPACE', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import experiment_archive as archive_module
archive_module.ROOT = ROOT
archive_module.ARCHIVES = ROOT / 'docs/manifests/experiments'
archive_module.LEGACY = ROOT / 'docs/report'
from experiment_archive import atomic, copy_changed, index, pack_rtl


def now():
    return datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return default


def write(path, data):
    atomic(Path(path), json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def live_vivado():
    output = subprocess.check_output(['ps', '-eo', 'pid,comm,args'], text=True)
    return [{'pid': int(fields[0]), 'command': fields[2]}
            for line in output.splitlines()
            if len(fields := line.split(None, 2)) == 3 and fields[1] == 'vivado'
            and '/bin/unwrapped/lnx64.o/vivado -mode batch' in fields[2]]


def resources(path):
    text = Path(path).read_text()
    data = {}
    for field, label in [('lut', 'Slice LUTs'), ('ff', 'Slice Registers'),
                         ('bram36', 'Block RAM Tile'), ('dsp', 'DSPs')]:
        match = re.search(r'^\|\s*' + re.escape(label) + r'\*?\s*\|\s*([\d.]+)', text, re.M)
        if not match:
            raise ValueError(f'Missing {label}: {path}')
        data[field] = float(match[1])
    data['equivalent_slice'] = data['lut']/4 + data['ff']/8 + 232.4*data['bram36'] + 102.4*data['dsp']
    return data


def route_status(path):
    text = Path(path).read_text()
    data = {}
    for key, label in [('routable', 'routable nets'), ('fully_routed', 'fully routed nets'),
                       ('routing_errors', 'nets with routing errors')]:
        match = re.search(r'# of ' + label + r'\.+\s*:\s*(\d+)', text)
        if not match:
            raise ValueError(f'Missing route status {key}: {path}')
        data[key] = int(match[1])
    data['passed'] = data['routable'] == data['fully_routed'] and data['routing_errors'] == 0
    return data


def select_configs(source_configs, requested=None):
    """Validate the frozen matrix, then select only explicitly present points."""
    if not isinstance(source_configs, list) or not source_configs:
        raise ValueError('Expected a nonempty frozen common synthesis matrix')
    available = []
    for entry in source_configs:
        if (not isinstance(entry, (list, tuple)) or len(entry) != 2
                or any(type(value) is not int for value in entry)):
            raise ValueError(f'Invalid frozen P/U configuration: {entry!r}')
        p, u = entry
        if p < 1 or u < 1 or p*u > 24 or 24 % (p*u):
            raise ValueError(f'Invalid frozen P/U configuration: P{p}U{u}')
        if [p, u] in available:
            raise ValueError(f'Duplicate frozen configuration: P{p}U{u}')
        available.append([p, u])
    selected = available if requested is None else []
    for name in requested or []:
        match = re.fullmatch(r'P([0-9]+)U([0-9]+)', name, re.I)
        if not match:
            raise ValueError(f'Invalid configuration: {name}')
        p, u = map(int, match.groups())
        if p < 1 or u < 1 or p*u > 24 or 24 % (p*u):
            raise ValueError(f'Invalid P/U configuration: {name}')
        if [p, u] not in available:
            raise ValueError(f'Configuration P{p}U{u} is absent from the frozen synthesis matrix; no other DCP substituted')
        if [p, u] in selected:
            raise ValueError(f'Duplicate configuration: P{p}U{u}')
        selected.append([p, u])
    if not selected:
        raise ValueError('Select at least one configuration')
    if any(u not in (1, 2) for p, u in selected):
        raise ValueError('Routing starting frequencies are specified only for U1=150 MHz and U2=100 MHz')
    return selected


class Runner:
    def __init__(self, run):
        self.run = Path(run)
        self.meta = read(self.run/'SOURCE.json')
        self.source_run = Path(self.meta['synthesis_run'])
        self.frozen_source = Path(self.meta['source_root'])
        self.out = Path(self.meta['archive_directory'])
        self.report = self.out/'reports'/('PU_Route_Matrix_' + self.meta['run_id'])
        self.tcl = self.run/'control/route_pu_limit.tcl'
        self.lock = threading.Lock()
        self.capacity_lock = threading.Lock()
        self.slots = 0
        self.stop_monitor = threading.Event()
        self.state = dict(schema='mhbs.pu_route_matrix.results.v1', run_id=self.meta['run_id'],
                          started_at=now(), updated_at=now(), pid=os.getpid(), complete=False,
                          synthesis_run=str(self.source_run), tasks={
                              f'P{p}U{u}': {'status': 'waiting_for_synthesis',
                                            'initial_frequency_mhz': self.meta['initial_frequency_mhz_by_unroll'][str(u)],
                                            'initial_period_ns': self.meta['initial_period_ns_by_unroll'][str(u)]}
                              for p, u in self.meta['configs']}, results=[],
                          scope='common OOC internal constrained setup/hold paths',
                          period_grid_ns=0.1, max_total_vivado=12, threads_per_vivado=2,
                          explicit_user_authorization=True, new_timing_exceptions=False)
        self.max_observed_vivado = 0

    def update(self, config, status, **data):
        with self.lock:
            self.state['tasks'][config].update(status=status, **data)
            self.publish()
        print(now(), config, status, data.get('error', ''), flush=True)

    def reserve(self):
        while True:
            with self.capacity_lock:
                live = live_vivado()
                outside = sum(str(self.tcl) not in item['command'] for item in live)
                if outside + self.slots < 12:
                    self.slots += 1
                    return
            time.sleep(3)

    def execute_one(self, config):
        try:
            initial = self.state['tasks'][config]
            while True:
                source = read(self.source_run/'status.json', {})
                task = source.get('tasks', {}).get(f'synth/{config}/common', {})
                if task.get('status') == 'passed':
                    break
                if task.get('status') in ('failed', 'error', 'cancelled', 'skipped'):
                    raise RuntimeError(f"Synthesis prerequisite {task['status']}; no other netlist substituted")
                time.sleep(10)
            checkpoint = self.source_run/'synth'/config/'common/synthesized.dcp'
            if not checkpoint.is_file():
                raise FileNotFoundError(checkpoint)
            folder = self.run/'route'/config
            folder.mkdir(parents=True, exist_ok=True)
            copied = folder/'input/synthesized.dcp'
            before = sha(checkpoint)
            copy_changed(checkpoint, copied)
            if sha(copied) != before or sha(checkpoint) != before:
                raise RuntimeError('Synthesis checkpoint changed while copying')
            provenance = dict(synthesis_checkpoint=str(checkpoint), frozen_checkpoint=str(copied),
                              checkpoint_sha256=before, synthesis_status=task,
                              source_manifest_sha256=self.meta['synthesis_manifest_sha256'],
                              routing_script_sha256=sha(self.tcl), threads=2,
                              initial_frequency_mhz=initial['initial_frequency_mhz'],
                              initial_period_ns=initial['initial_period_ns'])
            write(folder/'PROVENANCE.json', provenance)
            self.update(config, 'waiting_for_capacity', provenance=provenance)
            self.reserve()
            try:
                command = [self.meta['vivado'], '-mode', 'batch', '-nolog', '-nojournal',
                           '-notrace', '-source', str(self.tcl), '-tclargs',
                           str(copied), str(folder), str(self.meta['max_implementations']),
                           str(initial['initial_period_ns'])]
                start = time.monotonic()
                with (folder/'vivado.log').open('w') as log:
                    process = subprocess.Popen(command, cwd=folder, stdin=subprocess.DEVNULL,
                                               stdout=log, stderr=subprocess.STDOUT,
                                               start_new_session=True)
                    self.update(config, 'routing', pid=process.pid, started_at=now(),
                                command=command, log=str(folder/'vivado.log'))
                    code = process.wait()  # Routing is never killed by an analysis timeout.
                if code or 'PU_ROUTE_LIMIT_PASS' not in (folder/'vivado.log').read_text(errors='replace'):
                    raise RuntimeError(f'Vivado exit={code}; see {folder / "vivado.log"}')
                result = read(folder/'closed/result.json')
                if not result or result['wns_ns'] < 0 or result['whs_ns'] < 0:
                    raise RuntimeError('No verified setup/hold closure')
                status = route_status(folder/'closed/route_status.rpt')
                drc_text = (folder/'closed/drc.rpt').read_text()
                drc_errors = bool(re.search(r'^\|[^\n]*\|\s*(?:Error|Critical Warning)\s*\|', drc_text, re.M))
                sweep = read(Path(result['best_attempt'])/'sta_sweep.json')
                boundary = (sweep['failing_period_ns'] < result['period_ns'] and
                            (sweep['failing_wns_ns'] < 0 or sweep['failing_whs_ns'] < 0))
                if not status['passed'] or drc_errors or not boundary:
                    raise RuntimeError('Route completeness, DRC, or 0.1 ns boundary audit failed')
                self.update(config, 'passed', finished_at=now(), seconds=time.monotonic()-start,
                            result=result, routed_area=resources(folder/'closed/utilization.rpt'),
                            route_status=status, drc_errors=False, boundary_verified=True,
                            routed_checkpoint=str(folder/'closed/routed.dcp'),
                            routed_checkpoint_sha256=sha(folder/'closed/routed.dcp'))
            finally:
                with self.capacity_lock:
                    self.slots -= 1
        except Exception as error:
            self.update(config, 'failed', finished_at=now(), error=str(error))

    def publish(self):
        self.state['updated_at'] = now()
        source = read(self.source_run/'status.json', {})
        self.state['synthesis_matrix_complete'] = source.get('complete', False)
        self.state['counts'] = {s: sum(t['status'] == s for t in self.state['tasks'].values())
                                for s in ('waiting_for_synthesis', 'waiting_for_capacity', 'routing', 'passed', 'failed')}
        rows = []
        for config, task in self.state['tasks'].items():
            for profile in ('slh_128f', 'xmss_h10', 'lms_h10'):
                sim = source.get('tasks', {}).get(f'sim/{config}/{profile}', {})
                cycles = sim.get('cycles') if sim.get('status') == 'passed' else None
                passed = task['status'] == 'passed'
                hz = task['result']['frequency_mhz'] if passed else None
                area = task['routed_area']['equivalent_slice'] if passed else None
                ms = cycles/(hz*1000) if cycles is not None and hz is not None else None
                rows.append(dict(configuration=config, profile=profile, cycles=cycles,
                                 frequency_mhz=hz, routed_equivalent_slice=area,
                                 time_ms=ms, atp_slice_ms=area*ms if ms is not None else None,
                                 atp_rank=None, route_status=task['status']))
        for profile in ('slh_128f', 'xmss_h10', 'lms_h10'):
            available = sorted((r for r in rows if r['profile'] == profile and r['atp_slice_ms'] is not None),
                               key=lambda r: r['atp_slice_ms'])
            previous, rank = None, None
            for i, row in enumerate(available, 1):
                if row['atp_slice_ms'] != previous:
                    rank = i
                row['atp_rank'] = rank
                previous = row['atp_slice_ms']
        self.state['results'] = rows
        self.state['max_observed_main_vivado'] = self.max_observed_vivado
        write(self.run/'status.json', self.state)
        write(self.report.with_suffix('.json'), self.state)
        write(self.out/'status.json', self.state)
        def fmt(value, digits=3):
            return '—' if value is None else f'{value:,.{digits}f}'
        lines = [f'# {len(self.meta["configs"])} 点 common 布局布线与实测 STA 频率', '',
                 f"更新时间：{self.state['updated_at']}；状态：{'全部结束' if self.state['complete'] else '后台运行'}。{self.state['counts']}", '',
                 f"本次由用户明确授权布线。冻结综合矩阵：`{self.source_run}`，同器件 {self.meta['part']}，每个Vivado两线程，综合与布线合计最多12个主进程。未结束的综合保留后台，完成后自动接续其本次检查点。", '',
                 f'频率口径：common OOC内部受约束setup/hold路径；不含外部ROM、signature或板级IO时序。U1从150MHz（6.666667ns）开始，U2从100MHz（10ns）开始，近闭合周期重新布局布线，最多{self.meta["max_implementations"]}次独立实现；每份路由二分搜索0.1ns周期网格，选择实测最高闭合频率。更快相邻网格点的失败证据保留。结果是本次工具和搜索范围下的最佳实测值，不声称所有布局种子的理论全局极限。', '',
                 '未新增false-path/multicycle或关闭时序优化。闭合要求WNS/WHS≥0、可布线网络全部完成、无DRC Error/Critical Warning。综合面积与布线面积单列；下列实际ATP使用布线等效Slice×周期/STA频率，不沿用150/110MHz假定值。', '',
                 '## 面积及最高闭合频率', '',
                 '| P/U | 综合Slice | 布线LUT | 布线FF | 布线Slice | 闭合周期 ns | STA MHz | WNS ns | WHS ns | 状态 |',
                 '|---|---:|---:|---:|---:|---:|---:|---:|---:|---|']
        for config, task in self.state['tasks'].items():
            syn = source.get('tasks', {}).get(f'synth/{config}/common', {}).get('area', {})
            area, res = task.get('routed_area', {}), task.get('result', {}) if task['status'] == 'passed' else {}
            lines.append('| ' + ' | '.join([config, fmt(syn.get('equivalent_slice')), fmt(area.get('lut'), 0),
                fmt(area.get('ff'), 0), fmt(area.get('equivalent_slice')), fmt(res.get('period_ns')),
                fmt(res.get('frequency_mhz')), fmt(res.get('wns_ns')), fmt(res.get('whs_ns')), task['status']]) + ' |')
        for profile, title in [('slh_128f', 'SLH-DSA 128f Sign'), ('xmss_h10', 'XMSS h10 Sign'), ('lms_h10', 'LMS h10 Sign')]:
            lines += ['', '## ' + title, '', '| ATP排名 | P/U | 周期 | STA MHz | 时间 ms | 布线ATP Slice·ms | 状态 |',
                      '|---:|---|---:|---:|---:|---:|---|']
            for row in sorted((r for r in rows if r['profile'] == profile),
                              key=lambda r: (r['atp_slice_ms'] is None, r['atp_slice_ms'] or 0)):
                lines.append('| ' + ' | '.join([fmt(row['atp_rank'], 0), row['configuration'], fmt(row['cycles'], 0),
                    fmt(row['frequency_mhz']), fmt(row['time_ms'], 6), fmt(row['atp_slice_ms']), row['route_status']]) + ' |')
        lines += ['', '未完成或失败项的频率、ATP和排名留空。排名随本次有效数据更新。', '',
                  f'原始实现、检查点、每次周期扫描和日志：`{self.run}`。冻结RTL、来源校验、综合及路由报告已归档，原始仿真明细保留在综合矩阵build目录。', '']
        atomic(self.report.with_suffix('.md'), '\n'.join(lines))
        self.archive()

    def archive(self):
        for file in ('SOURCE.json', 'SYNTHESIS_SOURCE.json', 'CONTROL_SOURCE.json'):
            copy_changed(self.run/file, self.out/file)
        pack_rtl(self.frozen_source, self.out/'rtl.tar.gz', self.meta['rtl_and_dependency_sha256'])
        for path in (self.run/'control').glob('*'):
            if path.is_file():
                copy_changed(path, self.out/'control'/path.name)
        for config in self.state['tasks']:
            for base, target in [(self.source_run/'synth'/config/'common', self.out/'synth'/config/'common'),
                                 (self.run/'route'/config, self.out/'route'/config)]:
                if not base.exists():
                    continue
                for p in base.rglob('*'):
                    if p.is_file() and not any(x in ('.Xil', 'input') for x in p.relative_to(base).parts) and p.suffix in ('.rpt', '.log', '.json', '.txt'):
                        copy_changed(p, target/p.relative_to(base))
        checks = {str(p.relative_to(self.out)): sha(p) for p in self.out.rglob('*')
                  if p.is_file() and p.name != 'ARTIFACTS.json' and not p.name.endswith('.tmp')}
        write(self.out/'ARTIFACTS.json', dict(updated_at=now(), sha256=checks,
              checkpoints_retained_in_build=True, omitted_details=['sim', 'validation'], complete=self.state['complete']))
        index()

    def monitor(self):
        while not self.stop_monitor.wait(20):
            try:
                count = len(live_vivado())
                self.max_observed_vivado = max(self.max_observed_vivado, count)
                with self.lock:
                    self.publish()
            except Exception as error:
                print(now(), 'MONITOR_ERROR', str(error), flush=True)

    def execute(self):
        self.max_observed_vivado = len(live_vivado())
        with self.lock:
            self.publish()
        monitor = threading.Thread(target=self.monitor, daemon=True)
        monitor.start()
        source = read(self.source_run/'status.json', {})
        configs = sorted(self.state['tasks'], key=lambda c: source.get('tasks', {}).get(f'synth/{c}/common', {}).get('status') != 'passed')
        try:
            with ThreadPoolExecutor(max_workers=12) as pool:
                list(pool.map(self.execute_one, configs))
        finally:
            self.stop_monitor.set()
            monitor.join()
        integrity = all(sha(self.frozen_source/k) == v for k, v in self.meta['rtl_and_dependency_sha256'].items())
        control_integrity = all(sha(self.run/'control'/k) == v
                                for k, v in read(self.run/'CONTROL_SOURCE.json').items())
        with self.lock:
            self.state.update(complete=True, finished_at=now(), source_unchanged=integrity,
                              control_source_unchanged=control_integrity,
                              passed=integrity and control_integrity and all(t['status'] == 'passed' for t in self.state['tasks'].values()))
            self.publish()
        print(now(), 'PU_ROUTE_MATRIX_END', self.state['passed'], flush=True)
        return 0 if self.state['passed'] else 1


def launch(args):
    if not args.authorize_routing:
        raise SystemExit('Routing requires an explicit user request and --authorize-routing; default experiments synthesize only.')
    source_run = args.synthesis_run.resolve()
    source_meta = read(source_run/'SOURCE.json')
    if not source_meta or source_meta.get('area_top') != 'common':
        raise ValueError('Expected an existing frozen common synthesis matrix')
    configs = select_configs(source_meta.get('configs'), args.configs)
    source_status = read(source_run/'status.json', {})
    for p, u in configs:
        if f'synth/P{p}U{u}/common' not in source_status.get('tasks', {}):
            raise ValueError(f'Missing frozen synthesis task P{p}U{u}/common; no other DCP substituted')
    frozen = Path(source_meta['source_root'])
    if any(sha(frozen/k) != v for k, v in source_meta['sha256'].items()):
        raise ValueError('Frozen synthesis source integrity failed')
    stamp = datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y%m%d_%H%M%S')
    run = ROOT/'build/pu_route_matrix'/stamp
    (run/'control').mkdir(parents=True)
    for file in ('run_pu_route_matrix.py', 'route_pu_limit.tcl', 'experiment_archive.py'):
        shutil.copy2(ROOT/'scripts'/file, run/'control'/file)
    metadata = dict(schema='mhbs.pu_route_matrix.source.v1', run_id=stamp, started_at=now(),
                    source_root=str(frozen), synthesis_run=str(source_run), configs=configs,
                    synthesis_configs=source_meta['configs'],
                    area_top='common', part=source_meta['part'], vivado=source_meta['vivado'],
                    synthesis_manifest_sha256=sha(source_run/'SOURCE.json'),
                    rtl_and_dependency_sha256=source_meta['sha256'],
                    archive_directory=str(ROOT/'docs/manifests/experiments'/('pu_route_matrix_' + stamp)),
                    max_implementations=args.max_implementations, period_grid_ns=0.1,
                    initial_frequency_mhz_by_unroll={'1': 150, '2': 100},
                    initial_period_ns_by_unroll={'1': 6.666667, '2': 10.0},
                    max_total_vivado=12, threads_per_vivado=2,
                    explicit_user_authorization=True,
                    user_request=f'2026-10-15: 对明确选定的{len(configs)}个common配置布线并测STA闭合频率；U1起始150MHz、U2起始100MHz；只有明确指定才布线。')
    write(run/'SOURCE.json', metadata)
    shutil.copy2(source_run/'SOURCE.json', run/'SYNTHESIS_SOURCE.json')
    write(run/'CONTROL_SOURCE.json', {p.name: sha(p) for p in (run/'control').iterdir() if p.is_file()})
    # The frozen control directory needs the repository for output paths only.
    env = os.environ.copy()
    env['MHBS_ROUTE_WORKSPACE'] = str(ROOT)
    with (run/'runner.log').open('w') as log:
        child = subprocess.Popen([sys.executable, str(run/'control/run_pu_route_matrix.py'), '--run-root', str(run)],
                                 cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log,
                                 stderr=subprocess.STDOUT, start_new_session=True)
    write(run/'LAUNCH.json', dict(pid=child.pid, root=str(run), log=str(run/'runner.log')))
    deadline = time.monotonic() + 30
    while not (run/'status.json').exists():
        if child.poll() is not None:
            raise RuntimeError(f'Runner exited; see {run / "runner.log"}')
        if time.monotonic() >= deadline:
            raise RuntimeError(f'Runner active, initial status delayed; see {run / "runner.log"}')
        time.sleep(0.1)
    print(json.dumps(dict(pid=child.pid, root=str(run), status=str(run/'status.json'),
                         report=str(Path(metadata['archive_directory'])/'reports'/('PU_Route_Matrix_' + stamp + '.md'))), indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--launch', action='store_true')
    parser.add_argument('--authorize-routing', action='store_true')
    parser.add_argument('--synthesis-run', type=Path)
    parser.add_argument('--configs', nargs='+', metavar='PxUy',
                        help='Select configurations present in the frozen common matrix; default: all its points')
    parser.add_argument('--run-root', type=Path)
    parser.add_argument('--max-implementations', type=int, default=6)
    args = parser.parse_args()
    if args.launch == bool(args.run_root):
        parser.error('Choose --launch or --run-root')
    if args.launch and not args.synthesis_run:
        parser.error('--synthesis-run is required')
    if args.configs and not args.launch:
        parser.error('--configs requires --launch; existing runs use their frozen selection')
    if not 1 <= args.max_implementations <= 10:
        parser.error('--max-implementations must be 1..10')
    if args.launch:
        launch(args)
        return 0
    return Runner(args.run_root.resolve()).execute()


if __name__ == '__main__':
    if os.environ.get('MHBS_ROUTE_WORKSPACE'):
        ROOT = Path(os.environ['MHBS_ROUTE_WORKSPACE']).resolve()
    sys.exit(main())
