import concurrent.futures,hashlib,json,os,subprocess,threading,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
RUN=ROOT/'build/shake_timing_optimization/candidate_20261019_212542'
SOURCE=RUN/'source';META=json.loads((RUN/'SOURCE.json').read_text())
OUT=Path(__file__).resolve().parent/'candidate_212542_extended';OUT.mkdir(exist_ok=True)
LOCK=threading.Lock();RESULTS=[];START=time.monotonic()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def publish(complete=False):
 with LOCK:
  unchanged=all(sha(SOURCE/n)==h for n,h in META['sha256'].items())
  data=dict(candidate_run=str(RUN),source_manifest=str(RUN/'SOURCE.json'),source_manifest_sha256=sha(RUN/'SOURCE.json'),rtl_sha256={n:h for n,h in META['sha256'].items() if n.startswith('rtl/')},hash_backend='shake_and_sha2',source_unchanged=unchanged,complete=complete,passed=sum(t['passed'] for t in RESULTS),failed=sum(not t['passed'] for t in RESULTS),elapsed_seconds=time.monotonic()-START,tests=RESULTS,h20_full_keygen_sign_run=False)
  data['status']='failed' if data['failed'] or not unchanged else 'passed' if complete else 'running'
  p=OUT/'VALIDATION.json';t=OUT/'VALIDATION.json.tmp';t.write_text(json.dumps(data,indent=2)+'\n');t.replace(p)
def run(case):
 backend,p,u,profile,operation=case;log=OUT/f'{backend}_P{p}U{u}_{profile}_{operation}.log'
 env=dict(os.environ,HASH_BACKEND=backend,SIM_FAST_OPT_SLOW='-O1',SIM_SYNTHESIS='0');env.pop('PROFILE_ENABLE',None)
 command=['bash','scripts/simulate_fast.sh',profile,operation,str(p),str(u)]
 with log.open('w')as f:r=subprocess.run(command,cwd=SOURCE,env=env,stdout=f,stderr=subprocess.STDOUT)
 text=log.read_text();passed=r.returncode==0 and 'STATEFUL_PASS' in text
 with LOCK:RESULTS.append(dict(case=case,command=command,passed=passed,log=str(log),log_sha256=sha(log),result=text.strip()))
 publish();print(case,passed,flush=True)
def group(cases):
 for c in cases:run(c)
if __name__=='__main__':
 publish()
 groups=[ [('shake',12,1,'slh_'+x,'sign')for x in ('128s','192f','192s','256f','256s')], [('sha2',4,1,'slh_128f','sign')], [('shake',p,1,profile,'verify')for p in (4,12)for profile in ('xmss_h20','lms_h20')], [('shake',p,u,'slh_128f','sign')for p,u in ((6,1),(2,12))] ]
 with concurrent.futures.ThreadPoolExecutor(max_workers=4)as pool:
  list(pool.map(group,groups))
 publish(True)
