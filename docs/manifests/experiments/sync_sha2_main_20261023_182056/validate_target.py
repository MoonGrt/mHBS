from pathlib import Path
import subprocess,os,json,time
r=Path(__file__).resolve().parent
source=r/'target_source'
cases=[('sha2','slh_128f',False),('sha2','xmss_h10',False),('sha2','lms_h10',False),('shake','slh_128f',False),('sha2','slh_128f',True)]
records=[]
for backend,profile,syn in cases:
 name=f'target_c_{backend}_{profile}'+('_synthesis' if syn else '')
 log=r/'logs'/f'{name}.log'
 env=dict(os.environ,MHBS_DESIGN='c',HASH_BACKEND=backend,SIM_SYNTHESIS=str(int(syn)),SIM_HASH_TRACE='1',SIM_FAST_OPT_SLOW='-O1',PYTHONDONTWRITEBYTECODE='1')
 start=time.time()
 with log.open('w') as f:p=subprocess.run(['bash','scripts/simulate_fast.sh',profile,'sign','1','1'],cwd=source,env=env,stdout=f,stderr=subprocess.STDOUT)
 records.append(dict(backend=backend,profile=profile,synthesis=syn,returncode=p.returncode,seconds=time.time()-start,log=str(log),markers=[line for line in log.read_text().splitlines() if 'STATEFUL_PASS' in line or 'METRICS ' in line]))
 (r/'TARGET_VALIDATION.json').write_text(json.dumps(dict(complete=len(records)==len(cases),passed=all(x['returncode']==0 for x in records),records=records),indent=2)+'\n')
 if p.returncode:raise SystemExit(p.returncode)
