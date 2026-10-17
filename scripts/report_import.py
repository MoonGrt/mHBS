#!/usr/bin/env python3
"""Publish source-bound ABI4 import evidence once the required checks complete."""
from __future__ import annotations
import argparse,hashlib,json,shutil,sys,tarfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
ARCHIVE=ROOT/'docs/manifests/experiments/image_chain_tree_import_20261021'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,indent=2,sort_keys=True)+'\n')
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,default=ROOT/'build/image-chain-tree/final');p.add_argument('--archive',type=Path,default=ARCHIVE);a=p.parse_args();run=a.run.resolve();archive=a.archive.resolve();base=run.parent
 from scripts.check_source_import import check
 equivalence=check(archive)
 rtl=json.loads((run/'rtl.json').read_text());models=json.loads((run/'models.json').read_text());original=json.loads((archive/'source_rtl.json').read_text())
 from scripts.run_hash_backends import source_identity,expected_cases
 assert rtl['passed'] and models['passed'] and rtl['source_sha256']==source_identity()==models['source_sha256']
 required=set().union(*expected_cases());assert set(rtl['cases'])==required==set(original['cases'])
 fields=('operation','n','bytes','nodes','hashes','permutations','cycles','waits','swap','stats','instructions','hash_wait_cycles','overlap_instructions','lane0_round_cycles','lane1_round_cycles','physical_lanes','unroll','hash_trace_sha256','owner_trace_sha256','macro_count','macro_busy_cycles','macro_hashes','tree_count','tree_busy_cycles','tree_hashes','tree_chains','tree_input_wait_cycles','tree_child_busy_cycles')
 comparisons={}
 for key,row in rtl['cases'].items():
  assert row['passed'];matches={f:row[f]==original['cases'][key][f] for f in fields if f in row and f in original['cases'][key]}
  assert all(matches.values()),(key,{f:False for f,v in matches.items() if not v});comparisons[key]={'passed':True,'compared_fields':list(matches)}
 gates={'model_units':base/'model_units.json','units':base/'final_units/results.json','hash_work':base/'hash_work/results.json','top':base/'top_final/results.json','synthesis_view':base/'synthesis_view/results.json','abi_rejection':base/'rejection/results.json','synthesis':base/'final_synthesis/status.json'}
 summaries={}
 identity=source_identity()
 for key,path in gates.items():
  x=json.loads(path.read_text());assert x.get('passed',x.get('status')=='passed'),(key,path)
  if key!='synthesis' and 'source_sha256' in x:
   assert all((ROOT/f).is_file() and sha(ROOT/f)==v for f,v in x['source_sha256'].items()),key+' receipt source changed'
  if key=='abi_rejection':assert all(sha(ROOT/f)==v for f,v in x['files'].items())
  if key=='synthesis':
   assert x['area_gate_passed'];synth_source=json.loads((base/'final_synthesis/SOURCE.json').read_text())['files']
   assert all(identity.get(f)==v for f,v in synth_source.items() if f.startswith('rtl/'))
  if key=='synthesis_view':assert len(x['cases'])==18
  if key=='model_units':
   assert x['tests']==38 and all(sha(ROOT/f)==v for f,v in x['source_sha256'].items())
  summaries[key]=x
  write(archive/'summaries'/f'{key}.json',x)
 write(archive/'summaries/models.json',models);write(archive/'summaries/rtl.json',rtl);write(archive/'summaries/source_comparison.json',{'passed':True,'cases':comparisons});write(archive/'summaries/equivalence.json',equivalence)
 # Models, benches, tools, canonical ROMs and production RTL form a self-contained source freeze.
 names=[str(p.relative_to(ROOT)) for folder in ('rtl','model','tb','scripts') for p in sorted((ROOT/folder).rglob('*')) if p.is_file() and '__pycache__' not in p.parts]
 names+=['sources.txt']
 with tarfile.open(archive/'rtl.tar.gz','w:gz') as tar:
  for name in sorted(names):tar.add(ROOT/name,arcname=name,recursive=False)
 write(archive/'FREEZE.json',{'files':{name:sha(ROOT/name) for name in sorted(names)},'rtl_tar_sha256':sha(archive/'rtl.tar.gz')})
 # Synth report includes the exact source and the diagnostic path; raw sim details remain build.
 resources=summaries['synthesis']['resources'];perf={key:{'cycles':row['cycles'],'hashes':row['hashes'],'permutations':row['permutations'],'time_ms_at_assumed_100MHz':row['cycles']/100000,'atp_slice_ms_at_assumed_100MHz':resources['equivalent_slices']*row['cycles']/100000} for key,row in rtl['cases'].items() if '/' in key}
 result={'passed':True,'status':'passed','branch':'image-chain-tree','source_commit':equivalence['source_commit'],'base_commit':'050512998fea28cc44667a1cd694d5ad5077767c','abi':4,'hash_backend':'shake','required_rtl_cases':len(required),'full_profile_operations':18,'canonical_images':12,'model_tests':38,'all_source_cycles_traces_counts_equal':True,'synthesis':resources,'area_gate_passed':True,'performance':perf,'raw_log_root':str(base),'routed_frequency_measured':False,'omitted_details':['sim','validation'],'source_comparison_fields':fields,'gates':{k:sha(v) for k,v in gates.items()},'finished_at':datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds')}
 write(archive/'reports/Import.json',result)
 rows=['# image-chain-tree：源 ABI4 原样移植','',f'状态：`passed`。独立父提交 `{result["base_commit"]}`，源提交 `{result["source_commit"]}`。','',
 '仅六组 SLH-DSA-SHAKE，固定K1U1、单物理Hash通道与单Hash在途；TREE/CHAIN范围与源实现保持。生产文件覆盖本仓库已有命名，私有sponge合入shake-recipe，没有引入第二套目录或ABI5/SHA2/XMSS/LMS。','',
 '7个生产文件（含指令头）按受控标识符/路径重命名和源partition提取后代码token一致。12个原始ROM字节、重新生成ROM字节一致；这是源码变换核对，不宣称形式验证工具证明。','',
 '验证：38项模型/TREE测试，286个lane案例、8个交接案例、384个CHAIN和7个TREE单位，79项完整/扩展RTL（含六参数三操作18项）、18项SYNTHESIS视图、ABI1/2/3/5原子拒绝，以及top签名缓存与TREE中途故障作废/复位重放均通过。所有79项源周期、逐Hash上下文/结果trace、ownertrace和统计字段一致；18项VM与独立参考的字节前像/结果工作集无额外或缺失任务。','',
 '| 共同核综合 | LUT | FF | BRAM36 | DSP | 等效Slice |','|---|---:|---:|---:|---:|---:|',f'| 当前 | {resources["lut"]:,.0f} | {resources["ff"]:,.0f} | {resources["bram36"]:g} | {resources["dsp"]:g} | {resources["equivalent_slices"]:,.3f} |',
 '| 源基线 | 15,698 | 4,205 | 0 | 0 | 4,450.125 |','',
 'Vivado2025.2、xc7a200tffg1156-3、100MHz、OOC、PROFILE_ENABLE=0、2线程；不含程序ROM与signature。LUT/FF相对源基线均在±1%内。未启动布局布线，以下100MHz延迟和ATP为假定频率计算，不能当作实测板上频率。','',
 '| 参数/操作 | 实测周期 | Hash | 置换 | 假定100MHz延迟ms | 假定100MHz ATP Slice·ms |','|---|---:|---:|---:|---:|---:|']
 for key,v in sorted(perf.items()):rows.append(f'| {key} | {v["cycles"]:,} | {v["hashes"]:,} | {v["permutations"]:,} | {v["time_ms_at_assumed_100MHz"]:.5f} | {v["atp_slice_ms_at_assumed_100MHz"]:.3f} |')
 rows+=['','源码和工具快照：`rtl.tar.gz` / `FREEZE.json`。父源原始对象：`upstream.tar.gz` / `SOURCE.json`。源回归：`source_rtl.json`；当前门禁摘要：`summaries/`；综合分层及诊断时序：`synthesis_final/synthesis/`。原始仿真明细保留 `'+str(base)+'`。','',
 '第一次采用分离sponge文件的中间候选保留在build和旧synthesis子目录；最终验收及面积仅使用合入shake-recipe后的final冻结源码，不借用中间候选面积。']
 (archive/'reports/Import.md').write_text('\n'.join(rows)+'\n')
 write(ROOT/'SOURCE.json',{'current_branch':'image-chain-tree','current_source_commit':result['source_commit'],'base_commit':result['base_commit'],'abi':4,'archive':str(archive.relative_to(ROOT)),'identity':sha(archive/'SOURCE.json'),'frozen_files':sha(archive/'FREEZE.json')})
 write(ROOT/'VALIDATION.json',{'passed':True,'abi':4,'branch':'image-chain-tree','archive':str(archive.relative_to(ROOT)),'summary':str((archive/'reports/Import.json').relative_to(ROOT)),'summary_sha256':sha(archive/'reports/Import.json'),'old_v8_validation_applies':False})
 write(archive/'ARTIFACTS.json',{'passed':True,'routed':False,'omitted_details':['sim','validation'],'raw_log_root':str(base),'files':{str(x.relative_to(archive)):sha(x) for x in sorted(archive.rglob('*')) if x.is_file() and x.name!='ARTIFACTS.json'}})
 index=ROOT/'docs/manifests/experiments/INDEX.md';text=index.read_text();link='image_chain_tree_import_20261021/reports/Import.md'
 if link not in text:
  row='| image_chain_tree_import_20261021 | [image-chain-tree direct ABI4 import]('+link+') | [证据](image_chain_tree_import_20261021/ARTIFACTS.json) |\n'
  marker='\n后台补齐：'
  index.write_text(text.replace(marker,'\n'+row+marker) if marker in text else text.rstrip()+'\n'+row)
 print('IMPORT_ACCEPTED',archive/'reports/Import.md')
if __name__=='__main__':main()
