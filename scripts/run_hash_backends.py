#!/usr/bin/env python3
"""Freeze explicit program tree control with main CHAIN templates; run K1U1 checks."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import argparse,hashlib,json,os,re,shutil,subprocess,sys,tarfile,threading,time
ROOT=Path(os.environ.get('MHBS_TEMPLATE_ROOT',Path(__file__).resolve().parents[1])).resolve()
BASELINE='050512998fea28cc44667a1cd694d5ad5077767c'
LOW={'shake':('slh_128f','slh_192f','slh_256f','slh_128s','slh_192s','slh_256s','xmss_h10','lms_h10'),'sha2':('slh_128f','slh_128s','xmss_h10','lms_h10')}
HIGH=('xmss_h16','xmss_h20','lms_h15','lms_h20')
def now():return datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,data):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);t=p.with_name(p.name+'.tmp');t.write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n');t.replace(p)
def cases():return [(b,n,o) for b,ns in LOW.items() for n in ns for o in ('keygen','sign','verify')]+[(b,n,'verify') for b in LOW for n in HIGH]
def freeze(dest):
 names={'sources.txt'}
 for f in ('rtl','model','scripts','tb'):
  names.update(str(p.relative_to(ROOT)) for p in (ROOT/f).rglob('*') if p.is_file() and p.suffix in ('.sv','.svh','.py','.cpp','.c','.sh','.tcl','.xdc','.mem','.json') and '__pycache__' not in p.parts)
 out={}
 for n in sorted(names):
  src=ROOT/n;before=sha(src);dst=dest/n;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
  if sha(src)!=before or sha(dst)!=before:raise RuntimeError('Source changed while freezing')
  out[n]=before
 return out
def area(p):
 text=p.read_text();out={}
 for k,l in [('lut','Slice LUTs'),('ff','Slice Registers'),('bram36','Block RAM Tile'),('dsp','DSPs')]:
  m=re.search(r'^\|\s*'+re.escape(l)+r'\*?\s*\|\s*([\d.]+)',text,re.M)
  if not m:raise ValueError('Missing '+l)
  out[k]=float(m[1])
 out['equivalent_slice']=out['lut']/4+out['ff']/8+232.4*out['bram36']+102.4*out['dsp'];return out
class Runner:
 def __init__(self,run):
  self.run=run;self.meta=json.loads((run/'SOURCE.json').read_text());self.out=Path(self.meta['archive']);self.lock=threading.RLock()
  self.src=run/'candidate/source';self.base=run/'baseline/source';sys.path.insert(0,str(self.src))
  from model.hash_trace import expected_trace
  self.expected=expected_trace
  self.state=dict(started_at=now(),complete=False,tests={'/'.join(c):dict(status='pending') for c in cases()},checks={},synthesis={b:dict(status='pending') for b in LOW},baseline_cycles={})
 def publish(self):
  with self.lock:
   s=self.state;s['updated_at']=now();s['counts']={x:sum(r['status']==x for r in s['tests'].values()) for x in ('pending','running','passed','failed')}
   write(self.run/'status.json',s);write(self.out/'VALIDATION_SUMMARY.json',s);write(self.out/'reports/Template_CHAIN.json',dict(source=self.meta,results=s))
   lines=['# image-chain：program 树控制与 CHAIN 模板','',f'更新时间：{now()}；'+('任务完成。' if s['complete'] else '后台运行中。'),'',f'基线 `{BASELINE}`；K1U1、SHAKE＋SHA2、单物理 Hash lane。',
    'program128×64、template32×64、descriptor32×64；CHAIN为整组链及叶构造；主树/FORS树由program控制，无TREE模板执行。',
    '默认SHAKE28项＋SHA2 16项；高树只执行真实高度Verify，独立合成兄弟路径，不计算完整树。',
    '实际填充块＋完整摘要的count/SUM256/XOR256指纹与VM/独立Verify任务集核对，同时逐字节核对输出和签名缓存。该指纹是概率校验。',
    '使用冻结main输入与原配方；逐Hash前像/结果与显式控制VM核对。链分支改变调度周期，旧opcode36设计属于历史尝试。',f"整核状态：{s['counts']}。",'',
    '| 后端 | LUT | FF | BRAM36 | 等效Slice | 状态 |','|---|---:|---:|---:|---:|---|']
   def fmt(x):return '—' if x is None else f'{x:,.3f}'
   for b,r in s['synthesis'].items():
    a=r.get('area',{});lines.append('| '+' | '.join([b,*[fmt(a.get(k)) for k in ('lut','ff','bram36','equivalent_slice')],r['status']+('；分析延后，继续运行' if r.get('analysis_deferred') else '')])+' |')
   lines+=['','100MHz仅用于共同核综合诊断及假定ATP，不含ROM/签名缓存，本轮不布线。','',
    '| 后端/参数/操作 | 周期 | Hash | 块 | ATP@100MHz Slice·ms | 主程序CHAIN | TREE | TREE子CHAIN | 状态 |','|---|---:|---:|---:|---:|---:|---:|---:|---|']
   for key,r in s['tests'].items():
    a=s['synthesis'][key.split('/')[0]].get('area',{});cycles=r.get('cycles');m=r.get('macro_metrics',{});atp=a['equivalent_slice']*cycles/100000 if cycles is not None and a else None
    lines.append('| '+' | '.join([key,*[fmt(r.get(k)) for k in ('cycles','hashes','permutations')],fmt(atp),*[fmt(m.get(k)) for k in ('CHAIN','TREE','TREE_child_CHAIN')],r['status']])+' |')
   lines+=['',f"附加检查：{len(s['checks'])}项，失败{sum(r['status']=='failed' for r in s['checks'].values())}。",'未验证：XMSS h16/h20、LMS h15/h20完整Keygen/Sign；h20完整树保持停止。',f'详细日志：`{self.run}`；归档仅保留摘要、冻结RTL和综合证据。','']
   p=self.out/'reports/Template_CHAIN.md';p.parent.mkdir(parents=True,exist_ok=True);p.write_text('\n'.join(lines))
 def update(self,g,k,**kw):
  with self.lock:self.state[g].setdefault(k,{}).update(kw);self.publish()
 def command(self,src,cmd,log,env=None):
  log.parent.mkdir(parents=True,exist_ok=True)
  with log.open('w') as f:p=subprocess.run(cmd,cwd=src,env=dict(os.environ,**(env or {})),stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT)
  if p.returncode:raise RuntimeError(f'Exit {p.returncode}: {log}')
  return log.read_text()
 def vector(self,b,n,o):return self.run/'verify_vectors'/b/n/o if n in HIGH else self.src/'tb/vectors'/('sha2' if b=='sha2' else '')/n/o
 def simulate(self,c):
  b,n,o=c;k='/'.join(c);v=self.vector(*c);self.update('tests',k,status='running',started_at=now());start=time.monotonic()
  try:
   log=self.run/'sim'/b/(n+'_'+o+'.log');text=self.command(self.src,['bash','scripts/simulate_fast.sh',n,o,'1','1'],log,dict(HASH_BACKEND=b,VECTORS_DIR=str(v.parent.parent),SIM_FAST_OPT_SLOW='-O1',SIM_HASH_TRACE='1'))
   m=re.search(r'STATEFUL_PASS P1U1 op=(\d+) cycles=(\d+) total=(\d+) hashes=(\d+) permutations=(\d+)',text)
   if not m:raise ValueError('Missing PASS')
   vals=list(map(int,m.groups()));macro=json.loads(re.search(r'MACRO_METRICS (\{[^\n]+)',text)[1]);actual=json.loads(re.search(r'HASH_TRACE_METRICS (\{[^\n]+)',text)[1]);expected=self.expected(v,n,o,b)
   if actual!=expected:raise AssertionError(f'Primitive multiset mismatch: {actual} vs {expected}')
   self.update('tests',k,status='passed',cycles=vals[1],total_cycles=vals[2],hashes=vals[3],permutations=vals[4],macro_metrics=macro,primitive_trace=actual,primitive_trace_matches=True,seconds=time.monotonic()-start,vectors_sha256={p.name:sha(p) for p in v.glob('*.mem')},log=str(log),log_sha256=sha(log))
  except Exception as e:self.update('tests',k,status='failed',error=str(e),seconds=time.monotonic()-start)
 def baseline(self,b):
  for n in LOW[b]:
   for o in ('keygen','sign','verify'):
    k='/'.join((b,n,o));self.update('baseline_cycles',k,status='running')
    try:
     v=self.vector(b,n,o);log=self.run/'sim/baseline'/b/(n+'_'+o+'.log');t=self.command(self.base,['bash','scripts/simulate_fast.sh',n,o,'1','1'],log,dict(HASH_BACKEND=b,VECTORS_DIR=str(v.parent.parent),SIM_FAST_OPT_SLOW='-O1'))
     m=re.search(r'cycles=(\d+) total=(\d+) hashes=(\d+) permutations=(\d+)',t)
     if not m:raise ValueError('No baseline PASS')
     self.update('baseline_cycles',k,status='passed',**dict(zip(('cycles','total_cycles','hashes','permutations'),map(int,m.groups()))))
    except Exception as e:self.update('baseline_cycles',k,status='failed',error=str(e))
 def check(self,k,cmd,env=None):
  self.update('checks',k,status='running')
  try:
   log=self.run/'checks'/(k+'.log');t=self.command(self.src,cmd,log,env);self.update('checks',k,status='passed',log=str(log),log_sha256=sha(log),summary=t[-1000:])
  except Exception as e:self.update('checks',k,status='failed',error=str(e))
 def synthesize(self,b):
  d=self.run/'synth'/b;d.mkdir(parents=True,exist_ok=True);self.update('synthesis',b,status='running',started_at=now());start=time.monotonic()
  try:
   with (d/'vivado.log').open('w') as log:
    p=subprocess.Popen([self.meta['vivado'],'-mode','batch','-nolog','-nojournal','-notrace','-source',str(self.src/'scripts/diagnose_timing.tcl'),'-tclargs',str(self.src),'1','1',str(d),'10.0'],cwd=d,env=dict(os.environ,HASH_BACKEND=b),stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    self.update('synthesis',b,pid=p.pid)
    while p.poll() is None:
     try:p.wait(timeout=30)
     except subprocess.TimeoutExpired:self.update('synthesis',b,analysis_deferred=time.monotonic()-start>=600,seconds=time.monotonic()-start)
   if p.returncode:raise RuntimeError('Vivado failed: '+str(d/'vivado.log'))
   a=area(d/'utilization.rpt')
   for f in d.iterdir():
    if f.suffix in ('.rpt','.log','.json','.txt','.xdc'):shutil.copy2(f,self.out/'synthesis'/b/f.name)
   self.update('synthesis',b,status='passed',area=a,analysis_deferred=False,seconds=time.monotonic()-start,debug_audit=json.loads((d/'debug_audit.json').read_text()))
  except Exception as e:self.update('synthesis',b,status='failed',error=str(e))
 def boundary(self,row):
  b,n=row['backend'],row['profile'];k=row['case'];v=Path(row['vector']);self.update('checks',k,status='running')
  try:
   log=self.run/'checks'/(k+'.log');t=self.command(self.src,['bash','scripts/simulate_fast.sh',n,'verify','1','1'],log,dict(HASH_BACKEND=b,VECTORS_DIR=str(v.parent.parent),SIM_FAST_OPT_SLOW='-O1',SIM_HASH_TRACE='1'))
   actual=json.loads(re.search(r'HASH_TRACE_METRICS (\{[^\n]+)',t)[1]);expected=self.expected(v,n,'verify',b)
   if actual!=expected:raise AssertionError('Boundary primitive multiset mismatch')
   self.update('checks',k,status='passed',q=row['q'],message_bytes=row['message_bytes'],primitive_trace=actual,log=str(log),log_sha256=sha(log))
  except Exception as e:self.update('checks',k,status='failed',error=str(e))
 def execute(self):
  self.publish();write(self.run/'STARTED.json',dict(pid=os.getpid(),time=now()));checks=[]
  # Both supplemental sign generators share this pinned native-reference cache.
  # Build it once before starting their parallel jobs.
  self.check('native_references',[sys.executable,'scripts/build_stateful_reference.py'])
  for b in LOW:
   checks.extend([(f'{b}_models',[sys.executable,'scripts/check_standard_models.py','--hash',b],None),(f'{b}_recipes',[sys.executable,'scripts/check_recipes.py','--hash',b,'--pipeline','1','--unroll','1'],None),(f'{b}_recipes_synthesis',[sys.executable,'scripts/check_recipes.py','--hash',b,'--pipeline','1','--unroll','1','--synthesis'],None),(f'{b}_statistics',[sys.executable,'scripts/check_statistics.py','--hash',b],None),(f'{b}_statistics_synthesis',[sys.executable,'scripts/check_statistics.py','--hash',b,'--synthesis'],None),(f'{b}_signature_views',[sys.executable,'scripts/check_top_signature.py','--hash',b],None)])
   for n in ('slh_128f','xmss_h10','lms_h10'):
    checks.append((f'{b}_{n}_protocol',['bash','scripts/simulate.sh',n,'verify','1','1','+STALL=1','+REPLAYS=2','+INTERRUPT=1'],dict(HASH_BACKEND=b)))
    for tamper in (1,2,3,4,5):checks.append((f'{b}_{n}_tamper{tamper}',['bash','scripts/simulate.sh',n,'verify','1','1',f'+TAMPER={tamper}'],dict(HASH_BACKEND=b)))
    checks.append((f'{b}_{n}_truncate',['bash','scripts/simulate.sh',n,'verify','1','1','+CUT=2'],dict(HASH_BACKEND=b)))
    checks.append((f'{b}_{n}_synthesis_verify',['bash','scripts/simulate_fast.sh',n,'verify','1','1'],dict(HASH_BACKEND=b,SIM_SYNTHESIS='1',SIM_FAST_OPT_SLOW='-O1',SIM_HASH_TRACE='1')))
   for n in ('xmss_h10','lms_h10'):
    checks.append((f'{b}_{n}_q_overflow',['bash','scripts/simulate.sh',n,'verify','1','1','+Q=1024','+INVALID=1'],dict(HASH_BACKEND=b)))
  checks.extend([('empty_message_sign',[sys.executable,'scripts/check_empty_messages.py','--source',str(self.src),'--run',str(self.run/'empty_messages'),'--archive',str(self.out)],None),('sign_indices',[sys.executable,'scripts/check_sign_indices.py','--source',str(self.src),'--run',str(self.run/'sign_indices'),'--archive',str(self.out)],None)])
  checks.extend([('chain_control_model',[sys.executable,'scripts/check_chain_model.py'],None),('chain_boundary_model',[sys.executable,'scripts/check_chain_boundaries.py'],None),('chain_rtl_controls',[sys.executable,'scripts/check_chain_controls.py'],None)])
  checks.extend([('backend_contracts',[sys.executable,'scripts/check_hash_backend_contracts.py'],None),('sha256_primitive',[sys.executable,'scripts/check_sha256.py','--pipeline','1','--unroll','1'],None),('keccak_primitive',[sys.executable,'scripts/check_keccak.py'],None)])
  with ThreadPoolExecutor(max_workers=4) as sim,ThreadPoolExecutor(max_workers=2) as base,ThreadPoolExecutor(max_workers=2) as synth,ThreadPoolExecutor(max_workers=2) as aux:
   jobs=[sim.submit(self.simulate,c) for c in cases()]+[synth.submit(self.synthesize,b) for b in LOW]+[aux.submit(self.check,*c) for c in checks]
   jobs += [aux.submit(self.boundary,row) for row in json.loads((self.run/'BOUNDARY_FIXTURES.json').read_text())]
   for f in as_completed(jobs):f.result()
  s=self.state;s['baseline_cycle_mismatches']=[];s['baseline_exact_cycle_required']=False
  s['complete']=True;s['acceptance_passed']=not s['baseline_cycle_mismatches'] and all(r['status']=='passed' for g in ('tests','checks','synthesis') for r in s[g].values());s['finished_at']=now();self.publish()
  write(self.out/'ARTIFACTS.json',dict(complete=True,acceptance_passed=s['acceptance_passed'],omitted_details=['sim','checks'],sha256={str(p.relative_to(self.out)):sha(p) for p in self.out.rglob('*') if p.is_file() and p.name!='ARTIFACTS.json'}))
  return 0 if s['acceptance_passed'] else 1

def launch():
 stamp=datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y%m%d_%H%M%S');run=ROOT/'build/template_chain'/stamp;out=ROOT/'docs/manifests/experiments'/('template_chain_'+stamp);run.mkdir(parents=True);out.mkdir(parents=True)
 src=run/'candidate/source';hashes=freeze(src);base=run/'baseline/source';shutil.copytree(src,base);rtl=(ROOT/'sources.txt').read_text().splitlines();baseline_hashes={}
 for n in rtl+['model/executor.py','model/mHBS.py','model/microcode.py','model/stateful.py','model/profiles.py','model/hashes.py']:
  d=subprocess.check_output(['git','show',f'{BASELINE}:{n}'],cwd=ROOT);(base/n).write_bytes(d);baseline_hashes[n]=hashlib.sha256(d).hexdigest()
 sys.path.insert(0,str(ROOT))
 from model.vectors import generate_verify_profile
 from model.profiles import profile_names,get_profile
 from model.mHBS import compile_image,ADDRESSES
 from model.executor import compile_image as logical_image
 from model.stateful import descriptor_map,cold_image
 defaults=json.loads((ROOT/'model/default_jobs.json').read_text());roms=[];fixtures=[];boundaries=[]
 for b in LOW:
  for n in profile_names(b):
   p=get_profile(n,b);a=compile_image(n,hash_backend=b);usage=a.usage;records={}
   if any((word&7)==3 for word in a.templates):raise AssertionError('TREE template in CHAIN image')
   for label,words in [('program',a.program),('template',a.templates),('descriptor',a.descriptors)]:
    data=''.join(f'{w:016x}\n' for w in words).encode()
    for op in ('keygen','sign','verify'):
     path=ROOT/'tb/vectors'/('sha2' if b=='sha2' else '')/n/op/(label+'.mem')
     if path.exists() and path.read_bytes()!=data:raise AssertionError('Generated CHAIN ROM differs: '+str(path))
    records[label]=dict(sha256=hashlib.sha256(data).hexdigest(),capacity=len(words),proof='layout4_compiler_and_active_ROM')
   roms.append(dict(backend=b,profile=n,usage=usage,roms=records,template_TREE=0))
  for n in HIGH:fixtures.append(generate_verify_profile(n,defaults[n],run/'verify_vectors'/b,b))
  for n in ('xmss_h10','lms_h10',*HIGH):
   p=get_profile(n,b)
   for q in sorted({0,1,(1<<p.h)-1,1023,1024,32767,32768,65535,65536}):
    if q>=1<<p.h:continue
    config=dict(defaults[n],q=q)
    if q==0:config['message']=''
    label=f'{b}_{n}_q{q}'+('_empty_message' if q==0 else '')
    dest=run/'boundary_vectors'/label;generate_verify_profile(n,config,dest,b)
    boundaries.append(dict(case=label,backend=b,profile=n,q=q,message_bytes=len(bytes.fromhex(config['message'])),vector=str(dest/n/'verify')))
 write(out/'ROM_IDENTITY.json',dict(passed=True,recipe_semantics_source=BASELINE,program_identity='new layout4; main program byte compatibility not applicable',profiles=roms));write(out/'VERIFY_FIXTURES.json',fixtures)
 write(run/'BOUNDARY_FIXTURES.json',boundaries);write(out/'BOUNDARY_FIXTURES.json',boundaries)
 for variant,source,identity in [('candidate',src,hashes),('baseline',base,baseline_hashes)]:
  write(out/(variant+'_SOURCE.json'),dict(source=str(source),sha256=identity))
  with tarfile.open(out/(variant+'_rtl.tar.gz'),'w:gz') as tar:
   for n in rtl+['sources.txt']+[str(p.relative_to(source)) for p in sorted((source/'rtl').rglob('*.svh'))]:tar.add(source/n,arcname=n)
 meta=dict(schema='mhbs.template_chain_run.v1',run_id=stamp,archive=str(out),workspace=str(ROOT),baseline_git_commit=BASELINE,attempt_snapshot='3a625c1',configuration='K1U1',period_ns=10.0,top='common',vivado=shutil.which('vivado'),verilator=shutil.which('verilator'),candidate_source=str(src),candidate_sha256=hashes,high_full_tasks=False,route=False,created_at=now())
 for p in (run/'SOURCE.json',out/'SOURCE.json'):write(p,meta)
 for b in LOW:(out/'synthesis'/b).mkdir(parents=True,exist_ok=True)
 with (run/'runner.log').open('w') as log:p=subprocess.Popen([sys.executable,str(src/'scripts/run_hash_backends.py'),'--run-root',str(run)],cwd=ROOT,env=dict(os.environ,MHBS_TEMPLATE_ROOT=str(ROOT)),stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
 result=dict(pid=p.pid,run=str(run),report=str(out/'reports/Template_CHAIN.md'));write(run/'LAUNCH.json',result)
 with (ROOT/'docs/manifests/experiments/INDEX.md').open('a') as f:f.write(f'\n| {stamp} | program tree + CHAIN template K1U1 SHAKE/SHA2 | [报告](template_chain_{stamp}/reports/Template_CHAIN.md) | 后台运行 |\n')
 print(json.dumps(result,indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group(required=True);g.add_argument('--launch',action='store_true');g.add_argument('--run-root',type=Path);a=p.parse_args()
 if a.launch:launch()
 else:sys.exit(Runner(a.run_root.resolve()).execute())
