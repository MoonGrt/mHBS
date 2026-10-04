#!/usr/bin/env python3
"""Preserve SLH cycles across existing K/P/U and common/statistics variants."""
import json,concurrent.futures,shutil
from pathlib import Path
from v42_external_flow import ROOT,BASE,NAMES,simulate_case
from run_stateful import OUT
F=ROOT/'build/stateful_20261008/slh_variants';F.mkdir(parents=True,exist_ok=True)
normal=json.loads((ROOT/'build/v4.2/external_job_message/stateful_slh_regression_20261008/simulation.json').read_text())['cases']
expected={'slh_128f':(29862,729983),'slh_192f':(43654,1249491),'slh_256f':(115766,2579236),'slh_128s':(1909782,15317506),'slh_192s':(2792470,29016918),'slh_256s':(1851926,27069757)}
for n,(kg,sg) in expected.items():
 assert normal[n+'_keygen']['keygen_cycles']==kg,(n,'kg')
 assert normal[n+'_sign']['sign_cycles']==sg,(n,'sg')
checks={}
def one(case):
 n,op,kind=case;kw={'profile_enable':False} if kind=='off' else {'partitioned':True}
 label=f'{n}_{op}_{kind}';_,r=simulate_case(F,label,BASE/'vectors'/n/op,**kw)
 ref=normal[n+'_'+op]
 for key in ('keygen_cycles','sign_cycles','total_cycles','hashes','permutations','output_sha256'):assert r[key]==ref[key],(label,key)
 return label,r
with concurrent.futures.ThreadPoolExecutor(3) as pool:
 checks.update(pool.map(one,[(n,o,k) for n in NAMES for o in ('keygen','sign') for k in ('off','partition')]))
for k,p,u,cycles in [(1,1,1,2619719),(1,2,1,1402428),(1,3,1,979434),(1,4,1,766014),(2,1,1,1399919),(2,4,1,486328)]:
 label=f'K{k}P{p}U{u}';_,r=simulate_case(F,label,BASE/'vectors/slh_128f/sign',lanes=k,pipeline=p,unroll=u)
 assert r['sign_cycles']==cycles,(label,r['sign_cycles'],cycles)
 assert (r['hashes'],r['permutations'])==(104937,105641)
 checks[label]=r
 if p==4:
  _,s=simulate_case(F,label+'_reset',BASE/'vectors/slh_128f/sign',lanes=k,pipeline=p,unroll=u,options=('+REPLAYS=2','+INTERRUPT=1','+STALL=1','+TAIL_NOISE=1'))
  assert s['sign_cycles']-s['wait_cycles']==cycles
  checks[label+'_reset']=s
(OUT/'slh_variants.json').write_text(json.dumps(checks,indent=2)+'\n')
shutil.copytree(F/'logs',OUT/'slh_variants_logs',dirs_exist_ok=True)
print('SLH_VARIANTS_PASS',len(checks),flush=True)
