#!/usr/bin/env python3
"""Archive the SHAKE stateful extension, without starting experiments or rewriting history."""
from __future__ import annotations
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tarfile
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from model.microcode import ABI
from model.profiles import MICRO_NAMES,SLH_NAMES,STATEFUL_NAMES,get_profile

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text()) if Path(path).exists() else None
def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
def copy(source,target):
    source=Path(source);target=Path(target)
    if source.exists():target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
def bindings(row,*,models_only=False):
    identity=row.get('source_sha256',row.get('files',{}))
    for name,value in identity.items():
        if models_only and not name.startswith('model/'):continue
        path=ROOT/name
        if path.exists():assert sha(path)==value,('stale evidence',name)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('run','synthesis','units','archive'):p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--require-complete',action='store_true');args=p.parse_args()
    run=args.run.resolve();synthesis=args.synthesis.resolve();archive=args.archive.resolve()
    reports=archive/'reports';reports.mkdir(parents=True,exist_ok=True)
    old_name='image_chain_import_20261021' if ABI==3 else 'image_chain_tree_import_20261021'
    old=ROOT/'docs/manifests/experiments'/old_name
    base=read(old/('source_evidence/functional_rtl.json' if ABI==3 else 'source_rtl.json'))
    required=[name+'/'+op for name in MICRO_NAMES for op in ('keygen','sign','verify')
              if name in SLH_NAMES or get_profile(name).h==10 or op=='verify']
    receipts={'models':run/'models.json','rtl':run/'rtl.json',
        'synthesis_view':run/'synthesis_mode/results.json','units':args.units,
        'primitive':ROOT/'build/stateful_recipe/VALIDATION.json',
        'boundaries_hash_work':ROOT/'build/stateful_models/final_quick/results.json',
        'xmss_full_hash_work':ROOT/'build/stateful_models/final_full_xmss_h10/results.json',
        'lms_full_hash_work':ROOT/'build/stateful_models/final_full_lms_h10/results.json',
        'historical_source':ROOT/'build/stateful_models/final_import.json',
        'standard_adapter':ROOT/'build/stateful_models/adapter_rejection.json',
        'synthesis':synthesis/'status.json','netlist_statistics':synthesis/'synthesis/extended_pruning.json'}
    receipts.update({'top_'+name:run/'top_equivalence'/name/'results.json' for name in ('slh_128f','xmss_h10','lms_h10')})
    data={name:read(path) for name,path in receipts.items()};statuses={}
    for name,row in data.items():
        passed=row and (row.get('passed') is True or row.get('status') in ('passed','measured'))
        statuses[name]='passed' if passed else 'failed' if row and (row.get('passed') is False or row.get('status') in ('failed','area_gate_failed')) else 'pending'
        if passed:
            if name in ('boundaries_hash_work','xmss_full_hash_work','lms_full_hash_work'):bindings(row,models_only=True)
            elif name not in ('primitive','historical_source','synthesis','netlist_statistics'):bindings(row)
            copy(receipts[name],archive/'summaries'/(name+'.json'))
    copy(run/'early_default/rtl.json',archive/'summaries/default_normal_for_synthesis_view.json')
    copy(run/'PARALLEL_HANDOFF.json',archive/'orchestration/PARALLEL_HANDOFF.json')
    copy(run/'parallel_supervisor.py',archive/'orchestration/parallel_supervisor.py')
    if data['primitive']:
        for name,value in data['primitive']['production_sha256'].items():assert sha(ROOT/name)==value
    if data['rtl']:
        assert set(required)<=data['rtl']['cases'].keys(),'missing required default RTL operations'
        assert all(data['rtl']['cases'][key]['passed'] for key in required)
    if data['synthesis_view']:
        assert set(required)==data['synthesis_view']['cases'].keys(),'SYNTHESIS default operation matrix differs'
        assert len(data['synthesis_view']['statistics_off_cases'])==3
        if data['rtl']:
            sys.path.insert(0,str(ROOT/'scripts'))
            from check_statistics import COMPARE_FIELDS
            for key in required:
                for field in COMPARE_FIELDS:
                    assert data['synthesis_view']['cases'][key][field]==data['rtl']['cases'][key][field],('final normal/SYNTHESIS differs',key,field)
    comparisons={}
    if data['rtl'] and base:
        fields=('cycles','hashes','permutations','instructions','hash_trace_sha256',
            'macro_count','macro_busy_cycles','macro_hashes','tree_count','tree_busy_cycles','tree_hashes','tree_chains','tree_input_wait_cycles','tree_child_busy_cycles')
        for key,before in base['cases'].items():
            assert key in data['rtl']['cases'],('missing SLH compatibility case',key)
            after=data['rtl']['cases'][key]
            assert after['passed'],('SLH compatibility case failed',key)
            comparisons[key]={field:after[field] for field in fields if field in before}
            for field,value in comparisons[key].items():assert value==before[field],('SLH compatibility',key,field,value,before[field])
    write(archive/'summaries/slh_baseline_comparison.json',dict(passed=bool(comparisons),cases=comparisons,
        historical_receipt_sha256=sha(old/('source_evidence/functional_rtl.json' if ABI==3 else 'source_rtl.json'))))
    synth_source=read(synthesis/'SOURCE.json')
    if synth_source:
        bindings(synth_source)
        copy(synthesis/'SOURCE.json',archive/'synthesis/SOURCE.json')
        copy(synthesis/'rtl.tar.gz',archive/'synthesis/rtl.tar.gz')
        copy(synthesis/'rtl.tar.gz',archive/'rtl.tar.gz')
        for file in (synthesis/'synthesis').glob('*'):
            if file.suffix in ('.json','.log','.xdc','.rpt'):copy(file,archive/'synthesis'/file.name)
    # Freeze only active code and its test tools, never upstream history or raw simulation logs.
    names=set((ROOT/'sources.txt').read_text().split()+['sources.txt','rtl/executor/instructions.svh'])
    names.update(str(path.relative_to(ROOT)) for path in (ROOT/'model').rglob('*.py'))
    names.update('model/default_jobs.json' for _ in [0])
    names.update(str(path.relative_to(ROOT)) for path in (ROOT/'tb').glob('*') if path.suffix in ('.sv','.svh','.cpp'))
    names.update('scripts/'+name for name in ('run_hash_backends.py','check_recipes.py','check_hash_backend_contracts.py',
        'check_statistics.py','check_top_signature.py','check_source_import.py','check_stateful_models.py',
        'check_stateful_adapter.py','check_synthesis_pruning.tcl','simulate.sh','simulate_fast.sh','synthesize.sh','synthesize.py','synth.tcl','report_atp.py','report_stateful_extension.py'))
    names.update('scripts/'+name for name in ('generate_tree_vectors.py','check_hash_work.py','check_standard_models.py') if (ROOT/'scripts'/name).exists())
    names.update(str(path.relative_to(ROOT)) for path in (ROOT/'tb/kat').glob('*.json'))
    names.update(name for name in ('scripts/common_partition.py','docs/ISA.md','docs/Micro_ISA.md','docs/ABI.md','docs/Job_Interface.md') if (ROOT/name).exists())
    images={}
    for name in MICRO_NAMES:
        for file in ('program.mem','descriptor.mem'):
            path='tb/vectors/'+name+'/'+file;names.add(path);images[path]=sha(ROOT/path)
    identity={name:sha(ROOT/name) for name in sorted(names)}
    with tarfile.open(archive/'source.tar.gz','w:gz') as tar:
        for name in sorted(names):tar.add(ROOT/name,arcname=name,recursive=False)
    production={name:identity[name] for name in identity if name.startswith('rtl/')}
    write(archive/'SOURCE.json',dict(abi=ABI,hash_backend='shake',configuration='K1U1',
        source_sha256=identity,production_sha256=production,image_sha256=images,
        archived_source_sha256=sha(archive/'source.tar.gz'),base_commit='3e682545' if ABI==3 else 'a6d113e8',
        historical_source_proof_scope=old_name,current_extended_rtl_source_equivalence_claimed=False))
    area=data['synthesis'].get('resources') if data['synthesis'] else None
    baseline={'lut':12339,'ff':4113} if ABI==3 else {'lut':15698,'ff':4205}
    cycles={}
    if data['rtl']:
        for key in required:
            row=data['rtl']['cases'][key]
            cycles[key]={k:row[k] for k in ('cycles','hashes','permutations','instructions','macro_count','macro_hashes','tree_count','tree_hashes','tree_chains') if k in row}
            cycles[key]['assumed_100MHz_ms']=row['cycles']/100000
            if area:cycles[key]['assumed_100MHz_atp_slice_ms']=area['equivalent_slices']*row['cycles']/100000
    complete=all(value=='passed' for value in statuses.values()) and len(required)==28 and len(comparisons)>=18
    result=dict(status='passed' if complete else 'pending',abi=ABI,branch='image-chain' if ABI==3 else 'image-chain-tree',
        hash_backend='shake',configuration='K1U1',statuses=statuses,required_default_cases=28,
        default_cases=cycles,rtl_case_count=len(data['rtl']['cases']) if data['rtl'] else 0,
        slh_baseline_equal_cases=len(comparisons),area=area,baseline_area=baseline,
        area_increment={k:area[k]-v for k,v in baseline.items()} if area else None,
        model_hash_work_binding_scope='model sources; recorded RTL identities are collection context, not RTL simulation evidence',
        source_import_area_gate_applied=False,frequency_MHz=100,frequency_is_assumed=True,routing_performed=False,
        high_tree_full_operations='h16/h15/h20 complete Keygen and Sign not generated or run; h20 remains stopped',
        high_tree_verify='real-height Verify with explicitly synthetic authentication siblings',
        raw_simulation_logs=str(run),synthesis_run=str(synthesis),
        updated_at=datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds'))
    write(reports/'Stateful_Extension.json',result);write(archive/'VALIDATION.json',result)
    lines=[f'# {result["branch"]} 标准 XMSS／LMS 扩展','',f'验收状态：**{result["status"]}**。固定 SHAKE256、K1U1、单 Hash 在途，ABI{ABI}。','',
        '新增XMSS h10/h16/h20（n32、w16）及LMS h10/h15/h20（m32、LMOTS w4、type0x0B）。原六组SLH程序和描述符逐字保留。','',
        ('CHAIN仅接管单链，其余L-tree、叶压缩、树及认证路径均由image控制。opcode37拒绝执行。' if ABI==3 else 'TREE接管单棵树，包含子CHAIN、L-tree／LMS叶压缩及认证路径；image保留R/C、摘要、digits、q及根比较。stateful禁止TOP_SHORTCUT。'),'',
        '仍使用128×256单读单写节点RAM；KEY复用SLH摘要暂存，VALUE124、capture shadow123。新增q/I/C为Job输入快照。所有统计64位；PROFILE_ENABLE=0的网表裁剪检查状态见下表。','',
        '| 检查 | 状态 |','|---|---|',*[f'| {name} | {status} |' for name,status in statuses.items()],'',
        f'默认必选RTL矩阵为28项，含18项SLH、6项h10三操作及4项高树Verify；SYNTHESIS视图也要求28项，完成情况见上表。原SLH兼容对照通过{len(comparisons)}项。q1/末叶完整h10 Sign、显式镜像及故障/边界项目见摘要。','',
        '独立模型比较完整Hash前像、结果的多重集，保留重复次数；宏/显式执行要求密码学工作完全一致；各模型检查状态见上表。VM工作量摘要只绑定模型源码，不作为RTL仿真证据；有序VM/RTL任务轨迹由最终整核回归另行核对。高树路径兄弟节点为合成输入，不代表完整树生成。','',
        '**未验证范围：h16/h15/h20完整Keygen、Sign；不自动生成这些任务，h20保持停止。**','',
        '| 面积口径 | LUT | FF | BRAM36 | DSP | 等效Slice |','|---|---:|---:|---:|---:|---:|',
        f'| 原SLH common基线 | {baseline["lut"]:,} | {baseline["ff"]:,} | 0 | 0 | {baseline["lut"]/4+baseline["ff"]/8:,.3f} |']
    if area:lines +=[f'| 扩展后common | {area["lut"]:,.0f} | {area["ff"]:,.0f} | {area["bram36"]:g} | {area["dsp"]:g} | {area["equivalent_slices"]:,.3f} |',
        '',f'增量：{area["lut"]-baseline["lut"]:+,.0f} LUT、{area["ff"]-baseline["ff"]:+,.0f} FF。扩功能后不使用原移植±1%闸门。']
    if area and area.get('timing_diagnostic'):
        timing=area['timing_diagnostic']
        lines +=['',f'10ns约束综合诊断：WNS {timing["worst_slack_ns"]:+.3f}ns，数据路径延迟 {timing["data_path_delay_ns"]:.3f}ns。该结果不代表布线闭合频率。']
    lines +=['','Vivado2025.2、xc7a200tffg1156-3、100MHz OOC、2线程、统计关闭；不含程序ROM与签名缓存。综合时序仅诊断，无布局布线频率证据。']
    for family,title in (('slh','SLH-DSA'),('xmss','XMSS'),('lms','LMS')):
        lines +=['','## '+title,'','| 默认操作 | 实测周期 | Hash | 置换 | 假定100MHz ms | 假定ATP Slice·ms |','|---|---:|---:|---:|---:|---:|']
        for key,row in cycles.items():
            if get_profile(key.split('/')[0]).family!=family:continue
            atp=f'{row["assumed_100MHz_atp_slice_ms"]:.3f}' if 'assumed_100MHz_atp_slice_ms' in row else ''
            lines.append(f'| {key} | {row["cycles"]:,} | {row["hashes"]:,} | {row["permutations"]:,} | {row["assumed_100MHz_ms"]:.5f} | {atp} |')
    lines +=['',f'原始仿真日志：`{run}`。冻结源码、镜像校验、综合分层/时序/日志及验证摘要位于本实验目录。历史源码等价证明只绑定原冻结版本，不适用于新增RTL。','']
    (reports/'Stateful_Extension.md').write_text('\n'.join(lines))
    index=ROOT/'docs/manifests/experiments/INDEX.md'
    lines=index.read_text().splitlines()
    lines=[line for line in lines if not line.startswith('| '+archive.name+' |')]
    position=max(i for i,line in enumerate(lines) if line.startswith('|'))+1
    lines.insert(position,'| '+archive.name+' | [Stateful_Extension]('+archive.name+'/reports/Stateful_Extension.md) | [证据]('+archive.name+'/ARTIFACTS.json) |')
    index.write_text('\n'.join(lines).rstrip()+'\n')
    write(archive/'ARTIFACTS.json',dict(status=result['status'],omitted=['raw simulation and validation logs','CSV','README'],
        sha256={str(p.relative_to(archive)):sha(p) for p in sorted(archive.rglob('*')) if p.is_file() and p.name!='ARTIFACTS.json'}))
    relative=str(archive.relative_to(ROOT))
    write(ROOT/'SOURCE.json',dict(branch=result['branch'],abi=ABI,hash_backend='shake',
        current_manifest=relative+'/SOURCE.json',previous_import_manifest=str(old.relative_to(ROOT))+'/SOURCE.json',
        scope='six SLH-DSA plus six standard XMSS/LMS profiles; fixed K1U1',
        current_extended_rtl_source_equivalence_claimed=False,historical_source_proof_scope=old_name))
    write(ROOT/'VALIDATION.json',dict(status=result['status'],branch=result['branch'],abi=ABI,
        report=relative+'/reports/Stateful_Extension.json',area=area,required_default_cases=28,
        actual_rtl_cases=result['rtl_case_count'],slh_baseline_equal_cases=len(comparisons),
        statuses=statuses,routed_frequency_measured=False,assumed_frequency_MHz=100,
        high_tree_full_operations=result['high_tree_full_operations']))
    print('STATEFUL_EXTENSION_REPORT',result['status'],reports/'Stateful_Extension.md')
    if args.require_complete and not complete:raise SystemExit('mandatory validation is incomplete')
if __name__=='__main__':main()
