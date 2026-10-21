#!/usr/bin/env python3
"""Build a portable measured area/cycle/ATP comparison from frozen evidence."""
import argparse, hashlib, json, re, shutil, tarfile
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text())
def write(path,data):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n')
def area(path):
 s=path.read_text();d={}
 for key,label in [('lut','Slice LUTs'),('ff','Slice Registers'),('bram','Block RAM Tile'),('dsp','DSPs')]:
  m=re.search(r'^\|\s*'+re.escape(label)+r'\*?\s*\|\s*([\d.]+)',s,re.M)
  if not m:raise AssertionError('Missing '+label)
  d[key]=float(m[1])
 d['equivalent_slice']=d['lut']/4+d['ff']/8+232.4*d['bram']+102.4*d['dsp'];return d

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);p.add_argument('--out',type=Path,required=True);args=p.parse_args();config=read(args.config);out=args.out.resolve();out.mkdir(parents=True,exist_ok=True);rows=[];proofs={};validation_summary={}
 for branch,entry in config['architectures'].items():
  val=Path(entry['validation']);state=read(val/'VALIDATION_SUMMARY.json');meta=read(val/'SOURCE.json');old=read(val/'BASELINE.json')
  if not state.get('complete') or not state.get('passed'):raise AssertionError('Validation incomplete: '+branch)
  evidence=out/'evidence'/branch;evidence.mkdir(parents=True,exist_ok=True)
  for name in ('SOURCE.json','BASELINE.json','VALIDATION_SUMMARY.json','candidate_rtl.tar.gz','SIGN_INDEX_VALIDATION.json','EMPTY_MESSAGE_VALIDATION.json','SIGN_SUPPLEMENTS_SOURCE.json'):
   if (val/name).exists():shutil.copy2(val/name,evidence/name)
  supplements={}
  for name in ('SIGN_INDEX_VALIDATION.json','EMPTY_MESSAGE_VALIDATION.json'):
   record=read(val/name)
   if not record.get('complete') or record.get('passed')!=record.get('required'):raise AssertionError('Supplement not passed: '+branch+'/'+name)
   supplements[name]=record['passed']
  validation_summary[branch]=dict(core=state['counts'],checks=len(state['checks']),supplements=supplements,source_unchanged=state.get('source_unchanged'))
  sha_map=meta['sha256'];measured={}
  for backend,measurement in entry['synthesis'].items():
   mroot=Path(measurement['directory']);mmeta=read(Path(measurement['source_manifest']));msha=mmeta.get('source_sha256',mmeta.get('sha256',{}));prod=[n for n in sha_map if n.startswith('rtl/') or n=='sources.txt']
   mismatch={n:dict(sim=sha_map[n],synthesis=msha.get(n)) for n in prod if msha.get(n)!=sha_map[n]}
   # Header files may be tracked separately by synthesis; verify their frozen tar.
   if mismatch:
    tarname=measurement.get('rtl_tar')
    if tarname:
     with tarfile.open(tarname) as tar:
      members={m.name.removeprefix('./'):m for m in tar.getmembers() if m.isfile()}
      for n in list(mismatch):
       if n in members and hashlib.sha256(tar.extractfile(members[n]).read()).hexdigest()==sha_map[n]:del mismatch[n]
   if mismatch:raise AssertionError('Simulation/synthesis source mismatch '+str(mismatch))
   util=mroot/measurement.get('utilization','utilization.rpt');new=area(util);previous=old['synthesis'][backend]['area'];measured[backend]=new
   target=evidence/'synthesis'/backend;target.mkdir(parents=True,exist_ok=True)
   for source in mroot.iterdir():
    if source.is_file() and source.suffix in ('.rpt','.json','.log','.txt','.xdc'):shutil.copy2(source,target/source.name)
   shutil.copy2(measurement['source_manifest'],target/'MEASUREMENT_SOURCE.json')
   proofs[branch+'/'+backend]=dict(same_production_rtl=True,sha256={n:sha_map[n] for n in prod},new_area=new,old_area=previous)
   for profile in ('slh_128f','xmss_h10','lms_h10'):
    key='/'.join((backend,profile,'sign'));r=state['tests'][key];before=old['tests'][key]
    if r['primitive_trace']!=before['primitive_trace']:raise AssertionError('Workload changed '+key)
    atp=new['equivalent_slice']*r['cycles']/100000;before_atp=previous['equivalent_slice']*before['cycles']/100000
    rows.append(dict(architecture=branch,backend=backend,profile=profile,old_area=previous,new_area=new,old_cycles=before['cycles'],cycles=r['cycles'],hashes=r['hashes'],blocks=r['permutations'],old_atp=before_atp,atp=atp,area_change_pct=100*(new['equivalent_slice']/previous['equivalent_slice']-1),cycles_change_pct=100*(r['cycles']/before['cycles']-1),atp_change_pct=100*(atp/before_atp-1)))
 passed=all(r['new_area']['equivalent_slice']<r['old_area']['equivalent_slice'] and r['cycles']<r['old_cycles'] and r['atp']<r['old_atp'] for r in rows)
 result=dict(schema='mhbs.macro_atp_restart.v1',generated_at=datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds'),frequency_mhz_assumed=100,routed=False,scope='K1U1 common, excludes ROM and signature cache; 100 MHz is an assumption and synthesis diagnostic constraint',acceptance_passed=passed,validation=validation_summary,source_binding=proofs,results=rows,rejected_candidates=config.get('rejected_candidates',[]),changes=config.get('changes',{}))
 write(out/'reports/Macro_ATP_Restart.json',result)
 lines=['# image-chain / image-chain-tree 面积与周期优化','',f"更新时间：{result['generated_at']}；联合验收：{passed}。",'',
  '面积口径为K1U1共同核，不含program/template/descriptor ROM及签名缓存；Vivado2025.2、xc7a200tffg1156-3、OOC、通用Keccak、2线程、默认时序驱动综合。',
  '周期为真实完整Sign测量。ATP=等效Slice×周期/100000，单位Slice·ms，假定100MHz；未布线，也不以综合WNS宣称实际频率。','',
  '| 设计 | 后端 | 原LUT | 新LUT | 原FF | 新FF | 原等效Slice | 新等效Slice | 面积变化 |','|---|---|---:|---:|---:|---:|---:|---:|---:|']
 seen=set()
 for r in rows:
  key=(r['architecture'],r['backend'])
  if key in seen:continue
  seen.add(key);a=r['old_area'];b=r['new_area'];lines.append(f"| {key[0]} | {key[1]} | {a['lut']:,.0f} | {b['lut']:,.0f} | {a['ff']:,.0f} | {b['ff']:,.0f} | {a['equivalent_slice']:,.3f} | {b['equivalent_slice']:,.3f} | {r['area_change_pct']:.3f}% |")
 for profile in ('slh_128f','xmss_h10','lms_h10'):
  lines+=['',f'## {profile} Sign','', '| 设计 | 后端 | 原周期 | 新周期 | 周期变化 | 原ATP | 新ATP | ATP变化 |','|---|---|---:|---:|---:|---:|---:|---:|']
  for r in rows:
   if r['profile']==profile:lines.append(f"| {r['architecture']} | {r['backend']} | {r['old_cycles']:,} | {r['cycles']:,} | {r['cycles_change_pct']:.3f}% | {r['old_atp']:,.3f} | {r['atp']:,.3f} | {r['atp_change_pct']:.3f}% |")
 lines+=['','## 实现与验证','']
 for branch,changes in result['changes'].items():lines.append(branch+'：'+'；'.join(changes)+'。')
 for branch,v in validation_summary.items():lines.append(f"{branch}：完整三操作/高树Verify {v['core']['passed']}/44，附加检查{v['checks']}项；q=1/1023完整Sign8项及空消息Sign4项通过。")
 lines+=['','输出、公钥/签名缓存逐字节核对；Hash/块数及实际前像/完整结果指纹与相同冻结向量的认证基线一致。指纹采用count/SUM256/XOR256，是概率性补充检查。',
 'h16/h15/h20只执行真实高度Verify，完整Keygen/Sign未执行；h20完整树仍按要求停止。',
 '镜像、外部端口和两分支控制粒度保持；优化不靠删减标准配方或密码学Hash工作量。','', '## 未采用候选','']
 for record in result['rejected_candidates']:lines.append('- '+record)
 (out/'reports/Macro_ATP_Restart.md').write_text('\n'.join(lines)+'\n')
 (out/'tools').mkdir(exist_ok=True);shutil.copy2(__file__,out/'tools/report_macro_atp_restart.py');write(out/'CONFIG.json',config)
 write(out/'ARTIFACTS.json',dict(complete=True,acceptance_passed=passed,sha256={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p.name!='ARTIFACTS.json'}))
 print(json.dumps(dict(report=str(out/'reports/Macro_ATP_Restart.md'),acceptance_passed=passed,rows=len(rows)),indent=2))
 if not passed:raise SystemExit(1)
if __name__=='__main__':main()
