#!/usr/bin/env python3
"""Accept and archive a routed body only with all six INIT and functional proofs."""
import argparse,gzip,hashlib,json,re,shutil,tarfile
from pathlib import Path
from v42_flow import ROOT,BUILD,BASE,NAMES,sha,write
p=argparse.ArgumentParser();p.add_argument('tag');p.add_argument('--verification-tag',required=True);a=p.parse_args()
f=BUILD/a.tag;r=json.loads((f/'ppa.json').read_text());inp=json.loads((f/'inputs.json').read_text())
assert r['stage']=='post_route'
v=BUILD/a.verification_tag/'verification';vr=json.loads((v/'results.json').read_text())
assert vr['passed'] and vr['rtl_sha256']==inp['rtl_sha256'] and len(vr['cases'])>=42
assert sha(v/'tb_uhbs_v42.sv')==vr['bench_sha256']
for name,case in vr['cases'].items():
 assert case['passed'] and sha(v/(name.replace('/','_')+'.log'))==case['log_sha256']
 for filename,digest in case['image_sha256'].items():assert sha(v/'images'/name/filename)==digest
lid=hashlib.sha256(json.dumps(inp['rtl_sha256'],sort_keys=True).encode()).hexdigest()[:16]
u=BASE/'unit'/lid;ur=json.loads((u/'results.json').read_text())
assert ur['passed'] and ur['logic_sha256']==inp['rtl_sha256']
for name,digest in ur['logs'].items():assert sha(u/(name+'.log'))==digest
clock=json.loads((f/'final_clock.json').read_text());assert clock['wns_ns']>=.0999 and clock['whs_ns']>=0
status=(f/'route_status.rpt').read_text()
def net_count(label):
 m=re.search(r'# of '+label+r'\.*\s*:\s*(\d+)\s*:',status);assert m,label;return int(m[1])
assert net_count('routable nets')==net_count('fully routed nets') and net_count('nets with routing errors')==0
coverage=(f/'check_timing.rpt').read_text()
for key in ('no_clock','constant_clock','pulse_width_clock','unconstrained_internal_endpoints','multiple_clock','loops','latch_loops'):
 assert re.search(r'checking '+key+r' \(0\)',coverage),key
audit=json.loads((f/'routed_rom_audit.json').read_text())
assert audit['passed'] and audit['source_sha256']==sha(f/'rom_mapping.tsv') and audit['routed_sha256']==sha(f/'routed_rom_mapping.tsv')
assert (f/'rom_mapping.tsv').read_bytes()==(f/'routed_rom_mapping.tsv').read_bytes()
mapping=json.loads((f/'frozen/init/mapping.json').read_text());assert mapping['passed']
rows=dict(line.split('\t') for line in (f/'frozen/evidence.tsv').read_text().splitlines())
assert set(rows)=={n+'_'+o for n in NAMES for o in ('keygen','sign')} and len(set(rows.values()))==1
assert sha(f/'frozen/hardware.txt')==next(iter(rows.values()))
for name in rows:
 assert (f/'frozen'/(name+'.dcp')).is_file()
 actual=dict(line.split('\t') for line in (f/'frozen'/(name+'_init.tsv')).read_text().splitlines())
 expected={x['cell']:x['init'] for x in mapping['images'][name]}
 assert set(actual)==set(expected)
 assert all(int(actual[c].split("'h")[1],16)==value for c,value in expected.items())
 # Independent per-image timing and resource evidence at the same frozen clock.
 text=(f/'frozen'/(name+'_timing.rpt')).read_text()
 row=re.search(r'WNS\(ns\).*?\n\s*[- ]+\n([^\n]+)',text,re.S)[1].split()
 assert float(row[0])>=.0999 and float(row[4])>=0 and float(row[8])>=0
 util=(f/'frozen'/(name+'_utilization.rpt')).read_text()
 for label,key in [('Slice LUTs','lut'),('Slice Registers','ff'),('LUT as Memory','lutram'),('Block RAM Tile','bram36'),('DSPs','dsp')]:
  m=re.search(r'\|\s*'+re.escape(label)+r'\*?\s*\|\s*([\d,.]+)',util);assert m
  assert float(m[1].replace(',',''))==r[key],(name,label)
r.update(functional_pass=True,frozen_init_mapping_pass=True,frozen_hardware_sha256=next(iter(rows.values())),
         timing_pass=True,final_clock=clock,performance_pass=all(x['improved'] for x in r['profiles'].values()),
         verification_tag=a.verification_tag,verification_sha256=sha(v/'results.json'),unit_sha256=sha(u/'results.json'))
write(f/'ppa.json',r)
archive=BASE/'candidates'/a.tag;archive.mkdir(parents=True,exist_ok=True)
# Bind finalized evidence once; future workspace tests must not rewrite it.
for path in f.iterdir():
 if path.is_file() and path.suffix in ('.json','.rpt','.tcl','.tsv','.log','.txt','.dcp','.gz','.xdc'):
  shutil.copy2(path,archive/path.name)
shutil.copytree(f/'frozen',archive/'frozen',dirs_exist_ok=True,ignore=shutil.ignore_patterns('hardware.txt'))
with (f/'frozen/hardware.txt').open('rb') as src,gzip.open(archive/'frozen/hardware.txt.gz','wb') as dst:shutil.copyfileobj(src,dst)
shutil.copytree(u,archive/'unit',dirs_exist_ok=True)
for path in v.rglob('*'):
 if path.is_file() and not any(x.startswith('obj_') for x in path.relative_to(v).parts) and 'source' not in path.relative_to(v).parts:
  target=archive/'verification'/path.relative_to(v);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
# The current wrappers are provenance, not substitutions for the measured RTL snapshot.
with tarfile.open(archive/'verification_tools.tar.gz','w:gz') as t:
 for path in [*ROOT.glob('scripts/*v42*.py'),*ROOT.glob('tests/*.py'),*ROOT.glob('experiments/v4.2/*.tcl'),ROOT/'tb/integration/tb_uhbs_v42.sv',ROOT/'Makefile']:
  t.add(path,arcname=str(path.relative_to(ROOT)))
# Supplemental offline checks do not alter the measured RTL or image bytes.
for filename in ('format_gate.json',):
 if (BASE/filename).exists():shutil.copy2(BASE/filename,archive/filename)
write(archive/'evidence_sha256.json',{str(p.relative_to(archive)):sha(p) for p in sorted(archive.rglob('*')) if p.is_file() and p.name!='evidence_sha256.json'})
write(BASE/'final.json',dict(version='v4.2',candidate=a.tag,performance_pass=r['performance_pass'],ppa_sha256=sha(archive/'ppa.json')))
print('V42_FINALIZED',a.tag,'performance_pass',r['performance_pass'])
