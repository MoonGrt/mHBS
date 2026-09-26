#!/usr/bin/env python3
"""Bind measured area to a simulation of identical RTL, never mix candidates."""
import argparse,json,re,shutil
from pathlib import Path
from v42_flow import ROOT,BUILD,BASE,BASELINE,sha,write
p=argparse.ArgumentParser();p.add_argument('tag');p.add_argument('--sim-tag');p.add_argument('--route',action='store_true');a=p.parse_args()
f=BUILD/a.tag;inp=json.loads((f/'inputs.json').read_text())
sf=BUILD/(a.sim_tag or a.tag);sim_inp=json.loads((sf/'inputs.json').read_text())
assert inp['rtl_sha256']==sim_inp['rtl_sha256'],'RTL/source mismatch'
assert sha(f/'source_snapshot.tar.gz')==inp['snapshot_sha256']
sims=json.loads((sf/'sim_s0/results.json').read_text())
util=(f/'utilization.rpt').read_text()
def amount(label):
 m=re.search(r'\|\s*'+re.escape(label)+r'\*?\s*\|\s*([\d,.]+)',util)
 if not m:raise ValueError('utilization '+label)
 return float(m[1].replace(',',''))
lut,ff,ram,bram,dsp=map(amount,['Slice LUTs','Slice Registers','LUT as Memory','Block RAM Tile','DSPs'])
area=lut/4+ff/8+bram*232.4+dsp*102.4
period=json.loads((f/'final_clock.json').read_text())['period_ns'] if a.route else 10.
base=json.loads(BASELINE.read_text());profiles={}
for name in ('slh_128f','slh_192f','slh_256f'):
 kg=sims[name+'/keygen'];sg=sims[name+'/sign']
 kg_total=sum(map(int,re.findall(r'RESIDENCY state=\d+ cycles=(\d+)',(sf/f'sim_s0/{name}_keygen.log').read_text())))
 sg_total=sum(map(int,re.findall(r'RESIDENCY state=\d+ cycles=(\d+)',(sf/f'sim_s0/{name}_sign.log').read_text())))
 for op,sim in [('keygen',kg),('sign',sg)]:
  assert sim['passed'] and sha(sf/f'sim_s0/{name}_{op}.log')==sim['log_sha256']
 atp=area*sg['sign_cycles']*period/1e6
 profiles[name]=dict(keygen_cycles=kg['keygen_cycles'],sign_cycles=sg['sign_cycles'],keygen_boot=kg['boot_cycles'],sign_boot=sg['boot_cycles'],keygen_total_cycles=kg_total,sign_total_cycles=sg_total,
  keygen_atp=area*kg['keygen_cycles']*period/1e6,sign_atp=atp,baseline_atp=base['profiles'][name]['sign_atp'],huang_atp=base['profiles'][name]['huang_atp'],
  improved=atp<base['profiles'][name]['sign_atp'])
r=dict(version='v4.2',tag=a.tag,stage='post_route' if a.route else 'post_synth',lut=int(lut),ff=int(ff),lutram=int(ram),bram36=bram,dsp=int(dsp),
 equivalent_slice=area,period_ns=period,frequency_mhz=1000/period,normalized_frequency=not a.route,profiles=profiles,
 worst_ratio=max(x['sign_atp']/x['huang_atp'] for x in profiles.values()),performance_pass=False,
 simulation_tag=sf.name,simulation_sha256=sha(sf/'sim_s0/results.json'),inputs_sha256=sha(f/'inputs.json'))
write(f/'ppa.json',r)
out=BASE/'candidates'/a.tag;out.mkdir(parents=True,exist_ok=True)
for name in ['inputs.json','source_snapshot.tar.gz','ppa.json','utilization.rpt','utilization_hierarchical.rpt','timing_summary.rpt','rom_mapping.tsv','synth.log','synth_seconds.txt','synth_invocation.json','final_clock.json','route_status.rpt','check_timing.rpt']:
 if (f/name).exists():shutil.copy2(f/name,out/name)
for d in ('sim_s0','sim_s1'):
 if (sf/d).exists():
  target=out/d;target.mkdir(exist_ok=True)
  for x in (sf/d).glob('*'):
   if x.is_file():shutil.copy2(x,target/x.name)
print('V42_PPA',a.tag,int(lut),int(ff),area,r['worst_ratio'])
