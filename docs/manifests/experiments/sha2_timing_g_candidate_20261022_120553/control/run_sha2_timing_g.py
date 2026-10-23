#!/usr/bin/env python3
"""SHA2 G: all 14 configurations must physically close at U1=150/U2=100 MHz.

Preparation freezes evidence only. Measurements and fixed-target routes require
separate explicit commands. Existing F/dual scripts and controllers are untouched;
their methods are reused only inside this process with frozen helper controls.
"""
import argparse
from copy import deepcopy
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

import run_sha2_timing_f as f

ROOT=Path(os.environ.get('MHBS_SHA2_G_WORKSPACE',f.ROOT)).resolve()
FAMILY=ROOT/'build/sha2_timing_g'
CONFIGS=f.ALL_CONFIGS
CONTROLS=('run_sha2_timing_g.py','route_sha2_hard_target.tcl',*f.CONTROLS)
read,write,sha,require,now=f.read,f.write,f.sha,f.require,f.now
original_report,original_inventory,original_rows=f.publish_report,f.inventory,f.rows
PRIORITY=('sha2/P12U2','sha2/P6U1','sha2/P12U1','sha2/P4U1','sha2/P4U2','sha2/P8U1','sha2/P1U1')


def reference_evidence():
    proof=f.reference_evidence(CONFIGS);meta=read(f.REFERENCE/'SOURCE.json');state=read(f.REFERENCE/'status.json')
    all_tests={}
    for key,test in state['tests'].items():
        require(test['status']=='passed' and test['source_unchanged']
            and test['source_manifest_sha256']==f.REFERENCE_SHA
            and test['output_and_signature_cache_checked_bytewise'],'Baseline Sign missing/unbound: '+key)
        for field in ('log','raw_log'):require(sha(test[field])==test[field+'_sha256'],'Baseline raw log changed')
        for name,wanted in test['vectors_sha256'].items():
            require(meta['sha256'][name]==sha(Path(meta['source_root'])/name)==wanted,'Baseline vectors changed')
        all_tests[key]=deepcopy(test)
    require(len(all_tests)==84,'Baseline must contain 84 executed SHAKE/SHA2 Sign tests')
    proof.update(all_baseline_sign_tests=all_tests,all_84_baseline_sign_tests_verified=True)
    return proof


def controls(run,out):
    for name in CONTROLS:
        for base in (run,out):f.archive.copy_changed(ROOT/'scripts'/name,base/'control'/name)
    provenance=dict(alias='control/route_common_target.tcl',selected_source='scripts/route_sha2_hard_target.tcl',
        selected_source_sha256=sha(ROOT/'scripts/route_sha2_hard_target.tcl'),
        upstream_source='scripts/route_common_target.tcl',upstream_source_sha256=sha(ROOT/'scripts/route_common_target.tcl'),
        reason='G-only hard frequency: 150MHz uses 6.666ns; zero acceptance tolerance; old Tcl remains untouched.')
    for base in (run,out):
        f.archive.copy_changed(ROOT/'scripts/route_common_target.tcl',base/'control/upstream_route_common_target.tcl')
        f.archive.copy_changed(ROOT/'scripts/route_sha2_hard_target.tcl',base/'control/route_common_target.tcl')
        write(base/'ALIAS_PROVENANCE.json',provenance)
        write(base/'CONTROL_SOURCE.json',{name:sha(run/'control'/name) for name in (*CONTROLS,'upstream_route_common_target.tcl')})


