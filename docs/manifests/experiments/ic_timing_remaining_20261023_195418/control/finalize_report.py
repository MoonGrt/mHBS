#!/usr/bin/env python3
"""Assemble a final i/c report from immutable evidence; launch no tools.

Only <archive>/reports/IC_Timing_Remaining_Final_<stamp>.md/.json are written.
Production RTL, INDEX.md and the controller's progress report are never read
or modified. Missing measurements remain JSON null and Markdown em dashes.
"""
import argparse
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re

BACKENDS=('shake','sha2')
FOCUS=('slh_128f','xmss_h10','lms_h10')
EVIDENCE={}
WARNINGS=[]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    path=Path(path)
    if not path.is_file():
        return None
    try:
        value=json.loads(path.read_text())
        EVIDENCE[str(path.resolve())]=dict(sha256=digest(path),kind='json')
        return value
    except (ValueError,OSError) as exc:
        WARNINGS.append(dict(path=str(path),error=str(exc)))
        return None


def area(path):
    path=Path(path)
    if not path.is_file():
        return None
    text=path.read_text();EVIDENCE[str(path.resolve())]=dict(sha256=digest(path),kind='utilization')
    def number(label):
        m=re.search(r'^\|\s*'+re.escape(label)+r'\*?\s*\|\s*([\d,.]+)',text,re.M)
        return float(m[1].replace(',','')) if m else None
    lut,ff,bram,dsp=[number(x) for x in ('Slice LUTs','Slice Registers','Block RAM Tile','DSPs')]
    if lut is None or ff is None:
        return None
    return dict(lut=int(lut),ff=int(ff),bram=bram,dsp=dsp,
                equivalent_slice=lut/4+ff/8+232.4*bram+102.4*dsp if bram is not None and dsp is not None else None)


