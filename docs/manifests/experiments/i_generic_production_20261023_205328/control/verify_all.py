from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json,os,subprocess,re,sys
root=Path.cwd();run=Path(__file__).resolve().parent
layout=json.loads((root/'image/i/image_layout.json').read_text())
def group(backend):
 out=[];env=dict(os.environ,MHBS_DESIGN='i',HASH_BACKEND=backend,SIM_HASH_TRACE='0',SIM_FAST_OPT_SLOW='-O1',SIM_SYNTHESIS='0')
 env.pop('ALLOW_FULL_STATEFUL_TREE',None);env.pop('VECTORS_DIR',None)
 for name in layout['profiles'][backend]:
  log=run/(backend+'_'+name+'_verify.log')
  with log.open('w') as f:proc=subprocess.run(['bash','scripts/simulate_fast.sh',name,'verify','1','1'],cwd=root,env=env,stdout=f,stderr=subprocess.STDOUT)
  text=log.read_text();match=re.search(r'STATEFUL_PASS P1U1 op=2 cycles=(\d+).*hashes=(\d+) permutations=(\d+)',text)
  out.append(dict(backend=backend,profile=name,operation='verify',passed=proc.returncode==0 and bool(match),log=str(log),cycles=int(match[1]) if match else None))
  print(backend,name,'PASS' if out[-1]['passed'] else 'FAIL',flush=True)
 return out
with ThreadPoolExecutor(max_workers=2) as pool:records=sum(pool.map(group,layout['profiles']),[])
summary=dict(complete=True,passed=len(records)==20 and all(x['passed'] for x in records),cases=records,full_h20_keygen_sign=False)
(run/'VERIFY_SUMMARY.json').write_text(json.dumps(summary,indent=2)+'\n')
raise SystemExit(not summary['passed'])