def import_baseline_diagnostics(run,meta,state):
    """Import equal diagnostic inputs, never substitute another P/U's area."""
    native_runs=(ROOT/'build/sha2_timing_f/baseline_20261022_100516',
                 ROOT/'build/p1sha_atp_e/candidate_20261021_223449')
    names=meta['rtl_files']+['sources.txt','scripts/diagnose_timing.tcl'];source=Path(meta['source_root'])
    out=Path(meta['archive_directory']);imports={}
    for native in native_runs:
        old,results=read(native/'SOURCE.json'),read(native/'status.json');native_source=Path(old['source_root'])
        require(f.shared.unchanged(old),'Native diagnostic source changed')
        require(all(meta['sha256'][n]==old['sha256'][n]==sha(source/n)==sha(native_source/n) for n in names),
            'Diagnostic RTL/Tcl input mismatch')
        require(sha(run/'control/diagnose_timing.tcl')==meta['sha256']['scripts/diagnose_timing.tcl'],'Current diagnostic Tcl differs')
        for config,item in results['synthesis'].items():
            if config not in CONFIGS or config in imports or item['status']!='passed':continue
            require(item['source_unchanged'] and item['source_manifest_sha256']==sha(native/'SOURCE.json'),
                'Native diagnostic source binding differs')
            directory=native/'synth'/config;settings=(directory/'settings.txt').read_text().splitlines()
            require(all(line in settings for line in ('period_ns=10.0','threads=2','top=common','hash_backend=sha2',
                'part=xc7a200tffg1156-3','timing_driven=default','new_timing_exceptions=none','vivado=2025.2')),
                'Native diagnostic settings differ')
            for name,wanted in item['reports_sha256'].items():
                require(sha(directory/name)==wanted,'Native diagnostic report changed')
                for base in (run,out):f.archive.copy_changed(directory/name,base/'synth'/config/name)
            result=deepcopy(item)
            result.update(source_manifest_sha256=sha(run/'SOURCE.json'),source_unchanged=True,
                reused_native_source_manifest_sha256=sha(native/'SOURCE.json'),reused_from=str(directory),
                earlier_provenance=deepcopy(item),equivalent_diagnostic_inputs={n:meta['sha256'][n] for n in names},
                evidence_kind='reused_exact_RTL_Tcl_tool_and_clock_inputs',no_new_synthesis_run=True)
            imports[config]=state['synthesis'][config]=result
        f.archive.copy_changed(native/'SOURCE.json',out/'native_diagnostic_sources'/native.name/'SOURCE.json')
    proof=dict(active_inputs_verified=True,whole_source_manifests_are_distinct=True,
        imported_configurations=list(imports),missing_configurations=[c for c in CONFIGS if c not in imports],
        missing_values_are_not_substituted=True,configurations=imports)
    for base in (run,out):write(base/'DIAGNOSTIC_REUSE.json',proof)


def strict_goal(run,physical):
    meta,state=read(run/'SOURCE.json'),read(run/'status.json');proof=f.functional(run);routes=(physical or {}).get('routes',{})
    manifest=sha(run/'SOURCE.json');closed=[];pending=[];failed=[]
    for config in CONFIGS:
        item=routes.get(config,{})
        timing=item.get('result',{});target=150 if f.parts(config)[2]==1 else 100
        hard=bool(timing.get('setup_hold_met') and timing.get('drc_errors')==0
            and item.get('route_status',{}).get('passed') and timing.get('actual_period_ns',float('inf'))<=1000/target)
        if (hard and item.get('status')=='passed' and item.get('meets_target') and item.get('source_unchanged')
                and (physical or {}).get('source_manifest_sha256')==manifest):closed.append(config)
        elif item.get('status') in ('passed','target_not_met','validation_failed','error','failed'):failed.append(config)
        else:pending.append(config)
    sign_pass=(len(state['tests'])==42 and all(x['status']=='passed' and x['source_unchanged']
        and x['source_manifest_sha256']==manifest for x in state['tests'].values())) if meta['kind']=='candidate' else False
    functional_pass=bool(proof and proof.get('complete') and proof['source_manifest_sha256']==manifest
        and proof['source_unchanged'] and proof['passed']==proof['total_planned']==36 and not proof['failed'])
    met=bool(meta['kind']=='candidate' and len(closed)==14 and sign_pass and functional_pass and f.shared.unchanged(meta))
    return dict(goal='All 14 SHA2 configurations physically close at U1=150MHz/U2=100MHz',required_routes=14,
        closed_count=len(closed),closed=closed,pending=pending,failed=failed,all_42_sign_passed=sign_pass,
        same_source_36_functional_passed=functional_pass,goal_met=met,
        status='passed' if met else 'target_not_met' if failed else 'pending',
        low_frequency_diagnostics_never_count_as_frequency_acceptance=True,cycle_equality_not_required=True,
        actual_frequency_must_be_at_least_target=True,clock_period_quantization_tolerance_ns=0)


