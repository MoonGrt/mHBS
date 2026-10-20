#!/usr/bin/env python3
"""Observe existing 150-MHz routes; test only failing points once at 130 MHz.

This coordinator never changes the running candidate controller or RTL. It does
not search frequencies: the only additional implementation is the specified
130-MHz target for a configuration whose original 150-MHz setup/hold failed.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from zoneinfo import ZoneInfo

import experiment_archive as archive
from run_pu_route_matrix import live_vivado, resources, route_status

ROOT = Path(os.environ.get('MHBS_FIXED_TARGET_WORKSPACE', Path(__file__).resolve().parents[1])).resolve()
archive.ROOT = ROOT
archive.ARCHIVES = ROOT / 'docs/manifests/experiments'
CONFIGS = ('P12U1', 'P4U1')
PROFILES = ('slh_128f', 'lms_h10', 'xmss_h10')
SCHEMA = 'shake_two_fixed_targets_v1'
TERMINAL = ('passed', 'target_not_met', 'failed', 'blocked_validation')


def now():
    return datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds')


def sha(path):
    return archive.sha(Path(path))


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    archive.atomic(Path(path), json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def unchanged(meta):
    source = Path(meta['source_root'])
    return all((source / name).is_file() and sha(source / name) == value
               for name, value in meta['sha256'].items())


def accepted(result, routing, frequency):
    return bool(result.get('setup_hold_met') and result.get('drc_errors') == 0 and routing['passed']
                and result['actual_period_ns'] <= 1000 / frequency + 1e-6)


class Coordinator:
    def __init__(self, run):
        self.run = run
        self.meta = read(run / 'SOURCE.json')
        if self.meta.get('schema') != SCHEMA:
            raise ValueError('Unexpected coordinator schema')
        self.candidate_run = Path(self.meta['candidate_run'])
        self.candidate = read(self.candidate_run / 'SOURCE.json')
        self.out = Path(self.meta['archive_directory'])
        self.lock = threading.RLock()
        self.capacity_lock = threading.Lock()
        self.reserved = 0
        self.state = dict(schema=SCHEMA, pid=os.getpid(), complete=False, started_at=now(),
            source_unchanged=None, tasks={config: dict(status='waiting_for_150MHz',
                initial_frequency_mhz=150.0, additional_frequency_mhz=130.0,
                additional_implementations=0) for config in CONFIGS})

    def bound_source_valid(self):
        return (sha(self.candidate_run / 'SOURCE.json') == self.meta['candidate_manifest_sha256']
                and unchanged(self.candidate)
                and all(sha(self.run / 'control' / name) == value
                        for name, value in self.meta['control_sha256'].items()))

    def publish(self):
        self.state['updated_at'] = now()
        live = read(self.candidate_run / 'status.json')
        comparisons = []
        for config, task in self.state['tasks'].items():
            final = task.get('selected_result')
            for profile in PROFILES:
                sim = live.get('tests', {}).get(f'{config}/{profile}', {})
                row = dict(configuration=config, profile=profile, cycles=sim.get('cycles'),
                           sign_status=sim.get('status', 'pending'))
                if final and sim.get('status') == 'passed':
                    frequency = 1000 / final['result']['actual_period_ns']
                    row.update(verified_frequency_mhz=frequency, routed_slice=final['area']['equivalent_slice'],
                        time_ms=sim['cycles'] / (frequency * 1000),
                        atp_slice_ms=final['area']['equivalent_slice'] * sim['cycles'] / (frequency * 1000))
                comparisons.append(row)
        self.state['comparisons'] = comparisons
        write(self.run / 'status.json', self.state)
        write(self.out / 'status.json', self.state)
        prefix = self.out / 'reports' / ('SHAKE_Fixed_Targets_' + self.meta['run_id'])
        write(prefix.with_suffix('.json'), dict(source=self.meta, results=self.state))
        fmt = lambda value: '—' if value is None else f'{value:,.3f}'
        lines = ['# SHAKE 两个固定目标的布线验证', '',
            f'更新时间：{self.state["updated_at"]}；状态：{"完成" if self.state["complete"] else "后台观察／运行"}。', '',
            f'候选：`{self.candidate_run.name}`。先等现有 P12U1／P4U1 的 150 MHz 布线终态；'
            '仅 setup／hold 未闭合的点额外执行一次 130 MHz 重新综合和布线。'
            '150 MHz 通过的点直接采用原证据；工具错误、DRC 或路由错误不被当作频率失败自动重跑。'
            '这是两个预先指定的固定目标，不进行频率搜索或新增时序例外。', '',
            'common OOC、xc7a200tffg1156-3、SHAKE 通用 Keccak、默认时序驱动、SYNTHESIS 统计裁剪；'
            '每个 Vivado 两线程，全机最多 12 个。每个新增任务启动前核对冻结源码、控制脚本及三组完整 Sign 证据。'
            '异常耗时只延后分析，不停止任何原任务或新增任务。', '',
            '| 配置 | 150MHz WNS ns | 150MHz WHS ns | 130MHz WNS ns | 130MHz WHS ns | 验收频率 MHz | 状态 |',
            '|---|---:|---:|---:|---:|---:|---|']
        for config, task in self.state['tasks'].items():
            initial, extra = task.get('initial_result', {}).get('result', {}), task.get('additional_result', {}).get('result', {})
            chosen = task.get('selected_result', {}).get('result', {})
            frequency = 1000 / chosen['actual_period_ns'] if chosen else None
            label = task['status'] + ('／分析延后，进程继续' if task.get('analysis_deferred') else '')
            lines.append('| ' + ' | '.join([config, fmt(initial.get('wns_ns')), fmt(initial.get('whs_ns')),
                fmt(extra.get('wns_ns')), fmt(extra.get('whs_ns')), fmt(frequency), label]) + ' |')
        lines += ['', '| 配置 | 算法 | Sign周期 | 布线 Slice | 验收频率 MHz | 时间 ms | ATP Slice·ms |',
            '|---|---|---:|---:|---:|---:|---:|']
        for row in comparisons:
            lines.append('| ' + ' | '.join([row['configuration'], row['profile'], fmt(row.get('cycles')),
                fmt(row.get('routed_slice')), fmt(row.get('verified_frequency_mhz')),
                fmt(row.get('time_ms')), fmt(row.get('atp_slice_ms'))]) + ' |')
        lines += ['', '只有完整布线、DRC、受约束内部 setup／hold 及实际时钟周期全部满足目标时才填写频率与 ATP。'
            '100 MHz 诊断综合不作为布线验收；本报告不将失败目标的 WNS 代入公式估算最高频率。', '',
            '本协调器未额外启动基线 100 MHz 布线。归档的 `BASELINE_PREPROCESSED_EQUIVALENCE.json` '
            '仅证明此前 SHAKE SYNTHESIS common 可达的七个模块预处理源码一致；'
            '它不等于网表形式等价，也不新增基线布线结果。', '',
            f'运行目录：`{self.run}`。完整 Vivado 日志、综合与布线报告及冻结 RTL／SHA 归档；'
            '未完成项保留空白并自动补齐。原仿真明细继续保存在候选运行目录。', '']
        for config, task in self.state['tasks'].items():
            if task.get('error'):
                lines += [f'{config}：{task["error"]}', '']
        archive.atomic(prefix.with_suffix('.md'), '\n'.join(lines))
        missing = {}
        for config, task in self.state['tasks'].items():
            folders = [('initial_150MHz', self.candidate_run / 'route' / config),
                       ('additional_130MHz', self.run / 'jobs' / config)]
            for label, folder in folders:
                target = self.out / 'jobs' / config / label
                for path in folder.rglob('*') if folder.exists() else []:
                    if path.is_file() and path.suffix in ('.rpt', '.log', '.txt', '.xdc', '.json'):
                        archive.copy_changed(path, target / path.relative_to(folder))
                required = ['synth/hierarchical.rpt', 'synth/timing.rpt', 'route/hierarchical.rpt',
                            'route/timing.rpt', 'route/route_status.rpt', 'route/drc.rpt', 'result.json']
                if label == 'additional_130MHz' and not task.get('additional_implementations'):
                    required = []
                missing[f'{config}/{label}'] = [name for name in required if not (target / name).exists()]
        write(self.out / 'ARTIFACTS.json', dict(complete=self.state['complete'], missing=missing,
            omitted_details=['sim', 'validation'], sha256={str(p.relative_to(self.out)): sha(p)
                for p in self.out.rglob('*') if p.is_file() and p.name != 'ARTIFACTS.json'
                and not p.name.endswith('.tmp')}))

    def update(self, config, **values):
        with self.lock:
            self.state['tasks'][config].update(values)
            self.publish()

    def validated_sign(self, state, config):
        for profile in PROFILES:
            sim = state.get('tests', {}).get(f'{config}/{profile}', {})
            if (sim.get('status') != 'passed' or not sim.get('source_unchanged')
                    or sim.get('source_manifest_sha256') != self.meta['candidate_manifest_sha256']):
                return False
            if not sim.get('log') or sha(sim['log']) != sim.get('log_sha256'):
                return False
            for name, checksum in sim.get('vectors_sha256', {}).items():
                vector = Path(self.candidate['source_root']) / 'tb/vectors' / profile / 'sign' / name
                if sha(vector) != checksum:
                    return False
        return True

    def initial_evidence(self, config, task):
        folder = self.candidate_run / 'route' / config
        if task.get('source_manifest_sha256') != self.meta['candidate_manifest_sha256']:
            raise ValueError('Original route manifest binding differs')
        if not task.get('source_unchanged'):
            raise ValueError('Original route did not verify frozen source')
        reports = task.get('reports_sha256', {})
        if not reports or not all(sha(folder / name) == checksum for name, checksum in reports.items()):
            raise ValueError('Original route report checksum mismatch')
        result = read(folder / 'result.json')
        if result != task.get('result') or abs(result['target_frequency_mhz'] - 150.0) > 1e-6:
            raise ValueError('Original route was not the bound 150-MHz target')
        routing = route_status(folder / 'route/route_status.rpt')
        return dict(result=result, route_status=routing, area=resources(folder / 'route/utilization.rpt'),
                    reports_sha256=reports, evidence_directory=str(folder))

    def reserve(self):
        while True:
            with self.capacity_lock:
                outside = sum(str(self.run) not in item['command'] for item in live_vivado())
                if outside + self.reserved < 12:
                    self.reserved += 1
                    return
            time.sleep(3)

    def additional_route(self, config):
        output = self.run / 'jobs' / config
        if (output / 'vivado.log').exists():
            self.update(config, status='duplicate_launch_blocked',
                error='This coordinator already launched its single additional implementation; refusing to repeat it')
            return
        self.update(config, status='waiting_for_capacity')
        self.reserve()
        output.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        try:
            if not self.bound_source_valid():
                raise ValueError('Frozen candidate or controller source changed before fallback launch')
            live = read(self.candidate_run / 'status.json')
            if not self.validated_sign(live, config):
                raise ValueError('Sign source/log/vector validation failed before fallback launch')
            p = int(config[1:config.index('U')])
            command = [self.meta['vivado'], '-mode', 'batch', '-nolog', '-nojournal', '-notrace',
                '-source', str(self.run / 'control/route_common_target.tcl'), '-tclargs',
                self.candidate['source_root'], str(p), '1', str(output), '130.0', '2']
            with (output / 'vivado.log').open('w') as stream:
                process = subprocess.Popen(command, cwd=output, env=dict(os.environ, HASH_BACKEND='shake'),
                    stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                self.update(config, status='additional_130MHz_running', started_at=now(), pid=process.pid,
                            additional_implementations=1, command=command)
                while process.poll() is None:
                    try:
                        process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        stage_file = output / 'stage.json'
                        stage = read(stage_file).get('stage', 'synthesis') if stage_file.exists() else 'synthesis'
                        self.update(config, status='additional_130MHz_running', stage=stage,
                            elapsed_seconds=time.monotonic() - started,
                            analysis_deferred=stage == 'synthesis' and time.monotonic() - started >= 600)
            if process.returncode or 'COMMON_TARGET_PASS' not in (output / 'vivado.log').read_text(errors='replace'):
                raise ValueError(f'Additional fixed-target tool failure; see {output / "vivado.log"}')
            if not self.bound_source_valid():
                raise ValueError('Frozen source changed during additional route')
            result = read(output / 'result.json')
            routing = route_status(output / 'route/route_status.rpt')
            evidence = dict(result=result, route_status=routing, area=resources(output / 'route/utilization.rpt'),
                evidence_directory=str(output), routed_checkpoint_sha256=sha(output / 'route/routed.dcp'),
                source_manifest_sha256=self.meta['candidate_manifest_sha256'],
                reports_sha256={str(p.relative_to(output)): sha(p) for p in output.rglob('*')
                    if p.is_file() and p.suffix in ('.rpt', '.txt', '.xdc', '.log', '.json')})
            met = accepted(result, routing, 130.0)
            values = dict(status='passed_130MHz' if met else '130MHz_target_not_met',
                additional_result=evidence, elapsed_seconds=time.monotonic() - started,
                finished_at=now(), analysis_deferred=False)
            if met:
                values['selected_result'] = evidence
            self.update(config, **values)
        except Exception as error:
            self.update(config, status='additional_route_error', error=str(error), finished_at=now())
        finally:
            with self.capacity_lock:
                self.reserved -= 1

    def observe(self, config):
        try:
            while True:
                live = read(self.candidate_run / 'status.json')
                task = live.get('routing', {}).get(config, {})
                if task.get('status') in TERMINAL:
                    break
                self.update(config, status='waiting_for_150MHz',
                    original_status=task.get('status', 'pending'), original_stage=task.get('stage'))
                time.sleep(30)
            if not self.bound_source_valid() or not self.validated_sign(live, config):
                raise ValueError('Original route source or Sign evidence validation failed')
            if task.get('status') not in ('passed', 'target_not_met'):
                self.update(config, status='original_route_error',
                    error='Original route has no completed timing result; no automatic retry', original_task=task)
                return
            initial = self.initial_evidence(config, task)
            self.update(config, initial_result=initial)
            result, routing = initial['result'], initial['route_status']
            if accepted(result, routing, 150.0):
                self.update(config, status='passed_150MHz', selected_result=initial, finished_at=now())
            elif not result.get('setup_hold_met'):
                self.update(config, status='150MHz_setup_hold_not_met')
                self.additional_route(config)
            else:
                self.update(config, status='original_acceptance_error',
                    error='150MHz setup/hold passed but DRC/routing/clock acceptance failed; no frequency retry')
        except Exception as error:
            self.update(config, status='validation_error', error=str(error), finished_at=now())

    def execute(self):
        with self.lock:
            self.publish()
            write(self.run / 'INITIAL_PUBLICATION.json', dict(pid=os.getpid(), at=now()))
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(self.observe, CONFIGS))
        with self.lock:
            self.state.update(complete=True, finished_at=now(), source_unchanged=self.bound_source_valid())
            self.publish()
        return int(not self.state['source_unchanged'] or
                   any('selected_result' not in task for task in self.state['tasks'].values()))


def launch(args):
    candidate_run = args.candidate_run.resolve()
    candidate = read(candidate_run / 'SOURCE.json')
    if (candidate.get('schema') != 'shake_timing_optimization_v1' or candidate.get('hash_backend') != 'shake'
            or not candidate.get('route_requested') or candidate.get('route_frequency_mhz') != 150.0
            or not unchanged(candidate)):
        raise ValueError('Expected unchanged SHAKE candidate already scheduled for 150-MHz routes')
    stamp = datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y%m%d_%H%M%S')
    run = ROOT / 'build/shake_timing_fixed_targets' / stamp
    out = archive.ARCHIVES / ('shake_timing_fixed_targets_' + stamp)
    if run.exists():
        raise ValueError('Run timestamp collision; retry in the next second')
    controls = ('continue_shake_timing_targets.py', 'experiment_archive.py', 'run_pu_route_matrix.py')
    for name in controls:
        archive.copy_changed(ROOT / 'scripts' / name, run / 'control' / name)
    tcl = Path(candidate['source_root']) / 'scripts/route_common_target.tcl'
    if sha(tcl) != candidate['sha256']['scripts/route_common_target.tcl']:
        raise ValueError('Candidate fixed-target Tcl checksum mismatch')
    archive.copy_changed(tcl, run / 'control/route_common_target.tcl')
    controls = (*controls, 'route_common_target.tcl')
    meta = dict(schema=SCHEMA, run_id=stamp, started_at=now(), hash_backend='shake',
        candidate_run=str(candidate_run), candidate_manifest_sha256=sha(candidate_run / 'SOURCE.json'),
        source_root=candidate['source_root'], sha256=candidate['sha256'], archive_directory=str(out),
        vivado=candidate['vivado'], tool_versions=candidate['tool_versions'], configurations=CONFIGS,
        first_fixed_frequency_mhz=150.0, additional_fixed_frequency_mhz=130.0,
        max_additional_implementations_per_failing_configuration=1, frequency_search=False,
        new_timing_exceptions=False, threads_per_vivado=2, max_total_vivado=12,
        baseline_new_route_run=False, h20_full_keygen_sign_run=False,
        control_sha256={name: sha(run / 'control' / name) for name in controls})
    for base in (run, out):
        write(base / 'SOURCE.json', meta)
        archive.copy_changed(candidate_run / 'SOURCE.json', base / 'CANDIDATE_SOURCE.json')
        for name in controls:
            archive.copy_changed(run / 'control' / name, base / 'control' / name)
    archive.pack_rtl(Path(candidate['source_root']), out / 'rtl.tar.gz', candidate['sha256'])
    proof = ROOT / 'build/shake_timing_optimization/BASELINE_PREPROCESSED_EQUIVALENCE.json'
    if proof.exists():
        archive.copy_changed(proof, out / proof.name)
    report = out / 'reports' / ('SHAKE_Fixed_Targets_' + stamp + '.md')
    row = f'| {out.name} | [{report.stem}]({report.relative_to(archive.ARCHIVES)}) | [目录]({out.name}/) |'
    write(out / 'INDEX_ENTRY.json', dict(timestamp=stamp, markdown_row=row, index_updated=False))
    with (run / 'runner.log').open('w') as stream:
        process = subprocess.Popen([sys.executable, str(run / 'control/continue_shake_timing_targets.py'),
            '--run-root', str(run)], cwd=ROOT,
            env=dict(os.environ, MHBS_FIXED_TARGET_WORKSPACE=str(ROOT)), stdin=subprocess.DEVNULL,
            stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
    deadline = time.monotonic() + 30
    while not (run / 'INITIAL_PUBLICATION.json').exists():
        if process.poll() is not None or time.monotonic() > deadline:
            raise RuntimeError(f'Coordinator startup failed; see {run / "runner.log"}')
        time.sleep(.1)
    result = dict(pid=process.pid, root=str(run), report=str(report), index_row=row)
    write(run / 'LAUNCH.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--launch', action='store_true')
    group.add_argument('--run-root', type=Path)
    parser.add_argument('--candidate-run', type=Path,
        default=ROOT / 'build/shake_timing_optimization/candidate_20261019_212542')
    args = parser.parse_args()
    return Coordinator(args.run_root.resolve()).execute() if args.run_root else launch(args)


if __name__ == '__main__':
    sys.exit(main())
