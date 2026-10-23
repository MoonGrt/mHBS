#!/usr/bin/env python3
"""Finish focused measurements, then run only authorized fixed target routes.

C3 and C4 form the final comparison. The six target configurations must pass
complete Sign, 100 MHz diagnostics and the frozen 36-group functional validator.
P12U1 is supplemental and never a gate. A candidate dominated on both P1 fixed
frequency ATP and diagnostic path is not routed; nondominated alternatives may
both be routed (at most twelve jobs). Diagnostic delay is never treated as Fmax.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import experiment_archive as archive
import run_dual_pu_route_matrix as dual
import run_p1sha_atp_optimization as focused

ROOT, FAMILY = focused.ROOT, focused.ROOT / 'build/p1sha_atp_optimization'
RUNS = ('candidate_20261021_203556', 'candidate_20261021_204522')
TARGETS = focused.ROUTE_CONFIGS
BASELINE = focused.BASELINE
OUT = ROOT / 'docs/manifests/experiments/p1sha_atp_baseline_20261021_202753'
PREFIX = OUT / 'reports/P1_SHA_ATP_Automation_20261021'
read, write, sha, require, now = focused.read, focused.write, focused.sha, focused.require, focused.now


def readiness(run):
    meta, state = read(run / 'SOURCE.json'), read(run / 'status.json')
    pending, failed = [], []
    for config in TARGETS:
        synthesis = state['synthesis'][config]
        if synthesis['status'] == 'failed':
            failed.append('diagnostic/' + config)
        elif synthesis['status'] != 'passed':
            pending.append('diagnostic/' + config)
        for profile in dual.PROFILES:
            key = config + '/' + profile
            test = state['tests'][key]
            if test['status'] == 'failed':
                failed.append('Sign/' + key)
            elif test['status'] != 'passed':
                pending.append('Sign/' + key)
    functional = run / 'functional_validation/VALIDATION.json'
    if not functional.is_file() or not read(functional).get('complete'):
        pending.append('functional_validation/36')
    elif read(functional).get('failed') or read(functional).get('passed') != 36:
        failed.append('functional_validation/36')
    return dict(run_root=str(run), ready=not pending and not failed, pending=pending,
                failed=failed, source_manifest_sha256=sha(run / 'SOURCE.json'))


def validate_ready(run):
    require(readiness(run)['ready'], 'Target points not ready')
    meta, state = read(run / 'SOURCE.json'), read(run / 'status.json')
    manifest = sha(run / 'SOURCE.json')
    require(focused.unchanged(meta), 'Frozen source changed')
    summary = read(run / 'functional_validation/VALIDATION.json')
    require(summary['source_manifest_sha256'] == manifest and summary['source_unchanged']
            and not summary['source_mismatches'] and summary['passed'] == summary['total_planned'] == 36,
            'Functional summary source or count differs')
    require(sha(run / 'functional_validation/validator.py') == summary['validator_sha256'],
            'Functional validator changed')
    for test in summary['tests']:
        require(test['passed'] and sha(test['log']) == test['log_sha256'], 'Functional raw log changed')
    for config in TARGETS:
        syn = state['synthesis'][config]
        require(syn['source_manifest_sha256'] == manifest and syn['source_unchanged'], 'Diagnostic source differs')
        for name, wanted in syn['reports_sha256'].items():
            require(sha(run / 'synth' / config / name) == wanted, 'Diagnostic report changed')
        for profile in dual.PROFILES:
            test = state['tests'][config + '/' + profile]
            require(test['source_manifest_sha256'] == manifest and test['source_unchanged']
                    and test['output_and_signature_cache_checked_bytewise'], 'Sign source or byte checks differ')
            for field in ('log', 'raw_log'):
                require(sha(test[field]) == test[field + '_sha256'], 'Sign raw log changed')
    archive.copy_changed(run / 'functional_validation/VALIDATION.json',
        Path(meta['archive_directory']) / 'supplementary_evidence/functional/SUMMARY.json')
    archive.copy_changed(run / 'functional_validation/validator.py',
        Path(meta['archive_directory']) / 'supplementary_evidence/functional/validator.py')
    return meta, state


def score(run):
    meta, state = validate_ready(run)
    baseline = read(BASELINE / 'status.json')
    atp, paths, details = [], [], []
    for config in TARGETS:
        if '/P1U' not in config:
            continue
        syn, base_syn = state['synthesis'][config], baseline['synthesis'][config]
        path_ratio = syn['timing']['data_path_ns'] / base_syn['timing']['data_path_ns']
        paths.append(path_ratio)
        for profile in dual.PROFILES:
            key = config + '/' + profile
            ratio = (syn['area']['equivalent_slice'] * state['tests'][key]['cycles'] /
                     (base_syn['area']['equivalent_slice'] * baseline['tests'][key]['cycles']))
            atp.append(ratio)
            details.append(dict(config=config, profile=profile, assumed_atp_ratio=ratio,
                                diagnostic_path_ratio=path_ratio))
    return dict(run_root=str(run), source_manifest_sha256=sha(run / 'SOURCE.json'), label=state['label'],
        p1_assumed_atp_geomean_ratio=math.exp(sum(map(math.log, atp))/len(atp)),
        p1_diagnostic_path_geomean_ratio=math.exp(sum(map(math.log, paths))/len(paths)),
        p1_worst_assumed_atp_ratio=max(atp), p1_worst_diagnostic_path_ratio=max(paths), details=details)


class PhysicalRunner(dual.Runner):
    """Independent physical status avoids racing a supplemental P12 synthesis."""
    reserve = focused.Runner.reserve
    release_capacity = focused.Runner.release_capacity

    def __init__(self, run):
        self.run = Path(run).resolve()
        self.meta = dict(read(self.run / 'SOURCE.json'), **read(self.run / 'EXPERIMENT.json'))
        self.source, self.out = Path(self.meta['source_root']), Path(self.meta['archive_directory'])
        validate_ready(self.run)
        self.lock, self.capacity_lock = threading.RLock(), threading.Lock()
        self.capacity_token = threading.local()
        self.reserved, self.copied = 0, {}
        self.state = dict(schema='mhbs.p1sha.fixed_targets.v1', pid=os.getpid(), started_at=now(), complete=False,
            source_manifest_sha256=sha(self.run / 'SOURCE.json'), targets=TARGETS,
            source_unchanged=None, supplemental_p12_not_a_gate=True,
            routes={c: dict(status='pending', target_frequency_mhz=150 if focused.parts(c)[2] == 1 else 100)
                    for c in TARGETS})

    def route(self, backend, p, u):
        self.capacity_token.worker_marker = str(self.run / 'jobs' / f'{backend}/P{p}U{u}')
        try:
            return super().route(backend, p, u)
        finally:
            self.release_capacity()

    def publish(self):
        self.state['updated_at'] = now()
        self.state['counts'] = {s: sum(t['status'] == s for t in self.state['routes'].values())
                               for s in sorted({t['status'] for t in self.state['routes'].values()})}
        simulations = read(self.run / 'status.json')['tests']
        rows = []
        for config, route in self.state['routes'].items():
            if not route.get('meets_target') or not route.get('source_unchanged'):
                continue
            period = route['result']['actual_period_ns']
            for profile in dual.PROFILES:
                test = simulations[config + '/' + profile]
                rows.append(dict(config=config, profile=profile, cycles=test['cycles'],
                    actual_frequency_mhz=1000/period, routed_equivalent_slice=route['routed_area']['equivalent_slice'],
                    routed_time_ms=test['cycles']*period/1e6,
                    routed_atp_slice_ms=route['routed_area']['equivalent_slice']*test['cycles']*period/1e6))
        self.state['closed_routed_atp'] = rows
        for base in (self.run, self.out):
            write(base / 'PHYSICAL_STATUS.json', self.state)
        prefix = self.out / 'reports' / ('P1_SHA_Fixed_Targets_' + self.meta['run_id'])
        write(prefix.with_suffix('.json'), dict(source=self.meta, results=self.state))
        fmt = lambda v: '—' if v is None else f'{v:,.3f}'
        lines = ['# P1／SHA 最终指定频率物理验证', '',
            f'候选：{self.meta["label"]}；更新时间：{self.state["updated_at"]}；'
            f'状态：{"全部结束" if self.state["complete"] else "后台运行"}。', '',
            '仅六个目标点，U1=150MHz、U2=100MHz；common OOC、xc7a200tffg1156-3、'
            '默认时序驱动、每进程2线程、全机最多12个。没有降频、频率搜索或新增时序例外。'
            '全部18个目标完整Sign、六点100MHz诊断和36组冻结源功能验证通过后才启动。'
            '附加P12U1诊断不阻塞本物理阶段，物理状态独立写PHYSICAL_STATUS.json。', '',
            '150MHz的6.667ns量化以实际149.9925MHz计ATP。没有setup/hold、DRC和完整路由通过的数据不计算布线ATP。'
            '基线六点原目标均未闭合，不能从负WNS外推基线频率或布线ATP。', '',
            '| 后端／配置 | 目标MHz | 综合Slice | 布线Slice | BRAM36 | WNS ns | WHS ns | 状态 |',
            '|---|---:|---:|---:|---:|---:|---:|---|']
        for config, item in self.state['routes'].items():
            result = item.get('result', {})
            lines += ['| ' + ' | '.join([config, fmt(item['target_frequency_mhz']),
                fmt(item.get('synth_area', {}).get('equivalent_slice')),
                fmt(item.get('routed_area', {}).get('equivalent_slice')),
                fmt(item.get('routed_area', {}).get('bram36')), fmt(result.get('wns_ns')),
                fmt(result.get('whs_ns')), item['status']]) + ' |']
        lines += ['', '| 后端／配置 | Sign | 周期 | 实际MHz | 布线时间ms | 布线ATP Slice·ms |',
            '|---|---|---:|---:|---:|---:|']
        lines += ['| ' + ' | '.join([r['config'], r['profile'], fmt(r['cycles']), fmt(r['actual_frequency_mhz']),
            fmt(r['routed_time_ms']), fmt(r['routed_atp_slice_ms'])]) + ' |' for r in rows]
        lines += ['', f'冻结SOURCE SHA256：`{self.state["source_manifest_sha256"]}`；运行目录：`{self.run}`。', '']
        archive.atomic(prefix.with_suffix('.md'), '\n'.join(lines))
        for path in (self.run / 'jobs').rglob('*') if (self.run / 'jobs').exists() else []:
            if path.is_file() and path.suffix in ('.rpt', '.log', '.json', '.txt', '.xdc'):
                signature = (path.stat().st_mtime_ns, path.stat().st_size)
                if self.copied.get(path) != signature:
                    archive.copy_changed(path, self.out / path.relative_to(self.run))
                    self.copied[path] = signature
        required = ('synth/hierarchical.rpt', 'synth/timing.rpt', 'route/hierarchical.rpt',
                    'route/timing.rpt', 'route/critical_paths.rpt', 'route/route_status.rpt',
                    'route/drc.rpt', 'result.json')
        evidence = [p for p in (self.out / 'jobs').rglob('*') if p.is_file()] if (self.out / 'jobs').exists() else []
        evidence += [p for p in (self.out / 'physical_control').glob('*') if p.is_file()]
        evidence += [p for p in (prefix.with_suffix('.md'), prefix.with_suffix('.json'),
            self.out / 'PHYSICAL_STATUS.json', self.out / 'PHYSICAL_REQUEST.json', self.out / 'PHYSICAL_LAUNCH.json')
            if p.is_file()]
        write(self.out / 'PHYSICAL_ARTIFACTS.json', dict(complete=self.state['complete'],
            source_manifest_sha256=self.state['source_manifest_sha256'],
            missing={c: [n for n in required if not (self.out / 'jobs' / c / n).is_file()] for c in TARGETS},
            sha256={str(p.relative_to(self.out)): sha(p) for p in evidence}))

    def execute(self):
        self.publish()
        with ThreadPoolExecutor(max_workers=3) as pool:
            jobs = [pool.submit(self.route, *focused.parts(config)) for config in TARGETS]
            for job in as_completed(jobs):
                job.result()
        self.state.update(complete=True, source_unchanged=self.unchanged(), finished_at=now())
        self.publish()
        return 0


def launch_physical(run):
    require(not (run / 'PHYSICAL_LAUNCH.json').exists(), 'Physical phase already launched')
    meta = read(run / 'SOURCE.json')
    out = Path(meta['archive_directory'])
    controls = ('coordinate_p1sha_atp_optimization.py', *focused.CONTROLS)
    for name in controls:
        for base in (run, out):
            archive.copy_changed(ROOT / 'scripts' / name, base / 'physical_control' / name)
    request = dict(source_manifest_sha256=sha(run / 'SOURCE.json'), requested_at=now(),
        configs=TARGETS, targets_by_unroll={'1': 150, '2': 100}, user_authorized_fixed_targets=True,
        frequency_search=False, automatic_frequency_fallback=False, supplemental_p12_not_a_gate=True,
        controls_sha256={n: sha(run / 'physical_control' / n) for n in controls})
    for base in (run, out):
        write(base / 'PHYSICAL_REQUEST.json', request)
    with (run / 'physical_runner.log').open('w') as stream:
        process = subprocess.Popen([sys.executable, str(run / 'physical_control/coordinate_p1sha_atp_optimization.py'),
            '--physical-run', str(run)], cwd=ROOT, env=dict(os.environ, MHBS_P1SHA_WORKSPACE=str(ROOT)),
            stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
    request.update(pid=process.pid)
    for base in (run, out):
        write(base / 'PHYSICAL_LAUNCH.json', request)
    return request


def coordinate():
    state = dict(schema='mhbs.p1sha.coordinator.v1', pid=os.getpid(), started_at=now(), complete=False,
        runs=RUNS, targets=TARGETS, phase='waiting_for_measurements', upgraded=[], selected=[],
        policy='Nondominated C3/C4 by P1 assumed-ATP and diagnostic-path geometric mean; route at most two same-source candidates. Diagnostic path is not Fmax.')
    while True:
        # Original C2/C3 dispatchers were frozen before cross-process admission
        # improvements. Upgrade only after Sign completes and before any Vivado
        # has been started by that dispatcher; preserve all old controls/logs.
        for name in ('candidate_20261021_203456', 'candidate_20261021_203556'):
            run = FAMILY / name
            if (run / 'DISPATCHER_UPGRADE.json').exists():
                continue
            current = read(run / 'status.json')
            if (not current['complete'] and all(t['status'] == 'passed' for t in current['tests'].values())
                    and all(t['status'] in ('pending', 'waiting_for_capacity', 'passed')
                            for t in current['synthesis'].values())
                    and not any(str(run) in j['command'] for j in focused.live_groups())):
                focused.upgrade_dispatcher(run)
                state['upgraded'].append(name)
        state['readiness'] = {name: readiness(FAMILY / name) for name in RUNS}
        if not state['selected'] and all(r['ready'] or r['failed'] for r in state['readiness'].values()):
            scores = [score(FAMILY / name) for name in RUNS if state['readiness'][name]['ready']]
            selected = []
            for candidate in scores:
                dominated = any(other is not candidate and
                    other['p1_assumed_atp_geomean_ratio'] <= candidate['p1_assumed_atp_geomean_ratio'] and
                    other['p1_diagnostic_path_geomean_ratio'] <= candidate['p1_diagnostic_path_geomean_ratio'] and
                    (other['p1_assumed_atp_geomean_ratio'] < candidate['p1_assumed_atp_geomean_ratio'] or
                     other['p1_diagnostic_path_geomean_ratio'] < candidate['p1_diagnostic_path_geomean_ratio'])
                    for other in scores)
                if not dominated:
                    selected.append(candidate)
            state.update(scores=scores, selected=selected, phase='fixed_target_routes')
            require(selected, 'No final candidate passed validation')
            for candidate in selected:
                launch_physical(Path(candidate['run_root']))
        if state['selected']:
            state['physical'] = {}
            for candidate in state['selected']:
                path = Path(candidate['run_root']) / 'PHYSICAL_STATUS.json'
                state['physical'][Path(candidate['run_root']).name] = read(path) if path.is_file() else dict(complete=False)
            if all(v.get('complete') for v in state['physical'].values()):
                state.update(complete=True, phase='complete', finished_at=now())
        state['updated_at'] = now()
        write(FAMILY / 'COORDINATOR_STATUS.json', state)
        write(OUT / 'COORDINATOR_STATUS.json', state)
        write(PREFIX.with_suffix('.json'), state)
        lines = ['# P1／SHA 后台测量与最终路由协调', '',
            f'更新时间：{state["updated_at"]}；阶段：`{state["phase"]}`；PID：{state["pid"]}。', '',
            'C3/C4的六个目标点（SHAKE/SHA2 P1U1、P1U2，SHA2 P4U1、P4U2）完成18项完整Sign、'
            '六点100MHz诊断、36组正常/综合视图功能验证后自动启动最终路由。'
            'P12U1附加诊断不阻塞。U1固定150MHz、U2固定100MHz，不降频、不搜索、不加时序例外。', '',
            '对C3/C4计算四个P1配置三算法假定ATP比的几何均值，以及四点诊断路径比的几何均值；'
            '二者均被另一候选支配的候选不重复布线，存在取舍时保留两者，各自六点。'
            '这是选择实验范围的规则，不是最终Fmax或ATP结论；最终按实际STA和布线ATP评估。', '',
            '| 候选 | 就绪 | 尚待项 | 失败项 |', '|---|---|---:|---:|']
        for name, status in state['readiness'].items():
            lines += [f'| {name} | {status["ready"]} | {len(status["pending"])} | {len(status["failed"])} |']
        if state.get('scores'):
            lines += ['', '| 候选 | P1假定ATP几何均值比 | P1诊断路径几何均值比 | 选中 |', '|---|---:|---:|---|']
            selected_names = {c['run_root'] for c in state['selected']}
            for c in state['scores']:
                lines += [f'| {c["label"]} | {c["p1_assumed_atp_geomean_ratio"]:.6f} | '
                    f'{c["p1_diagnostic_path_geomean_ratio"]:.6f} | {c["run_root"] in selected_names} |']
        for name, physical in state.get('physical', {}).items():
            meta = read(FAMILY / name / 'SOURCE.json')
            target_report = Path(meta['archive_directory']) / 'reports' / ('P1_SHA_Fixed_Targets_' + meta['run_id'] + '.md')
            lines += ['', f'[{name}最终物理报告]({target_report.relative_to(ROOT)})；状态：'
                f'`{json.dumps(physical.get("counts", {}), ensure_ascii=False)}`。']
        lines += ['', '长任务保留后台。全机跨进程预约包含Vivado wrapper与实际进程并去重，最多12个、每进程2线程。'
            '所有冻结源码、逐项证据和控制器升级记录保留；原矩阵进程不终止。', '']
        archive.atomic(PREFIX.with_suffix('.md'), '\n'.join(lines))
        for control in ('coordinate_p1sha_atp_optimization.py', 'run_p1sha_atp_optimization.py'):
            archive.copy_changed(ROOT / 'scripts' / control, OUT / 'automation_control' / control)
        write(OUT / 'automation_control/SOURCE.json', {n: sha(OUT / 'automation_control' / n)
            for n in ('coordinate_p1sha_atp_optimization.py', 'run_p1sha_atp_optimization.py')})
        if state['complete']:
            for name in RUNS:
                run = FAMILY / name
                if (run / 'PHYSICAL_ARTIFACTS.json').is_file():
                    # The detailed fixed-clock evidence stays in the candidate
                    # archive; the coordinator never combines candidate areas.
                    archive.copy_changed(run / 'PHYSICAL_STATUS.json',
                        OUT / 'final_physical_status' / (name + '.json'))
            subprocess.run([sys.executable, str(ROOT / 'scripts/report_p1sha_atp_optimization.py')], cwd=ROOT, check=True)
            subprocess.run([sys.executable, str(ROOT / 'scripts/audit_p1sha_atp_archive.py')], cwd=ROOT, check=True)
            archive.index()
            return
        time.sleep(15)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--launch', action='store_true')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--physical-run', type=Path)
    args = parser.parse_args()
    if args.physical_run:
        raise SystemExit(PhysicalRunner(args.physical_run).execute())
    if args.launch:
        require(not (FAMILY / 'COORDINATOR_LAUNCH.json').exists(), 'Coordinator already launched')
        with (FAMILY / 'coordinator.log').open('w') as stream:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--run'], cwd=ROOT,
                stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        value = dict(pid=process.pid, report=str(PREFIX.with_suffix('.md')), source_sha256=sha(__file__))
        write(FAMILY / 'COORDINATOR_LAUNCH.json', value)
        print(json.dumps(value, indent=2))
    elif args.run:
        coordinate()
    else:
        parser.error('Choose --launch, --run or --physical-run')
