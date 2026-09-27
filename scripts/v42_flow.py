#!/usr/bin/env python3
"""Immutable v4.2 builds and common-hardware candidate evidence."""
import argparse,concurrent.futures,hashlib,json,re,subprocess,sys,tarfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
BASE=ROOT/'manifests/experiments/unified_hbs_v4.2'
BUILD=ROOT/'build/v4.2'
BASELINE=ROOT/'manifests/experiments/unified_hbs_v4.1/slh_only/candidates/slh_only_u2_l2_hil_cursor_c2_route/ppa.json'
NAMES=('slh_128f','slh_192f','slh_256f')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,indent=2)+'\n')
def sources():return (ROOT/'manifests/v42_sources.txt').read_text().split()
def run(cmd,log,cwd=ROOT):
 log.parent.mkdir(parents=True,exist_ok=True)
 with log.open('w') as f:subprocess.run(cmd,cwd=cwd,stdout=f,stderr=subprocess.STDOUT,check=True)
def capture(tag):
 folder=BUILD/tag;folder.mkdir(parents=True,exist_ok=True)
 paths=set(sources()+['Makefile','manifests/v42_sources.txt','tb/integration/tb_mhbs_v42.sv','scripts/v42_flow.py','scripts/verify_v42_models.py','scripts/v42_rom.py','model/slh64.py'])
 for d in ('experiments/v4.2','model','tests','tb','scripts'):
  paths.update(str(p.relative_to(ROOT)) for p in (ROOT/d).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.sv','.svh','.mem','.json','.tcl'))
 paths.update(str(p.relative_to(ROOT)) for p in (BASE/'images').rglob('*') if p.is_file())
 paths.update(str(p.relative_to(ROOT)) for p in BASE.glob('*.json') if p.name.endswith('_gate.json') or p.name in ('software_gate_initial.json','rtl_start.json'))
 hashes={p:sha(ROOT/p) for p in sorted(paths)}
 record=dict(version='v4.2',format='slh64_v4.2',layout_revision=json.loads((BASE/'software_gate.json').read_text()).get('layout_revision',1),baseline=str(BASELINE.relative_to(ROOT)),baseline_sha256=sha(BASELINE),source_sha256=hashes,
             rtl_sha256={p:hashes[p] for p in sources()},lanes=2,unroll=2,part='xc7a200tffg1156-3',captured_unix=time.time(),
             tool_versions={'verilator':subprocess.check_output(['verilator','--version'],text=True).strip(),
               'iverilog':subprocess.check_output(['iverilog','-V'],text=True,stderr=subprocess.DEVNULL).splitlines()[0],
               'vivado':subprocess.check_output(['vivado','-version'],text=True).strip()})
 if (folder/'inputs.json').exists():
  old=json.loads((folder/'inputs.json').read_text())
  if old['source_sha256']!=hashes:raise ValueError('tag sources changed: choose new tag')
  return folder
 with tarfile.open(folder/'source_snapshot.tar.gz','w:gz') as t:
  for p in hashes:t.add(ROOT/p,arcname=p)
 record['snapshot_sha256']=sha(folder/'source_snapshot.tar.gz');write(folder/'inputs.json',record)
 return folder

def simulate(args):
 folder=capture(args.tag)
 out=folder/f'sim_s{args.swap}';out.mkdir(exist_ok=True)
 binary=out/'obj/Vtb_mhbs_v42'
 if not binary.exists():
  run(['verilator','--binary','--timing','-O3','-j','8','-Wno-fatal','-Wno-WIDTH','-Wno-UNOPTFLAT',
       '--top-module','tb_mhbs_v42',f'-GSWAP={args.swap}','--Mdir',str(binary.parent),*sources(),'tb/integration/tb_mhbs_v42.sv'],out/'compile.log')
 def one(case):
  name,op=case;log=out/f'{name}_{op}.log'
  image=BASE/'images'/name/op
  cmd=[str(binary),'+IMAGE='+str(image),'+DUMP='+str(out/f'{name}_{op}_actual.mem')]
  if args.replay:cmd+=['+INTERRUPT=1','+REPLAYS=2']
  run(cmd,log)
  hits=re.findall(r'V42_PASS boot=(\d+) keygen=(\d+) sign=(\d+) hashes=(\d+) permutations=(\d+)',log.read_text())
  if len(hits)!=(2 if args.replay else 1):raise ValueError('missing pass '+str(log))
  r=dict(zip(('boot_cycles','keygen_cycles','sign_cycles','hashes','permutations'),map(int,hits[-1])))
  r.update(passed=True,swap=args.swap,replay=args.replay,log_sha256=sha(log),binary_sha256=sha(binary),
           image_sha256={p.name:sha(p) for p in image.glob('*.mem')})
  write(log.with_suffix('.json'),r);print('SIM_PASS',name,op,r['keygen_cycles'],r['sign_cycles'],flush=True)
  return name+'/'+op,r
 with concurrent.futures.ThreadPoolExecutor(3) as pool:results=dict(pool.map(one,((n,o) for n in NAMES if args.profile in ('all',n) for o in ('keygen','sign') if args.operation in ('all',o))))
 write(out/'results.json',results)

def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=['sim','capture']);p.add_argument('--tag',required=True)
 p.add_argument('--profile',choices=['all',*NAMES],default='all');p.add_argument('--operation',choices=['all','keygen','sign'],default='all');
 p.add_argument('--swap',type=int,default=0);p.add_argument('--replay',action='store_true');args=p.parse_args()
 if args.action=='sim':simulate(args)
 else:capture(args.tag)
if __name__=='__main__':main()
