#!/usr/bin/env python3
"""Resume the selected K/U routes under one internal timing contract."""
import argparse
import concurrent.futures
import json
import subprocess
import time
from pathlib import Path
from v42_external_flow import ROOT,BASE,BUILD,NAMES,sha,write,tool_version
from v42_external_route import resources,audit_rom,audit_timing

POINTS=((1,1),(1,2),(1,4),(2,2),(2,4),(4,2),(4,4))
SHELLS=[f'{n}_{op}' for n in NAMES for op in ('keygen','sign')]
ROUTE_DIR='route_internal20_v1'
FLOW=ROOT/'experiments/v4.2/ku_matrix/route.tcl'

def main():
 p=argparse.ArgumentParser();p.add_argument('--jobs',type=int,default=6);a=p.parse_args()
 version=tool_version('vivado','-version')
 def one(task):
  k,u,shell=task;tag=f'ku_k{k}u{u}_v2';base=BUILD/tag;out=base/ROUTE_DIR/shell;out.mkdir(parents=True,exist_ok=True)
  source=base/'synthesis'/shell/'post_synth.dcp';inputs=json.loads((base/'inputs.json').read_text());sim=json.loads((base/'simulation.json').read_text())
  assert inputs['rtl_sha256']=={path:sha(ROOT/path) for path in inputs['rtl_sha256']}
  invocation=dict(lanes=k,unroll=u,initial_period_ns=20.0,external_paths_excluded=True,source_dcp_sha256=sha(source),source_snapshot_sha256=inputs['snapshot_sha256'],route_script_sha256=sha(FLOW),tool_version=version)
  if (out/'result.json').exists():
   result=json.loads((out/'result.json').read_text())
   if result.get('passed'):
    old=json.loads((out/'invocation.json').read_text());assert all(old[key]==value for key,value in invocation.items());return tag,shell,result
  command=['vivado','-mode','batch','-nolog','-nojournal','-source',str(FLOW),'-tclargs',str(source),str(out)]
  invocation.update(command=command,started=time.time());write(out/'invocation.json',invocation)
  print('KU_ROUTE_START',tag,shell,flush=True)
  try:
   with (out/'route.log').open('w') as log:subprocess.run(command,cwd=out,stdout=log,stderr=subprocess.STDOUT,check=True)
   clock=json.loads((out/'final_clock.json').read_text());assert clock['wns_ns']>=.0999 and clock['whs_ns']>=0
   audit_timing(out);name,op=shell.rsplit('_',1);rom=audit_rom(out/'initialized_rom.tsv',BASE/'images'/name)
   cycles=sim['cases'][shell][op+'_cycles'];result=dict(passed=True,core_timing_pass=True,lanes=k,unroll=u,**resources(out/'utilization.rpt'),**clock,frequency_mhz=1000/clock['period_ns'],operation_cycles=cycles,rom_audit=rom)
   result['latency_ms']=cycles*clock['period_ns']/1e6;result['area_time_product']=result['equivalent_slice']*result['latency_ms']
   result['evidence_sha256']={str(path.relative_to(out)):sha(path) for path in out.iterdir() if path.is_file() and path.name!='result.json'}
   print('KU_ROUTED_TOP_PASS',tag,shell,result['frequency_mhz'],flush=True)
  except Exception as exc:
   result=dict(passed=False,lanes=k,unroll=u,failure=repr(exc),log_sha256=sha(out/'route.log') if (out/'route.log').exists() else None)
   print('KU_ROUTED_TOP_FAIL',tag,shell,repr(exc),flush=True)
  write(out/'result.json',result);return tag,shell,result
 tasks=[(k,u,shell) for k,u in POINTS for shell in SHELLS]
 with concurrent.futures.ThreadPoolExecutor(a.jobs) as pool:
  rows=list(pool.map(one,tasks))
 for k,u in POINTS:
  tag=f'ku_k{k}u{u}_v2';tops={shell:row for rowtag,shell,row in rows if rowtag==tag}
  write(BUILD/tag/ROUTE_DIR/'result.json',dict(passed=all(row['passed'] for row in tops.values()),initial_period_ns=20.0,io_timing_qualified=False,timing_scope='out-of-context internal register-to-register; external interfaces excluded from place and route',tops=tops))
 write(BUILD/'ku_internal20_route_results.json',dict(passed=all(row['passed'] for _,_,row in rows),cases={tag+'/'+shell:row for tag,shell,row in rows}))
 print('KU_ROUTE_MATRIX_DONE',sum(row['passed'] for _,_,row in rows),len(rows),flush=True)

if __name__=='__main__':main()
