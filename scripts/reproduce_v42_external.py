#!/usr/bin/env python3
"""Audit the external-input source, functional evidence and shared-core PPA."""
import gzip,hashlib,json,math,tarfile
from v42_external_flow import ROOT,BASE,sha
final=json.loads((BASE/'final.json').read_text());f=BASE/'candidates'/final['candidate'];result=json.loads((f/'result.json').read_text())
assert sha(f/'result.json')==final['result_sha256'] and result['post_synth_acceptance']
assert result['stage']=='post_synth' and not result['post_route_pass'] and result['frequency_mhz'] is None
inp=json.loads((f/'inputs.json').read_text());assert sha(f/'source_snapshot.tar.gz')==inp['snapshot_sha256']
with tarfile.open(f/'source_snapshot.tar.gz') as t:
 for p,h in inp['source_sha256'].items():assert hashlib.sha256(t.extractfile(p).read()).hexdigest()==h,p
for p,h in json.loads((f/'evidence_sha256.json').read_text()).items():assert sha(f/p)==h,p
for name,r in [('core',result['core']),*result['tops'].items()]:
 area=r['lut']/4+r['ff']/8+r['bram36']*232.4+r['dsp']*102.4;assert math.isclose(area,r['equivalent_slice'])
 if name!='core':
  assert math.isclose(r['normalized_100mhz_atp'],area*r['operation_cycles']/100000)
  with gzip.open(f/'synthesis'/name/'core_structure.txt.gz','rb') as stream:
   h=hashlib.sha256()
   for block in iter(lambda:stream.read(1<<20),b''):h.update(block)
  assert h.hexdigest()==result['common_core_sha256']==r['core_sha256']
  assert json.loads((f/'synthesis'/name/'rom_audit.json').read_text())['passed']
assert len(result['tops']) in (6,12) and len(json.loads((f/'extended.json').read_text())['cases'])==len(result['tops'])*11//2
assert json.loads((f/'unit/results.json').read_text())['passed']
assert json.loads((f/'software_gate.json').read_text())['passed']
if result.get('partition_equivalence_pass'):
 partition=json.loads((f/'simulation_partition.json').read_text());sim=json.loads((f/'simulation.json').read_text())
 assert partition['passed'] and len(partition['cases'])==len(result['tops'])
 for name,row in partition['cases'].items():
  original=sim['cases'][name.removesuffix('_partition')]
  for key in ('boot_cycles','keygen_cycles','sign_cycles','hashes','permutations','total_cycles'):assert row[key]==original[key]
print('EXTERNAL_REPRODUCE_PASS',final['candidate'],
      'functional+post_synth; see separate routed evidence' if final.get('post_route_pass')
      else 'functional+post_synth; post-route not measured')
