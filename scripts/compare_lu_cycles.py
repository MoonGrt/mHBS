#!/usr/bin/env python3
"""Compare final-cycle rows against the frozen structural implementation."""
import sys,json,re
import run_lu_p1 as m
label=sys.argv[1];records=[]
for l,u in m.POINTS:
 f=m.OUT/label/f'L{l}U{u}_simulation_s1_x0.json'
 rows=json.loads(f.read_text())
 # A simultaneous matrix run can replace the summary with its single SG
 # row. Recover all regression cases from their retained, distinct logs.
 if (l,u) in m.REPS:
  from model.profiles import PROFILES
  rows=[]
  for profile in PROFILES:
   for op in range(3):
    log=m.OUT/label/'logs'/f'L{l}U{u}_{profile}_{op}_s1_x0.log'
    match=re.search(r'STATEFUL_PASS L\d+U\d+ op=(\d+) cycles=(\d+) total=(\d+) hashes=(\d+) permutations=(\d+)',log.read_text())
    assert match is not None and int(match[1])==op,log
    rows.append(dict(profile=profile,op=op,**dict(zip(('cycles','total','hashes','permutations'),map(int,match.groups()[1:]))),log_sha256=m.sha(log)))
  m.write(m.OUT/label/f'L{l}U{u}_regression_complete.json',rows)
 for r in rows:
  baseline=m.OUT/'structure_initial'/f'L{l}U{u}_simulation_s1_x0.json'
  if (l,u) not in m.REPS:baseline=m.OUT/'structure'/f'L{l}U{u}_simulation_s1_x0.json'
  refs=json.loads(baseline.read_text());ref=next((x for x in refs if (x['profile'],x['op'])==(r['profile'],r['op'])),None)
  assert ref is not None,(l,u,r['profile'],r['op'],'missing baseline')
  for k in ('cycles','total','hashes','permutations'):assert r[k]==ref[k],(l,u,r['profile'],r['op'],k,r[k],ref[k])
  records.append(dict(lanes=l,unroll=u,profile=r['profile'],op=r['op'],cycles=r['cycles'],passed=True))
extra=m.OUT/label/'L4U2_simulation_s1_x0_all.json'
if extra.exists():
 refs=json.loads((m.OUT/'structure'/'L4U2_simulation_s1_x0_all.json').read_text())
 rows=json.loads(extra.read_text());assert len(rows)==len(refs)==30
 for r in rows:
  ref=next(x for x in refs if (x['profile'],x['op'])==(r['profile'],r['op']))
  for k in ('cycles','total','hashes','permutations'):assert r[k]==ref[k],(4,2,r['profile'],r['op'],k)
  records.append(dict(lanes=4,unroll=2,profile=r['profile'],op=r['op'],cycles=r['cycles'],passed=True))
m.write(m.OUT/label/'cycle_comparison.json',dict(passed=True,cases=len(records),rows=records));print('CYCLE_COMPARISON_PASS',len(records))
