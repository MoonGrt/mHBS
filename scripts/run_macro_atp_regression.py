#!/usr/bin/env python3
"""Reproduce complete macro-core correctness on an immutable source snapshot."""
import argparse, concurrent.futures as cf, hashlib, json, os, re, shutil, subprocess, sys, tarfile, threading, time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
LOW={'shake':('slh_128f','slh_192f','slh_256f','slh_128s','slh_192s','slh_256s','xmss_h10','lms_h10'),'sha2':('slh_128f','slh_128s','xmss_h10','lms_h10')}
HIGH=('xmss_h16','xmss_h20','lms_h15','lms_h20')
def now():return datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,data):
 p.parent.mkdir(parents=True,exist_ok=True);t=p.with_name(p.name+'.tmp');t.write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n');t.replace(p)
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--source',type=Path);p.add_argument('--run',type=Path);p.add_argument('--launch',action='store_true');a=p.parse_args();root=a.root.resolve()
 if a.launch:
  source=(a.source or root).resolve();branch=subprocess.check_output(['git','branch','--show-current'],cwd=root,text=True).strip();stamp=datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y%m%d_%H%M%S')
  run=root/'build/macro_atp_acceptance'/stamp;out=root/'docs/manifests/experiments'/('macro_atp_acceptance_'+stamp);run.mkdir(parents=True);out.mkdir(parents=True)
  src=run/'source';identity={}
  for folder in ('rtl','model','scripts','tb'):
   for path in (source/folder).rglob('*'):
    if not path.is_file() or '__pycache__' in path.parts or path.suffix not in ('.sv','.svh','.py','.sh','.cpp','.c','.tcl','.xdc','.mem','.json'):continue
    name=path.relative_to(source);target=src/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target);identity[str(name)]=sha(target)
  shutil.copy2(source/'sources.txt',src/'sources.txt');identity['sources.txt']=sha(src/'sources.txt')
  shutil.copy2(__file__,src/'scripts/run_macro_atp_regression.py');identity['scripts/run_macro_atp_regression.py']=sha(src/'scripts/run_macro_atp_regression.py')
  base_name='template_chain_20261021_151824' if branch=='image-chain' else 'template_tree_20261021_150603';base=root/'docs/manifests/experiments'/base_name
  shutil.copy2(base/'VALIDATION_SUMMARY.json',out/'BASELINE.json')
  meta=dict(branch=branch,root=str(root),source=str(src),measured_source=str(source),run=str(run),archive=str(out),baseline=base_name,baseline_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),sha256=identity,created_at=now(),high_full_trees=False,route=False)
  write(run/'SOURCE.json',meta);write(out/'SOURCE.json',meta)
  with tarfile.open(out/'candidate_rtl.tar.gz','w:gz') as tar:
   for name in sorted(identity):
    if name.startswith('rtl/') or name=='sources.txt':tar.add(src/name,arcname=name)
  sys.path.insert(0,str(src));from model.vectors import generate_verify_profile
  defaults=json.loads((src/'model/default_jobs.json').read_text())
  for b in LOW:
   for n in HIGH:generate_verify_profile(n,defaults[n],run/'high_vectors'/b,b)
  with (run/'runner.log').open('w') as log:
   task=subprocess.Popen([sys.executable,str(src/'scripts/run_macro_atp_regression.py'),'--root',str(root),'--run',str(run)],cwd=src,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
  write(run/'LAUNCH.json',dict(pid=task.pid,run=str(run),report=str(out/'reports/Macro_ATP_Acceptance.md')))
  with (root/'docs/manifests/experiments/INDEX.md').open('a') as index:index.write(f'\n| {stamp} | {branch} ATP optimization complete regression | [报告](macro_atp_acceptance_{stamp}/reports/Macro_ATP_Acceptance.md) | 后台运行；无高树完整操作；不布线 |\n')
  print((run/'LAUNCH.json').read_text());return
 run=a.run.resolve();meta=json.loads((run/'SOURCE.json').read_text());src=Path(meta['source']);out=Path(meta['archive']);baseline=json.loads((out/'BASELINE.json').read_text());lock=threading.RLock()
 cases=[(b,n,o) for b,names in LOW.items() for n in names for o in ('keygen','sign','verify')]+[(b,n,'verify') for b in LOW for n in HIGH]
 cases.sort(key=lambda c:(0 if c[2]=='sign' and c[1] in ('slh_128f','xmss_h10','lms_h10') else 1,c))
 state=dict(complete=False,started_at=now(),tests={'/'.join(c):dict(status='pending') for c in cases},checks={})
 def publish():
  state['updated_at']=now();state['counts']={s:sum(r['status']==s for r in state['tests'].values()) for s in ('pending','running','passed','failed')}
  write(run/'status.json',state);write(out/'VALIDATION_SUMMARY.json',state);write(out/'reports/Macro_ATP_Acceptance.json',dict(source=meta,results=state))
  lines=[f"# {meta['branch']} ATP候选完整回归",'',f"更新时间：{now()}；完成：{state['complete']}。",'',f"44项整核：{state['counts']}。",'逐字节核对输出和签名缓存；核对64位Hash/块数；对相同冻结输入逐Hash前像和完整结果指纹进行count/SUM256/XOR256比较。指纹比较是概率性检查。',
   '高树只执行真实高度Verify；h16/h15/h20完整Keygen、Sign未执行。详细日志保留在build，不复制到归档。','', '| 后端/参数/操作 | 原周期 | 新周期 | Hash | 块数 | 状态 |','|---|---:|---:|---:|---:|---|']
  for key,r in state['tests'].items():lines.append('| '+' | '.join([key,str(baseline['tests'].get(key,{}).get('cycles','—')),str(r.get('cycles','—')),str(r.get('hashes','—')),str(r.get('permutations','—')),r['status']])+' |')
  lines+=['','附加检查：'+str({k:v['status'] for k,v in state['checks'].items()}),'',f'日志运行目录：`{run}`。']
  (out/'reports/Macro_ATP_Acceptance.md').write_text('\n'.join(lines)+'\n')
 def update(group,key,**data):
  with lock:state[group].setdefault(key,{}).update(data);publish()
 def command(cmd,log,env=None):
  log.parent.mkdir(parents=True,exist_ok=True)
  with log.open('w') as f:r=subprocess.run(cmd,cwd=src,env=dict(os.environ,**(env or {})),stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT)
  if r.returncode:raise RuntimeError('Exit '+str(r.returncode)+': '+str(log))
  return log.read_text()
 def simulate(case):
  b,n,o=case;key='/'.join(case);update('tests',key,status='running');started=time.monotonic()
  try:
   v=(run/'high_vectors'/b if n in HIGH else src/'tb/vectors'/('sha2' if b=='sha2' else ''))/n/o
   old=baseline['tests'][key];actual_identity={p.name:sha(p) for p in v.glob('*.mem')};same=actual_identity==old['vectors_sha256']
   if not same:raise AssertionError('Frozen vector identity differs from certified baseline; no trace reuse allowed')
   log=run/'sim'/b/(n+'_'+o+'.log');text=command(['bash','scripts/simulate_fast.sh',n,o,'1','1'],log,dict(HASH_BACKEND=b,VECTORS_DIR=str(v.parent.parent),SIM_FAST_OPT_SLOW='-O1',SIM_HASH_TRACE='1'))
   match=re.search(r'STATEFUL_PASS P1U1 op=(\d+) cycles=(\d+) total=(\d+) hashes=(\d+) permutations=(\d+)',text)
   if not match:raise AssertionError('Missing complete byte/count PASS')
   _,cycles,total,hashes,blocks=map(int,match.groups());trace=json.loads(re.search(r'HASH_TRACE_METRICS (\{[^\n]+)',text)[1]);expected=old['primitive_trace']
   if trace!=expected or hashes!=old['hashes'] or blocks!=old['permutations']:raise AssertionError('Primitive workload/result mismatch')
   update('tests',key,status='passed',cycles=cycles,total_cycles=total,hashes=hashes,permutations=blocks,primitive_trace=trace,vectors_sha256=actual_identity,baseline_vector_identity_equal=True,macro_metrics=json.loads(re.search(r'MACRO_METRICS (\{[^\n]+)',text)[1]),seconds=time.monotonic()-started,log=str(log),log_sha256=sha(log))
  except Exception as e:update('tests',key,status='failed',error=str(e),seconds=time.monotonic()-started)
 def check(key,cmd,env):
  update('checks',key,status='running');started=time.monotonic()
  try:
   log=run/'checks'/(key+'.log');text=command(cmd,log,env);update('checks',key,status='passed',seconds=time.monotonic()-started,log=str(log),log_sha256=sha(log),summary=text[-1800:])
  except Exception as e:update('checks',key,status='failed',error=str(e))
 checks=[]
 for b in LOW:
  for s in (False,True):checks.append((b+'_recipes'+('_synthesis' if s else ''),[sys.executable,'scripts/check_recipes.py','--hash',b,'--pipeline','1','--unroll','1']+(['--synthesis'] if s else []),None))
  checks.append((b+'_signature_views',[sys.executable,'scripts/check_top_signature.py','--hash',b],None))
  for n in ('slh_128f','xmss_h10','lms_h10'):
   checks.append((b+'_'+n+'_stall_reset',['bash','scripts/simulate.sh',n,'verify','1','1','+STALL=1','+REPLAYS=2','+INTERRUPT=1'],dict(HASH_BACKEND=b)))
   checks.append((b+'_'+n+'_truncate',['bash','scripts/simulate.sh',n,'verify','1','1','+CUT=2'],dict(HASH_BACKEND=b)))
   for tamper in (1,2,3,4,5):checks.append((b+'_'+n+'_tamper'+str(tamper),['bash','scripts/simulate.sh',n,'verify','1','1','+TAMPER='+str(tamper)],dict(HASH_BACKEND=b)))
  for n in ('xmss_h10','lms_h10'):checks.append((b+'_'+n+'_q_overflow',['bash','scripts/simulate.sh',n,'verify','1','1','+Q=1024','+INVALID=1'],dict(HASH_BACKEND=b)))
 if meta['branch']=='image-chain':checks.append(('control_faults',[sys.executable,'scripts/check_chain_controls.py'],None))
 publish()
 with cf.ThreadPoolExecutor(max_workers=4) as sim,cf.ThreadPoolExecutor(max_workers=2) as aux:
  jobs=[sim.submit(simulate,c) for c in cases]+[aux.submit(check,*row) for row in checks]
  for f in cf.as_completed(jobs):f.result()
 state['complete']=True;state['finished_at']=now();state['source_unchanged']=all(sha(src/name)==value for name,value in meta['sha256'].items());state['passed']=state['source_unchanged'] and all(r['status']=='passed' for g in ('tests','checks') for r in state[g].values());publish()
 write(out/'ARTIFACTS.json',dict(complete=True,passed=state['passed'],sha256={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p.name!='ARTIFACTS.json'}))
 raise SystemExit(0 if state['passed'] else 1)
if __name__=='__main__':main()
