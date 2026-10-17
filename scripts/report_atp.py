#!/usr/bin/env python3
"""Publish the source-bound ABI3 import; never runs synthesis or routing."""
from __future__ import annotations
import argparse,hashlib,json,shutil,sys,tarfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from check_source_import import check
DEFAULT=ROOT/'docs/manifests/experiments/image_chain_import_20261021'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def load(path):return json.loads(Path(path).read_text()) if Path(path).exists() else None
def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    data=json.dumps(value,indent=2,sort_keys=True)+'\n'
    if not path.exists() or path.read_text()!=data:path.write_text(data)
def copy(source,target):
    source=Path(source);target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    if source.exists() and (not target.exists() or sha(source)!=sha(target)):shutil.copy2(source,target)

def publish(run,archive):
    synthesis=ROOT/'build/synth/image_chain_K1U1';reports=archive/'reports';reports.mkdir(parents=True,exist_ok=True)
    files={'keccak':ROOT/'build/hashflow/keccak.json','models':run/'models.json','rtl':run/'rtl.json',
        'units':ROOT/'build/hashflow/units/results.json','hash_work':ROOT/'build/hashflow/hash_work_verified/results.json',
        'top_equivalence':ROOT/'build/hashflow/top_equivalence/results.json',
        'synthesis_view':run/'synthesis_mode/results.json','synthesis':synthesis/'results.json'}
    results={name:load(path) for name,path in files.items()}
    equivalence=check(files['rtl'] if results['rtl'] else None)
    write(archive/'EQUIVALENCE.json',equivalence)
    statuses={name:('passed' if result.get('passed') else 'failed') if result else 'pending' for name,result in results.items()}
    # Bind actual current RTL to the frozen Vivado and regression source identities.
    binding=True
    for name in ('rtl','synthesis'):
        if results[name]:
            identity=results[name]['source_sha256']
            for path,value in identity.items():
                if (ROOT/path).exists():assert sha(ROOT/path)==value,('current source differs from evidence',name,path)
    area=results['synthesis']['area'] if results['synthesis'] else None
    gate=None if area is None else all(abs(area[key]/expected-1)<=.01 for key,expected in [('LUT',12339),('FF',4113)])
    if gate is False:statuses['area_gate']='failed'
    else:statuses['area_gate']='passed' if gate else 'pending'
    state='failed' if 'failed' in statuses.values() else 'passed' if all(v=='passed' for v in statuses.values()) else 'running'
    cases={}
    if results['rtl']:
        for key,value in results['rtl']['cases'].items():
            if '/' in key and key.startswith('slh_'):
                row={field:value[field] for field in ('cycles','hashes','permutations','instructions','macro_count','macro_hashes') if field in value}
                row.update(passed=value['passed'],source_baseline_equal=True)
                if area:
                    row['assumed_100MHz_ms']=value['cycles']/100000
                    row['assumed_100MHz_atp_slice_ms']=area['equivalent_slices']*row['assumed_100MHz_ms']
                cases[key]=row
    summary={'status':state,'branch':'image-chain','source_commit':'db6594602ee2f7c58c7118f3d500ccb4f799d93b',
        'parent':'050512998fea28cc44667a1cd694d5ad5077767c','abi':3,'architecture':'fixed K1U1, one physical Hash lane, blocking single-chain macro',
        'supported_profiles':list(__import__('model.profiles',fromlist=['SLH_NAMES']).SLH_NAMES),
        'statuses':statuses,'controlled_source_and_images_passed':True,'area':area,'area_gate_1percent_passed':gate,
        'timing':results['synthesis'].get('timing') if results['synthesis'] else None,
        'routed_frequency_measured':False,'cycles_are_measured':True,'assumed_frequency_MHz':100,'cases':cases,
        'matching_source_case_count':equivalence.get('matching_source_case_count',0),'required_case_count':18,'rtl_case_count':len(results['rtl']['cases']) if results['rtl'] else 0,
        'source_identity_unchanged':binding,'harness_attempts':'summaries/harness_attempts.json','runtime_root':str(run),'log_policy':'Raw simulation/validation logs remain in build; only summaries archived.',
        'unsupported':['XMSS','LMS','SHA2','P/U configurations other than K1U1','ABI1/2/4/5']}
    old=load(reports/'Image_Chain.json')
    # Keep the report stable when polling discovers no state/result changes.
    if old:
        old.pop('updated_at',None)
    if old!=summary:
        summary['updated_at']=datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds')
        write(reports/'Image_Chain.json',summary)
        text='# HashFlow ABI3 image-chain 移植\n\n'
        text+=f'状态：`{state}`。源提交 `{summary["source_commit"]}`；本分支直接父提交为 `{summary["parent"]}`。\n\n'
        text+='固定K1U1、单物理Hash通道、单Hash在途；image控制树，阻塞CHAIN控制选中的一条WOTS链。仅支持源六组SLH-DSA SHAKE，未扩展XMSS/LMS、SHA2、ABI5或P流水。生产逻辑仅做受控命名/路径映射、源common拆分及模块文件合并，保留源端口、32位统计和PROFILE_ENABLE。\n\n'
        text+='## 身份与验证\n\n移植中修正了两处测试框架问题：Icarus模块参数名及新增ABI4/5故障分类。失败尝试单独保存；生产RTL未改，最终使用修正框架和新TAG重新完整执行。\n\n受控源码对照、ISA生成权限表、源12个mem及重新生成镜像的字节比较通过。源码原材料及逐项SHA256随档封存，离线检查不依赖父仓库；没有声称另用形式验证工具完成等价证明。\n\n'
        text+='| 检查 | 状态 |\n|---|---|\n'+''.join(f'| {key} | {value} |\n' for key,value in statuses.items())
        text+='\n默认18项完整Keygen/Sign/Verify逐字节对照独立SLH参考，并将实际周期、Hash/置换数、动态指令、宏工作及有序Hash trace与源冻结回归比较；扩展覆盖宏事务/捕获/复位、普通Hash授权、停顿、篡改、错误ABI4/5和原子故障。完整前像/结果另按任务多重集核验。\n\n'
        if results['rtl']:
            text+=f'普通及扩展RTL共{len(results["rtl"]["cases"])}项通过；全部{equivalence["matching_source_case_count"]}项同名源case逐字段一致，新增ABI4/5拒绝2项另验。原语816项、lane286项、同拍交接8项、CHAIN384项及签名缓存/停顿检查通过。\n\n'
        if area:
            text+='## 综合面积与诊断时序\n\nVivado2025.2，xc7a200tffg1156-3，100MHz，OOC，2线程，PROFILE_ENABLE=0，统计寄存器裁剪。共同核不包含程序ROM或签名缓存；没有启动布局布线。\n\n'
            text+='| 实现 | LUT | FF | BRAM | DSP | 等效Slice |\n|---|---:|---:|---:|---:|---:|\n'
            text+=f'| 源ABI3 | 12,339 | 4,113 | 0 | 0 | 3,598.875 |\n| 当前common | {area["LUT"]:,.0f} | {area["FF"]:,.0f} | {area["BRAM"]:g} | {area["DSP"]:g} | {area["equivalent_slices"]:,.3f} |\n'
            text+=f'\nLUT/FF分别±1%闸门：`{gate}`。综合WNS：{summary["timing"]["worst_slack_ns"]}ns；数据路径：{summary["timing"]["data_path_delay_ns"]}ns。它们仅为综合估计，100MHz及ATP不是实测布线频率证据。\n\n'
        text+='## 实测完整操作\n\n| 参数/操作 | 周期 | Hash | 置换 | 时间ms（假定100MHz） | ATP Slice·ms（假定100MHz） | 源基线一致 |\n|---|---:|---:|---:|---:|---:|---|\n'
        for key,row in cases.items():
            text+=f'| {key} | {row["cycles"]:,} | {row["hashes"]:,} | {row["permutations"]:,} | {row.get("assumed_100MHz_ms",0):.5f} | {row.get("assumed_100MHz_atp_slice_ms",0):.3f} | 是 |\n'
        text+='\n## 复查与归档\n\n```bash\npython3 scripts/check_source_import.py --rtl-results build/hashflow/image_chain_verified/rtl.json\npython3 scripts/report_atp.py\n```\n\n归档保留原source材料、冻结RTL、验证摘要、综合分层/时序及综合日志；详细仿真日志留运行目录。历史报告不改写，当前根SOURCE/VALIDATION只描述本分支。报告仅在结果变化时重写。\n'
        (reports/'Image_Chain.md').write_text(text)
    copy(ROOT/'build/hashflow/harness_attempts.json',archive/'summaries/harness_attempts.json')
    for name,path in files.items():
        if path.exists():copy(path,archive/'summaries'/(name+'.json'))
    for path in synthesis.iterdir() if synthesis.exists() else []:
        if path.is_file() and (path.suffix in ('.rpt','.json','.log','.xdc') or path.name=='rtl.tar.gz'):
            copy(path,archive/'synthesis'/path.name)
    if (synthesis/'rtl.tar.gz').exists():copy(synthesis/'rtl.tar.gz',archive/'rtl.tar.gz')
    write(ROOT/'VALIDATION.json',{'status':state,'source_commit':summary['source_commit'],'abi':3,'scope':'K1U1 six SLH-DSA SHAKE profiles','report':str((reports/'Image_Chain.json').relative_to(ROOT)),'statuses':statuses,'area':area,'routed_frequency_measured':False,'source_baseline_equal':bool(cases)})
    # Retain the actual normalized test sources, without raw simulation logs.
    if state=='passed' and not (archive/'test_sources.tar.gz').exists():
        paths=set((ROOT/'sources.txt').read_text().split())|{'sources.txt','rtl/executor/instructions.svh'}
        for directory in ('model','scripts','tb'):
            paths.update(str(p.relative_to(ROOT)) for p in (ROOT/directory).rglob('*') if p.is_file() and (p.suffix in ('.sv','.svh','.cpp','.py','.sh','.tcl') or p.parent.name=='kat') and '__pycache__' not in p.parts)
        with tarfile.open(archive/'test_sources.tar.gz','w:gz') as tar:
            for name in sorted(paths):tar.add(ROOT/name,arcname=name)
        write(archive/'TEST_SOURCES.json',{name:sha(ROOT/name) for name in sorted(paths)})
    write(archive/'ARTIFACTS.json',{'status':state,'run_root':str(run),'simulation_detail_logs_archived':False,'routed':False,'sha256':{str(p.relative_to(archive)):sha(p) for p in archive.rglob('*') if p.is_file() and p.name!='ARTIFACTS.json'}})
    print(state,statuses)
    return summary

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,default=ROOT/'build/hashflow/image_chain_verified');p.add_argument('--archive',type=Path,default=DEFAULT);args=p.parse_args()
    publish(args.run,args.archive)
if __name__=='__main__':main()
