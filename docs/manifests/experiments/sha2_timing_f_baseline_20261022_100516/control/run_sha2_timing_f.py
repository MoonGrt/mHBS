#!/usr/bin/env python3
"""Freeze SHA2 F candidates, diagnose at 100 MHz, and route only explicitly.

The baseline is the immutable 20261022_093744 matrix. Preparing/freezing starts
no hardware. --launch-measure and --route-existing are separate explicit stages.
Each route waits only for its own three complete Sign tests and diagnostic plus
the same-source 36-group functional validator. Old controllers remain untouched.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
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
import run_dual_pu_route_matrix as dual
import run_p1sha_atp_optimization as shared

ROOT=Path(os.environ.get('MHBS_SHA2_F_WORKSPACE',Path(__file__).resolve().parents[1])).resolve()
archive.ROOT=dual.ROOT=shared.ROOT=ROOT
archive.ARCHIVES=ROOT/'docs/manifests/experiments'
FAMILY=ROOT/'build/sha2_timing_f'
REFERENCE=ROOT/'build/dual_pu_route_matrix/20261022_093744'
REFERENCE_SHA='6361eeed6936b3714835aade83b7b8e04ce9140c679b455bf1893d25f30d9c7d'
DEFAULT_CONFIGS=('sha2/P1U1','sha2/P4U1','sha2/P12U1','sha2/P4U2','sha2/P8U1','sha2/P12U2')
ALL_CONFIGS=tuple(dual.route_key('sha2',p,u) for p,u in dual.CONFIGS)
CONTROLS=('run_sha2_timing_f.py',*shared.CONTROLS)
read,write,sha,require,now,parts=shared.read,shared.write,shared.sha,shared.require,shared.now,shared.parts


def selected(values=None,all14=False):
    configs=list(ALL_CONFIGS if all14 else values or DEFAULT_CONFIGS)
    configs=[value if value.startswith('sha2/') else 'sha2/'+value for value in configs]
    require(configs and len(set(configs))==len(configs) and all(c in ALL_CONFIGS for c in configs),
        'Select distinct SHA2 configurations from the existing 14-point matrix')
    return configs


def reference_evidence(configs):
    require(sha(REFERENCE/'SOURCE.json')==REFERENCE_SHA,'Wrong baseline SOURCE')
    meta,state=read(REFERENCE/'SOURCE.json'),read(REFERENCE/'status.json')
    require(shared.unchanged(meta),'Baseline frozen inputs changed')
    tests={}
    for config in configs:
        for profile in dual.PROFILES:
            key=config+'/'+profile;test=deepcopy(state['tests'][key])
            require(test['status']=='passed' and test['source_unchanged']
                and test['source_manifest_sha256']==REFERENCE_SHA
                and test['output_and_signature_cache_checked_bytewise'],'Baseline Sign missing/unbound: '+key)
            for field in ('log','raw_log'):require(sha(test[field])==test[field+'_sha256'],'Baseline Sign log changed')
            for name,wanted in test['vectors_sha256'].items():
                require(meta['sha256'][name]==sha(Path(meta['source_root'])/name)==wanted,'Baseline vector changed')
            tests[key]=test
    return dict(reference_run=str(REFERENCE),source_manifest_sha256=REFERENCE_SHA,checked_at=now(),
        source_inputs_checked=True,actual_logs_and_vectors_checked=True,tests=tests,
        baseline_100mhz_diagnostic_reused=False,physical_results_are_independent_dynamic_evidence=True)


def controls(run,out,folder='control'):
    for name in CONTROLS:
        for base in (run,out):archive.copy_changed(ROOT/'scripts'/name,base/folder/name)
    proof={name:sha(run/folder/name) for name in CONTROLS}
    for base in (run,out):write(base/(folder.upper()+'_SOURCE.json'),proof)


def import_diagnostics(run,meta,state):
    """Reuse only equal RTL/Tcl/tool/clock inputs; retain the native identity."""
    original=ROOT/'build/p1sha_atp_e/candidate_20261021_223449'
    old,results=read(original/'SOURCE.json'),read(original/'status.json')
    names=meta['rtl_files']+['sources.txt','scripts/diagnose_timing.tcl']
    source=Path(meta['source_root']);native=Path(old['source_root']);out=Path(meta['archive_directory'])
    require(all(meta['sha256'][n]==old['sha256'][n]==sha(source/n)==sha(native/n) for n in names),
        'Baseline diagnostics have different active RTL/Tcl inputs')
    require(sha(run/'control/diagnose_timing.tcl')==meta['sha256']['scripts/diagnose_timing.tcl'],
        'Baseline diagnostic control differs')
    imported={}
    for config in meta['configs']:
        if config not in results['synthesis']:continue
        item=deepcopy(results['synthesis'][config]);require(item['status']=='passed' and item['source_unchanged'],
            'Native E2 diagnostic incomplete')
        directory=original/'synth'/config;settings=(directory/'settings.txt').read_text().splitlines()
        require(all(line in settings for line in ('period_ns=10.0','threads=2','top=common','hash_backend=sha2',
            'part=xc7a200tffg1156-3','timing_driven=default','new_timing_exceptions=none','vivado=2025.2')),
            'Native E2 diagnostic tool/clock differs')
        for name,wanted in item['reports_sha256'].items():
            require(sha(directory/name)==wanted,'Native diagnostic report changed')
            archive.copy_changed(directory/name,run/'synth'/config/name)
            archive.copy_changed(directory/name,out/'synth'/config/name)
        item.update(source_manifest_sha256=sha(run/'SOURCE.json'),reused_native_source_manifest_sha256=sha(original/'SOURCE.json'),
            reused_from=str(directory),equivalent_diagnostic_inputs={n:meta['sha256'][n] for n in names},
            evidence_kind='reused_exact_RTL_Tcl_tool_and_clock_inputs',no_new_synthesis_run=True)
        state['synthesis'][config]=item;imported[config]=item
    for base in (run,out):write(base/'DIAGNOSTIC_REUSE.json',dict(native_run=str(original),native_source_manifest_sha256=sha(original/'SOURCE.json'),
        active_inputs_verified=True,whole_source_manifests_are_distinct=True,configurations=imported))


def freeze(kind,label,configs,baseline=None):
    reference=reference_evidence(configs)
    if baseline:
        old=read(baseline/'SOURCE.json')
        require(old['kind']=='baseline' and all(c in old['configs'] for c in configs),'Baseline scope differs')
        require(shared.unchanged(old),'F baseline inputs changed')
    stamp=datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y%m%d_%H%M%S')
    run=FAMILY/(kind+'_'+stamp);out=archive.ARCHIVES/('sha2_timing_f_'+kind+'_'+stamp)
    source=Path(read(REFERENCE/'SOURCE.json')['source_root']) if kind=='baseline' else ROOT
    checks=dual.frozen_snapshot(source,run/'source')
    rtl=[n for n in (run/'source/sources.txt').read_text().splitlines() if n.strip()]
    meta=dict(schema='mhbs.p1sha_atp.source.v1',experiment_family='sha2_timing_f',kind=kind,label=label,
        run_id=stamp,started_at=now(),source_root=str(run/'source'),archive_directory=str(out),
        sha256=checks,rtl_files=rtl,configs=configs,reference_manifest_sha256=REFERENCE_SHA,
        baseline_run=str(baseline.resolve()) if baseline else None)
    settings=dict(shared.tool_settings(),vivado_workers=3,configs=configs,operation='sign',cycle_changes_allowed=True)
    for base in (run,out):
        write(base/'SOURCE.json',meta);write(base/'EXPERIMENT.json',settings);write(base/'REFERENCE_EVIDENCE.json',reference)
    controls(run,out);archive.pack_rtl(run/'source',out/'rtl.tar.gz',checks);shared.pack_support(run/'source',out,checks)
    if kind=='candidate':
        patch=subprocess.run(['diff','-ru',str(Path(read(REFERENCE/'SOURCE.json')['source_root'])/'rtl'),str(run/'source/rtl')],
            text=True,stdout=subprocess.PIPE)
        require(patch.returncode in (0,1),'Could not create baseline lineage')
        archive.atomic(out/'lineage/from_matrix_E2.patch',patch.stdout)
    initial=dict(schema='mhbs.sha2_timing_f.results.v1',label=label,pid=None,complete=False,measurement_started=False,
        source_manifest_sha256=sha(run/'SOURCE.json'),
        tests=deepcopy(reference['tests']) if kind=='baseline' else {c+'/'+p:dict(status='pending') for c in configs for p in dual.PROFILES},
        synthesis={c:dict(status='pending') for c in configs})
    if kind=='baseline':import_diagnostics(run,meta,initial)
    for base in (run,out):write(base/'status.json',initial)
    publish_report(run);inventory(run);archive.index()
    return dict(run_root=str(run),source_manifest_sha256=sha(run/'SOURCE.json'),archive_directory=str(out),
        configurations=configs,hardware_started=False)


def functional(run):
    path=run/'functional_validation/VALIDATION.json'
    return read(path) if path.exists() else None


def rows(run):
    meta,state=read(run/'SOURCE.json'),read(run/'status.json');reference=read(run/'REFERENCE_EVIDENCE.json')
    physical=read(run/'PHYSICAL_STATUS.json') if (run/'PHYSICAL_STATUS.json').exists() else {}
    baseline=read(Path(meta['baseline_run'])/'status.json') if meta.get('baseline_run') else {}
    results=[]
    for config in meta['configs']:
        target=150 if parts(config)[2]==1 else 100;syn=state['synthesis'][config];route=physical.get('routes',{}).get(config,{})
        for profile in dual.PROFILES:
            key=config+'/'+profile;test=state['tests'][key];old=reference['tests'][key]
            row=dict(config=config,profile=profile,simulation_status=test['status'],diagnostic_status=syn['status'],
                physical_status=route.get('status','not_requested'),target_mhz=target,cycles=test.get('cycles'),
                baseline_cycles=old['cycles'],cycles_change_pct=None,workload_equal=None,assumed_time_ms=None,
                assumed_atp_slice_ms=None,baseline_diagnostic_atp_change_pct=None,actual_mhz=None,routed_atp_slice_ms=None,rank=None)
            if test['status']=='passed':
                row.update(cycles_change_pct=100*(test['cycles']/old['cycles']-1),
                    workload_equal=all(test[n]==old[n] for n in ('hashes','permutations','vectors_sha256')),
                    assumed_time_ms=test['cycles']/(target*1000))
                if syn['status']=='passed':
                    row['assumed_atp_slice_ms']=syn['area']['equivalent_slice']*row['assumed_time_ms']
                    previous=baseline.get('synthesis',{}).get(config,{})
                    if previous.get('status')=='passed':
                        row['baseline_diagnostic_atp_change_pct']=100*(syn['area']['equivalent_slice']*test['cycles']/
                            (previous['area']['equivalent_slice']*old['cycles'])-1)
                if route.get('meets_target') and route.get('source_unchanged'):
                    period=route['result']['actual_period_ns'];row.update(actual_mhz=1000/period,
                        routed_atp_slice_ms=route['routed_area']['equivalent_slice']*test['cycles']*period/1e6)
            results.append(row)
    for profile in dual.PROFILES:
        ranked=sorted((row for row in results if row['profile']==profile and row['routed_atp_slice_ms'] is not None),
            key=lambda row:row['routed_atp_slice_ms'])
        for rank,row in enumerate(ranked,1):row['rank']=rank
    return results


def publish_report(run):
    meta,state=read(run/'SOURCE.json'),read(run/'status.json');out=Path(meta['archive_directory'])
    baseline_state=read(REFERENCE/'status.json');reference=read(run/'REFERENCE_EVIDENCE.json')
    require(baseline_state['source_manifest_sha256']==REFERENCE_SHA,'Baseline physical identity changed')
    physical=read(run/'PHYSICAL_STATUS.json') if (run/'PHYSICAL_STATUS.json').exists() else None
    result=dict(updated_at=now(),source=meta,results=state,rows=rows(run),functional=functional(run),physical=physical,
        baseline_source_manifest_sha256=REFERENCE_SHA,baseline_physical={c:baseline_state['routes'][c] for c in meta['configs']},
        diagnostic_is_not_fmax=True,frequency_search=False,automatic_frequency_fallback=False)
    prefix=out/'reports'/('SHA2_Timing_F_'+meta['run_id']);write(prefix.with_suffix('.json'),result)
    fmt=lambda value:'—' if value is None else f'{value:,.3f}'
    lines=['# SHA2 F轮时序、面积与ATP','',f'候选：{meta["label"]}；更新时间：{result["updated_at"]}。','',
        '基线为20261022_093744冻结E2矩阵，SOURCE SHA256='+REFERENCE_SHA+'。复用其逐字节/签名缓存及Hash/压缩计数通过的完整Sign，'
        '候选Hash工作量和向量必须相同，周期允许变化。基线正在后台的物理结果单列，不从负WNS推测Fmax。','',
        '100MHz common OOC综合只用于面积/关键路径诊断，最终目标U1=150MHz、U2=100MHz。'
        '最终布线必须单独明确发起；每配置自己的三个Sign、100MHz诊断及同源36组正常/综合视图验证通过后才启动该点。'
        '无频率搜索、自动降频或新增时序例外。旧任务保留；全机最多12个顶层Vivado、每个2线程。','',
        '器件xc7a200tffg1156-3、默认时序驱动、SYNTHESIS统计裁剪；等效Slice=LUT/4+FF/8+232.4×BRAM36+102.4×DSP。'
        '超10分钟只标analysis_deferred继续后台。h20完整Keygen/Sign不运行。','',
        '## 100MHz common诊断面积','',
        '| 配置 | LUT | FF | BRAM36 | 等效Slice | 路径ns | 级数 | 状态 |',
        '|---|---:|---:|---:|---:|---:|---:|---|']
    for config,syn in state['synthesis'].items():
        area,timing=syn.get('area',{}),syn.get('timing',{})
        lines.append('| '+' | '.join([config,*[fmt(area.get(n)) for n in ('lut','ff','bram36','equivalent_slice')],
            fmt(timing.get('data_path_ns')),fmt(timing.get('logic_levels')),
            syn['status']+('；analysis_deferred' if syn.get('analysis_deferred') else '')])+' |')
    for profile in dual.PROFILES:
        lines+=['',f'## {profile} 完整Sign','',
            '| 配置 | 周期 | 基线周期 | 变化% | 假定时间ms | 假定ATP | 对基线100MHz面积ATP% | 实际MHz | 布线ATP | 排名 | 状态 |',
            '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|']
        for row in result['rows']:
            if row['profile']==profile:
                lines.append('| '+' | '.join([row['config'],*[fmt(row[n]) for n in ('cycles','baseline_cycles','cycles_change_pct',
                    'assumed_time_ms','assumed_atp_slice_ms','baseline_diagnostic_atp_change_pct','actual_mhz','routed_atp_slice_ms','rank')],
                    row['simulation_status']])+' |')
    lines+=['','## 固定目标物理证据','',
        '| 源码 | 配置 | 目标MHz | 布线Slice | WNS | WHS | 状态 |','|---|---|---:|---:|---:|---:|---|']
    for label,group in [('基线E2',result['baseline_physical']),(meta['label'],(physical or {}).get('routes',{}))]:
        for config,job in group.items():
            timing=job.get('result',{});area=job.get('routed_area',{})
            lines.append('| '+' | '.join([label,config,fmt(job.get('target_frequency_mhz')),fmt(area.get('equivalent_slice')),
                fmt(timing.get('wns_ns')),fmt(timing.get('whs_ns')),job['status']])+' |')
    proof=result['functional']
    lines+=['',f'同源局部验证：{proof["passed"] if proof else 0}/36通过；'+
        ('已完成。' if proof and proof.get('complete') else '尚未完成，不作为通过。'),'',
        '冻结RTL/support、源码与控制器校验、分层/时序和Vivado日志均归档；详细sim/validation日志保留运行目录。'
        '仅Markdown/JSON，不归档CSV/README。','']
    archive.atomic(prefix.with_suffix('.md'),'\n'.join(lines))


def inventory(run):
    meta=read(run/'SOURCE.json');out=Path(meta['archive_directory'])
    for folder in ('synth','jobs'):
        for path in (run/folder).rglob('*') if (run/folder).exists() else []:
            if path.is_file() and path.suffix in ('.rpt','.log','.json','.txt','.xdc'):
                archive.copy_changed(path,out/path.relative_to(run))
    if functional(run):
        archive.copy_changed(run/'functional_validation/VALIDATION.json',out/'supplementary_evidence/functional/SUMMARY.json')
        archive.copy_changed(run/'functional_validation/validator.py',out/'supplementary_evidence/functional/validator.py')
    state=read(run/'status.json');physical=read(run/'PHYSICAL_STATUS.json') if (run/'PHYSICAL_STATUS.json').exists() else {}
    missing={c:[name for name in ('hierarchical.rpt','timing.rpt') if not (out/'synth'/c/name).exists()] for c in meta['configs']}
    write(out/'ARTIFACTS.json',dict(updated_at=now(),measurements_complete=state['complete'],physical_complete=physical.get('complete',False),
        missing_diagnostic_reports=missing,source_manifest_sha256=sha(run/'SOURCE.json'),omitted_details=['sim','validation'],
        sha256={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p.name!='ARTIFACTS.json' and not p.name.endswith('.tmp')}))


class Measurement(dual.Runner):
    synthesize=shared.Runner.synthesize

    def __init__(self,run):
        self.run=Path(run).resolve();self.meta=dict(read(self.run/'SOURCE.json'),**read(self.run/'EXPERIMENT.json'))
        self.source,self.out=Path(self.meta['source_root']),Path(self.meta['archive_directory'])
        self.configs=self.meta['configs'];self.lock=threading.RLock();self.capacity_lock=threading.Lock()
        self.capacity_token=threading.local();self.reserved=0;self.copied={};self.checksums={}
        self.state=read(self.run/'status.json');self.state.update(pid=os.getpid(),measurement_started=True,started_at=now())

    def publish(self):
        self.state['updated_at']=now()
        for base in (self.run,self.out):write(base/'status.json',self.state)
        publish_report(self.run);inventory(self.run)

    def execute(self):
        self.publish();archive.index()
        with ThreadPoolExecutor(max_workers=3) as synth_pool,ThreadPoolExecutor(max_workers=4) as sim_pool:
            jobs=[synth_pool.submit(self.synthesize,c) for c in self.configs if self.state['synthesis'][c]['status']!='passed']
            if self.meta['kind']=='candidate':jobs += [sim_pool.submit(self.simulate,*parts(c)) for c in self.configs]
            for job in as_completed(jobs):job.result()
        self.state.update(complete=True,source_unchanged=self.unchanged(),finished_at=now());self.publish();archive.index()
        return int(not self.unchanged() or any(job['status']!='passed' for group in ('tests','synthesis') for job in self.state[group].values()))


def gate(run,config,verify=False):
    meta,state=read(run/'SOURCE.json'),read(run/'status.json');manifest=sha(run/'SOURCE.json');pending=[];failed=[]
    jobs=[('diagnostic',state['synthesis'][config])]+[(p,state['tests'][config+'/'+p]) for p in dual.PROFILES]
    for label,job in jobs:
        if job['status'] in ('failed','error'):failed.append(label)
        elif job['status']!='passed':pending.append(label)
    proof=functional(run)
    if not proof or not proof.get('complete'):pending.append('functional36')
    elif proof['passed']!=proof['total_planned'] or proof['total_planned']!=36 or proof['failed'] or not proof['source_unchanged']:
        failed.append('functional36')
    if not pending and not failed and verify:
        require(shared.unchanged(meta),'Frozen candidate changed');reference=read(run/'REFERENCE_EVIDENCE.json')
        require(proof['source_manifest_sha256']==manifest and sha(run/'functional_validation/validator.py')==proof['validator_sha256'],
            'Functional source/validator differs')
        for test in proof['tests']:require(test['passed'] and sha(test['log'])==test['log_sha256'],'Functional raw log changed')
        for label,job in jobs:
            require(job['source_unchanged'] and job['source_manifest_sha256']==manifest,'Gate source differs')
            if label=='diagnostic':
                for name,wanted in job['reports_sha256'].items():require(sha(run/'synth'/config/name)==wanted,'Diagnostic report changed')
                require(sha(run/'synth'/config/'synthesized.dcp')==job['checkpoint_sha256'],'Diagnostic checkpoint changed')
            else:
                require(job['output_and_signature_cache_checked_bytewise'],'Sign byte checks absent')
                for name in ('hashes','permutations','vectors_sha256'):
                    require(job[name]==reference['tests'][config+'/'+label][name],'Sign workload differs')
                for field in ('log','raw_log'):require(sha(job[field])==job[field+'_sha256'],'Sign log changed')
    return dict(ready=not pending and not failed,pending=pending,failed=failed)


class Physical(dual.Runner):
    def __init__(self,run):
        self.run=Path(run).resolve();self.meta=dict(read(self.run/'SOURCE.json'),**read(self.run/'EXPERIMENT.json'))
        self.source,self.out=Path(self.meta['source_root']),Path(self.meta['archive_directory'])
        request=read(self.run/'PHYSICAL_REQUEST.json');require(request['source_manifest_sha256']==sha(self.run/'SOURCE.json'),'Route request source differs')
        self.configs=request['configs'];self.lock=threading.RLock();self.capacity_lock=threading.Lock()
        self.capacity_token=threading.local();self.reserved=0;self.copied={};self.checksums={}
        self.state=dict(schema='mhbs.sha2_timing_f.physical.v1',pid=os.getpid(),complete=False,started_at=now(),
            source_manifest_sha256=sha(self.run/'SOURCE.json'),routes={c:dict(status='pending',target_frequency_mhz=150 if parts(c)[2]==1 else 100) for c in self.configs})

    def publish(self):
        self.state['updated_at']=now()
        for base in (self.run,self.out):write(base/'PHYSICAL_STATUS.json',self.state)
        publish_report(self.run);inventory(self.run)

    def route(self,backend,p,u):
        config=dual.route_key(backend,p,u)
        while True:
            status=gate(self.run,config)
            if status['failed']:self.update('routes',config,status='validation_failed',gate=status);return
            if status['ready']:break
            self.update('routes',config,status='waiting_for_validation',gate=status);time.sleep(15)
        try:gate(self.run,config,True)
        except Exception as error:self.update('routes',config,status='validation_failed',error=str(error));return
        return super().route(backend,p,u)

    def execute(self):
        self.publish();archive.index()
        with ThreadPoolExecutor(max_workers=len(self.configs)) as pool:
            jobs=[pool.submit(self.route,*parts(c)) for c in self.configs]
            for job in as_completed(jobs):job.result()
        self.state.update(complete=True,source_unchanged=self.unchanged(),finished_at=now());self.publish();archive.index()


def detach(run,mode,log):
    env=dict(os.environ,MHBS_SHA2_F_WORKSPACE=str(ROOT),MHBS_P1SHA_WORKSPACE=str(ROOT),MHBS_DUAL_MATRIX_WORKSPACE=str(ROOT))
    with (run/log).open('w') as stream:
        proc=subprocess.Popen([sys.executable,str(run/'control/run_sha2_timing_f.py'),mode,str(run)],cwd=ROOT,
            env=env,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
    return proc.pid


def launch_measure(run):
    run=run.resolve();meta=read(run/'SOURCE.json');require(meta['experiment_family']=='sha2_timing_f','Wrong family')
    require(not (run/'MEASUREMENT_LAUNCH.json').exists() and shared.unchanged(meta),'Already launched/changed source')
    value=dict(requested_at=now(),source_manifest_sha256=sha(run/'SOURCE.json'),pid=detach(run,'--run-root','runner.log'))
    if meta['kind']=='candidate':
        with (run/'functional_validator.log').open('w') as stream:
            proc=subprocess.Popen([sys.executable,str(Path(meta['source_root'])/'scripts/validate_p1sha_candidate.py'),'--run-root',str(run)],
                cwd=ROOT,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        value['functional_pid']=proc.pid
    write(run/'MEASUREMENT_LAUNCH.json',value);return value


def launch_physical(run,configs):
    run=run.resolve();meta=read(run/'SOURCE.json');require(meta['kind']=='candidate' and meta['experiment_family']=='sha2_timing_f','Candidate required')
    require(shared.unchanged(meta) and not (run/'PHYSICAL_REQUEST.json').exists(),'Changed/already routed candidate')
    configs=selected(configs or meta['configs']);require(all(c in meta['configs'] for c in configs),'Route outside frozen measured scope')
    request=dict(requested_at=now(),source_manifest_sha256=sha(run/'SOURCE.json'),configs=configs,
        explicit_user_authorization=True,root_explicit_final_freeze=True,per_configuration_gate=True,
        targets_mhz={'1':150,'2':100},frequency_search=False,automatic_frequency_fallback=False)
    for base in (run,Path(meta['archive_directory'])):write(base/'PHYSICAL_REQUEST.json',request)
    request['pid']=detach(run,'--physical-run','physical_runner.log')
    for base in (run,Path(meta['archive_directory'])):write(base/'PHYSICAL_LAUNCH.json',request)
    return request


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare-baseline',action='store_true');mode.add_argument('--freeze-candidate',action='store_true')
    mode.add_argument('--launch-measure',type=Path);mode.add_argument('--route-existing',type=Path)
    mode.add_argument('--run-root',type=Path);mode.add_argument('--physical-run',type=Path);mode.add_argument('--report-existing',type=Path)
    parser.add_argument('--baseline',type=Path);parser.add_argument('--label',default='F1');parser.add_argument('--configs',nargs='+')
    parser.add_argument('--all14',action='store_true');args=parser.parse_args()
    if args.prepare_baseline:result=freeze('baseline','E2_matrix_093744',selected(args.configs,args.all14))
    elif args.freeze_candidate:
        require(args.baseline is not None,'--baseline must select the prepared F diagnostic baseline')
        result=freeze('candidate',args.label,selected(args.configs,args.all14),args.baseline)
    elif args.launch_measure:result=launch_measure(args.launch_measure)
    elif args.route_existing:result=launch_physical(args.route_existing,args.configs)
    elif args.run_root:raise SystemExit(Measurement(args.run_root).execute())
    elif args.physical_run:Physical(args.physical_run).execute();raise SystemExit()
    else:publish_report(args.report_existing);inventory(args.report_existing);archive.index();result=dict(report_refreshed=str(args.report_existing))
    print(json.dumps(result,ensure_ascii=False,indent=2))
