from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import argparse,hashlib,json,os,re,subprocess,threading,time

parser=argparse.ArgumentParser()
parser.add_argument('--run',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
RUN=args.run.resolve(); SOURCE=RUN/'source'; PROJECT=Path(__file__).resolve().parents[2]
OUT=args.output.resolve();DETAIL=RUN/'validation/timing_latency';DETAIL.mkdir(parents=True,exist_ok=True)
META=json.loads((RUN/'SOURCE.json').read_text());START=time.monotonic();LOCK=threading.Lock();RESULTS=[]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
now=lambda:datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds')
TARGETS=('slh_128f','xmss_h10','lms_h10')
PROFILES=('slh_128f','slh_192f','slh_256f','slh_128s','slh_192s','slh_256s','xmss_h10','xmss_h16','xmss_h20','lms_h10','lms_h15','lms_h20')
GROUPS=[]
def task(name,cmd,marker='STATEFUL_PASS',env=None):return dict(name=name,cmd=cmd,marker=marker,env=env or {})
def fast(profile,op,p,u,syn=0,suffix='',env=None):
 return task(f'{profile}_{op}_P{p}U{u}_syn{syn}{suffix}',['bash','scripts/simulate_fast.sh',profile,op,str(p),str(u)],env=dict(SIM_SYNTHESIS=str(syn),**(env or {})))
for p,u in ((1,1),(4,1),(4,2),(12,1)):
 group=[]
 for syn in (0,1):
  group.append(task(f'recipes_P{p}U{u}_syn{syn}',['python3','scripts/check_recipes.py','--pipeline',str(p),'--unroll',str(u),*(['--synthesis'] if syn else [])],'RECIPE_PASS cases=459'))
 if p in (1,4) and u==1:
  group.append(task(f'recipes_mask_P{p}U{u}',['python3','scripts/check_recipes.py','--pipeline',str(p),'--unroll',str(u),'--recipe-mask','0x101e'],'RECIPE_PASS cases=186'))
 for profile in PROFILES if u==1 and p in (1,4) else TARGETS:
  group.append(fast(profile,'verify',p,u))
 if p==4 and u==1:
  for profile in TARGETS:group.append(fast(profile,'keygen',p,u))
  for profile in ('xmss_h10','lms_h10'):
   for q in (1,1023):
    fixture=PROJECT/'build/pu_generic/20261013_201408/audit/extended'/f'{profile}_q{q}'
    group.append(fast(profile,'sign',p,u,suffix=f'_q{q}',env={'VECTORS_DIR':str(fixture)}))
 GROUPS.append(group)
for p,u in ((1,1),(4,1),(4,2)):
 group=[]
 for profile in TARGETS:
  group.append(fast(profile,'sign',p,u,1))
  group.append(fast(profile,'verify',p,u,1))
 for syn in (0,1):
  group.append(task(f'statistics_P{p}U{u}_syn{syn}',['python3','scripts/check_statistics.py','--pipeline',str(p),'--unroll',str(u),*(['--synthesis'] if syn else [])],'STATISTICS_PASS'))
 GROUPS.append(group)
group=[task('source_audit',['python3','scripts/audit_rtl_debug.py','--lint','--output',str(DETAIL/'source_audit.json')],'RTL_DEBUG_AUDIT_PASS')]
for syn in (0,1):group.append(task(f'batch_tags_syn{syn}',['python3','scripts/check_pipeline.py',*(['--synthesis'] if syn else [])],'PIPELINE_PASS'))
GROUPS.append(group)
for p,u in ((1,1),(4,1),(4,2)):
 group=[]
 for profile in TARGETS:
  group.append(task(f'events_{profile}_P{p}U{u}',['bash','scripts/simulate.sh',profile,'verify',str(p),str(u),'+STALL=1','+REPLAYS=2','+INTERRUPT=1','+CUT=5']))
 if p==4 and u==1:
  for profile in TARGETS:
   group.append(task(f'sign_events_{profile}',['bash','scripts/simulate.sh',profile,'sign','4','1','+STALL=1','+REPLAYS=2','+INTERRUPT=1']))
   for tamper in (1,2,3,4,5):group.append(task(f'tamper_{profile}_{tamper}',['bash','scripts/simulate.sh',profile,'verify','4','1','+STALL=1',f'+TAMPER={tamper}']))
  for name,opts,marker in (('q_invalid',['+Q=1024','+INVALID=1'],'INDEX_REJECT_PASS'),('invalid_profile',['+PROFILE=9'],'INDEX_REJECT_PASS'),('scalar_fault',['+FAULT=1'],'STATEFUL_FAULT_PASS'),('batch_fault',['+FAULT=2'],'STATEFUL_FAULT_PASS'),('state_fault',['+FAULT=3'],'STATEFUL_FAULT_PASS')):
   group.append(task(name,['bash','scripts/simulate.sh','xmss_h10','verify','4','1',*opts],marker))
 GROUPS.append(group)
EXPECTED=sum(map(len,GROUPS))
def publish(complete=False):
 data=dict(schema='mhbs.timing_latency.validation.v1',source_run=str(RUN),source_manifest_sha256=sha(RUN/'SOURCE.json'),complete=complete,total=EXPECTED,passed=sum(x['passed'] for x in RESULTS),failed=sum(not x['passed'] for x in RESULTS),status='failed' if any(not x['passed'] for x in RESULTS) else 'passed' if complete and len(RESULTS)==EXPECTED else 'running',elapsed_seconds=time.monotonic()-START,updated_at=now(),results=RESULTS,h20_full_keygen_sign_run=False,source_unchanged=all(sha(SOURCE/n)==h for n,h in META['sha256'].items()))
 OUT.parent.mkdir(parents=True,exist_ok=True);tmp=OUT.with_suffix('.json.tmp');tmp.write_text(json.dumps(data,indent=2)+'\n');tmp.replace(OUT)
def run_group(group):
 for item in group:
  log=DETAIL/(item['name']+'.log');env=os.environ.copy();env.pop('PROFILE_ENABLE',None);env.update(SIM_VCD='0',SIM_SYNTHESIS='0');env.update(item['env']);started=time.monotonic()
  with log.open('w') as h:r=subprocess.run(item['cmd'],cwd=SOURCE,env=env,stdout=h,stderr=subprocess.STDOUT)
  text=log.read_text();result=dict(name=item['name'],passed=r.returncode==0 and item['marker'] in text,seconds=time.monotonic()-started,log=str(log),log_sha256=sha(log),command=item['cmd'])
  matches=re.findall(r'STATEFUL_PASS P(\d+)U(\d+) op=(\d+) cycles=(\d+) total=(\d+) hashes=(\d+) permutations=(\d+)',text)
  result['measurements']=[dict(zip(('pipeline','unroll','operation','cycles','total_cycles','hashes','permutations'),map(int,x))) for x in matches]
  with LOCK:RESULTS.append(result);publish()
  print(now(),item['name'],result['passed'],flush=True)
  if not result['passed']:raise RuntimeError(str(log))
publish()
try:
 with ThreadPoolExecutor(max_workers=4) as pool:
  for future in as_completed([pool.submit(run_group,g) for g in GROUPS]):future.result()
finally:publish(True)
if len(RESULTS)!=EXPECTED or any(not x['passed'] for x in RESULTS):raise RuntimeError('Incomplete/failed validation')
print('TIMING_LATENCY_VALIDATION_PASS',EXPECTED,flush=True)