def hard_rows(run):
    rows=original_rows(run);reference=read(f.REFERENCE/'status.json')['routes']
    for row in rows:
        native=reference[row['config']];timing=native.get('result',{})
        hard=bool(native.get('meets_target') and native.get('source_unchanged') and timing.get('setup_hold_met')
            and timing.get('drc_errors')==0 and native.get('route_status',{}).get('passed')
            and timing.get('actual_period_ns',float('inf'))<=1000/row['target_mhz'])
        row.update(baseline_hard_frequency_met=hard,baseline_historical_nominal_only=bool(native.get('meets_target') and not hard))
        if not hard:row.update(baseline_routed_atp_slice_ms=None,routed_atp_change_pct=None)
        if row['actual_mhz'] is not None and row['actual_mhz']<row['target_mhz']:
            row.update(routed_atp_slice_ms=None,routed_atp_change_pct=None,rank=None)
    for profile in f.dual.PROFILES:
        ranked=sorted((r for r in rows if r['profile']==profile and r['routed_atp_slice_ms'] is not None),
            key=lambda r:r['routed_atp_slice_ms'])
        for rank,row in enumerate(ranked,1):row['rank']=rank
    return rows


def publish_report(run):
    run=Path(run);meta=read(run/'SOURCE.json');out=Path(meta['archive_directory'])
    # Serialise new G report producers; the frozen F helper remains untouched.
    with (run/'G_REPORT.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX);original_report(run)
        old=out/'reports'/('SHA2_Timing_F_'+meta['run_id']);new=out/'reports'/('SHA2_Timing_G_'+meta['run_id'])
        value=read(old.with_suffix('.json'));goal=strict_goal(run,value['physical'])
        value.update(experiment_family='sha2_timing_g',strict_acceptance=goal,all_14_configs_required=True)
        for config,item in value['baseline_physical'].items():
            period=item.get('result',{}).get('actual_period_ns',float('inf'));target=150 if f.parts(config)[2]==1 else 100
            item['historical_nominal_reference_only']=bool(item.get('meets_target') and period>1000/target)
        write(new.with_suffix('.json'),value)
        text=old.with_suffix('.md').read_text().replace('# SHA2 F轮时序、面积与ATP','# SHA2 G轮：14点严格频率验收')
        text=text.replace('候选：',f'严格目标状态：**{goal["status"]}**；实际闭合 **{goal["closed_count"]}/14**。'
            '全部14点均需在U1=150MHz、U2=100MHz完成实际布线/setup/hold/DRC检查；100MHz诊断不能替代验收。\n\n候选：',1)
        text+='\n缺失的基线100MHz面积保持空白；不使用其他配置或当前源码替代历史证据。'
        text+='周期允许改变，实际Sign周期计入ATP；不要求与E2周期相等。\n'
        text+='G硬频率采用1ps向下量化：150MHz写6.666ns、100MHz写10.000ns；'
        text+='实际周期必须≤1000/目标MHz，验收容差为零。旧6.667ns记录仅为历史标称参考，不算150MHz硬通过。\n'
        text=text.replace('| 基线E2 |','| 基线E2（历史参考） |')
        for config,item in value['baseline_physical'].items():
            if item['historical_nominal_reference_only']:
                text='\n'.join(line.replace('| passed |','| historical_nominal_only |')
                    if line.startswith('| 基线E2（历史参考） | '+config+' |') else line for line in text.split('\n'))
        f.archive.atomic(new.with_suffix('.md'),text)
        for path in (old.with_suffix('.md'),old.with_suffix('.json')):path.unlink()
        for base in (run,out):write(base/'GOAL_STATUS.json',goal)


def inventory(run):
    original_inventory(run)


# Only this new interpreter's callback bindings change. No old controller does.
f.publish_report=publish_report
f.inventory=inventory
f.rows=hard_rows


def freeze(kind,label,baseline=None):
    reference=reference_evidence()
    if baseline:
        previous=read(baseline/'SOURCE.json');require(previous['kind']=='baseline'
            and previous['experiment_family']=='sha2_timing_g' and tuple(previous['configs'])==CONFIGS
            and f.shared.unchanged(previous),'Wrong/changed G baseline')
    stamp=datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y%m%d_%H%M%S')
    run=FAMILY/(kind+'_'+stamp);out=f.archive.ARCHIVES/('sha2_timing_g_'+kind+'_'+stamp)
    source=Path(read(f.REFERENCE/'SOURCE.json')['source_root']) if kind=='baseline' else ROOT
    checks=f.dual.frozen_snapshot(source,run/'source');rtl=[n for n in (run/'source/sources.txt').read_text().splitlines() if n.strip()]
    meta=dict(schema='mhbs.p1sha_atp.source.v1',experiment_family='sha2_timing_g',kind=kind,label=label,run_id=stamp,
        started_at=now(),source_root=str(run/'source'),archive_directory=str(out),sha256=checks,rtl_files=rtl,
        configs=list(CONFIGS),reference_manifest_sha256=f.REFERENCE_SHA,baseline_run=str(baseline.resolve()) if baseline else None)
    settings=dict(f.shared.tool_settings(),vivado_workers=3,configs=list(CONFIGS),operation='sign',cycle_changes_allowed=True,
        mandatory_actual_frequency_all_14=True)
    for base in (run,out):
        write(base/'SOURCE.json',meta);write(base/'EXPERIMENT.json',settings);write(base/'REFERENCE_EVIDENCE.json',reference)
    controls(run,out);f.archive.pack_rtl(run/'source',out/'rtl.tar.gz',checks);f.shared.pack_support(run/'source',out,checks)
    state=dict(schema='mhbs.sha2_timing_g.results.v1',label=label,pid=None,complete=False,measurement_started=False,
        source_manifest_sha256=sha(run/'SOURCE.json'),tests=deepcopy(reference['tests']) if kind=='baseline' else
        {c+'/'+p:dict(status='pending') for c in CONFIGS for p in f.dual.PROFILES},
        synthesis={c:dict(status='not_measured' if kind=='baseline' else 'pending') for c in CONFIGS})
    if kind=='baseline':import_baseline_diagnostics(run,meta,state)
    else:
        delta=subprocess.run(['diff','-ru',str(Path(read(f.REFERENCE/'SOURCE.json')['source_root'])/'rtl'),str(run/'source/rtl')],
            text=True,stdout=subprocess.PIPE);require(delta.returncode in (0,1),'Cannot create lineage')
        f.archive.atomic(out/'lineage/from_matrix_E2.patch',delta.stdout)
    for base in (run,out):write(base/'status.json',state)
    publish_report(run);inventory(run);f.archive.index()
    return dict(run_root=str(run),source_manifest_sha256=sha(run/'SOURCE.json'),archive_directory=str(out),
        configurations=list(CONFIGS),hardware_started=False)


class Measurement(f.Measurement):
    def __init__(self,run):
        super().__init__(run);self.configs=[c for c in (*PRIORITY,*CONFIGS) if c in self.meta['configs']]
        self.configs=list(dict.fromkeys(self.configs))


class Physical(f.Physical):
    def __init__(self,run):
        super().__init__(run);self.state['schema']='mhbs.sha2_timing_g.physical.v1'

    def route(self,backend,p,u):
        super().route(backend,p,u)
        config=f.dual.route_key(backend,p,u);item=self.state['routes'][config]
        if 'result' not in item:return
        result=deepcopy(item['result']);target=150 if u==1 else 100
        hard=bool(result['setup_hold_met'] and result['drc_errors']==0 and item['route_status']['passed']
            and result['actual_period_ns']<=1000/target)
        result.update(hard_frequency_target_met=hard,strict_frequency_target_met=hard,
            clock_quantization_tolerance_ns=0,hard_constraint_period_ns=6.666 if u==1 else 10.0)
        self.update('routes',config,status='passed' if hard else 'target_not_met',meets_target=hard,result=result,
            inherited_nominal_gate_replaced=True)


def detach(run,mode,log):
    env=dict(os.environ,MHBS_SHA2_G_WORKSPACE=str(ROOT),MHBS_SHA2_F_WORKSPACE=str(ROOT),
        MHBS_P1SHA_WORKSPACE=str(ROOT),MHBS_DUAL_MATRIX_WORKSPACE=str(ROOT))
    with (run/log).open('w') as stream:
        process=subprocess.Popen([sys.executable,str(run/'control/run_sha2_timing_g.py'),mode,str(run)],cwd=ROOT,
            env=env,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
    return process.pid


def launch_measure(run):
    run=run.resolve();meta=read(run/'SOURCE.json')
    require(meta['experiment_family']=='sha2_timing_g' and meta['kind']=='candidate' and f.shared.unchanged(meta),
        'Only the frozen G candidate can be measured')
    require(not (run/'MEASUREMENT_LAUNCH.json').exists(),'Measurement already launched')
    result=dict(requested_at=now(),source_manifest_sha256=sha(run/'SOURCE.json'),pid=detach(run,'--run-root','runner.log'))
    with (run/'functional_validator.log').open('w') as stream:
        process=subprocess.Popen([sys.executable,str(Path(meta['source_root'])/'scripts/validate_p1sha_candidate.py'),'--run-root',str(run)],
            cwd=ROOT,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
    result['functional_pid']=process.pid;write(run/'MEASUREMENT_LAUNCH.json',result);return result


def launch_physical(run):
    run=run.resolve();meta=read(run/'SOURCE.json')
    require(meta['experiment_family']=='sha2_timing_g' and meta['kind']=='candidate' and f.shared.unchanged(meta),
        'Only the explicit frozen G candidate may route')
    require(not (run/'PHYSICAL_REQUEST.json').exists(),'Physical phase already requested')
    result=dict(requested_at=now(),source_manifest_sha256=sha(run/'SOURCE.json'),configs=list(CONFIGS),
        explicit_user_authorization=True,root_explicit_final_freeze=True,per_configuration_gate=True,
        targets_mhz={'1':150,'2':100},all_14_configs_required=True,frequency_search=False,automatic_frequency_fallback=False)
    for base in (run,Path(meta['archive_directory'])):write(base/'PHYSICAL_REQUEST.json',result)
    result['pid']=detach(run,'--physical-run','physical_runner.log')
    for base in (run,Path(meta['archive_directory'])):write(base/'PHYSICAL_LAUNCH.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare-baseline',action='store_true');mode.add_argument('--freeze-candidate',action='store_true')
    mode.add_argument('--launch-measure',type=Path);mode.add_argument('--route-existing',type=Path)
    mode.add_argument('--run-root',type=Path);mode.add_argument('--physical-run',type=Path)
    mode.add_argument('--report-existing',type=Path);mode.add_argument('--audit-existing',type=Path)
    parser.add_argument('--baseline',type=Path);parser.add_argument('--label',default='G1');args=parser.parse_args()
    if args.prepare_baseline:value=freeze('baseline','E2_matrix_093744_all14')
    elif args.freeze_candidate:
        require(args.baseline is not None,'--baseline must identify the frozen all14 G baseline')
        value=freeze('candidate',args.label,args.baseline)
    elif args.launch_measure:value=launch_measure(args.launch_measure)
    elif args.route_existing:value=launch_physical(args.route_existing)
    elif args.run_root:raise SystemExit(Measurement(args.run_root).execute())
    elif args.physical_run:Physical(args.physical_run).execute();raise SystemExit()
    elif args.audit_existing:value=f.audit(args.audit_existing)
    else:publish_report(args.report_existing);inventory(args.report_existing);f.archive.index();value=dict(report_refreshed=str(args.report_existing))
    print(json.dumps(value,ensure_ascii=False,indent=2))
