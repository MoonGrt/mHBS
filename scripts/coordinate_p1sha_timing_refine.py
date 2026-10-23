#!/usr/bin/env python3
"""Source-bound D1/D2 fixed-target routes with independent per-point gates.

Four P1 configurations determine the initial comparison. A slow SHA2 P4
diagnostic never blocks ready P1 routes: each configuration waits only for its
own three complete Sign tests and 100 MHz diagnostic plus the same-source
36-group functional validator. No frequency search, fallback or RTL mutation.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import experiment_archive as archive
import run_dual_pu_route_matrix as dual
import run_p1sha_atp_optimization as previous
import coordinate_p1sha_atp_optimization as physical_helpers
import run_p1sha_timing_refine as refine

ROOT,FAMILY,BASELINE=refine.ROOT,refine.FAMILY,refine.BASELINE
TARGETS=refine.TARGETS
P1_TARGETS=TARGETS[:4]
RUNS=('candidate_20261021_214504','candidate_20261021_215634')
OUT=Path(refine.read(BASELINE/'SOURCE.json')['archive_directory'])
PREFIX=OUT/'reports/P1_SHA_Timing_Refine_Automation_20261021'
read,write,sha,require,now,parts=refine.read,refine.write,refine.sha,refine.require,refine.now,refine.parts


def point_status(run,config):
    state=read(run/'status.json');pending=[];failed=[]
    syn=state['synthesis'][config]
    if syn['status']=='failed':failed.append('diagnostic')
    elif syn['status']!='passed':pending.append('diagnostic')
    for profile in dual.PROFILES:
        test=state['tests'][config+'/'+profile]
        if test['status']=='failed':failed.append('Sign/'+profile)
        elif test['status']!='passed':pending.append('Sign/'+profile)
    functional=run/'functional_validation/VALIDATION.json'
    if not functional.is_file() or not read(functional).get('complete'):pending.append('functional/36')
    else:
        proof=read(functional)
        if proof['failed'] or proof['passed']!=36 or not proof['source_unchanged']:failed.append('functional/36')
    return dict(ready=not pending and not failed,pending=pending,failed=failed)


def validate_point(run,config):
    require(point_status(run,config)['ready'],'Point validation not complete: '+config)
    meta,state=read(run/'SOURCE.json'),read(run/'status.json');manifest=sha(run/'SOURCE.json')
    require(previous.unchanged(meta),'Frozen source changed')
    baseline=read(run/'C3_EVIDENCE.json')
    syn=state['synthesis'][config]
    require(syn['source_unchanged'] and syn['source_manifest_sha256']==manifest,'Diagnostic source differs')
    for name,wanted in syn['reports_sha256'].items():
        require(sha(run/'synth'/config/name)==wanted,'Changed diagnostic report: '+name)
    require(sha(run/'synth'/config/'synthesized.dcp')==syn['checkpoint_sha256'],'Changed diagnostic checkpoint')
    for profile in dual.PROFILES:
        key=config+'/'+profile;test=state['tests'][key];old=baseline['tests'][key]
        require(test['source_unchanged'] and test['source_manifest_sha256']==manifest
            and test['output_and_signature_cache_checked_bytewise'],'Sign source/output binding differs')
        require(all(test[n]==old[n] for n in ('hashes','permutations','vectors_sha256')),'Sign workload differs')
        for field in ('log','raw_log'):require(sha(test[field])==test[field+'_sha256'],'Changed Sign log')
    functional=read(run/'functional_validation/VALIDATION.json')
    require(functional['source_manifest_sha256']==manifest and functional['source_unchanged']
        and functional['passed']==functional['total_planned']==36 and not functional['failed'],
        'Functional source/count differs')
    require(sha(run/'functional_validation/validator.py')==functional['validator_sha256'],'Functional validator changed')
    for test in functional['tests']:require(test['passed'] and sha(test['log'])==test['log_sha256'],'Changed functional raw log')
    out=Path(meta['archive_directory'])/'supplementary_evidence/functional'
    archive.copy_changed(run/'functional_validation/VALIDATION.json',out/'SUMMARY.json')
    archive.copy_changed(run/'functional_validation/validator.py',out/'validator.py')
    return dict(validated_at=now(),source_manifest_sha256=manifest,configuration=config,
        full_sign_tests=3,functional_groups=36,diagnostic_mhz=100,raw_logs_and_report_checksums_verified=True)


class PhysicalRunner(dual.Runner):
    reserve=refine.Runner.reserve
    release_capacity=previous.Runner.release_capacity

    def __init__(self,run):
        self.run=Path(run).resolve()
        self.meta=dict(read(self.run/'SOURCE.json'),**read(self.run/'EXPERIMENT.json'))
        self.source,self.out=Path(self.meta['source_root']),Path(self.meta['archive_directory'])
        request=read(self.run/'PHYSICAL_REQUEST.json')
        require(request['source_manifest_sha256']==sha(self.run/'SOURCE.json'),'Physical request source differs')
        self.lock,self.capacity_lock=threading.RLock(),threading.Lock()
        self.capacity_token=threading.local();self.reserved=0;self.copied={}
        self.state=dict(schema='mhbs.p1sha_timing_refine.fixed_targets.v1',pid=os.getpid(),started_at=now(),
            complete=False,source_manifest_sha256=sha(self.run/'SOURCE.json'),targets=TARGETS,
            source_unchanged=None,p4_not_a_gate_for_p1=True,gate_policy='Per configuration: 3 Sign + diagnostic + same-source 36 functional groups',
            routes={c:dict(status='pending',target_frequency_mhz=150 if parts(c)[2]==1 else 100) for c in TARGETS})

    def route(self,backend,p,u):
        config=f'{backend}/P{p}U{u}'
        while True:
            status=point_status(self.run,config)
            if status['failed']:
                self.update('routes',config,status='validation_failed',error='; '.join(status['failed']))
                return
            if status['ready']:break
            self.update('routes',config,status='waiting_for_validation',pending_gate_items=status['pending'])
            time.sleep(15)
        try:proof=validate_point(self.run,config)
        except Exception as error:
            self.update('routes',config,status='validation_failed',error=str(error));return
        self.update('routes',config,gate=proof,pending_gate_items=[])
        self.capacity_token.worker_marker=str(self.run/'jobs'/config)
        try:return super().route(backend,p,u)
        finally:self.release_capacity()

    def publish(self):
        physical_helpers.PhysicalRunner.publish(self)
        prefix=self.out/'reports'/('P1_SHA_Fixed_Targets_'+self.meta['run_id'])
        text=prefix.with_suffix('.md').read_text()
        text=text.replace('全部18个目标完整Sign、六点100MHz诊断和36组冻结源功能验证通过后才启动。',
            '每配置自己的3项完整Sign、100MHz诊断和同源36组功能验证通过后单独启动；SHA2P4慢点不阻塞P1。')
        text=text.replace('附加P12U1诊断不阻塞本物理阶段，物理状态独立写PHYSICAL_STATUS.json。',
            '本轮不运行P12Vivado，物理状态独立写PHYSICAL_STATUS.json。')
        text=text.replace('基线六点原目标均未闭合，不能从负WNS外推基线频率或布线ATP。',
            '本轮基线为C3，其仍在后台的物理结果单列；未闭合点不从负WNS外推Fmax或ATP。')
        archive.atomic(prefix.with_suffix('.md'),text)
        artifact=self.out/'PHYSICAL_ARTIFACTS.json'
        if artifact.is_file():
            proof=read(artifact);proof['sha256'][str(prefix.with_suffix('.md').relative_to(self.out))]=sha(prefix.with_suffix('.md'));write(artifact,proof)
        refine.publish_family()

    def execute(self):
        self.publish();archive.index()
        # P1 submissions precede both P4 submissions. Waiting for one P4 gate
        # cannot consume a worker needed to submit a ready P1 configuration.
        with ThreadPoolExecutor(max_workers=3) as pool:
            jobs=[pool.submit(self.route,*parts(config)) for config in TARGETS]
            for job in as_completed(jobs):job.result()
        self.state.update(complete=True,source_unchanged=self.unchanged(),finished_at=now())
        self.publish();archive.index()
        return 0


def launch_physical(run):
    require(not (run/'PHYSICAL_LAUNCH.json').exists(),'Physical phase already launched')
    meta=read(run/'SOURCE.json');out=Path(meta['archive_directory'])
    controls=('coordinate_p1sha_timing_refine.py',*refine.CONTROLS)
    budget=FAMILY/'ROUTE_BUDGET.json'
    with budget.with_suffix('.lock').open('a+') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX);entries=read(budget) if budget.exists() else []
        require(len(entries)<2,'At most two source candidates are authorized')
        entries.append(dict(run_root=str(run),source_manifest_sha256=sha(run/'SOURCE.json'),configs=TARGETS));write(budget,entries)
    for name in controls:
        for base in (run,out):archive.copy_changed(ROOT/'scripts'/name,base/'refine_physical_control'/name)
    request=dict(source_manifest_sha256=sha(run/'SOURCE.json'),requested_at=now(),configs=TARGETS,
        targets_by_unroll={'1':150,'2':100},per_configuration_gate=True,p4_does_not_block_p1=True,
        explicit_user_authorization=True,frequency_search=False,automatic_frequency_fallback=False,
        controls_sha256={n:sha(run/'refine_physical_control'/n) for n in controls})
    for base in (run,out):write(base/'PHYSICAL_REQUEST.json',request)
    with (run/'physical_runner.log').open('w') as stream:
        process=subprocess.Popen([sys.executable,str(run/'refine_physical_control/coordinate_p1sha_timing_refine.py'),
            '--physical-run',str(run)],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,
            env=dict(os.environ,MHBS_P1SHA_REFINE_WORKSPACE=str(ROOT),MHBS_P1SHA_WORKSPACE=str(ROOT)),start_new_session=True)
    request['pid']=process.pid
    for base in (run,out):write(base/'PHYSICAL_LAUNCH.json',request)
    return request


def choose(candidates):
    """Never average away a bad backend/P/U point.

    Exclude a candidate only when both candidates have all six diagnostics and
    it is weakly worse on every algorithm's assumed ATP and every diagnostic
    path, with at least one strict inequality. Missing P4 evidence preserves
    both candidates within the two-source budget, rather than delaying P1.
    """
    details=[]
    for run in candidates:
        state=read(run/'status.json');points={}
        for config in TARGETS:
            syn=state['synthesis'][config]
            if syn['status']!='passed':continue
            points[config]=dict(area=syn['area']['equivalent_slice'],diagnostic_path_ns=syn['timing']['data_path_ns'],
                cycles={p:state['tests'][config+'/'+p].get('cycles') for p in dual.PROFILES})
        details.append(dict(run_root=str(run),label=state['label'],points=points))
    selected=list(candidates);reason='Keep both: preserve per-backend/P/U tradeoffs and do not wait for missing P4 diagnostics'
    if len(details)==2 and all(len(d['points'])==len(TARGETS) for d in details):
        def dominates(a,b):
            ratios=[]
            for config in TARGETS:
                x,y=a['points'][config],b['points'][config]
                ratios.append(x['diagnostic_path_ns']/y['diagnostic_path_ns'])
                for profile in dual.PROFILES:
                    if x['cycles'][profile] is None or y['cycles'][profile] is None:return False
                    ratios.append(x['area']*x['cycles'][profile]/(y['area']*y['cycles'][profile]))
            return all(r<=1 for r in ratios) and any(r<1 for r in ratios)
        for a,b in ((details[0],details[1]),(details[1],details[0])):
            if dominates(a,b):
                selected=[Path(a['run_root'])];reason='One candidate dominates on every backend/P/U, all three assumed ATPs, and every diagnostic path'
    require(len(selected)<=2,'Candidate budget exceeded')
    return selected,dict(reason=reason,per_point_metrics=details,geometric_mean_not_used=True,diagnostic_delay_is_not_fmax=True)


def coordinate():
    state=dict(schema='mhbs.p1sha_timing_refine.coordinator.v1',pid=os.getpid(),started_at=now(),complete=False,
        phase='waiting_for_p1',runs=RUNS,selected=[],targets=TARGETS)
    while True:
        state['readiness']={name:{c:point_status(FAMILY/name,c) for c in TARGETS} for name in RUNS}
        if not state['selected']:
            pending=False;eligible=[]
            for name in RUNS:
                p1=[state['readiness'][name][c] for c in P1_TARGETS]
                if any(p['failed'] for p in p1):continue
                if all(p['ready'] for p in p1):eligible.append(FAMILY/name)
                else:pending=True
            if not pending:
                require(eligible,'Both candidates failed P1 gates')
                for run in eligible:
                    for config in P1_TARGETS:validate_point(run,config)
                selected,policy=choose(eligible)
                state.update(selected=[str(r) for r in selected],selection_policy=policy,phase='fixed_target_routes')
                for run in selected:launch_physical(run)
        if state['selected']:
            state['physical']={}
            for name in state['selected']:
                path=Path(name)/'PHYSICAL_STATUS.json'
                state['physical'][Path(name).name]=read(path) if path.exists() else dict(complete=False)
            if all(p.get('complete') for p in state['physical'].values()):
                state.update(complete=True,phase='complete',finished_at=now())
        state['updated_at']=now()
        for base in (FAMILY,OUT):write(base/'COORDINATOR_STATUS.json',state)
        write(PREFIX.with_suffix('.json'),state)
        lines=['# C3基础 D1／D2 最终固定频率协调','',
            f'更新时间：{state["updated_at"]}；PID：{state["pid"]}；阶段：`{state["phase"]}`。','',
            '四个P1配置就绪后确定最多两份候选。每配置仅等待自身3个完整Sign、对应100MHz common诊断和'
            '同源码36组功能验证；SHA2P4异常慢点保留后台，不阻塞P1路由。'
            'U1固定150MHz、U2固定100MHz，最多两份源码各六点。不搜索、降频或新增时序例外。','',
            '按各后端、各P/U、三个算法逐项比较假定ATP与诊断路径；不使用均值掩盖坏点。'
            '只有六点证据齐全且一候选各项都被另一候选支配时才排除；P4证据未齐时保留两份并先跑P1。'
            '诊断路径不代表Fmax，最终只按真实STA和布线ATP作结论。','',
            '| 候选 | 配置 | 就绪 | 待完成 | 失败 |','|---|---|---|---:|---:|']
        for name,points in state['readiness'].items():
            for config,status in points.items():
                lines.append(f'| {name} | {config} | {status["ready"]} | {len(status["pending"])} | {len(status["failed"])} |')
        if state['selected']:
            lines += ['',state['selection_policy']['reason'],'']
            for name in state['selected']:
                run=Path(name);meta=read(run/'SOURCE.json');report=Path(meta['archive_directory'])/'reports'/('P1_SHA_Fixed_Targets_'+meta['run_id']+'.md')
                lines += [f'- [{meta["label"]}]({report.relative_to(ROOT)})：`{sha(run/"SOURCE.json")}`。']
        lines += ['', '跨进程预约共享旧任务锁，统计顶层job（wrapper/实际进程去重，忽略SYNTH_DESIGN_PARENT内部worker），'
            '全机最多12个Vivado，每个2线程。旧矩阵和旧协调器保留，不修改生产RTL。','']
        archive.atomic(PREFIX.with_suffix('.md'),'\n'.join(lines));refine.publish_family()
        if state['complete']:
            subprocess.run([sys.executable,str(ROOT/'scripts/audit_p1sha_timing_refine.py')],cwd=ROOT,check=True)
            archive.index();return
        time.sleep(15)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--launch',action='store_true');mode.add_argument('--run',action='store_true');mode.add_argument('--physical-run',type=Path)
    args=parser.parse_args()
    if args.physical_run:raise SystemExit(PhysicalRunner(args.physical_run).execute())
    if args.launch:
        require(not (FAMILY/'COORDINATOR_LAUNCH.json').exists(),'Coordinator already launched')
        controls=('coordinate_p1sha_timing_refine.py',*refine.CONTROLS)
        for name in controls:
            for base in (BASELINE,OUT):archive.copy_changed(ROOT/'scripts'/name,base/'automation_control'/name)
        control=BASELINE/'automation_control/coordinate_p1sha_timing_refine.py'
        with (FAMILY/'coordinator.log').open('w') as stream:
            process=subprocess.Popen([sys.executable,str(control),'--run'],cwd=ROOT,stdin=subprocess.DEVNULL,
                stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,
                env=dict(os.environ,MHBS_P1SHA_REFINE_WORKSPACE=str(ROOT),MHBS_P1SHA_WORKSPACE=str(ROOT)))
        value=dict(pid=process.pid,report=str(PREFIX.with_suffix('.md')),source_sha256=sha(control),
            controls_sha256={n:sha(BASELINE/'automation_control'/n) for n in controls})
        for base in (FAMILY,OUT):write(base/'COORDINATOR_LAUNCH.json',value)
        print(json.dumps(value,indent=2))
    else:coordinate()
