#!/usr/bin/env python3
"""Independent masked seed/chain vectors, ordinary chain feedback."""
from pathlib import Path
import subprocess,json,hashlib,sys
from v42_external_flow import ROOT
label=sys.argv[1] if len(sys.argv)>1 else ''
OUT=ROOT/'manifests/experiments/lu_p1_20261012'/label/'masked_chain';OUT.mkdir(parents=True,exist_ok=True)
BUILD=ROOT/'build/lu_p1_20261012'/label/'masked_chain';BUILD.mkdir(parents=True,exist_ok=True)
def h(x):return hashlib.shake_256(x).digest(32)
def be(x,n=4):return x.to_bytes(n,'big')
public=bytes(range(64,96));secret=bytes(range(32));vectors=[]
for steps,cap in ((0,0),(3,0),(3,3),(15,7),(15,15)):
 addr=lambda j:bytes(12)+be(0)+be(5)+be(132)+be(j)
 value=h(be(4,32)+secret+public+addr(0)+be(0));captured=value if cap==0 else None
 for j in range(steps):
  key=h(be(3,32)+public+addr(j)+be(0));mask=h(be(3,32)+public+addr(j)+be(1))
  value=h(bytes(32)+key+bytes(a^b for a,b in zip(value,mask)))
  if j+1==cap:captured=value
 seed=(7<<56)|(1<<40);step=(8<<56)|(1<<40)
 vectors.append((seed<<960)|(step<<896)|(1<<895)|(steps<<890)|(cap<<885)|(132<<877)|(32<<839)|(int.from_bytes(value,'little')<<256)|int.from_bytes(captured,'little'))
vec=OUT/'vectors.mem';vec.write_text(''.join(f'{v:0256x}\n' for v in vectors))
sources=(ROOT/'manifests/v42_sources.txt').read_text().split()+['tb/reference/mhbs_shake_pre_direct_ref.sv','tb/reference/mhbs_recipe_pre_direct_ref.sv','tb/unit/tb_mhbs_v42_recipe_lane.sv'];rows=[]
for u in (1,2):
 name=f'U{u}';obj=BUILD/name;exe=obj/'Vtb_mhbs_v42_recipe_lane';log=OUT/(name+'.log')
 with log.open('w') as f:
  subprocess.run(['verilator','--binary','--timing','-j','2','-Wno-fatal','--top-module','tb_mhbs_v42_recipe_lane','-GPROFILE=2','-GMASK=65534','-GCASES=5',f'-GUNROLL={u}','--Mdir',str(obj),*sources],cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True)
  subprocess.run([str(exe),f'+VECTORS={vec}'],cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True)
 assert 'UNIFIED_RECIPE_PASS' in log.read_text()
 rows.append(dict(configuration=name,passed=True,cases=5,log_sha256=hashlib.sha256(log.read_bytes()).hexdigest()));print('MASKED_CHAIN_PASS',name,flush=True)
(OUT/'results.json').write_text(json.dumps(rows,indent=2)+'\n')
