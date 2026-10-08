#!/usr/bin/env python3
"""Layout 3 external-input builds, traces and source-bound measurements."""
import argparse,concurrent.futures,hashlib,json,re,subprocess,sys,tarfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
BASE=ROOT/'manifests/experiments/unified_hbs_v4.2/external_job_message'
BUILD=ROOT/'build/v4.2/external_job_message'
from model.profiles import SLH_NAMES
NAMES=SLH_NAMES
PARAMS=('secret_seed','secret_prf','public_seed','randomizer','public_root')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,indent=2)+'\n')
def rtl():return (ROOT/'manifests/v42_sources.txt').read_text().split()
def run(cmd,log,cwd=ROOT):
 log.parent.mkdir(parents=True,exist_ok=True)
 with log.open('w') as f:subprocess.run(cmd,cwd=cwd,stdout=f,stderr=subprocess.STDOUT,check=True)
def identity():return {p:sha(ROOT/p) for p in rtl()}
def tool_version(name, *args):
 try:
  return subprocess.check_output([name,*args],text=True,stderr=subprocess.DEVNULL).splitlines()[0]
 except (OSError,subprocess.CalledProcessError,IndexError) as exc:
  raise RuntimeError(f'{name} is required for this operation and must run from PATH') from exc
def capture(tag):
 if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*',tag):
  raise ValueError('tag must start with a letter, digit or underscore and contain only letters, digits, _, . or -')
 f=BUILD/tag;f.mkdir(parents=True,exist_ok=True)
 paths=set(rtl()+['Makefile','README.md','manifests/v42_sources.txt','manifests/unified_sources.txt',
                  'docs/Architecture.md','docs/Job_Interface.md','docs/Verification.md'])
 for directory in ('rtl','model','tests','scripts','tb','experiments/v4.2'):
  paths.update(str(p.relative_to(ROOT)) for p in (ROOT/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.sv','.svh','.tcl','.mem','.json'))
 for directory in (BASE/'images',BASE/'vectors',BASE/'unit',ROOT/'manifests/experiments/unified_hbs_v4.2/images'):
  paths.update(str(p.relative_to(ROOT)) for p in directory.rglob('*') if p.is_file() and p.suffix in ('.mem','.json'))
 paths.update(str(p.relative_to(ROOT)) for p in BASE.glob('*.json') if p.name in ('software_gate.json','rtl_start.json'))
 source={p:sha(ROOT/p) for p in sorted(paths)}
 if (f/'inputs.json').exists():
  old=json.loads((f/'inputs.json').read_text());assert old['source_sha256']==source,'use a fresh tag after changes';return f
 with tarfile.open(f/'source_snapshot.tar.gz','w:gz') as t:
  for p in source:t.add(ROOT/p,arcname=p)
 write(f/'inputs.json',dict(version='v4.2',layout_revision=3,tag=tag,rtl_sha256=identity(),source_sha256=source,snapshot_sha256=sha(f/'source_snapshot.tar.gz'),software_gate_sha256=sha(BASE/'software_gate.json'),baseline_commit='366b614',tool_versions={'verilator':tool_version('verilator','--version')}))
 return f

def build_binary(folder,cfg,swap=0,partitioned=False,profile_enable=True,unroll=2,lanes=2):
 key=hashlib.sha256(json.dumps((cfg,swap,identity(),partitioned,profile_enable,unroll,lanes,[(str(p),sha(p)) for p in sorted((ROOT/"tb/integration").glob("*.svh"))],sha(ROOT/'tb/integration/tb_mhbs_external.sv'),sha(ROOT/'scripts/v42_common_partition.py')),sort_keys=True).encode()).hexdigest()[:16]
 d=folder/'binaries'/key;binary=d/'obj/Vtb_mhbs_external'
 if not binary.exists():
  d.mkdir(parents=True,exist_ok=True)
  parameters=[f"-G{k.upper()}=256'h{int.from_bytes(bytes.fromhex(cfg[k]),'little'):064x}" for k in PARAMS]
  parameters += [f"-GOPERATION={cfg['operation']}",f"-GMESSAGE_BYTES={cfg['message_bytes']}",f'-GSWAP={swap}',f'-GPROFILE_ENABLE={int(profile_enable)}',f'-GUNROLL={unroll}',f'-GLANES={lanes}']
  sources=rtl();defines=[]
  if partitioned:
   from v42_common_partition import partition
   common,shell=partition((ROOT/'rtl/top/mhbs_top.sv').read_text())
   (d/'mhbs_common.sv').write_text(common);(d/'mhbs_top.sv').write_text(shell)
   sources=[p for p in sources if p!='rtl/top/mhbs_top.sv']+[str(d/'mhbs_common.sv'),str(d/'mhbs_top.sv')]
   defines=['-DMHBS_PARTITIONED']
  run(['verilator','--binary','--timing','-O3','-j','2','-Wno-fatal','-Wno-WIDTH','-Wno-UNOPTFLAT',*defines,'--top-module','tb_mhbs_external',*parameters,'--Mdir',str(binary.parent),*sources,'tb/integration/tb_mhbs_external.sv'],d/'compile.log')
 return binary

def simulate_case(folder,name,vector,swap=0,options=(),partitioned=False,profile_enable=True,unroll=2,lanes=2):
 cfg=json.loads((vector/'job.json').read_text());binary=build_binary(folder,cfg,swap,partitioned,profile_enable,unroll,lanes)
 log=folder/'logs'/(name+'.log');log.parent.mkdir(parents=True,exist_ok=True)
 dump=log.with_suffix('.actual.mem')
 cmd=[str(binary),'+IMAGE='+str(BASE/'images'/cfg['profile']),'+VECTOR='+str(vector),'+DUMP='+str(dump),*options]
 run(cmd,log)
 hits=re.findall(r'EXTERNAL_PASS boot=(\d+) keygen=(\d+) sign=(\d+) hashes=(\d+) permutations=(\d+) swap=(\d+) run=(\d+) wait=(\d+) total=(\d+)',log.read_text())
 assert len(hits)==(2 if '+REPLAYS=2' in options else 1),str(log)
 result=dict(zip(('boot_cycles','keygen_cycles','sign_cycles','hashes','permutations','swap','run','wait_cycles','total_cycles'),map(int,hits[-1])))
 result.update(passed=True,lanes=lanes,unroll=unroll,profile_enable=profile_enable,statistics_source="testbench completed-permutation observer",log_sha256=sha(log),output_sha256=sha(dump),binary_sha256=sha(binary),config=cfg,vector_sha256={p.name:sha(p) for p in vector.iterdir() if p.is_file()})
 write(log.with_suffix('.json'),result);print('EXTERNAL_SIM_PASS',name,result['keygen_cycles'],result['sign_cycles'],flush=True)
 return name,result

def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=['capture','sim']);p.add_argument('--tag',required=True);p.add_argument('--profile',choices=['all',*NAMES],default='all');p.add_argument('--operation',choices=['all','keygen','sign'],default='all');p.add_argument('--swap',type=int,choices=[0,1],default=0);p.add_argument('--partition',action='store_true');p.add_argument('--no-profile',action='store_true');p.add_argument('--unroll',type=int,default=2);p.add_argument('--lanes',type=int,choices=[1,2,3,4,6,8,12,24],default=2);a=p.parse_args()
 f=capture(a.tag)
 if a.action=='sim':
  def one(case):
   n,o=case;return simulate_case(f,n+'_'+o+('_swap' if a.swap else '')+('_partition' if a.partition else '')+('_no_profile' if a.no_profile else ''),BASE/'vectors'/n/o,a.swap,partitioned=a.partition,profile_enable=not a.no_profile,unroll=a.unroll,lanes=a.lanes)
  with concurrent.futures.ThreadPoolExecutor(3) as pool:r=dict(pool.map(one,[(n,o) for n in NAMES if a.profile in ('all',n) for o in ('keygen','sign') if a.operation in ('all',o)]))
  filename='simulation_partition' if a.partition else 'simulation_s1' if a.swap else 'simulation'
  if a.no_profile:filename+='_no_profile'
  write(f/(filename+'.json'),dict(passed=True,rtl_sha256=identity(),cases=r))
if __name__=='__main__':main()