def number(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def strict_closed(result,source_intact=None,process=None):
    if not result:
        return None
    required=('actual_period_ns','wns_ns','whs_ns','setup_hold_met','fully_routed','route_has_errors','drc_errors','accepted_frequency')
    if any(result.get(k) is None for k in required):
        return None
    if not all(number(result.get(k)) for k in ('actual_period_ns','wns_ns','whs_ns','drc_errors')):
        return None
    good=(result['actual_period_ns']<=10.000001 and result['wns_ns']>=0 and result['whs_ns']>=0 and
          result['setup_hold_met'] is True and result['fully_routed'] is True and
          result['route_has_errors'] is False and result['drc_errors']==0 and result['accepted_frequency'] is True)
    if source_intact is False:
        return False
    if good and source_intact is None:
        return None
    if process is not None and (process.get('status')!='complete' or process.get('returncode')!=0 or process.get('source_unchanged') is False):
        return False
    return good


def safe_ratio(new,old):
    return new/old if number(new) and number(old) and old else None


def percent(new,old):
    ratio=safe_ratio(new,old)
    return 100*(ratio-1) if ratio is not None else None


def intact(source,checks):
    if not source or not isinstance(checks,dict) or not checks:
        return None
    return all((Path(source)/name).is_file() and digest(Path(source)/name)==expected for name,expected in checks.items())


def compact_validation(path):
    value=read(path)
    if value is None:
        return None
    cases=value.get('cases',{})
    tests=value.get('tests',{})
    return dict(path=str(Path(path).resolve()),source=value.get('source'),source_id=value.get('source_id'),
                complete=value.get('complete'),passed=value.get('passed'),source_unchanged=value.get('source_unchanged'),
                expected_cases=value.get('expected_cases'),case_counts=value.get('case_counts'),
                expected_tests=value.get('expected_tests'),test_counts=value.get('test_counts'),
                tests={k:{x:v.get(x) for x in ('status','cases','returncode','log','pass_marker')} for k,v in tests.items()},
                h20_verify={k:v.get('status') for k,v in cases.items() if re.match(r'(xmss|lms)_h20/verify$',k)},
                h20_full_tree_cases_present=[k for k in cases if re.match(r'(xmss|lms)_h20/(keygen|sign)$',k)],
                high_tree_keygen_sign_requested=value.get('high_tree_keygen_sign_requested'),
                runtime_log_directory=value.get('runtime_log_directory'),
                failed_cases=[k for k,v in cases.items() if v.get('status')=='failed'])


def case_data(summary_path,design,backend,profile):
    summary=read(summary_path)
    if not summary:
        return None
    raw=summary.get('cases',{}).get(profile+'/sign')
    if not raw:
        return None
    source=Path(raw.get('cwd') or summary.get('source') or '')
    vector=source/'tb/vectors'/design
    if backend=='sha2':
        vector=vector/'sha2'
    vector=vector/profile/'sign'
    job=vector/'job.mem';message_bytes=None
    if job.is_file():
        try:message_bytes=int(job.read_text().split()[8],16)
        except (ValueError,IndexError):pass
    vector_hashes={name:digest(vector/name) if (vector/name).is_file() else None
                   for name in ('job.mem','message.mem','expected.mem','nodes.mem')}
    return dict(status=raw.get('status'),cycles=raw.get('cycles'),hashes=raw.get('hashes'),
                physical_blocks=raw.get('physical_blocks',raw.get('permutations')),
                logical_blocks=raw.get('logical_permutations'),message_bytes=message_bytes,
                output_bytes_checked=raw.get('output_bytes_checked'),
                signature_cache_checked=raw.get('signature_cache_checked'),
                signature_cache_and_output_validated=raw.get('signature_cache_and_output_validated'),
                log=raw.get('log'),summary=str(Path(summary_path).resolve()),source_id=raw.get('source_id'),
                vector=str(vector),vector_sha256=vector_hashes)


def workload_match(new,old):
    if not new or not old or new.get('status')!='passed' or old.get('status')!='passed':
        return None
    keys=('hashes','physical_blocks','logical_blocks','message_bytes')
    if any(new.get(k) is None or old.get(k) is None for k in keys):
        return None
    inputs=('job.mem','message.mem','expected.mem','nodes.mem')
    if any(new.get('vector_sha256',{}).get(k) is None or old.get('vector_sha256',{}).get(k) is None for k in inputs):
        return None
    return all(new[k]==old[k] for k in keys) and all(new['vector_sha256'][k]==old['vector_sha256'][k] for k in inputs)


def profile(path):
    value=read(path)
    if value is None:
        return None
    keys=('status','total','hash','transfer','remaining','rounds','feedforward','hash_count','physical_blocks','logical_blocks',
          'signature_sha256','signature_cache_sha256','signature_cache_and_kat_match','message_bytes','configuration',
          'source_unchanged','returncode','stage','seconds')
    row={k:value.get(k) for k in keys}
    row.update(path=str(Path(path).resolve()),log=str(Path(path).with_name('run.log').resolve()),compile_log=str(Path(path).with_name('compile.log').resolve()))
    att=value.get('attribution') or {}
    row['attribution']={k:att.get(k) for k in ('categories','hash_template_count','hash_template_nonhash','recipe_nonhash','control_op_histogram')}
    return row


def first_profile(run,label,backend):
    names=[label]
    if label=='i_prefetch':
        names=['i_prefetch_fixed_profiler','i_prefetch']
    attempts=[]
    for name in names:
        p=run/'profiles'/name/backend/'result.json';item=profile(p)
        if item is not None:attempts.append(item)
    passed=next((item for item in attempts if item.get('status')=='passed'),None)
    return passed or (attempts[0] if attempts else None),attempts


def fmt(x,places=3):
    if x is None:return '—'
    if isinstance(x,bool):return '是' if x else '否'
    if isinstance(x,int):return f'{x:,}'
    if isinstance(x,float):return f'{x:,.{places}f}'
    return str(x).replace('|','\\|').replace('\n',' ')


def table(lines,head,rows):
    lines+=['','| '+' | '.join(head)+' |','|'+'|'.join('---' for _ in head)+'|']
    lines+=['| '+' | '.join(fmt(v) for v in row)+' |' for row in rows]


def directed_compatibility(data,record):
    checks={}
    def collect(value):
        if not isinstance(value,dict):return
        for key,item in value.items():
            if key in ('source_sha256','sha256','candidate_sha256') and isinstance(item,dict):
                for path,h in item.items():
                    if isinstance(h,str):
                        match=re.search(r'(?:^|/)(rtl/[ict]/.+)$',path)
                        if match:checks[match[1]]=h
            if key=='files' and isinstance(item,dict):
                for path,info in item.items():
                    if isinstance(info,dict) and isinstance(info.get('candidate_sha256'),str):
                        match=re.search(r'(?:^|/)(rtl/[ict]/.+)$',path)
                        if match:checks[match[1]]=info['candidate_sha256']
            if isinstance(item,dict):collect(item)
    collect(data)
    design=record.get('design');checks={k:v for k,v in checks.items() if k.startswith(f'rtl/{design}/')}
    return intact(record.get('source'),checks) if checks else None


def adopted_value(argument,decision):
    if argument is not None:return argument.lower() in ('true','1','yes','adopted')
    value=decision.get('adopted') if isinstance(decision,dict) else None
    if isinstance(value,bool):return value
    status=decision.get('status') if isinstance(decision,dict) else None
    if status in ('adopted','applied'):return True
    if status in ('rejected','not_adopted'):return False
    return None


def selected_c(argument,decision):
    if argument:return argument
    if not isinstance(decision,dict):return None
    if isinstance(decision.get('selected_c'),str):return decision['selected_c']
    for key in ('selected','selected_candidates'):
        value=decision.get(key,{})
        if isinstance(value,dict) and isinstance(value.get('c'),str):return value['c']
    return None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',required=True,type=Path)
    parser.add_argument('--selected-i',default='i_software')
    parser.add_argument('--selected-c')
    parser.add_argument('--adopted',nargs='?',const='true',choices=['true','false','1','0','yes','no','adopted','not_adopted'])
    args=parser.parse_args();run=args.run.resolve();meta=read(run/'SOURCE.json') or {}
    if not meta.get('root') or not meta.get('archive') or not meta.get('stamp'):
        parser.error('run/SOURCE.json must supply root, archive, stamp')
    root=Path(meta['root']);archive=Path(meta['archive']);stamp=meta['stamp'];decision=read(run/'DECISION.json')
    selected={'i':args.selected_i,'c':selected_c(args.selected_c,decision)}
    baseline_name=meta.get('baseline');baseline_archive=root/'docs/manifests/experiments'/baseline_name if baseline_name else None
    baseline_report=baseline_archive/'reports'/f'Ablation_Route_{baseline_name.removeprefix("ablation_route_")}.json' if baseline_archive else None
    baseline=read(baseline_report) if baseline_report else None
    baseline_rows={}
    for row in (baseline or {}).get('rows',[]):
        key=(row.get('design'),row.get('backend'));result=row.get('result')
        baseline_rows[key]=dict(label='baseline_'+str(key[0]),design=key[0],backend=key[1],synth_area=row.get('synth_area'),
                                route_area=row.get('route_area'),result=result,
                                accepted_100mhz=strict_closed(result,row.get('source_intact')),
                                source_intact=row.get('source_intact'),log=row.get('log'),status=row.get('status'))
    records={}
    for path in sorted((run/'queue').glob('*.json')):
        rec=read(path)
        if rec and rec.get('label'):records[rec['label']]=rec
    candidate_routes=[];validation=[];candidate_intact={}
    for label,rec in records.items():
        candidate_intact[label]=intact(rec.get('source'),rec.get('sha256'))
        for backend in rec.get('backends',BACKENDS):
            folder=run/'routes'/label/backend;result=read(folder/'result.json');process=read(folder/'PROCESS.json');stage=read(folder/'stage.json')
            candidate_routes.append(dict(label=label,design=rec.get('design'),backend=backend,selected=selected.get(rec.get('design'))==label,
                synth_area=area(folder/'synth/utilization.rpt'),route_area=area(folder/'route/utilization.rpt'),result=result,
                accepted_100mhz=strict_closed(result,candidate_intact[label],process),source_intact=candidate_intact[label],
                process=process,stage=(stage or {}).get('stage'),failure=read(folder/'failure.json'),
                log=str(folder/'vivado.log'),synth_hierarchical=str(folder/'synth/hierarchical.rpt'),
                synth_timing=str(folder/'synth/timing.rpt'),route_hierarchical=str(folder/'route/hierarchical.rpt'),route_timing=str(folder/'route/timing.rpt')))
            summary=compact_validation(run/'validation'/label/backend/'SUMMARY.json')
            validation.append(dict(label=label,design=rec.get('design'),backend=backend,summary=summary))
    old_run=root/'build/c_idea_migration/20261023_191653'
    baseline_validation={}
    for design in ('i','c'):
        for backend in BACKENDS:
            choices=[run/'baseline_validation'/design/backend/'SUMMARY.json',old_run/'validation'/('baseline_'+design)/backend/'SUMMARY.json']
            chosen=next((p for p in choices if p.is_file()),None)
            baseline_validation[(design,backend)]=chosen
    focus=[]
    for design,label in selected.items():
        if not label:continue
        for backend in BACKENDS:
            route=next((x for x in candidate_routes if x['label']==label and x['backend']==backend),None)
            old_route=baseline_rows.get((design,backend),{})
            for name in FOCUS:
                cand=case_data(run/'validation'/label/backend/'SUMMARY.json',design,backend,name)
                old=case_data(baseline_validation[(design,backend)],design,backend,name) if baseline_validation[(design,backend)] else None
                eq=((route or {}).get('route_area') or {}).get('equivalent_slice');old_eq=(old_route.get('route_area') or {}).get('equivalent_slice')
                cycles=cand.get('cycles') if cand and cand.get('status')=='passed' else None
                old_cycles=old.get('cycles') if old and old.get('status')=='passed' else None
                ac=eq*cycles if number(eq) and number(cycles) else None
                old_ac=old_eq*old_cycles if number(old_eq) and number(old_cycles) else None
                match=workload_match(cand,old)
                focus.append(dict(design=design,label=label,backend=backend,profile=name,operation='Sign',candidate=cand,baseline=old,
                    same_inputs_and_workload=match,cycle_change_percent=percent(cycles,old_cycles),route_equivalent_slice=eq,
                    baseline_route_equivalent_slice=old_eq,candidate_area_cycles=ac,baseline_area_cycles=old_ac,
                    fixed_frequency_area_cycles_change_percent=percent(ac,old_ac) if match is True else None,
                    actual_atp_100mhz_slice_s=ac/100_000_000 if ac is not None and (route or {}).get('accepted_100mhz') is True else None,
                    actual_time_100mhz_s=cycles/100_000_000 if cycles is not None and (route or {}).get('accepted_100mhz') is True else None,
                    baseline_actual_atp_100mhz_slice_s=old_ac/100_000_000 if old_ac is not None and old_route.get('accepted_100mhz') is True else None,
                    comparison_basis='Unclosed baseline: equal-frequency area×cycle hypothesis, not measured 100MHz baseline ATP.' if old_route.get('accepted_100mhz') is False else 'Actual100MHz comparison only if both endpoints close; missing closure remains null.'))
    comparison_path=root/'tmp/sloth_ict_cycle_comparison/cycle_breakdown_data.json';comparison=read(comparison_path) or {}
    sloth={row.get('backend'):row for row in comparison.get('rows',[]) if row.get('design')=='SLotH'}
    profiles=[]
    for backend in BACKENDS:
        baseline_paths=[root/'build/ic_timing_staging/profile_baseline'/backend/'result.json',root/'tmp/sloth_ict_cycle_comparison/profile/i'/backend/'result.json']
        bp=next((p for p in baseline_paths if p.is_file()),None);old=profile(bp) if bp else None
        first,attempts=first_profile(run,'i_prefetch',backend)
        new,new_attempts=first_profile(run,selected['i'],backend)
        passed_fields=('hash_count','physical_blocks','logical_blocks','message_bytes','signature_sha256','hash','rounds','feedforward')
        matched=(all(new.get(k) is not None and old.get(k) is not None and new[k]==old[k] for k in passed_fields)
                 and new.get('signature_cache_and_kat_match') is True and new.get('status')=='passed') if new and old else None
        sr=sloth.get(backend);delta=(new['remaining']-sr['remaining']) if new and sr and number(new.get('remaining')) and number(sr.get('remaining')) and matched else None
        profiles.append(dict(backend=backend,baseline=old,first_candidate=first,first_candidate_attempts=attempts,
                             selected_label=selected['i'],selected=new,selected_attempts=new_attempts,sloth=sr,
                             matched_baseline_kat_and_workload=matched,selected_remaining_minus_sloth=delta,
                             selected_remaining_lower_than_sloth=(delta<0) if delta is not None else None))
    profiler_failures=[]
    for failure_path in sorted((run/'profiles').glob('*/*/result.json')):
        value=read(failure_path)
        if not value or value.get('status')=='passed':continue
        log=failure_path.with_name('compile.log')
        text=log.read_text() if log.is_file() else ''
        internal_enum=('EnumItemRef' in text and ('Internal Error' in text or 'InternalError' in text))
        profiler_failures.append(dict(path=str(failure_path),status=value.get('status'),
            compile_log=str(log),compile_log_sha256=digest(log) if log.is_file() else None,
            reason='Verilator internal error on cross-hierarchy enum reference in diagnostic wrapper' if internal_enum else None,
            is_dut_failure=False if internal_enum else None,
            error_lines=[line for line in text.splitlines() if '%Error' in line][:5],
            remediation='Diagnostic wrapper only: parse frozen state_t enums and generate localparams with STATE_ENUMS.json provenance' if internal_enum else None,
            detail_log_archive_policy='Original failure logs stay under run; not copied into validation detail archive.'))
    supplements=[]
    derived=read(run/'DERIVED_IMAGE_LAYOUT.json')
    if derived is not None:supplements.append(dict(kind='derived_image_layout',path=str(run/'DERIVED_IMAGE_LAYOUT.json'),sha256=digest(run/'DERIVED_IMAGE_LAYOUT.json'),data=derived))
    for label in records:
        for name in ('SUPPORT_SOURCE.json','DERIVED_IMAGE_LAYOUT.json'):
            supplement_path=archive/'candidates'/label/name;value=read(supplement_path)
            if value is not None:supplements.append(dict(candidate=label,kind=name,path=str(supplement_path),sha256=digest(supplement_path),data=value))
    rom=[];base_source=old_run/'baseline_source'
    for design,label in selected.items():
        source=Path(records[label]['source']) if label in records else None
        if source is None:
            rom.append(dict(design=design,label=label,observed_sets=None,all_templates_descriptors_equal=None));continue
        dirs=sorted(set(p.parent.relative_to(base_source) for p in (base_source/f'image/{design}').glob('*/*/program.mem')))
        items=[]
        for rel in dirs:
            files={}
            for name in ('program.mem','template.mem','descriptor.mem'):
                old=base_source/rel/name;new=source/rel/name
                oh=digest(old) if old.is_file() else None;nh=digest(new) if new.is_file() else None
                files[name]=dict(baseline_sha256=oh,candidate_sha256=nh,equal=(oh==nh) if oh is not None and nh is not None else None)
            items.append(dict(path=str(rel),files=files))
        identical=all(x['files'][name]['equal'] is True for x in items for name in ('template.mem','descriptor.mem')) if items else None
        rom.append(dict(design=design,label=label,expected_existing_sets=20,observed_sets=len(items) if dirs else None,
                        all_templates_descriptors_equal=identical,programs_changed=sum(x['files']['program.mem']['equal'] is False for x in items) if items else None,
                        baseline_source=str(base_source),candidate_source=str(source),sets=items))
    directed=[]
    evidence_paths=sorted(set((root/'build/ic_timing_staging').glob('*/AUDIT.json'))|
                          set((root/'build/ic_timing_staging').glob('*/DIRECTED_VALIDATION.json'))|
                          set((root/'build/ic_timing_staging').glob('*/MODEL_VALIDATION.json'))|
                          set((root/'build/ic_timing_staging/c_v2/validation').glob('*VALIDATION.json')))
    for path in evidence_paths:
        value=read(path)
        if not value:continue
        summary=value.get('validation') or value.get('directed_validation')
        if summary is None and any(k in value for k in ('passed','results','cases')):summary={k:value.get(k) for k in ('passed','total','complete','source_unchanged','results','checks') if k in value}
        if summary is None:continue
        directed.append(dict(path=str(path.resolve()),summary=summary,
                             selected_rtl_match={design:directed_compatibility(value,records[label]) if label in records else None for design,label in selected.items()}))
    for label,rec in records.items():
        unit=Path(rec['source'])/'build/ablation'/rec['design']/'chain_controls/VALIDATION.json'
        value=read(unit)
        if value:directed.append(dict(path=str(unit),candidate=label,summary={k:value.get(k) for k in ('passed','total','source_unchanged','results','checks')},selected_rtl_match=directed_compatibility(value,rec)))
    missing=[]
    for row in candidate_routes:
        if row['result'] is None:missing.append(row['label']+'/'+row['backend']+'/route')
    for row in validation:
        if not row['summary'] or row['summary'].get('complete') is not True:missing.append(row['label']+'/'+row['backend']+'/validation')
    for row in focus:
        if not row['candidate'] or row['candidate'].get('status')!='passed':missing.append(row['label']+'/'+row['backend']+'/'+row['profile']+'/Sign')
        if row['same_inputs_and_workload'] is not True:missing.append(row['label']+'/'+row['backend']+'/'+row['profile']+'/baseline_workload_comparison')
    adoption=adopted_value(args.adopted,decision)
    report=dict(schema='mhbs.ic.timing_remaining.final.v1',assembled_at=datetime.now().astimezone().isoformat(),stamp=stamp,
        run=str(run),archive=str(archive),baseline=baseline_name,configuration=meta.get('configuration'),frequency_mhz=100,
        part=meta.get('part'),top='common',decision=decision,selected=selected,adopted=adoption,
        adoption_note='Adoption is recorded from CLI/DECISION.json; this script never opens production RTL to infer adoption.',
        candidate_count=len(records),backend_validation_groups=len(validation),candidate_source_intact=candidate_intact,
        baseline_routes=list(baseline_rows.values()),candidate_routes=candidate_routes,focus_sign=focus,profiles_33B=profiles,profiler_diagnostic_failures=profiler_failures,supplemental_source_metadata=supplements,
        baseline_validation={f'{d}/{b}':str(p) if p else None for (d,b),p in baseline_validation.items()},
        validation=validation,directed_validation=directed,rom_audit=rom,
        failed_i_prefetch=[x for x in candidate_routes if x['label']=='i_prefetch'],
        sloth_comparison_source=str(comparison_path),sloth_partition_definitions=comparison.get('definitions'),sloth_caveats=comparison.get('caveats'),
        missing_or_unfinished=missing,evidence=EVIDENCE,warnings=WARNINGS,
        artifact_policy='Existing archive retains each frozen RTL tar/source manifest and synth/route hierarchical/timing/DRC/log evidence; detailed sim/validation logs remain in original run paths. This assembler writes only final Markdown/JSON and never modifies INDEX, ARTIFACTS, progress reports or production RTL.',
        scope_limits=['100MHz is a tested OOC common target, not an Fmax search or a board-level I/O timing claim.',
          'Actual ATP100MHz is populated only for fully routed setup/hold/DRC-accepted points; negative-WNS baseline has no actual ATP100MHz.',
          'Default regression Sign vectors are ordinarily1byte; their actual job.mem message lengths are reported separately from the33byte matched-KAT profile.',
          'Project Hash counts only primitive round updates plus SHA256 feed-forward. SLotH reported engine Hash also contains some load/PRF setup/chain padding; Remaining comparison preserves the published boundary rather than moving project control into Hash.',
          'XMSS/LMS h20 full Keygen/Sign are not run; only Verify/address/elaboration evidence is within scope.',
          'Missing, incomplete or nonmatching measurements stay null; no extrapolation or cross-configuration area borrowing.'])
    lines=['# i/c 时序与 Remaining 最终取舍','',f'组装：{report["assembled_at"]}；P1U1 common，100MHz，{meta.get("part")}。',
        '',f'选择：i=`{selected["i"]}`，c=`{selected["c"]}`；采用状态：{fmt(adoption)}。实际采用状态来自参数或 DECISION.json，脚本不读取生产 RTL。',
        '',f'本轮动态汇总 {len(records)} 个候选、{len(validation)} 个后端验证组。缺失/未完成条目：{len(missing)}。基线：`{baseline_name}`。']
    for backend in BACKENDS:
        lines+=['',f'## {backend.upper()} 面积与100MHz布线','',
                '等效Slice = LUT/4 + FF/8 +232.4×BRAM +102.4×DSP；综合和布线面积分别列出。']
        rows=[]
        for row in [x for x in baseline_rows.values() if x['backend']==backend]+[x for x in candidate_routes if x['backend']==backend]:
            sa=row.get('synth_area') or {};ra=row.get('route_area') or {};res=row.get('result') or {}
            rows.append([row['label']+('（选择）' if row.get('selected') else ''),sa.get('lut'),sa.get('ff'),sa.get('equivalent_slice'),ra.get('lut'),ra.get('ff'),ra.get('equivalent_slice'),res.get('wns_ns'),res.get('whs_ns'),res.get('fully_routed'),res.get('drc_errors'),row.get('accepted_100mhz')])
        table(lines,['配置','综合LUT','FF','等效Slice','布线LUT','FF','等效Slice','WNS ns','WHS ns','完整路由','DRC错误','100MHz接受'],rows)
    lines+=['','## 相同33字节KAT的 i 周期组成','',
        '通过的本核结果保持 Hash 优先、Transfer=0、Remaining 为补集，并通过总和与签名/cache/Hash/物理块断言；未完成或失败项不作通过声明。SLotH使用原报告口径，其Hash另含部分引擎装载和链控制，不能把两方Hash差直接解释为算法工作量差。']
    rows=[]
    for entry in profiles:
        for label,item in [('SLotH',entry['sloth']),('i baseline',entry['baseline']),('i_prefetch',entry['first_candidate']),(entry['selected_label'],entry['selected'])]:
            item=item or {};rows.append([entry['backend'],label,item.get('status') if label!='SLotH' else '原报告',item.get('total'),item.get('hash'),item.get('transfer'),item.get('remaining'),item.get('hash_count'),item.get('physical_blocks')])
    table(lines,['后端','实现','状态','总周期','Hash','Transfer','Remaining','Hash数','物理块'],rows)
    for entry in profiles:
        lines+=['',f'{entry["backend"]}：所选i的KAT/工作量与基线匹配={fmt(entry["matched_baseline_kat_and_workload"])}；Remaining−SLotH={fmt(entry["selected_remaining_minus_sloth"])}；低于SLotH={fmt(entry["selected_remaining_lower_than_sloth"])}。']
    lines+=['','诊断工具失败与DUT结果分开：第一次 `profiles/i_prefetch` 的编译失败来自该Verilator版本处理跨层枚举引用时的内部错误（EnumItemRef），不是DUT功能不通过。只修诊断wrapper：解析冻结RTL枚举并生成localparam，STATE_ENUMS.json记录源校验与映射。后续各profiling是否通过以表格及原始result.json为准，旧失败日志在运行目录保留。']
    lines+=['','## 三个目标的默认回归 Sign','',
        '这是默认向量的实测周期，实际消息长度由各冻结包 job.mem读取；与上表33字节KAT分开。ATP100单位为等效Slice·秒。旧未闭合基线仅进行同频“面积×周期”假设比较，该列不代表基线实际达到100MHz。']
    rows=[]
    for row in focus:
        c=row['candidate'] or {};b=row['baseline'] or {}
        rows.append([row['design']+'/'+row['backend'],row['profile'],b.get('message_bytes'),c.get('message_bytes'),b.get('cycles'),c.get('cycles'),row['cycle_change_percent'],c.get('hashes'),c.get('physical_blocks'),row['same_inputs_and_workload'],row['actual_atp_100mhz_slice_s'],row['fixed_frequency_area_cycles_change_percent']])
    table(lines,['实现/后端','参数','旧消息B','消息B','旧周期','周期','周期变化%','Hash数','物理块','输入/工作量一致','实际ATP100','同频面积×周期变化%'],rows)
    lines+=['','## 验证与拒绝路径','',
        '验证组按当前队列动态列出。通过只按完整SUMMARY记录；待完成不标为通过。h20仅Verify，完整Keygen/Sign保持停止。']
    rows=[]
    for row in validation:
        s=row['summary'] or {};cc=s.get('case_counts') or {};tc=s.get('test_counts') or {};syn=(s.get('tests') or {}).get('synthesis_slh_128f_sign') or {}
        rows.append([row['label']+'/'+row['backend'],s.get('complete'),s.get('passed'),cc.get('passed'),s.get('expected_cases'),tc.get('passed'),s.get('expected_tests'),syn.get('status'),s.get('source_unchanged'),','.join(f'{k}:{v}' for k,v in (s.get('h20_verify') or {}).items()) or None])
    table(lines,['验证组','完成','通过','已通过操作','应有操作','已通过测试','应有测试','SYNTHESIS Sign','源码未变','h20 Verify'],rows)
    lines+=['','定向控制、FORS慢操作数、快慢分支交替、RAM107/108及拒绝后无部分写入的摘要在JSON的directed_validation中；每项附候选RTL哈希匹配结果，匹配未知时不宣称该测试覆盖所选候选。']
    for item in directed:
        s=item['summary'];passed=s.get('passed',s.get('status')) if isinstance(s,dict) else None
        lines+=['',f'- `{item["path"]}`：通过/状态={fmt(passed)}；RTL对应={json.dumps(item.get("selected_rtl_match"),ensure_ascii=False)}。']
    lines+=['','## ROM、失败候选与适用范围','']
    for item in rom:
        lines+=[f'- {item["design"]}/{item["label"]}：观察到 {fmt(item.get("observed_sets"))} 组（原有20组）ROM；template/descriptor不变={fmt(item.get("all_templates_descriptors_equal"))}；program改变组数={fmt(item.get("programs_changed"))}。']
    for item in report['failed_i_prefetch']:
        r=item['result'] or {};lines += [f'- i_prefetch/{item["backend"]}：WNS={fmt(r.get("wns_ns"))}ns，WHS={fmt(r.get("whs_ns"))}ns，100MHz接受={fmt(item.get("accepted_100mhz"))}。失败/未达标证据保留，不用低频或推算频率替代验收。']
    lines+=['','i的软件逐Hash链/树边界、c的硬件CHAIN＋软件树边界保持；共享Hash后端及标准输出语义不变。所选i可以调整普通ROM程序以搬出不变条件，但每一步Hash仍有独立软件授权。',
        '', '本报告仅覆盖共同核OOC的受约束内部路径；没有执行极限频率搜索，不宣称板级接口时序。',
        '', '## 来源与原始日志','',
        f'- 本轮运行：`{run}`；候选冻结包：`{archive}/candidates/<候选>/frozen_rtl.tar.gz` 及 `SOURCE.json`。',
        f'- 同口径基线：`{baseline_archive}`。',
        f'- 路由/综合原始日志：`{run}/routes/<候选>/<后端>/vivado.log`；分层与时序在对应 synth/route 子目录。',
        f'- 完整验证SUMMARY：`{run}/validation/<候选>/<后端>/SUMMARY.json`，其 runtime_log_directory 指向原始明细。',
        f'- 33字节profiling：`{run}/profiles/`；baseline分解：`{root}/build/ic_timing_staging/profile_baseline/`。',
        '- 归档保留冻结RTL、源码校验、综合/布线分层、时序及工具日志；仿真/验证明细留在运行目录，仅汇总摘要进入归档。',
        '- i_software冻结包的旧image_layout元数据不冒充新程序占用；run/DERIVED_IMAGE_LAYOUT.json及各候选归档中的同名文件另列派生的20组ROM占用。若实际采用，metadata更新由采用步骤负责。',
        '- i_software缺失的model/default_jobs.json以候选归档support/及SUPPORT_SOURCE.json补证；不回写历史immutable tar或SOURCE清单。所有补充元数据来源见JSON supplemental_source_metadata。',
        '- 本脚本只写本次Final Markdown/JSON；不覆盖progress report、不写INDEX或ARTIFACTS，也不读写生产RTL。']
    if missing:lines+=['','缺失/未完成：']+['',*['- `'+x+'`' for x in missing]]
    if WARNINGS:lines+=['','读取警告：']+['',*['- `'+x['path']+'`：'+x['error'] for x in WARNINGS]]
    dest=archive/'reports'/f'IC_Timing_Remaining_Final_{stamp}';dest.parent.mkdir(parents=True,exist_ok=True)
    # Final filenames deliberately differ from the controller's progress output.
    for path,text in [(dest.with_suffix('.json'),json.dumps(report,ensure_ascii=False,indent=2)+'\n'),(dest.with_suffix('.md'),'\n'.join(lines)+'\n')]:
        tmp=path.with_name(path.name+f'.{os.getpid()}.tmp');tmp.write_text(text);tmp.replace(path)
    print(json.dumps(dict(markdown=str(dest.with_suffix('.md')),json=str(dest.with_suffix('.json')),selected=selected,adopted=adoption,missing=len(missing)),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
