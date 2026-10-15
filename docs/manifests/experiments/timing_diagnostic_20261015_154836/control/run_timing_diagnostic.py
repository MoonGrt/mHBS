#!/usr/bin/env python3
"""Freeze two P12U1 variants and diagnose paths with a relaxed 50 ns clock."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from zoneinfo import ZoneInfo

ROOT = Path(os.environ.get('MHBS_DIAGNOSTIC_WORKSPACE', Path(__file__).resolve().parents[1])).resolve()
import experiment_archive as archive
from run_pu_sign_matrix import utilization
from report_timing_focus import timing

archive.ROOT = ROOT
archive.ARCHIVES = ROOT/'docs/manifests/experiments'


def now():
    return datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, data):
    archive.atomic(Path(path), json.dumps(data, ensure_ascii=False, indent=2)+'\n')


def live_vivado():
    lines = subprocess.check_output(['ps', '-eo', 'comm=,args='], text=True).splitlines()
    return [fields[1] for line in lines if len(fields := line.split(None, 1)) == 2
            and fields[0] == 'vivado' and '/bin/unwrapped/lnx64.o/vivado -mode batch' in fields[1]]


def freeze(source, destination, expected=None):
    names = [name.strip() for name in (source/'sources.txt').read_text().splitlines() if name.strip()]
    hashes = {}
    for name in [*names, 'sources.txt', 'scripts/diagnose_timing.tcl']:
        origin = ROOT/name if name == 'scripts/diagnose_timing.tcl' else source/name
        before = sha(origin)
        if expected and name != 'scripts/diagnose_timing.tcl' and expected.get(name) != before:
            raise ValueError(f'Baseline source checksum mismatch: {name}')
        target = destination/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, target)
        if sha(origin) != before or sha(target) != before:
            raise RuntimeError(f'Source changed while freezing {name}')
        hashes[name] = before
    return hashes


class Runner:
    def __init__(self, run):
        self.run = run
        self.meta = json.loads((run/'SOURCE.json').read_text())
        self.out = Path(self.meta['archive_directory'])
        self.lock = threading.Lock()
        self.capacity_lock = threading.Lock()
        self.slots = 0
        self.state = dict(schema='mhbs.timing_diagnostic.results.v1', started_at=now(),
                          updated_at=now(), pid=os.getpid(), complete=False, diagnostic_only=True,
                          configuration='P12U1', period_ns=50.0, threads_per_vivado=2,
                          maximum_own_vivado=2, max_observed_main_vivado=0,
                          no_simulation_launched=True, no_routing_launched=True,
                          candidate_full_sign_measured=False,
                          variants={name: dict(status='waiting_for_capacity') for name in self.meta['variants']})

    def publish(self):
        self.state['updated_at'] = now()
        write(self.run/'status.json', self.state)
        write(self.out/'status.json', self.state)
        prefix = self.out/'reports'/('Timing_Diagnostic_'+self.meta['run_id'])
        write(prefix.with_suffix('.json'), dict(source=self.meta, results=self.state))
        fmt = lambda value, digits=3: '—' if value is None else f'{value:,.{digits}f}'
        lines = ['# P12U1 低频综合关键路径诊断', '',
                 f'更新时间：{self.state["updated_at"]}；状态：{"结束" if self.state["complete"] else "后台运行"}。', '',
                 '两版本均使用 common、xc7a200tffg1156-3、P12U1、50 ns（20 MHz）诊断约束、默认时序驱动综合和通用 Keccak；每个 Vivado 两线程，本次最多两个并发，全机主 Vivado 达到12个时等待。未启动仿真或布局布线。', '',
                 '**本次只定位组合路径和比较低频综合映射；面积、WNS不能作为原高频约束的验收结果，不计算频率上限或ATP。** ready_simplify 候选已绑定局部配方/链控制验证摘要；第二候选完整 Sign 周期尚未实测。', '',
                 '| 版本 | LUT | FF | 等效 Slice | WNS ns | 数据路径 ns | 逻辑级数 | 综合耗时 s | 状态 |',
                 '|---|---:|---:|---:|---:|---:|---:|---:|---|']
        for name, task in self.state['variants'].items():
            area, path = task.get('area', {}), task.get('timing', {})
            status = task['status'] + ('；分析延后，综合继续后台' if task.get('analysis_deferred') else '')
            lines.append('| '+' | '.join([name, fmt(area.get('lut'), 0), fmt(area.get('ff'), 0),
                fmt(area.get('equivalent_slice')), fmt(path.get('wns_ns')), fmt(path.get('data_path_ns')),
                fmt(path.get('logic_levels'), 0), fmt(task.get('seconds'), 1), status])+' |')
        lines += ['', '## 关键路径', '']
        for name, task in self.state['variants'].items():
            path = task.get('timing', {})
            lines += [f'- **{name}**：`{path.get("source", "待综合完成")}` → `{path.get("destination", "待综合完成")}`。']
            if task.get('error'):
                lines += [f'  错误：{task["error"]}']
        lines += ['', '每版目录保存冻结RTL压缩包、SOURCE.json逐文件SHA、综合日志、hierarchical.rpt、timing.rpt和前20条关键路径报告。缺项在ARTIFACTS.json明确列出，后台完成后自动补齐；原始DCP留在build运行目录。', '',
                  f'运行目录：`{self.run}`。', '']
        archive.atomic(prefix.with_suffix('.md'), '\n'.join(lines))
        missing = {}
        for name, spec in self.meta['variants'].items():
            base = self.run/name/'synth/P12U1/common'
            dest = self.out/name/'synth/P12U1/common'
            for path in base.glob('*'):
                if path.is_file() and path.suffix in ('.rpt', '.log', '.json', '.txt', '.xdc'):
                    archive.copy_changed(path, dest/path.name)
            missing[name] = [file for file in ('hierarchical.rpt', 'timing.rpt', 'critical_paths.rpt', 'vivado.log')
                             if not (dest/file).exists()]
        if (self.run/'runner.log').exists():
            archive.copy_changed(self.run/'runner.log', self.out/'runner.log')
        checks = {str(path.relative_to(self.out)): sha(path) for path in self.out.rglob('*')
                  if path.is_file() and path.name != 'ARTIFACTS.json' and not path.name.endswith('.tmp')}
        write(self.out/'ARTIFACTS.json', dict(updated_at=now(), complete=self.state['complete'],
              missing=missing, omitted_details=['sim', 'validation'], sha256=checks))
        archive.index()

    def update(self, name, **values):
        with self.lock:
            self.state['variants'][name].update(values)
            self.state['max_observed_main_vivado'] = max(self.state['max_observed_main_vivado'], len(live_vivado()))
            self.publish()

    def reserve(self):
        while True:
            with self.capacity_lock:
                commands = live_vivado()
                outside = sum(str(self.run) not in command for command in commands)
                if len(commands) < 12 and outside+self.slots < 12:
                    self.slots += 1
                    return
            time.sleep(3)

    def execute_one(self, name):
        self.reserve()
        try:
            spec = self.meta['variants'][name]
            source = Path(spec['source_root'])
            output = self.run/name/'synth/P12U1/common'
            output.mkdir(parents=True, exist_ok=True)
            command = [self.meta['vivado'], '-mode', 'batch', '-nolog', '-nojournal', '-notrace',
                       '-source', str(source/'scripts/diagnose_timing.tcl'), '-tclargs',
                       str(source), '12', '1', str(output), '50.0']
            start = time.monotonic()
            with (output/'vivado.log').open('w') as log:
                process = subprocess.Popen(command, cwd=output, stdin=subprocess.DEVNULL, stdout=log,
                                           stderr=subprocess.STDOUT, start_new_session=True)
                self.update(name, status='running', pid=process.pid, started_at=now(), command=command)
                while process.poll() is None:
                    try:
                        process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        self.update(name, seconds=time.monotonic()-start,
                                    analysis_deferred=time.monotonic()-start >= 600)
            if process.returncode or 'MHBS_TIMING_DIAGNOSTIC_PASS P12U1 period_ns=50.0' not in (output/'vivado.log').read_text(errors='replace'):
                raise RuntimeError(f'Vivado exit {process.returncode}; see {output / "vivado.log"}')
            unchanged = all(sha(source/path) == value for path, value in spec['sha256'].items())
            if not unchanged:
                raise RuntimeError('Frozen diagnostic source changed')
            self.update(name, status='passed', seconds=time.monotonic()-start, finished_at=now(),
                        area=utilization(output/'utilization.rpt'), timing=timing(output/'timing.rpt'),
                        source_unchanged=True, analysis_deferred=False,
                        checkpoint_sha256=sha(output/'synthesized.dcp'))
        except Exception as error:
            self.update(name, status='failed', finished_at=now(), error=str(error))
        finally:
            with self.capacity_lock:
                self.slots -= 1

    def execute(self):
        with self.lock:
            self.publish()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(self.execute_one, self.meta['variants']))
        with self.lock:
            self.state.update(complete=True, finished_at=now(),
                              passed=all(t['status'] == 'passed' for t in self.state['variants'].values()))
            self.publish()
        return 0 if self.state['passed'] else 1


def launch(args):
    baseline = args.baseline_source.resolve()
    baseline_meta = json.loads((baseline.parent/'SOURCE.json').read_text())
    validation = json.loads(args.validation.read_text())
    if not validation.get('passed') or validation.get('candidate_recipe_sha256') != sha(ROOT/'rtl/hash/recipe.sv'):
        raise ValueError('ready_simplify validation does not match the current candidate recipe')
    run_id = datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y%m%d_%H%M%S')
    run = ROOT/'build/timing_diagnostic'/run_id
    out = ROOT/'docs/manifests/experiments'/('timing_diagnostic_'+run_id)
    vivado = shutil.which(os.environ.get('VIVADO', 'vivado'))
    if not vivado:
        raise RuntimeError('Vivado is required')
    meta = dict(schema='mhbs.timing_diagnostic.source.v1', run_id=run_id, started_at=now(),
                diagnostic_only=True, configuration='P12U1', period_ns=50.0,
                part='xc7a200tffg1156-3', area_top='common', vivado=vivado,
                vivado_version=subprocess.check_output([vivado, '-version'], text=True).strip(),
                archive_directory=str(out), baseline_manifest=str(baseline.parent/'SOURCE.json'),
                baseline_manifest_sha256=sha(baseline.parent/'SOURCE.json'),
                candidate_full_sign_measured=False, variants={})
    for name, source in [('baseline', baseline), ('candidate', ROOT)]:
        frozen = run/name/'source'
        hashes = freeze(source, frozen, baseline_meta['sha256'] if name == 'baseline' else None)
        spec = dict(original_source=str(source), source_root=str(frozen), sha256=hashes)
        meta['variants'][name] = spec
        write(run/name/'SOURCE.json', spec)
        write(out/name/'SOURCE.json', spec)
        archive.pack_rtl(frozen, out/name/'rtl.tar.gz', hashes)
        archive.copy_changed(frozen/'scripts/diagnose_timing.tcl', out/name/'diagnose_timing.tcl')
    summary = dict(source_validation=str(args.validation.resolve()), validation_sha256=sha(args.validation),
                   candidate_recipe_sha256=validation['candidate_recipe_sha256'],
                   candidate_source_sha256=meta['variants']['candidate']['sha256'],
                   passed=validation['passed'], candidate_full_sign_measured=False,
                   scope='Local recipe/chain-control validation; complete Sign not measured for this second candidate',
                   tests=[{key: case[key] for key in ('name', 'passed', 'scope') if key in case}
                          for case in validation.get('tests', [])], algebra=validation.get('algebra'))
    write(out/'VALIDATION_SUMMARY.json', summary)
    write(run/'SOURCE.json', meta)
    write(out/'SOURCE.json', meta)
    for name in ('run_timing_diagnostic.py', 'experiment_archive.py', 'run_pu_sign_matrix.py', 'report_timing_focus.py'):
        archive.copy_changed(ROOT/'scripts'/name, run/'control'/name)
        archive.copy_changed(run/'control'/name, out/'control'/name)
    controls = {p.name: sha(p) for p in (run/'control').glob('*.py')}
    write(run/'CONTROL_SOURCE.json', controls)
    write(out/'CONTROL_SOURCE.json', controls)
    env = os.environ.copy()
    env['MHBS_DIAGNOSTIC_WORKSPACE'] = str(ROOT)
    with (run/'runner.log').open('w') as log:
        process = subprocess.Popen([sys.executable, str(run/'control/run_timing_diagnostic.py'), '--run-root', str(run)],
                                   cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
    result = dict(pid=process.pid, root=str(run), report=str(out/'reports'/('Timing_Diagnostic_'+run_id+'.md')))
    write(run/'LAUNCH.json', result)
    deadline = time.monotonic()+30
    while not (run/'status.json').exists():
        if process.poll() is not None or time.monotonic() > deadline:
            raise RuntimeError(f'Runner initial publication failed; see {run / "runner.log"}')
        time.sleep(0.1)
    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--launch', action='store_true')
    parser.add_argument('--run-root', type=Path)
    parser.add_argument('--baseline-source', type=Path, default=ROOT/'build/pu_sign_matrix/20261015_152159/source')
    parser.add_argument('--validation', type=Path, default=ROOT/'build/timing_latency_20261015/ready_simplify/VALIDATION.json')
    args = parser.parse_args()
    if args.launch == bool(args.run_root):
        parser.error('Choose --launch or --run-root')
    return launch(args) if args.launch else Runner(args.run_root.resolve()).execute()


if __name__ == '__main__':
    sys.exit(main())
