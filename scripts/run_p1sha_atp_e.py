#!/usr/bin/env python3
"""Lightweight E-round measurement: one primary, at most one targeted repair.

Reuse D1/D2/C3 measured evidence without mixing sources. D1 is the primary area
comparison. Cycle changes are allowed; output/cache bytes, vectors and Hash/
compression workload must match. Routing remains a separate per-point action.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import fcntl
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
import run_p1sha_atp_optimization as previous
import run_p1sha_timing_refine as shared
import coordinate_p1sha_timing_refine as point_route

ROOT=shared.ROOT
FAMILY=ROOT/'build/p1sha_atp_e'
BASELINE=FAMILY/'baseline_20261021_221413'
BASELINE_SHA='955e06922499b2cf80232dc719251bb4339712dbbe497d561017fe553af67fa9'
REFERENCES={'D1':ROOT/'build/p1sha_timing_refine/candidate_20261021_214504',
            'D2':ROOT/'build/p1sha_timing_refine/candidate_20261021_215634',
            'C3':ROOT/'build/p1sha_atp_optimization/candidate_20261021_203556'}
TARGETS=shared.TARGETS
CONTROLS=('run_p1sha_atp_e.py','coordinate_p1sha_timing_refine.py',*shared.CONTROLS)
read,write,sha,require,now,parts=shared.read,shared.write,shared.sha,shared.require,shared.now,shared.parts


def checked_reference(run):
    meta,state=read(run/'SOURCE.json'),read(run/'status.json');manifest=sha(run/'SOURCE.json')
    require(previous.unchanged(meta) and state['complete'] and state['source_unchanged'],'Reference incomplete/changed')
    for config in TARGETS:
        syn=state['synthesis'][config]
        require(syn['status']=='passed' and syn['source_unchanged'] and syn['source_manifest_sha256']==manifest,'Diagnostic source differs')
        for name,wanted in syn['reports_sha256'].items():require(sha(run/'synth'/config/name)==wanted,'Diagnostic reference changed')
        for profile in dual.PROFILES:
            test=state['tests'][config+'/'+profile]
            require(test['status']=='passed' and test['source_unchanged']
                and test['source_manifest_sha256']==manifest and test['output_and_signature_cache_checked_bytewise'],
                'Reference Sign source/output differs')
            for field in ('log','raw_log'):require(sha(test[field])==test[field+'_sha256'],'Reference Sign log changed')
    proof=read(run/'functional_validation/VALIDATION.json')
    require(proof['complete'] and proof['passed']==36 and not proof['failed'] and proof['source_unchanged']
        and proof['source_manifest_sha256']==manifest,'Reference functional proof differs')
    return dict(reference_run=str(run),source_manifest_sha256=manifest,checked_at=now(),
        tests={c+'/'+p:state['tests'][c+'/'+p] for c in TARGETS for p in dual.PROFILES},
        synthesis={c:state['synthesis'][c] for c in TARGETS},functional=proof,
        source_inputs_checked=True,actual_logs_and_reports_checked=True)


def freeze_controls(run,out,folder='control'):
    for name in CONTROLS:
        for base in (run,out):archive.copy_changed(ROOT/'scripts'/name,base/folder/name)
    checks={n:sha(run/folder/n) for n in CONTROLS}
    for base in (run,out):write(base/(folder.upper()+'_SOURCE.json'),checks)


class Runner(shared.Runner):
    def __init__(self,run):
        self.run=Path(run).resolve();self.meta=dict(read(self.run/'SOURCE.json'),**read(self.run/'EXPERIMENT.json'))
        require(self.meta['experiment_family']=='p1sha_atp_e','Wrong E experiment')
        self.source,self.out=Path(self.meta['source_root']),Path(self.meta['archive_directory'])
        self.base=read(self.run/'D1_EVIDENCE.json');self.configs=TARGETS
        self.lock,self.capacity_lock=threading.RLock(),threading.Lock();self.capacity_token=threading.local()
        self.reserved=0;self.copied={};self.checksums={};self.routes_only=False;self.continuing=False
        self.state=dict(schema='mhbs.p1sha_atp_e.results.v1',label=self.meta['label'],pid=os.getpid(),started_at=now(),
            complete=False,source_manifest_sha256=sha(self.run/'SOURCE.json'),
            tests={c+'/'+p:dict(status='pending') for c in TARGETS for p in dual.PROFILES},
            synthesis={c:dict(status='pending') for c in TARGETS},routing={})


class PhysicalRunner(point_route.PhysicalRunner):
    def publish(self):
        super().publish()
        prefix=self.out/'reports'/('P1_SHA_Fixed_Targets_'+self.meta['run_id'])
        text=prefix.with_suffix('.md').read_text().replace('本轮基线为C3，其仍在后台的物理结果单列；',
            'E轮主基线为D1，D2/C3作为独立参考源码单列；')
        archive.atomic(prefix.with_suffix('.md'),text)
        artifact=self.out/'PHYSICAL_ARTIFACTS.json'
        if artifact.is_file():
            proof=read(artifact);proof['sha256'][str(prefix.with_suffix('.md').relative_to(self.out))]=sha(prefix.with_suffix('.md'));write(artifact,proof)


def publish_family():
    out=Path(read(BASELINE/'SOURCE.json')['archive_directory']);prefix=out/'reports/P1_SHA_ATP_E_20261021'
    references=read(BASELINE/'REFERENCES.json');candidates=[];withdrawn=[]
    for manifest in sorted(FAMILY.glob('candidate_*/SOURCE.json')):
        run=manifest.parent
        if (run/'DISPOSITION.json').exists():
            disposition=read(run/'DISPOSITION.json')
            require(disposition['status']=='withdrawn_before_synthesis' and not disposition['vivado_started']
                and not disposition['route_requested'] and disposition['source_manifest_sha256']==sha(manifest),
                'Unsupported/changed withdrawn precursor')
            withdrawn.append(dict(run_root=str(run),source=read(manifest),disposition=disposition))
            continue
        if not (run/'status.json').exists():continue
        candidates.append(dict(run_root=str(run),source=read(manifest),source_manifest_sha256=sha(manifest),
            results=read(run/'status.json'),physical=read(run/'PHYSICAL_STATUS.json') if (run/'PHYSICAL_STATUS.json').exists() else None))
    reference_physical={}
    for label,reference in references.items():
        path=Path(reference['reference_run'])/'PHYSICAL_STATUS.json'
        if path.exists():
            status=read(path)
            require(status['source_manifest_sha256']==reference['source_manifest_sha256'],'Reference physical source differs')
            reference_physical[label]=status
    closed=[]
    for label,physical in reference_physical.items():
        for config,job in physical['routes'].items():
            if config not in TARGETS or not job.get('meets_target') or not job.get('source_unchanged'):continue
            period=job['result']['actual_period_ns'];area=job['routed_area']['equivalent_slice']
            for profile in dual.PROFILES:
                cycles=references[label]['tests'][config+'/'+profile]['cycles']
                closed.append(dict(source=label,source_manifest_sha256=references[label]['source_manifest_sha256'],
                    config=config,profile=profile,cycles=cycles,actual_frequency_mhz=1000/period,routed_equivalent_slice=area,
                    time_ms=cycles*period/1e6,atp_slice_ms=area*cycles*period/1e6,changes_vs_closed_reference_pct={}))
    reference_closed=list(closed)
    for candidate in candidates:
        for config,job in (candidate['physical'] or {}).get('routes',{}).items():
            if not job.get('meets_target') or not job.get('source_unchanged'):continue
            period=job['result']['actual_period_ns'];area=job['routed_area']['equivalent_slice']
            for profile in dual.PROFILES:
                cycles=candidate['results']['tests'][config+'/'+profile]['cycles'];atp=area*cycles*period/1e6
                closed.append(dict(source=candidate['results']['label'],source_manifest_sha256=candidate['source_manifest_sha256'],
                    config=config,profile=profile,cycles=cycles,actual_frequency_mhz=1000/period,routed_equivalent_slice=area,
                    time_ms=cycles*period/1e6,atp_slice_ms=atp,changes_vs_closed_reference_pct={ref['source']:100*(atp/ref['atp_slice_ms']-1)
                        for ref in reference_closed if ref['config']==config and ref['profile']==profile}))
    value=dict(updated_at=now(),baseline_manifest_sha256=BASELINE_SHA,primary_reference='D1',references=references,
        candidates=candidates,cycle_changes_allowed=True,same_output_cache_and_hash_workload_required=True,
        max_primary_candidates=1,max_targeted_repairs=1,mixed_source_area_frequency_cycles=False,
        reference_physical=reference_physical,closed_routed_atp=closed,withdrawn_precursors=withdrawn)
    write(prefix.with_suffix('.json'),value);fmt=lambda x:'—' if x is None else f'{x:,.3f}'
    lines=['# E轮：低面积执行路径与发送延迟优化','',f'更新时间：{value["updated_at"]}。','',
        '主对照为冻结D1，D2和C3另列完整实测证据；不混合不同源码的面积、周期或频率。'
        '仅一个主候选，若实测失败最多追加一次针对性修正。允许周期变化，但输出/签名缓存字节、向量及Hash/压缩工作量必须一致。','',
        '每候选18项完整Sign（SHAKE/SHA2的P1U1/P1U2及SHA2 P4U1/P4U2），六点100MHz common诊断，'
        '另执行同源36组正常/综合视图验证。100MHz只作面积与路径诊断，假定ATP按U1=150MHz/U2=100MHz。'
        '最终路由逐配置门禁，不等待异常P4点；同一配置三个Sign、对应诊断及同源36组功能通过后才可布线。'
        '最多两份源码各六个固定目标，不降频、不搜索、不新增时序例外。','',
        '器件xc7a200tffg1156-3，Vivado2025.2，common OOC、SYNTHESIS统计裁剪、默认时序驱动。'
        '全机顶层Vivado最多12、每个2线程；wrapper/实际进程去重，忽略内部SYNTH_DESIGN_PARENT worker，旧任务继续后台。'
        '等效Slice=LUT/4+FF/8+232.4×BRAM36+102.4×DSP。','']
    entries=[(label,reference['synthesis']) for label,reference in references.items()]
    entries += [(c['results']['label'],c['results']['synthesis']) for c in candidates]
    for backend in ('shake','sha2'):
        lines += [f'## {backend.upper()} common诊断面积','',
            '| 源码 | 配置 | LUT | FF | BRAM36 | 等效Slice | 相对D1% | 路径ns | 状态 |',
            '|---|---|---:|---:|---:|---:|---:|---:|---|']
        for label,synthesis in entries:
            for config,syn in synthesis.items():
                if not config.startswith(backend+'/'):continue
                area,path=syn.get('area',{}),syn.get('timing',{});base=references['D1']['synthesis'][config]['area']['equivalent_slice']
                delta=100*(area['equivalent_slice']/base-1) if syn['status']=='passed' else None
                lines.append('| '+' | '.join([label,config.split('/')[1],*[fmt(area.get(n)) for n in
                    ('lut','ff','bram36','equivalent_slice')],fmt(delta),fmt(path.get('data_path_ns')),
                    syn['status']+('；analysis_deferred，后台继续' if syn.get('analysis_deferred') else '')])+' |')
        lines.append('')
    for profile in dual.PROFILES:
        lines += [f'## {profile} 完整Sign','',
            '| 候选 | 后端／配置 | 周期 | D1周期 | 周期变化% | 假设时间ms | 假设ATP | 比D1% | 比D2% | 比C3% | 实际MHz | 布线ATP | 状态 |',
            '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|']
        for c in candidates:
            for row in c['results']['rows']:
                if row['profile']!=profile:continue
                deltas=[]
                for ref in references.values():
                    key=row['config']+'/'+profile;old=ref['tests'][key];area=ref['synthesis'][row['config']]['area']['equivalent_slice']
                    deltas.append(None if row['diagnostic_atp'] is None else 100*(row['diagnostic_atp']/(area*old['cycles']/(row['target_mhz']*1000))-1))
                physical=(c['physical'] or {}).get('routes',{}).get(row['config'],{});mhz,atp=None,None
                if physical.get('meets_target') and physical.get('source_unchanged') and row['status']=='passed':
                    period=physical['result']['actual_period_ns'];mhz=1000/period;atp=physical['routed_area']['equivalent_slice']*row['cycles']*period/1e6
                lines.append('| '+' | '.join([c['results']['label'],row['config'],fmt(row['cycles']),fmt(row['baseline_cycles']),
                    fmt(row.get('cycles_change_pct')),fmt(row.get('assumed_target_time_ms')),fmt(row['diagnostic_atp']),
                    *map(fmt,deltas),fmt(mhz),fmt(atp),row['status']])+' |')
        lines.append('')
    lines += ['## 指定频率物理证据','',
        '| 源码 | 配置 | 目标MHz | 布线Slice | WNS ns | WHS ns | 状态 |','|---|---|---:|---:|---:|---:|---|']
    physical_entries=[]
    for label,ref in references.items():
        p=Path(ref['reference_run'])/'PHYSICAL_STATUS.json'
        if p.exists():physical_entries.append((label,read(p)))
    physical_entries += [(c['results']['label'],c['physical']) for c in candidates]
    for label,physical in physical_entries:
        for config,job in (physical or {}).get('routes',{}).items():
            timing=job.get('result',{});area=job.get('routed_area',{})
            lines.append('| '+' | '.join([label,config,fmt(job.get('target_frequency_mhz')),fmt(area.get('equivalent_slice')),
                fmt(timing.get('wns_ns')),fmt(timing.get('whs_ns')),job['status']])+' |')
    if closed:
        lines += ['', '## 闭合频率下的实际ATP比较','',
            '每行严格使用该源码自己的Sign周期、布线面积和闭合时钟。负WNS点不填写实际ATP；'
            '只有相同配置与算法且两份源码均闭合时才填写净变化。D1为主对照，D2/C3各自独立。','',
            '| 源码 | 配置 | Sign | 实际MHz | 布线Slice | 时间ms | ATP Slice·ms | 比D1% | 比D2% | 比C3% |',
            '|---|---|---|---:|---:|---:|---:|---:|---:|---:|']
        for row in closed:
            changes=row['changes_vs_closed_reference_pct']
            lines.append('| '+' | '.join([row['source'],row['config'],row['profile'],fmt(row['actual_frequency_mhz']),
                fmt(row['routed_equivalent_slice']),fmt(row['time_ms']),fmt(row['atp_slice_ms']),
                *[fmt(changes.get(label)) for label in references]])+' |')
    lines += ['', 'SHA2 P1的非轮运算上界余量约10%（U1）/18%（U2），来自实测压缩次数与理论最少轮周期比较，'
        '不是FSM状态耗时实测。四拍BUILD不能直接乘压缩次数声称净收益，最终以完整Sign周期和实际STA为准。','',
        '每候选归档冻结RTL/support、分层/时序、源码/控制器SHA和Vivado日志；详细仿真/验证日志留运行目录。'
        '只生成Markdown/JSON，不归档README/CSV，不执行h20完整Keygen/Sign。','']
    if withdrawn:
        lines += ['## 撤回的冻结前驱','',
            '以下快照因冻结授权与随后修正消息交叉，在启动综合前撤回。原目录、冻结源码及已启动的仿真日志保留；'
            '不计入最终候选、已完成Sign总数或物理预算，也不记作验证通过。','',
            '| 运行目录 | SOURCE SHA256 | 原因 |','|---|---|---|']
        for item in withdrawn:
            lines.append('| '+item['run_root']+' | '+item['disposition']['source_manifest_sha256']+' | '+
                item['disposition']['reason']+' |')
        lines.append('')
    archive.atomic(prefix.with_suffix('.md'),'\n'.join(lines))


# Only this process's callback changes. No prior controller file or running
# interpreter is modified; common synthesis/simulation methods are reused.
shared.publish_family=publish_family


def prepare_baseline():
    require(sha(BASELINE/'SOURCE.json')==BASELINE_SHA,'Wrong E baseline')
    refs={label:checked_reference(run) for label,run in REFERENCES.items()};meta=read(BASELINE/'SOURCE.json');out=Path(meta['archive_directory'])
    for base in (BASELINE,out):
        write(base/'REFERENCES.json',refs);write(base/'D1_EVIDENCE.json',refs['D1'])
        write(base/'C3_EVIDENCE.json',refs['C3'])
    for label,reference in refs.items():
        run=Path(reference['reference_run']);old=read(run/'SOURCE.json');original_out=Path(old['archive_directory'])
        for name in ('SOURCE.json','rtl.tar.gz','RTL_SOURCE.json','support.tar.gz','SUPPORT_SOURCE.json'):
            archive.copy_changed(original_out/name,out/'reference_sources'/label/name)
        for config in TARGETS:
            for p in (run/'synth'/config).iterdir():
                if p.is_file() and p.suffix in ('.rpt','.log','.txt','.xdc'):
                    archive.copy_changed(p,out/'reference_sources'/label/'synth'/config/p.name)
    previous.pack_support(Path(meta['source_root']),out,meta['sha256']);freeze_controls(BASELINE,out)
    publish_family();archive.index();print(json.dumps(dict(baseline=str(BASELINE),source_manifest_sha256=BASELINE_SHA,
        report=str(out/'reports/P1_SHA_ATP_E_20261021.md'),top_level_vivado_jobs=len(shared.live_top_jobs())),indent=2))


def launch(args):
    require(len([p for p in FAMILY.glob('candidate_*/SOURCE.json') if not (p.parent/'DISPOSITION.json').exists()])<2,
        'E allows one primary and one targeted repair only')
    require((BASELINE/'REFERENCES.json').exists(),'Prepare E references first')
    stamp=datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y%m%d_%H%M%S');run=FAMILY/('candidate_'+stamp)
    out=archive.ARCHIVES/('p1sha_atp_e_candidate_'+stamp);checks=dual.frozen_snapshot(ROOT,run/'source')
    meta=dict(schema='mhbs.p1sha_atp.source.v1',experiment_family='p1sha_atp_e',kind='candidate',label=args.label,
        run_id=stamp,started_at=now(),source_root=str(run/'source'),archive_directory=str(out),sha256=checks,
        rtl_files=read(BASELINE/'SOURCE.json')['rtl_files'],baseline_manifest_sha256=BASELINE_SHA,
        primary_reference_manifest_sha256=read(BASELINE/'D1_EVIDENCE.json')['source_manifest_sha256'])
    settings=dict(previous.tool_settings(),diagnostic_configs=TARGETS,configs=TARGETS,operation='sign',cycle_changes_allowed=True)
    for base in (run,out):
        write(base/'SOURCE.json',meta);write(base/'EXPERIMENT.json',settings)
        for name in ('REFERENCES.json','D1_EVIDENCE.json','C3_EVIDENCE.json'):archive.copy_changed(BASELINE/name,base/name)
    freeze_controls(run,out);archive.pack_rtl(run/'source',out/'rtl.tar.gz',checks);previous.pack_support(run/'source',out,checks)
    patch=subprocess.run(['diff','-ru',str(BASELINE/'source/rtl'),str(run/'source/rtl')],text=True,stdout=subprocess.PIPE)
    require(patch.returncode in (0,1),'Could not create E lineage');archive.atomic(out/'lineage/from_D1.patch',patch.stdout)
    with (run/'runner.log').open('w') as stream:
        process=subprocess.Popen([sys.executable,str(run/'control/run_p1sha_atp_e.py'),'--run-root',str(run)],cwd=ROOT,
            env=dict(os.environ,MHBS_P1SHA_REFINE_WORKSPACE=str(ROOT),MHBS_P1SHA_WORKSPACE=str(ROOT)),
            stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
    value=dict(pid=process.pid,root=str(run),source_manifest_sha256=sha(run/'SOURCE.json'),sign_tests=18,
        diagnostic_syntheses=6,cycle_changes_allowed=True,automatic_routing=False)
    write(run/'LAUNCH.json',value);print(json.dumps(value,indent=2))


def route_existing(run):
    run=Path(run).resolve();require(not (run/'PHYSICAL_LAUNCH.json').exists(),'Physical phase already exists')
    require(not (run/'DISPOSITION.json').exists(),'Withdrawn precursor cannot enter physical phase')
    meta=read(run/'SOURCE.json');out=Path(meta['archive_directory'])
    require(meta['experiment_family']=='p1sha_atp_e' and previous.unchanged(meta),'Wrong/changed E source')
    budget=FAMILY/'ROUTE_BUDGET.json'
    with budget.with_suffix('.lock').open('a+') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX);entries=read(budget) if budget.exists() else [];require(len(entries)<2,'E physical budget exceeded')
        entries.append(dict(run_root=str(run),source_manifest_sha256=sha(run/'SOURCE.json'),configs=TARGETS));write(budget,entries)
    freeze_controls(run,out,'physical_control')
    request=dict(source_manifest_sha256=sha(run/'SOURCE.json'),requested_at=now(),configs=TARGETS,
        explicit_user_authorization=True,per_configuration_gate=True,frequency_search=False,automatic_frequency_fallback=False)
    for base in (run,out):write(base/'PHYSICAL_REQUEST.json',request)
    with (run/'physical_runner.log').open('w') as stream:
        process=subprocess.Popen([sys.executable,str(run/'physical_control/run_p1sha_atp_e.py'),'--physical-run',str(run)],cwd=ROOT,
            env=dict(os.environ,MHBS_P1SHA_REFINE_WORKSPACE=str(ROOT),MHBS_P1SHA_WORKSPACE=str(ROOT)),
            stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
    request['pid']=process.pid
    for base in (run,out):write(base/'PHYSICAL_LAUNCH.json',request)
    print(json.dumps(request,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare-baseline',action='store_true');mode.add_argument('--launch-candidate',action='store_true')
    mode.add_argument('--run-root',type=Path);mode.add_argument('--physical-run',type=Path);mode.add_argument('--route-existing',type=Path)
    mode.add_argument('--watch',action='store_true');parser.add_argument('--label',default='E1_primary');args=parser.parse_args()
    if args.prepare_baseline:prepare_baseline()
    elif args.launch_candidate:launch(args)
    elif args.run_root:sys.exit(Runner(args.run_root).execute())
    elif args.physical_run:sys.exit(PhysicalRunner(args.physical_run).execute())
    elif args.route_existing:route_existing(args.route_existing)
    else:
        while True:publish_family();time.sleep(60)
