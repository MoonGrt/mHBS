#!/usr/bin/env python3
"""Read-only audit of v4.2 sources, numeric results and frozen proof files."""
import argparse,gzip,hashlib,json,math,subprocess,sys,tarfile
from pathlib import Path
from v42_flow import ROOT,BASE,BASELINE,sha
p=argparse.ArgumentParser();p.add_argument('--allow-incomplete',action='store_true');a=p.parse_args()
base=json.loads(BASELINE.read_text());candidates=sorted((BASE/'candidates').glob('*/ppa.json'))
for pp in candidates:
 f=pp.parent;r=json.loads(pp.read_text());inp=json.loads((f/'inputs.json').read_text())
 assert sha(f/'source_snapshot.tar.gz')==inp['snapshot_sha256']
 with tarfile.open(f/'source_snapshot.tar.gz') as t:
  for name,digest in inp['source_sha256'].items():assert hashlib.sha256(t.extractfile(name).read()).hexdigest()==digest,(f.name,name)
 assert sha(BASELINE)==inp['baseline_sha256']
 area=r['lut']/4+r['ff']/8+r['bram36']*232.4+r['dsp']*102.4
 assert math.isclose(area,r['equivalent_slice'])
 assert math.isclose(r['frequency_mhz'],1000/r['period_ns'])
 for n,row in r['profiles'].items():
  atp=area*row['sign_cycles']*r['period_ns']/1e6
  assert math.isclose(atp,row['sign_atp']) and row['baseline_atp']==base['profiles'][n]['sign_atp']
  assert row['improved']==(atp<row['baseline_atp'])
 if r.get('performance_pass'):
  assert r['stage']=='post_route' and r['functional_pass'] and r['frozen_init_mapping_pass'] and r['timing_pass']
  evidence=json.loads((f/'evidence_sha256.json').read_text())
  for name,digest in evidence.items():assert sha(f/name)==digest,(f.name,name)
  with gzip.open(f/'frozen/hardware.txt.gz','rb') as stream:
   h=hashlib.sha256()
   for data in iter(lambda:stream.read(1<<20),b''):h.update(data)
  assert h.hexdigest()==r['frozen_hardware_sha256']
  assert all(x['improved'] for x in r['profiles'].values())
  proof=json.loads((f/'verification/results.json').read_text())
  assert proof['passed'] and proof['rtl_sha256']==inp['rtl_sha256'] and len(proof['cases'])>=42
  for case in proof['cases'].values():assert case['passed']
final=BASE/'final.json'
if not final.exists():
 if not a.allow_incomplete:raise SystemExit('V42_INCOMPLETE: no final routed acceptance')
 print('V42_AUDIT_PASS',len(candidates),'candidates; performance INCOMPLETE')
else:
 data=json.loads(final.read_text());pp=BASE/'candidates'/data['candidate']/'ppa.json'
 assert sha(pp)==data['ppa_sha256']
 if not data['performance_pass'] and not a.allow_incomplete:raise SystemExit('V42_PERFORMANCE_INCOMPLETE')
 print('V42_REPRODUCE_PASS',len(candidates),'candidates',data['candidate'],'performance_pass',data['performance_pass'])
