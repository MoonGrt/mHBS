#!/usr/bin/env python3
"""Check 32-word program inference and every initialized address/data bit."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
f=Path(sys.argv[1]);profile=sys.argv[2]
def words(path):return [int(w,16) for w in path.read_text().split()]
def rows(path):
 result=[]
 for line in path.read_text().splitlines():
  kind,port,bit,cell,abits,pins,init=line.split('\t')
  result.append(dict(kind=kind,port=int(port),bit=int(bit),cell=cell,abits=int(abits),pins=list(map(int,pins.split(','))),init=int(init.split("'h")[1],16)))
 return result
def encoded(row,data):
 assert sorted(row['pins'])==list(range(row['abits']))
 return sum(((data[sum(((i>>p)&1)<<a for p,a in enumerate(row['pins']))]>>row['bit'])&1)<<i for i in range(1<<row['abits']))
mapping=rows(f/'rom_mapping.tsv');assert len(mapping)==256 and len({r['cell'] for r in mapping})==256
construct={k:words(ROOT/f'experiments/v4.2/external_job_message/{k}_construction.mem') for k in ('program','template','descriptor')}
real={k:words(ROOT/f'manifests/experiments/unified_hbs_v4.2/external_job_message/images/{profile}/{k}.mem') for k in construct}
commands=[]
for r in mapping:
 assert encoded(r,construct[r['kind']])==r['init']
 value=encoded(r,real[r['kind']]);width=1<<r['abits']
 commands.append(f"set_property INIT {width}'h{value:0{width//4}x} [get_cells {{{r['cell']}}}]")
if '--audit' in sys.argv:
 actual=rows(f/'initialized_rom.tsv')
 assert len(actual)==len(mapping)
 for a,r in zip(actual,mapping):
  assert all(a[k]==r[k] for k in ('kind','port','bit','cell','abits','pins'))
  assert a['init']==encoded(a,real[a['kind']])
 (f/'rom_audit.json').write_text(json.dumps(dict(passed=True,cells=len(mapping),profile=profile),indent=2)+'\n')
else:(f/'init.tcl').write_text('\n'.join(commands)+'\n')
print('EXTERNAL_ROM_PASS',profile)
