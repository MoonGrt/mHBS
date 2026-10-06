#!/usr/bin/env python3
"""Single-lane topology, protocol and boundary regression against frozen L1 RTL."""
import concurrent.futures,json
from verify_single_lane import ROOT,OUT,build,run,prepare_vectors
VECTORS=ROOT/'manifests/experiments/stateful_20261008/vectors'
NAMES=('xmss_omega2','xmss_omega4','lms_omega2','lms_omega4')
def main():
 prepare_vectors()
 def topology(point):
  p,u,stats=point;exe=build(p,u,stats);label=f'P{p}U{u}_stats{stats}';rows={}
  def case(name,v,opts=()):rows[label+'_'+name]=run(exe,v,label+'_'+name,opts)
  for op in (0,1,2):case('slh128f_'+str(op),OUT/'vectors/slh_128f'/str(op))
  case('slh128f_sign_reset',OUT/'vectors/slh_128f/1',('+STALL=1','+INTERRUPT=1','+REPLAYS=2'))
  case('fault',OUT/'vectors/slh_128f/1',('+FAULT=1',))
  for name in NAMES:case(name+'_verify',VECTORS/name/'q0_m1/2')
  if (p,u,stats)==(4,1,1):
   for name in NAMES:case(name+'_sign',VECTORS/name/'q0_m1/1')
  (OUT/('edges_'+label+'.json')).write_text(json.dumps(rows,indent=2)+'\n');return rows
 with concurrent.futures.ThreadPoolExecutor(3) as pool:
  rows={k:v for r in pool.map(topology,[(2,1,1),(3,1,1),(4,1,1),(1,2,1),(2,2,1),(3,2,1),(4,2,1),(1,1,0),(4,1,0)]) for k,v in r.items()}
 exe=build()
 for name in NAMES:
  v=VECTORS/name/'q0_m1/2'
  for t in range(1,6):
   label=f'{name}_tamper{t}';rows[label]=run(exe,v,label,(f'+TAMPER={t}',))
  for label,opts in [('stall_reset',('+STALL=1','+INTERRUPT=1','+REPLAYS=2')),('cut',('+CUT=3',)),('fault',('+FAULT=1',)),('q1024',('+Q=1024','+INVALID=1')),('qmax',('+Q=2147483647','+INVALID=1'))]:
   key=name+'_'+label;rows[key]=run(exe,v,key,opts)
  for path in sorted((VECTORS/name).glob('q*/2')):
   if path.parent.name=='q0_m1':continue
   label=name+'_'+path.parent.name;rows[label]=run(exe,path,label,('+STALL=1',))
 (OUT/'edges.json').write_text(json.dumps(dict(passed=True,cases=rows),indent=2)+'\n')
 print('SINGLE_LANE_EDGES_PASS',len(rows),flush=True)
if __name__=='__main__':main()
