#!/usr/bin/env python3
"""Assemble the final L/U evidence gate without rerunning hardware tools."""
import sys,json,hashlib
import run_lu_p1 as m
label=sys.argv[1];base=m.OUT/label;records={}
def check(name,path,predicate=lambda d:d.get('passed',False)):
 data=json.loads(path.read_text());assert predicate(data),name
 records[name]=dict(path=str(path.relative_to(m.ROOT)),sha256=m.sha(path))
 return data
check('matrix',base/'matrix_status.json')
check('all_profile_regression',base/'regress_status.json')
check('l4_all_profile_regression',base/'l4_regression.json')
check('protocol',base/'protocol_status.json')
check('cycle_comparison',base/'cycle_comparison.json')
check('netlist',base/'netlist_audit.json')
check('handshakes',m.OUT/(label+'_handshake_test')/'results.json')
check('original_p1_cycle_equivalence',m.OUT/'equivalence/results.json')
check('message_edges',base/'message_edges/results.json',lambda d:len(d)==5 and all(x['passed'] for x in d))
check('masked_chain',base/'masked_chain/results.json',lambda d:len(d)==2 and all(x['passed'] for x in d))
for l,u in ((3,1),(12,2),(24,1)):
 check(f'stateful_edges_L{l}U{u}',base/'stateful_edges'/f'L{l}U{u}.json')
partition=json.loads((base/'partition_check.json').read_text())
for key in ('keygen_cycles','sign_cycles','total_cycles','hashes','permutations','output_sha256'):
 assert partition['True'][key]==partition['False'][key],key
records['partition']=dict(path=str((base/'partition_check.json').relative_to(m.ROOT)),sha256=m.sha(base/'partition_check.json'))
rtl={p:m.sha(m.ROOT/p) for p in (m.ROOT/'manifests/v42_sources.txt').read_text().split()}
lid=hashlib.sha256(json.dumps(rtl,sort_keys=True).encode()).hexdigest()[:16]
unit=check('units',m.OUT/'unit_wrapper'/lid/'results.json');assert unit['rtl_sha256']==rtl
for name,h in unit['logs'].items():assert m.sha(m.OUT/'unit_wrapper'/lid/name)==h
frozen=json.loads((base/'inputs.json').read_text())['source_sha256']
assert all(frozen[p]==h for p,h in rtl.items())
for l,u in m.POINTS:
 rows=json.loads((base/f'L{l}U{u}_simulation_s1_x0.json').read_text())
 row=next(x for x in rows if x['profile']=='slh_128f' and x['op']==1)
 assert (row['hashes'],row['permutations'])==(104937,105641)
m.write(base/'validation.json',dict(passed=True,evidence=records,rtl_sha256=rtl,scope='14 configurations, 128f sign; six configurations, ten profiles, three operations; protocol and units'))
print('FINAL_VALIDATION_PASS',len(records))
