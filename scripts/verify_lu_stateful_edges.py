import sys,concurrent.futures,json
sys.path.insert(0,'scripts');import run_lu_p1 as m
label=sys.argv[1] if len(sys.argv)>1 else 'structure'
old=m.ROOT/'manifests/experiments/stateful_20261008/vectors'
def work(x):
 l,u=x;b=m.build(label,l,u);logs=m.OUT/label/'stateful_edges';records=[]
 for name in ('xmss_omega2','xmss_omega4','lms_omega2','lms_omega4'):
  for cfg in ('q1_m1','q1023_m1','q0_m7','q0_m8','q0_m9','q0_m87'):
   for op in (2,):
    vec=old/name/cfg/str(op);log=logs/f'L{l}U{u}_{name}_{cfg}_{op}.log'
    m.run([b,f'+VECTOR={vec}','+STALL=1'],log);assert 'STATEFUL_PASS' in log.read_text();records.append(str(log.relative_to(m.ROOT)))
  log=logs/f'L{l}U{u}_{name}_badq.log';m.run([b,f'+VECTOR={old/name/"q0_m1/1"}','+Q=1024','+INVALID=1'],log);assert 'INDEX_REJECT_PASS' in log.read_text()
 m.write(logs/f'L{l}U{u}.json',dict(passed=True,cases=records));print('STATEFUL_EDGES_PASS',x,flush=True)
with concurrent.futures.ThreadPoolExecutor(3) as p:list(p.map(work,[(3,1),(12,2),(24,1)]))
