import concurrent.futures,subprocess,time
from pathlib import Path
TAG='program16_20260927_v1'
OUT=Path('build/program16')
def run(label,command):
 start=time.time()
 with (OUT/(label+'.log')).open('w') as log:r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
 print(label,'PASS' if r.returncode==0 else 'FAIL',round(time.time()-start),'s',flush=True)
 if r.returncode:
  print((OUT/(label+'.log')).read_text()[-4000:],flush=True)
  raise RuntimeError(label)
def regress():
 with concurrent.futures.ThreadPoolExecutor(3) as p:
  fs=[p.submit(run,'extended',['python3','scripts/verify_v42_external_rtl.py',TAG]),p.submit(run,'partition',['python3','scripts/v42_external_flow.py','sim','--tag',TAG,'--partition']),p.submit(run,'pruning',['python3','scripts/verify_v42_pruning.py',TAG,'--baseline','verify_area_compare_20260927_v1','--node-output'])]
  for f in fs:f.result()
run('capture',['python3','scripts/v42_external_flow.py','capture','--tag',TAG])
with concurrent.futures.ThreadPoolExecutor(4) as p:
 synth=p.submit(run,'synthesis',['python3','scripts/v42_external_synth.py',TAG])
 verify=p.submit(run,'verify',['python3','scripts/verify_v42_verify.py',TAG])
 normal=p.submit(run,'normal',['python3','scripts/v42_external_flow.py','sim','--tag',TAG])
 normal.result()
 route=p.submit(run,'route',['python3','scripts/v42_external_route.py',TAG,'--jobs','3','--wait-for-synthesis'])
 regression=p.submit(regress)
 verify.result();regression.result()
 run('audit',['python3','scripts/verify_v42_current.py',TAG])
 synth.result()
 run('collect_synth',['python3','scripts/collect_v42_external.py',TAG,'--sim-tag',TAG])
 route.result()
 run('collect_route',['python3','scripts/collect_v42_external_route.py',TAG])
 run('report',['python3','scripts/report_v42_external_ppa.py'])
print('PROGRAM16_COMPLETE',flush=True)
