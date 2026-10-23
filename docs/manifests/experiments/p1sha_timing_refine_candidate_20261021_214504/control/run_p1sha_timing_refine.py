#!/usr/bin/env python3
"""Measure new P1/SHA timing candidates against the frozen, validated C3.

No candidate is launched without --launch-candidate. Fixed target routing is a
separate --route-existing action, gated by 18 full Sign, six common/100-MHz
diagnostics and source-bound 36-group validation. Existing controllers are not
changed or stopped. Optional P12 diagnosis never gates the target routes.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from zoneinfo import ZoneInfo

import experiment_archive as archive
import run_dual_pu_route_matrix as dual
import run_p1sha_atp_optimization as previous
import coordinate_p1sha_atp_optimization as physical_helpers

ROOT = Path(os.environ.get('MHBS_P1SHA_REFINE_WORKSPACE', Path(__file__).resolve().parents[1])).resolve()
archive.ROOT = ROOT
archive.ARCHIVES = ROOT / 'docs/manifests/experiments'
FAMILY = ROOT / 'build/p1sha_timing_refine'
BASELINE = FAMILY / 'baseline_20261021_214038'
REFERENCE = ROOT / 'build/p1sha_atp_optimization/candidate_20261021_203556'
REFERENCE_SHA = 'b96cb542044c062f8623ac69cdcf25b6d7bc26a3fa0da1038df099fc70aaa7f1'
BASELINE_SHA = 'd9fa5f48eecf03241200b32b0352641565a62a2ddbcd7dda1c0964e463d14f14'
TARGETS = previous.ROUTE_CONFIGS
CONTROLS = ('run_p1sha_timing_refine.py', 'coordinate_p1sha_atp_optimization.py', *previous.CONTROLS)
read, write, sha, require, now, parts = previous.read, previous.write, previous.sha, previous.require, previous.now, previous.parts


def live_top_jobs():
    """Deduplicate wrappers and real executables; exclude internal task workers."""
    return [job for job in previous.live_groups() if 'SYNTH_DESIGN_PARENT' not in job['command']]


def reference_evidence():
    require(sha(REFERENCE / 'SOURCE.json') == REFERENCE_SHA, 'Wrong C3 reference manifest')
    meta, state = read(REFERENCE / 'SOURCE.json'), read(REFERENCE / 'status.json')
    require(previous.unchanged(meta) and state['complete'] and state['source_unchanged'], 'Reference source changed or incomplete')
    for key, test in state['tests'].items():
        require(test['status'] == 'passed' and test['source_unchanged']
                and test['source_manifest_sha256'] == REFERENCE_SHA, 'Unbound C3 Sign: ' + key)
        for field in ('log', 'raw_log'):
            require(sha(test[field]) == test[field + '_sha256'], 'C3 Sign log changed: ' + key)
    for key, syn in state['synthesis'].items():
        require(syn['status'] == 'passed' and syn['source_unchanged']
                and syn['source_manifest_sha256'] == REFERENCE_SHA, 'Unbound C3 diagnostic: ' + key)
        folder = REFERENCE / 'synth' / key
        for name, wanted in syn['reports_sha256'].items():
            require(sha(folder / name) == wanted, 'C3 diagnostic changed: ' + key + '/' + name)
        settings = (folder / 'settings.txt').read_text().splitlines()
        require(all(line in settings for line in ('period_ns=10.0', 'threads=2', 'top=common',
            'timing_driven=default', 'new_timing_exceptions=none', 'part=xc7a200tffg1156-3')), 'C3 diagnostic settings differ')
    validation = read(REFERENCE / 'functional_validation/VALIDATION.json')
    require(validation['complete'] and validation['passed'] == 36 and not validation['failed']
            and validation['source_unchanged'] and validation['source_manifest_sha256'] == REFERENCE_SHA,
            'C3 source-bound functional validation incomplete')
    for test in validation['tests']:
        require(test['passed'] and sha(test['log']) == test['log_sha256'], 'C3 functional log changed')
    return dict(reference_run=str(REFERENCE), source_manifest_sha256=REFERENCE_SHA, checked_at=now(),
        tests=state['tests'], synthesis=state['synthesis'], functional=validation,
        source_inputs_checked=True, actual_logs_and_reports_checked=True)


def freeze_controls(run, out):
    checks = {}
    for name in CONTROLS:
        require((ROOT / 'scripts' / name).is_file(), 'Missing controller: ' + name)
        for base in (run, out):
            archive.copy_changed(ROOT / 'scripts' / name, base / 'control' / name)
        checks[name] = sha(run / 'control' / name)
    for base in (run, out):
        write(base / 'CONTROL_SOURCE.json', checks)


class Runner(previous.Runner):
    def __init__(self, run, resume=False):
        self.run = Path(run).resolve()
        self.meta = dict(read(self.run / 'SOURCE.json'), **read(self.run / 'EXPERIMENT.json'))
        require(self.meta['experiment_family'] == 'p1sha_timing_refine', 'Wrong experiment family')
        self.source, self.out = Path(self.meta['source_root']), Path(self.meta['archive_directory'])
        self.base = read(self.run / 'C3_EVIDENCE.json')
        require(self.base['source_manifest_sha256'] == REFERENCE_SHA, 'Wrong comparison baseline')
        self.configs = self.meta['diagnostic_configs']
        self.lock, self.capacity_lock = threading.RLock(), threading.Lock()
        self.capacity_token = threading.local()
        self.reserved, self.copied, self.checksums = 0, {}, {}
        self.routes_only, self.continuing = False, False
        if resume:
            self.state = read(self.run / 'status.json')
        else:
            self.state = dict(schema='mhbs.p1sha_timing_refine.results.v1', label=self.meta['label'], pid=os.getpid(),
                complete=False, started_at=now(), source_manifest_sha256=sha(self.run / 'SOURCE.json'),
                tests={config+'/'+profile: dict(status='pending') for config in TARGETS for profile in dual.PROFILES},
                synthesis={config: dict(status='pending') for config in self.configs}, routing={})

    def reserve(self):
        """Share the prior controllers' lock; admission includes pending wrappers.

        Prior controllers remain conservative and may count internal workers.
        They see our reservations through the same file. New jobs use the exact
        top-level count, preserving the global twelve-job limit without treating
        Vivado's SYNTH_DESIGN_PARENT internal workers as independent tool jobs.
        """
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
                records = [r for r in records if alive(r)]
                live = live_top_jobs()
                pending = [r for r in records if not any(r['worker_marker'] in j['command'] for j in live)]
                ours = sum(r['owner_pid'] == os.getpid() for r in records)
                if len(live)+len(pending) < 12 and ours < 3:
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

    def rows(self):
        rows = []
        for config in TARGETS:
            syn, base_syn = self.state['synthesis'][config], self.base['synthesis'][config]
            for profile in dual.PROFILES:
                key = config+'/'+profile
                test, old = self.state['tests'][key], self.base['tests'][key]
                row = dict(config=config, profile=profile, status=test['status'], cycles=test.get('cycles'),
                    baseline_cycles=old['cycles'], hashes=test.get('hashes'), permutations=test.get('permutations'),
                    target_mhz=150 if parts(config)[2] == 1 else 100, workload_equal=None,
                    diagnostic_equivalent_slice=None, baseline_diagnostic_equivalent_slice=base_syn['area']['equivalent_slice'],
                    diagnostic_atp=None, diagnostic_atp_change_pct=None,
                    routed_atp=None, routed_frequency_mhz=None, routed_time_ms=None)
                if test['status'] == 'passed':
                    row.update(workload_equal=all(test.get(n) == old[n] for n in ('hashes','permutations','vectors_sha256')),
                        cycles_change_pct=100*(test['cycles']/old['cycles']-1),
                        assumed_target_time_ms=test['cycles']/(row['target_mhz']*1000))
                    if syn['status'] == 'passed':
                        area, old_area = syn['area']['equivalent_slice'], base_syn['area']['equivalent_slice']
                        row.update(diagnostic_equivalent_slice=area, diagnostic_atp=area*test['cycles']/(row['target_mhz']*1000),
                            diagnostic_area_change_pct=100*(area/old_area-1),
                            diagnostic_atp_change_pct=100*(area*test['cycles']/(old_area*old['cycles'])-1))
                rows.append(row)
        return rows

    def publish(self):
        self.state['updated_at'] = now()
        self.state['counts'] = {g:{s:sum(t['status']==s for t in self.state[g].values())
            for s in sorted({t['status'] for t in self.state[g].values()})} for g in ('tests','synthesis','routing')}
        self.state['rows'] = self.rows()
        self.state['validation_passed'] = self.validated()
        for base in (self.run,self.out):
            write(base/'status.json',self.state)
        write(self.out/'VALIDATION_SUMMARY.json',dict(complete=self.state['complete'],tests=self.state['tests'],
            source_manifest_sha256=self.state['source_manifest_sha256'],h20_full_keygen_sign_run=False))
        publish_family()
        for directory in ('synth','jobs'):
            for path in (self.run/directory).rglob('*') if (self.run/directory).exists() else []:
                if path.is_file() and path.suffix in ('.rpt','.log','.json','.txt','.xdc'):
                    identity=(path.stat().st_mtime_ns,path.stat().st_size)
                    if self.copied.get(path)!=identity:
                        archive.copy_changed(path,self.out/path.relative_to(self.run));self.copied[path]=identity
        if (self.run/'runner.log').is_file():
            archive.copy_changed(self.run/'runner.log',self.out/'runner.log')
        missing={config:[n for n in ('hierarchical.rpt','timing.rpt','critical_paths.rpt')
            if not (self.out/'synth'/config/n).is_file()] for config in self.configs}
        write(self.out/'ARTIFACTS.json',dict(complete=self.state['complete'],missing=missing,
            omitted_details=['sim','validation'],sha256={str(p.relative_to(self.out)):sha(p)
                for p in self.out.rglob('*') if p.is_file() and p.name!='ARTIFACTS.json' and not p.name.endswith('.tmp')}))

    def execute(self):
        self.publish();archive.index()
        with ThreadPoolExecutor(max_workers=3) as synth_pool,ThreadPoolExecutor(max_workers=4) as sim_pool:
            jobs=[synth_pool.submit(self.synthesize,c) for c in self.configs]
            jobs += [sim_pool.submit(self.simulate,*parts(c)) for c in TARGETS]
            for job in as_completed(jobs):job.result()
        self.state.update(complete=True,finished_at=now(),source_unchanged=self.unchanged())
        self.publish();archive.index()
        return int(not self.validated())


class PhysicalRunner(physical_helpers.PhysicalRunner):
    reserve = Runner.reserve
    def publish(self):
        super().publish()
        prefix=self.out/'reports'/('P1_SHA_Fixed_Targets_'+self.meta['run_id'])
        text=prefix.with_suffix('.md').read_text()
        text=text.replace('基线六点原目标均未闭合，不能从负WNS外推基线频率或布线ATP。',
            '本轮基线为冻结C3；其未闭合点不推算频率或ATP，已完成物理证据在新主报告单列。')
        archive.atomic(prefix.with_suffix('.md'),text)
        publish_family()


def publish_family():
    out=Path(read(BASELINE/'SOURCE.json')['archive_directory'])
    prefix=out/'reports/P1_SHA_Timing_Refine_20261021'
    evidence=read(BASELINE/'C3_EVIDENCE.json')
    rows=[]
    for manifest in sorted(FAMILY.glob('candidate_*/SOURCE.json')):
        run=manifest.parent
        if not (run/'status.json').is_file():continue
        meta,state=read(manifest),read(run/'status.json')
        physical=read(run/'PHYSICAL_STATUS.json') if (run/'PHYSICAL_STATUS.json').is_file() else None
        rows.append(dict(run_root=str(run),source=meta,source_manifest_sha256=sha(manifest),results=state,physical=physical))
    baseline_physical=read(REFERENCE/'PHYSICAL_STATUS.json') if (REFERENCE/'PHYSICAL_STATUS.json').is_file() else None
    value=dict(updated_at=now(),baseline_manifest_sha256=BASELINE_SHA,reference_manifest_sha256=REFERENCE_SHA,
        baseline_evidence=evidence,baseline_physical=baseline_physical,candidates=rows,
        diagnostic_frequency_is_not_fmax=True,frequency_search=False,new_timing_exceptions=False)
    write(prefix.with_suffix('.json'),value)
    fmt=lambda x:'—' if x is None else f'{x:,.3f}'
    lines=['# C3基础 P1／SHA 时序与ATP优化','',f'更新时间：{value["updated_at"]}。','',
        '唯一基线为上一轮冻结C3：21项完整Sign、7点100MHz common诊断、36组正常/综合视图验证全部通过。'
        '本轮逐文件、日志和报告SHA核对后复用这些实测基线，不重新解释为旧B0或旧omega工作量。'
        'C3的指定频率路由继续后台，物理结果单列；负WNS不外推Fmax。','',
        '候选默认18项完整Sign与六点100MHz诊断：SHAKE/SHA2的P1U1、P1U2，SHA2的P4U1、P4U2。'
        '目标U1=150MHz，U2=100MHz；可选P12诊断仅作兼容补充，不阻塞六目标点路由门禁。'
        '最终路由需要独立命令、36组source-bound功能验证和目标点Sign/诊断全通过，最多两候选各六点；不搜索或自动降频。','',
        '器件xc7a200tffg1156-3，Vivado2025.2，common OOC、默认时序驱动、SYNTHESIS统计裁剪，每工具两线程。'
        '全机顶层Vivado最多12，wrapper/实际进程去重，SYNTH_DESIGN_PARENT内部worker不算独立job；旧任务保留。'
        '等效Slice=LUT/4+FF/8+232.4×BRAM36+102.4×DSP；100MHz面积和路径仅为诊断。','']
    for backend in ('shake','sha2'):
        lines += [f'## {backend.upper()} common诊断面积','',
            '| 候选 | 配置 | LUT | FF | BRAM36 | 等效Slice | 相对C3% | 路径ns | 状态 |',
            '|---|---|---:|---:|---:|---:|---:|---:|---|']
        entries=[('C3基线',evidence['synthesis'])]+[(r['results']['label'],r['results']['synthesis']) for r in rows]
        for label,synthesis in entries:
            for config,syn in synthesis.items():
                if not config.startswith(backend+'/'):continue
                area,path=syn.get('area',{}),syn.get('timing',{})
                base=evidence['synthesis'][config]['area']['equivalent_slice']
                delta=100*(area['equivalent_slice']/base-1) if syn['status']=='passed' else None
                lines.append('| '+' | '.join([label,config.split('/')[1],*[fmt(area.get(n)) for n in
                    ('lut','ff','bram36','equivalent_slice')],fmt(delta),fmt(path.get('data_path_ns')),
                    syn['status']+('；analysis_deferred，后台继续' if syn.get('analysis_deferred') else '')])+' |')
        lines.append('')
    for profile in dual.PROFILES:
        lines += [f'## {profile} 完整Sign','',
            '| 候选 | 后端／配置 | 周期 | C3周期 | 变化% | 假设时间ms | 假设ATP | ATP变化% | 实际MHz | 布线ATP | 状态 |',
            '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|']
        for r in rows:
            for row in r['results']['rows']:
                if row['profile']!=profile:continue
                actual,atp=None,None
                physical=(r['physical'] or {}).get('routes',{}).get(row['config'],{})
                if physical.get('meets_target') and row['status']=='passed':
                    period=physical['result']['actual_period_ns'];actual=1000/period
                    atp=physical['routed_area']['equivalent_slice']*row['cycles']*period/1e6
                lines.append('| '+' | '.join([r['results']['label'],row['config'],fmt(row['cycles']),fmt(row['baseline_cycles']),
                    fmt(row.get('cycles_change_pct')),fmt(row.get('assumed_target_time_ms')),fmt(row['diagnostic_atp']),
                    fmt(row['diagnostic_atp_change_pct']),fmt(actual),fmt(atp),row['status']])+' |')
        lines.append('')
    lines += ['## C3基线与候选的指定频率物理证据','',
        '| 候选 | 后端／配置 | 目标MHz | 布线Slice | WNS ns | WHS ns | 状态 |',
        '|---|---|---:|---:|---:|---:|---|']
    for label,state in [('C3基线',baseline_physical)]+[(r['results']['label'],r['physical']) for r in rows]:
        for config,job in (state or {}).get('routes',{}).items():
            timing=job.get('result',{});area=job.get('routed_area',{})
            lines.append('| '+' | '.join([label,config,fmt(job.get('target_frequency_mhz')),fmt(area.get('equivalent_slice')),
                fmt(timing.get('wns_ns')),fmt(timing.get('whs_ns')),job['status']])+' |')
    lines += ['',f'基线源码：`{BASELINE_SHA}`；参考C3源码：`{REFERENCE_SHA}`。','',
        '每候选归档冻结RTL/support、控制器、分层与时序、源码SHA及Vivado日志；仿真/验证详细日志留运行目录。'
        '不生成CSV或归档README，不执行h20完整Keygen/Sign。','']
    archive.atomic(prefix.with_suffix('.md'),'\n'.join(lines))


def prepare_baseline():
    require(sha(BASELINE/'SOURCE.json')==BASELINE_SHA,'Wrong newly frozen baseline')
    evidence=reference_evidence();meta=read(BASELINE/'SOURCE.json');out=Path(meta['archive_directory'])
    for base in (BASELINE,out):write(base/'C3_EVIDENCE.json',evidence)
    for config in evidence['synthesis']:
        for p in (REFERENCE/'synth'/config).iterdir():
            if p.is_file() and p.suffix in ('.rpt','.log','.txt','.xdc'):
                archive.copy_changed(p,out/'reference_synth'/config/p.name)
    archive.copy_changed(REFERENCE/'functional_validation/VALIDATION.json',out/'reference_validation/SUMMARY.json')
    previous.pack_support(Path(meta['source_root']),out,meta['sha256']);freeze_controls(BASELINE,out)
    publish_family();archive.index()
    print(json.dumps(dict(baseline=str(BASELINE),source_manifest_sha256=BASELINE_SHA,
        report=str(out/'reports/P1_SHA_Timing_Refine_20261021.md'),top_level_vivado_jobs=len(live_top_jobs())),indent=2))


def launch(args):
    require((BASELINE/'C3_EVIDENCE.json').is_file(),'Prepare C3 evidence first')
    stamp=datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y%m%d_%H%M%S')
    run=FAMILY/('candidate_'+stamp);out=archive.ARCHIVES/('p1sha_timing_refine_candidate_'+stamp)
    checks=dual.frozen_snapshot(ROOT,run/'source')
    meta=dict(schema='mhbs.p1sha_atp.source.v1',experiment_family='p1sha_timing_refine',kind='candidate',label=args.label,
        run_id=stamp,started_at=now(),source_root=str(run/'source'),archive_directory=str(out),sha256=checks,
        rtl_files=read(BASELINE/'SOURCE.json')['rtl_files'],baseline_manifest_sha256=BASELINE_SHA,reference_manifest_sha256=REFERENCE_SHA)
    settings=dict(previous.tool_settings(),diagnostic_configs=list(TARGETS)+(['sha2/P12U1'] if args.with_p12 else []),
        configs=list(TARGETS),operation='sign',p12_not_a_gate=True)
    for base in (run,out):
        write(base/'SOURCE.json',meta);write(base/'EXPERIMENT.json',settings)
        archive.copy_changed(BASELINE/'C3_EVIDENCE.json',base/'C3_EVIDENCE.json')
    freeze_controls(run,out);archive.pack_rtl(run/'source',out/'rtl.tar.gz',checks);previous.pack_support(run/'source',out,checks)
    patch=subprocess.run(['diff','-ru',str(BASELINE/'source/rtl'),str(run/'source/rtl')],text=True,stdout=subprocess.PIPE)
    require(patch.returncode in (0,1),'Could not create lineage');archive.atomic(out/'lineage/from_C3.patch',patch.stdout)
    with (run/'runner.log').open('w') as stream:
        process=subprocess.Popen([sys.executable,str(run/'control/run_p1sha_timing_refine.py'),'--run-root',str(run)],
            cwd=ROOT,env=dict(os.environ,MHBS_P1SHA_REFINE_WORKSPACE=str(ROOT),MHBS_P1SHA_WORKSPACE=str(ROOT)),
            stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
    value=dict(pid=process.pid,root=str(run),source_manifest_sha256=sha(run/'SOURCE.json'),sign_tests=18,
        diagnostic_syntheses=len(settings['diagnostic_configs']),automatic_routing=False)
    write(run/'LAUNCH.json',value);print(json.dumps(value,indent=2))


def route_existing(run):
    run=Path(run).resolve();physical_helpers.validate_ready(run)
    require(not (run/'PHYSICAL_LAUNCH.json').exists(),'Route phase already launched')
    budget=FAMILY/'ROUTE_BUDGET.json'
    with budget.with_suffix('.lock').open('a+') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX)
        entries=read(budget) if budget.exists() else []
        require(len(entries)<2,'At most two frozen candidates / twelve fixed routes are authorized')
        entries.append(dict(run_root=str(run),source_manifest_sha256=sha(run/'SOURCE.json'),targets=TARGETS));write(budget,entries)
    meta=read(run/'SOURCE.json');out=Path(meta['archive_directory'])
    for name in CONTROLS:
        for base in (run,out):archive.copy_changed(ROOT/'scripts'/name,base/'physical_control'/name)
    request=dict(source_manifest_sha256=sha(run/'SOURCE.json'),requested_at=now(),configs=TARGETS,
        frequency_search=False,automatic_frequency_fallback=False,user_authorized_fixed_targets=True,
        controls_sha256={n:sha(run/'physical_control'/n) for n in CONTROLS})
    for base in (run,out):write(base/'PHYSICAL_REQUEST.json',request)
    with (run/'physical_runner.log').open('w') as stream:
        process=subprocess.Popen([sys.executable,str(run/'physical_control/run_p1sha_timing_refine.py'),
            '--physical-run',str(run)],cwd=ROOT,env=dict(os.environ,MHBS_P1SHA_REFINE_WORKSPACE=str(ROOT),MHBS_P1SHA_WORKSPACE=str(ROOT)),
            stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
    request['pid']=process.pid
    for base in (run,out):write(base/'PHYSICAL_LAUNCH.json',request)
    print(json.dumps(request,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare-baseline',action='store_true');mode.add_argument('--launch-candidate',action='store_true')
    mode.add_argument('--run-root',type=Path);mode.add_argument('--route-existing',type=Path)
    mode.add_argument('--physical-run',type=Path);mode.add_argument('--watch',action='store_true')
    parser.add_argument('--label',default='candidate');parser.add_argument('--with-p12',action='store_true');args=parser.parse_args()
    if args.prepare_baseline:prepare_baseline()
    elif args.launch_candidate:launch(args)
    elif args.run_root:sys.exit(Runner(args.run_root).execute())
    elif args.route_existing:route_existing(args.route_existing)
    elif args.physical_run:sys.exit(PhysicalRunner(args.physical_run).execute())
    else:
        while True:
            publish_family();time.sleep(20)
