import concurrent.futures,hashlib,json,os,subprocess,time
from pathlib import Path
work=Path(__file__).resolve().parent
source=work/'source'; out=work/'validation';out.mkdir(exist_ok=True)
cases=[(backend,p,u,syn,profile) for backend,p,u in [('shake',6,2),('shake',1,1),('sha2',4,2)] for syn in [0,1] for profile in ['slh_128f','xmss_h10','lms_h10']]
results=[];started=time.time()
def run(case):
 backend,p,u,syn,profile=case;name=f'{backend}_P{p}U{u}_s{syn}_{profile}'
 log=out/(name+'.log');env=dict(os.environ,HASH_BACKEND=backend,SIM_SYNTHESIS=str(syn),SIM_VCD='0',KECCAK_LUT6='0')
 cmd=['bash','scripts/simulate.sh',profile,'verify',str(p),str(u),'+STALL=1','+REPLAYS=2','+INTERRUPT=1']
 start=time.time()
 with log.open('w') as f: proc=subprocess.run(cmd,cwd=source,env=env,stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT)
 text=log.read_text(); r=dict(name=name,command=cmd,passed=proc.returncode==0 and 'STATEFUL_PASS ' in text,returncode=proc.returncode,elapsed_seconds=time.time()-start,log=str(log),log_sha256=hashlib.sha256(log.read_bytes()).hexdigest(),markers=[l for l in text.splitlines() if 'STATEFUL_PASS ' in l])
 print(name,'PASS' if r['passed'] else 'FAIL',flush=True)
 return r
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
 for r in pool.map(run,cases):
  results.append(r);(out/'SUMMARY.json').write_text(json.dumps(dict(complete=False,total=18,passed=sum(x['passed'] for x in results),results=results),indent=2)+'\n')
meta=json.loads((work/'SOURCE.json').read_text());changed=[name for name,h in meta['sha256'].items() if hashlib.sha256((source/name).read_bytes()).hexdigest()!=h]
summary=dict(complete=True,total=18,passed=sum(x['passed'] for x in results),elapsed_seconds=time.time()-started,source_unchanged=not changed,changed=changed,source_manifest_sha256=hashlib.sha256((work/'SOURCE.json').read_bytes()).hexdigest(),results=results)
(out/'SUMMARY.json').write_text(json.dumps(summary,indent=2)+'\n')
raise SystemExit(int(summary['passed']!=18 or bool(changed)))
