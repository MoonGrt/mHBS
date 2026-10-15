#!/usr/bin/env python3
"""Freeze validated RTL and dispatch four explicitly requested fixed-clock routes."""
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

ROOT = Path(os.environ.get('MHBS_TARGET_WORKSPACE', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(Path(__file__).resolve().parent))
import experiment_archive as archive
from run_pu_route_matrix import live_vivado, resources, route_status

archive.ROOT = ROOT
archive.ARCHIVES = ROOT/'docs/manifests/experiments'
TARGETS = [(1, 1, 125), (4, 1, 130), (4, 2, 90), (12, 1, 135)]


def now():
    return datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    archive.atomic(Path(path), json.dumps(value, ensure_ascii=False, indent=2)+'\n')


class Runner:
    def __init__(self, run):
        self.run = run
        self.meta = json.loads((run/'SOURCE.json').read_text())
        self.out = Path(self.meta['archive_directory'])
        self.source = run/'source'
        self.lock = threading.Lock()
        self.capacity_lock = threading.Lock()
        self.slots = 0
        self.state = dict(started_at=now(), updated_at=now(), pid=os.getpid(), complete=False,
            top='common', threads_per_vivado=2, max_total_vivado=12,
            frequency_search=False, tasks={f'P{p}U{u}':dict(status='waiting_for_capacity',
                target_frequency_mhz=f, target_period_ns=1000/f) for p,u,f in self.meta['targets']})

    def publish(self):
        self.state['updated_at'] = now()
        prefix = self.out/'reports'/('Timing_Targets_'+self.meta['run_id'])
        write(self.run/'status.json', self.state)
        write(self.out/'status.json', self.state)
        write(prefix.with_suffix('.json'), dict(source=self.meta, results=self.state))
        lines = ['# 指定频率四点布局布线', '',
            f'更新时间：{self.state["updated_at"]}；状态：'+('完成' if self.state['complete'] else '后台运行')+'。', '',
            '冻结当前RTL，common OOC，xc7a200tffg1156-3，通用Keccak；各点按指定频率重新综合，再执行opt/place/phys_opt/route。每个Vivado两线程，全机主任务最多12个。每点只检查指定目标，未进行频率搜索或新增时序例外。旧后台任务保持运行。', '',
            '源码与32/32项验证逐文件绑定。验收范围为common核内部受约束路径；完整布线、DRC、setup/hold通过且实际时钟不低于目标才记为达到。共同核结果不代表封装顶层I/O时序。', '',
            '| 配置 | 目标 MHz | 周期 ns | 综合 Slice | 布线 Slice | WNS ns | WHS ns | 达到目标 | 状态 |',
            '|---|---:|---:|---:|---:|---:|---:|---|---|']
        fmt = lambda v: '—' if v is None else f'{v:,.3f}'
        for name, task in self.state['tasks'].items():
            result = task.get('result', {})
            verdict = ('是' if task['meets_target'] else '否') if 'meets_target' in task else '—'
            label = task['status']+('；分析延后，综合继续' if task.get('analysis_deferred') else '')
            lines.append('| '+' | '.join([name,fmt(task['target_frequency_mhz']),
                fmt(result.get('actual_period_ns',task['target_period_ns'])),
                fmt(task.get('synth_area',{}).get('equivalent_slice')),
                fmt(task.get('routed_area',{}).get('equivalent_slice')),
                fmt(result.get('wns_ns')),fmt(result.get('whs_ns')),verdict,label])+' |')
            if task.get('error'):
                lines += ['',f'{name} 错误：{task["error"]}']
        lines += ['',f'运行目录：`{self.run}`。', '',
            'DCP保留在运行目录；归档保留冻结RTL、源码校验、验证摘要、完整Vivado日志、综合及布线hierarchical/timing/route/DRC报告。未完成证据在ARTIFACTS.json列明，完成后自动补齐。', '']
        archive.atomic(prefix.with_suffix('.md'),'\n'.join(lines))
        missing = {}
        for name in self.state['tasks']:
            folder = self.run/'jobs'/name
            for path in folder.rglob('*') if folder.exists() else []:
                if path.is_file() and path.suffix in ('.rpt','.log','.json','.txt','.xdc'):
                    archive.copy_changed(path,self.out/'jobs'/name/path.relative_to(folder))
            required = ['synth/hierarchical.rpt','synth/timing.rpt','route/hierarchical.rpt',
                        'route/timing.rpt','route/route_status.rpt','route/drc.rpt','result.json']
            missing[name] = [f for f in required if not (self.out/'jobs'/name/f).exists()]
        if (self.run/'runner.log').exists():
            archive.copy_changed(self.run/'runner.log',self.out/'runner.log')
        write(self.out/'ARTIFACTS.json',dict(updated_at=now(),complete=self.state['complete'],
            missing=missing,omitted_details=['sim','validation'],
            sha256={str(p.relative_to(self.out)):sha(p) for p in self.out.rglob('*')
                    if p.is_file() and p.name!='ARTIFACTS.json' and not p.name.endswith('.tmp')}))
        archive.index()

    def update(self, name, **values):
        with self.lock:
            self.state['tasks'][name].update(values)
            self.publish()

    def reserve(self):
        while True:
            with self.capacity_lock:
                outside = sum(str(self.run) not in t['command'] for t in live_vivado())
                if outside+self.slots < 12:
                    self.slots += 1
                    return
            time.sleep(3)

    def execute_one(self, target):
        p,u,frequency = target
        name = f'P{p}U{u}'
        folder = self.run/'jobs'/name
        folder.mkdir(parents=True,exist_ok=True)
        self.reserve()
        start = time.monotonic()
        try:
            command = [self.meta['vivado'],'-mode','batch','-nolog','-nojournal','-notrace',
                '-source',str(self.run/'control/route_common_target.tcl'),'-tclargs',
                str(self.source),str(p),str(u),str(folder),str(frequency),'2']
            with (folder/'vivado.log').open('w') as log:
                process = subprocess.Popen(command,cwd=folder,stdin=subprocess.DEVNULL,
                    stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                self.update(name,status='synthesis',pid=process.pid,command=command,started_at=now())
                while process.poll() is None:
                    try:
                        process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        stage = json.loads((folder/'stage.json').read_text()) if (folder/'stage.json').exists() else {}
                        values = dict(status=stage.get('stage','synthesis'),seconds=time.monotonic()-start,
                            analysis_deferred=stage.get('stage','synthesis')=='synthesis' and time.monotonic()-start>=600)
                        if (folder/'synth/utilization.rpt').exists():
                            values['synth_area'] = resources(folder/'synth/utilization.rpt')
                        self.update(name,**values)
            if process.returncode or 'COMMON_TARGET_PASS' not in (folder/'vivado.log').read_text(errors='replace'):
                raise RuntimeError(f'Vivado exit {process.returncode}; see {folder/"vivado.log"}')
            result = json.loads((folder/'result.json').read_text())
            routing = route_status(folder/'route/route_status.rpt')
            unchanged = all(sha(self.source/f)==h for f,h in self.meta['sha256'].items())
            if not unchanged:
                raise RuntimeError('Frozen source checksum changed')
            met = (result['setup_hold_met'] and result['drc_errors']==0 and routing['passed']
                   and result['actual_period_ns'] <= 1000/frequency+1e-6)
            self.update(name,status='passed' if met else 'target_not_met',meets_target=met,
                finished_at=now(),seconds=time.monotonic()-start,analysis_deferred=False,
                result=result,route_status=routing,source_unchanged=True,
                synth_area=resources(folder/'synth/utilization.rpt'),
                routed_area=resources(folder/'route/utilization.rpt'),
                synthesized_checkpoint_sha256=sha(folder/'synth/synthesized.dcp'),
                routed_checkpoint_sha256=sha(folder/'route/routed.dcp'))
        except Exception as error:
            self.update(name,status='error',error=str(error),finished_at=now(),seconds=time.monotonic()-start)
        finally:
            with self.capacity_lock:
                self.slots -= 1

    def execute(self):
        with self.lock:
            self.publish()
            write(self.run/'INITIAL_PUBLICATION.json',dict(pid=os.getpid(),at=now()))
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(self.execute_one,self.meta['targets']))
        with self.lock:
            self.state.update(complete=True,finished_at=now())
            self.publish()


def launch():
    validation_path = ROOT/'build/timing_format_20261015/VALIDATION.json'
    validation = json.loads(validation_path.read_text())
    assert validation['complete'] and validation['passed']==validation['total']==32 and not validation['failed']
    assert validation['source_unchanged']
    names = [n.strip() for n in (ROOT/'sources.txt').read_text().splitlines() if n.strip()]
    assert {n:sha(ROOT/n) for n in names} == validation['rtl_sha256'], 'Current RTL differs from validated RTL'
    run_id = datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y%m%d_%H%M%S')
    run = ROOT/'build/timing_targets'/run_id
    out = ROOT/'docs/manifests/experiments'/('timing_targets_'+run_id)
    hashes = {}
    for name in [*names,'sources.txt']:
        target = run/'source'/name
        before = sha(ROOT/name)
        archive.copy_changed(ROOT/name,target)
        assert sha(target)==sha(ROOT/name)==before
        hashes[name] = before
    vivado = shutil.which('vivado')
    if not vivado:
        raise RuntimeError('Vivado not found')
    meta = dict(run_id=run_id,started_at=now(),source_root=str(run/'source'),sha256=hashes,
        archive_directory=str(out),targets=TARGETS,top='common',part='xc7a200tffg1156-3',
        vivado=vivado,vivado_version=subprocess.check_output([vivado,'-version'],text=True).strip(),
        threads_per_vivado=2,max_total_vivado=12,frequency_search=False,new_timing_exceptions=False,
        validation_source=str(validation_path),validation_sha256=sha(validation_path),
        validation_source_manifest_sha256=validation['source_manifest_sha256'],
        validation_passed=32,explicit_user_authorization=True)
    for base in (run,out):
        write(base/'SOURCE.json',meta)
        for name in ('run_timing_targets.py','route_common_target.tcl','experiment_archive.py','run_pu_route_matrix.py'):
            archive.copy_changed(ROOT/'scripts'/name,base/'control'/name)
        write(base/'CONTROL_SOURCE.json',{str(p.relative_to(base)):sha(p) for p in (base/'control').iterdir()})
    summary = dict(validation)
    summary['tests'] = [{k:v for k,v in t.items() if k not in ('logs','command')} for t in validation['tests']]
    write(out/'VALIDATION_SUMMARY.json',summary)
    archive.pack_rtl(run/'source',out/'rtl.tar.gz',hashes)
    env = dict(os.environ,MHBS_TARGET_WORKSPACE=str(ROOT))
    with (run/'runner.log').open('w') as log:
        process = subprocess.Popen([sys.executable,str(run/'control/run_timing_targets.py'),'--run-root',str(run)],
            cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    deadline = time.monotonic()+30
    while not (run/'INITIAL_PUBLICATION.json').exists():
        if process.poll() is not None or time.monotonic()>deadline:
            raise RuntimeError(f'Initial publication failed: {run/"runner.log"}')
        time.sleep(0.1)
    result = dict(pid=process.pid,root=str(run),report=str(out/'reports'/('Timing_Targets_'+run_id+'.md')))
    write(run/'LAUNCH.json',result)
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--launch',action='store_true')
    group.add_argument('--run-root',type=Path)
    args = parser.parse_args()
    launch() if args.launch else Runner(args.run_root.resolve()).execute()
