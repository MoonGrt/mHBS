#!/usr/bin/env python3
"""Index, message, corruption, reset, profile and L/U coverage."""
from pathlib import Path
import sys,json
from stateful_vectors import generate,OUT,PROFILE_CODES
from run_stateful import build,run

def main():
 rows=json.loads((OUT/'edge_lu_results.json').read_text()) if (OUT/'edge_lu_results.json').exists() else {};b=build()
 names=list(PROFILE_CODES.values())
 normal={(x["profile"],x["operation"]):x for x in json.loads((OUT/"L2U1_simulation.json").read_text())}
 for name in names:
  if name+'_sign87' in rows:continue
  v=OUT/'vectors'/name/'q0_m1'/'2'
  for t in range(1,6):rows[f'{name}_tamper{t}']=run(b,v,(f'+TAMPER={t}',),f'_tamper{t}')
  rows[name+'_stall_reset']=run(b,v,('+STALL=1','+REPLAYS=2','+INTERRUPT=1'),'_stall_reset')
  rows[name+'_truncated_reset']=run(b,v,('+CUT=3',),'_truncated_reset')
  rows[name+'_fault']=run(b,v,('+FAULT=1',),'_fault')
  for q in (1024,2147483647):rows[f'{name}_invalid{q}']=run(b,v,(f'+Q={q}','+INVALID=1'),f'_invalid{q}')
  for q in (1,1023):
   folder=generate(name,q,b'B')
   for op in (1,2):rows[f'{name}_q{q}_{op}']=run(b,folder/str(op))
  for size in (7,8,9,87):
   folder=generate(name,0,bytes(range(size)))
   rows[f'{name}_message{size}']=run(b,folder/'2',('+STALL=1',),'_stall')
  # Boundary message signature additionally checks the signing Hmsg path.
  rows[name+'_sign87']=run(b,folder/'1',('+STALL=1',),'_stall')
  (OUT/'edge_lu_results.json').write_text(json.dumps(rows,indent=2)+'\n')
 for label,kw in [('stats_off',dict(profile=0)),('swap',dict(swap=1)),('L3',dict(lanes=3)),('default',dict(u=2))]:
  alt=build(**kw)
  for name in names:
   rows[name+'_'+label]=run(alt,OUT/'vectors'/name/'q0_m1'/'2')
   if label in ('stats_off','swap'):
    assert rows[name+'_'+label]['compute_cycles']==normal[name,2]['compute_cycles']
  if label in ('stats_off','swap','L3'):
   rows['lms_omega2_sign_'+label]=run(alt,OUT/'vectors/lms_omega2/q0_m1/1')
   if label in ('stats_off','swap'):
    assert rows['lms_omega2_sign_'+label]['compute_cycles']==normal['lms_omega2',1]['compute_cycles']
  (OUT/'edge_lu_results.json').write_text(json.dumps(rows,indent=2)+'\n')
 print('STATEFUL_EDGES_PASS',len(rows),flush=True)
if __name__=='__main__':main()
