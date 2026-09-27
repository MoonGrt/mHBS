#!/usr/bin/env python3
"""Archive source-bound external-input post-synth acceptance; no frequency claim."""
import argparse,gzip,json,re,shutil,tarfile
from pathlib import Path
from v42_external_flow import ROOT,BASE,BUILD,NAMES,sha,write
p=argparse.ArgumentParser();p.add_argument('tag');p.add_argument('--sim-tag',required=True);a=p.parse_args()
f=BUILD/a.tag;sf=BUILD/a.sim_tag;inp=json.loads((f/'inputs.json').read_text())
assert inp['rtl_sha256']==json.loads((sf/'inputs.json').read_text())['rtl_sha256']
sim=json.loads((sf/'simulation.json').read_text());ext=json.loads((sf/'extended.json').read_text());unit=json.loads((BASE/'unit/results.json').read_text())
assert sim['passed'] and len(sim['cases'])==6 and ext['passed'] and len(ext['cases'])==33 and unit['passed']
assert sim['rtl_sha256']==ext['rtl_sha256']==unit['rtl_sha256']==inp['rtl_sha256']
for group in (sim['cases'],ext['cases']):
 for name,row in group.items():assert sha(sf/'logs'/(name+'.log'))==row['log_sha256']
for path,h in unit['logs'].items():assert sha(BASE/'unit'/path)==h
s=f/'synthesis'
pruning=json.loads((sf/'pruning_verification.json').read_text())
assert pruning['passed'] and pruning['rtl_sha256']==inp['rtl_sha256']
for path,h in pruning['evidence_sha256'].items():assert sha(sf/path)==h,path
hardware_pruning=json.loads((s/'pruning_audit.json').read_text())
assert hardware_pruning['passed'] and hardware_pruning['profile_enable'] is False
assert hardware_pruning['redundant_registers']==0
partition=None
if (s/'mhbs_common.sv').exists():
 partition=json.loads((sf/'simulation_partition.json').read_text())
 assert partition['passed'] and partition['rtl_sha256']==inp['rtl_sha256'] and len(partition['cases'])==6
 for name,row in partition['cases'].items():
  assert sha(sf/'logs'/(name+'.log'))==row['log_sha256']
  original=sim['cases'][name.removesuffix('_partition')]
  for key in ('boot_cycles','keygen_cycles','sign_cycles','hashes','permutations','total_cycles'):assert row[key]==original[key],(name,key)
def resources(path):
 text=path.read_text();d={}
 for label,key in [('Slice LUTs','lut'),('Slice Registers','ff'),('LUT as Memory','lutram'),('Block RAM Tile','bram36'),('DSPs','dsp')]:
  m=re.search(r'\|\s*'+re.escape(label)+r'\*?\s*\|\s*([\d,.]+)',text);assert m,label;d[key]=float(m[1].replace(',',''))
 d['equivalent_slice']=d['lut']/4+d['ff']/8+d['bram36']*232.4+d['dsp']*102.4
 return d
core=resources(s/'core_utilization.rpt');tops={};fingerprints=set()
for name,row in sim['cases'].items():
 d=s/name;h=(d/'core_sha256.txt').read_text().strip();assert sha(d/'core_structure.txt')==h;fingerprints.add(h)
 assert json.loads((d/'rom_audit.json').read_text())['passed']
 r=resources(d/'utilization.rpt')
 op='sign' if row['config']['operation'] else 'keygen';cycles=row[op+'_cycles']
 r.update(boot_cycles=row['boot_cycles'],operation_cycles=cycles,total_cycles=row['total_cycles'],hashes=row['hashes'],permutations=row['permutations'],normalized_100mhz_atp=r['equivalent_slice']*cycles/100000,
          operation=op,config=row['config'],core_sha256=h)
 tops[name]=r
assert len(fingerprints)==1
result=dict(version='v4.2',layout_revision=3,stage='post_synth',functional_pass=True,common_core_pass=True,rom_mapping_pass=True,post_synth_acceptance=True,post_route_pass=False,frequency_mhz=None,
 tag=a.tag,simulation_tag=a.sim_tag,simulation_profile_enable=True,synthesis_profile_enable=False,pruning_verification_pass=True,core=core,tops=tops,common_core_sha256=next(iter(fingerprints)),rtl_sha256=inp['rtl_sha256'],source_snapshot_sha256=sha(f/'source_snapshot.tar.gz'))
write(f/'result.json',result)
if partition:
 result.update(reset='active_high_synchronous',common_execution_scope='boot_and_core',partition_equivalence_pass=True)
 write(f/'result.json',result)
out=BASE/'candidates'/a.tag;out.mkdir(parents=True,exist_ok=False)
for name in ('source_snapshot.tar.gz','inputs.json','synth.log','synth_invocation.json','synth_elapsed.json','result.json'):shutil.copy2(f/name,out/name)
for path in s.rglob('*'):
 if not path.is_file():continue
 target=out/'synthesis'/path.relative_to(s);target.parent.mkdir(parents=True,exist_ok=True)
 if path.name=='core_structure.txt':
  with path.open('rb') as src,gzip.open(str(target)+'.gz','wb') as dst:shutil.copyfileobj(src,dst)
 else:shutil.copy2(path,target)
for name in ('simulation.json','simulation_partition.json','extended.json','extended_previous.json','faults.json','pruning_verification.json','simulation_no_profile.json','simulation_partition_no_profile.json','verification.json'):
 if (sf/name).exists():shutil.copy2(sf/name,out/name)
for sub in ('logs','extended_vectors'):
 shutil.copytree(sf/sub,out/sub)
shutil.copytree(BASE/'unit',out/'unit')
for name in ('software_gate.json','rtl_start.json'):shutil.copy2(BASE/name,out/name)
shutil.copytree(BASE/'images',out/'images');shutil.copytree(BASE/'vectors',out/'vectors')
with tarfile.open(out/'verification_tools.tar.gz','w:gz') as t:
 for name in ('Makefile','README.md'):t.add(ROOT/name,arcname=name)
 for directory in ('scripts','tb','tests','experiments/v4.2','manifests/experiments/unified_hbs_v4.2/images'):
  for path in (ROOT/directory).rglob('*'):
   if path.is_file() and '__pycache__' not in path.parts and path.suffix in ('.py','.sv','.tcl','.json','.mem'):t.add(path,arcname=str(path.relative_to(ROOT)))
write(out/'evidence_sha256.json',{str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file() and p.name!='evidence_sha256.json'})
write(BASE/'final.json',dict(candidate=a.tag,functional_pass=True,post_synth_acceptance=True,post_route_pass=False,result_sha256=sha(out/'result.json')))
print('EXTERNAL_ACCEPTED_POST_SYNTH',a.tag,core,flush=True)
