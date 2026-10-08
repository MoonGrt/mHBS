#!/usr/bin/env python3
"""Frozen-source Verilator and common-core synthesis for L/U (no pipeline).

Vivado: six concurrent workers, four threads each. Compilation: two threads.
All logs are retained. No synthesis timeout or routing.
"""
from pathlib import Path
import fcntl,threading,contextlib
import argparse,concurrent.futures,hashlib,importlib.util,json,re,shutil,subprocess,sys,tarfile,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
OUT=ROOT/'manifests/experiments/lu_p1_20261012';BUILD=ROOT/'build/lu_p1_20261012'
POINTS=[(l,1) for l in (1,2,3,4,6,8,12,24)]+[(l,2) for l in (1,2,3,4,6,12)]
REPS=[(1,1),(2,2),(3,1),(12,2),(24,1)]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,d):p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(d,indent=2)+'\n');t.replace(p)
def run(cmd,log,cwd=ROOT):
 log.parent.mkdir(parents=True,exist_ok=True)
 with log.open('w') as f:r=subprocess.run(list(map(str,cmd)),cwd=cwd,stdout=f,stderr=subprocess.STDOUT)
 if r.returncode:raise RuntimeError(f'exit {r.returncode}: {log}')
def module(path,name):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

@contextlib.contextmanager
def synth_slot():
 locks=BUILD/'vivado_slots';locks.mkdir(parents=True,exist_ok=True)
 while True:
  for i in range(6):
   f=(locks/str(i)).open('w')
   try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
   except BlockingIOError:f.close();continue
   try:yield
   finally:f.close()
   return
  time.sleep(2)

def validate(label):
 src=source(label);meta=json.loads((OUT/label/'inputs.json').read_text())
 hashes=meta.get('source_sha256',meta.get('files',{}))
 for name,h in hashes.items():
  if isinstance(h,str):assert (src/name).is_file() and sha(src/name)==h, name
 for name,h in json.loads((OUT/'vectors_sha256.json').read_text()).items():assert sha(OUT/'vectors'/name)==h,name

def vectors():
 from model.profiles import PROFILES
 from model.reference import slh_dsa
 base=ROOT/'manifests/experiments/unified_hbs_v4.2/external_job_message'
 def mem(p,seq,width):p.write_text(''.join(f'{v:0{width}x}\n' for v in seq))
 for name,profile in PROFILES.items():
  if profile.stateful:
   for op in range(3):shutil.copytree(ROOT/'manifests/experiments/stateful_20261008/vectors'/name/'q0_m1'/str(op),OUT/'vectors'/name/str(op),dirs_exist_ok=True)
   continue
  source=base/'vectors'/name/'sign';cfg=json.loads((source/'job.json').read_text());n=profile.n
  sig=bytes(int(x,16) for x in (source/'expected.mem').read_text().split());msg=bytes(int(x,16) for x in (source/'message.mem').read_text().split())[:cfg['message_bytes']]
  params=getattr(slh_dsa,f'SLH_DSA_SHAKE_{n*8}{name[-1].upper()}');counts=[0,0]
  def observe(kind,data,result):counts[0]+=1;counts[1]+=len(data)//136+1
  assert slh_dsa.verify_internal(params,msg,sig,bytes.fromhex(cfg['public_seed']+cfg['public_root']),observe)
  for op in range(3):
   d=OUT/'vectors'/name/str(op);d.mkdir(parents=True,exist_ok=True)
   for f in ('program.mem','template.mem','descriptor.mem'):shutil.copy2(base/'images'/name/f,d/f)
   v=base/'vectors'/name/('keygen' if op==0 else 'sign');meta=[int(x,16) for x in (v/'metadata.mem').read_text().split()]
   shutil.copy2(v/'expected.mem',d/'expected.mem') if op<2 else mem(d/'expected.mem',[0],2)
   values=[int.from_bytes(bytes.fromhex(cfg[k]),'little') for k in ('secret_seed','secret_prf','public_seed','randomizer','public_root')]+[0,0,op,len(msg)]
   mem(d/'job.mem',values,64);mem(d/'message.mem',msg+bytes(87-len(msg)),2)
   mem(d/'nodes.mem',[int.from_bytes(sig[i:i+n],'little') for i in range(0,len(sig),n)],64)
   mem(d/'meta.mem',[meta[0] if op<2 else 0,*(meta[1:3] if op<2 else counts),len(sig)//n,int(op==2)],8)
 write(OUT/'vectors_sha256.json',{str(p.relative_to(OUT/'vectors')):sha(p) for p in (OUT/'vectors').rglob('*') if p.is_file()})

def freeze(label):
 d=OUT/label;target=BUILD/label/'source'
 if (d/'inputs.json').exists():raise ValueError('snapshot exists; choose a new label')
 names=set((ROOT/'manifests/v42_sources.txt').read_text().split())
 names.update(['README.md','Makefile','docs/Architecture.md','docs/Job_Interface.md','docs/Verification.md','manifests/unified_sources.txt','manifests/v42_sources.txt','scripts/v42_common_partition.py','scripts/run_lu_p1.py','tb/integration/tb_mhbs_stateful.sv'])
 names.update(str(p.relative_to(ROOT)) for p in (ROOT/'tb').rglob('*') if p.is_file() and p.suffix in ('.sv','.svh'))
 names.update(str(p.relative_to(ROOT)) for p in (ROOT/'scripts').glob('*.py'))
 names.update(str(p.relative_to(ROOT)) for p in (ROOT/'tests').rglob('*.py'))
 d.mkdir(parents=True,exist_ok=True)
 with tarfile.open(d/'source_snapshot.tar.gz','w:gz') as t:
  for f in sorted(names):t.add(ROOT/f,arcname=f)
 with tarfile.open(d/'source_snapshot.tar.gz') as t:t.extractall(target,filter='data')
 write(d/'inputs.json',dict(source_sha256={f:sha(ROOT/f) for f in sorted(names)},snapshot_sha256=sha(d/'source_snapshot.tar.gz'),clock_ns=10,threads=4,part='xc7a200tffg1156-3'))
 patch=subprocess.check_output(['git','diff','--','rtl','scripts','tb','tests','docs','README.md','Makefile','manifests/v42_sources.txt','manifests/unified_sources.txt'])
 tracked=set(subprocess.check_output(['git','ls-files'],text=True).splitlines())
 for f in sorted(names-tracked):
  patch+=subprocess.run(['git','diff','--no-index','--','/dev/null',f],capture_output=True).stdout
 (d/'source.patch').write_bytes(patch)

def source(label):return BUILD/'original' if label=='baseline' else BUILD/label/'source'
def build(label,l,u,stats=1,swap=0):
 d=BUILD/label/f'L{l}U{u}_s{stats}_x{swap}';d.mkdir(parents=True,exist_ok=True)
 with (d/'build.lock').open('w') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  return _build(label,l,u,stats,swap)

def _build(label,l,u,stats=1,swap=0):
 validate(label);src=source(label);key=f'L{l}U{u}_s{stats}_x{swap}';d=BUILD/label/key;d.mkdir(parents=True,exist_ok=True)
 part=module(src/'scripts/v42_common_partition.py','partition_'+label).partition
 common,_=part((src/'rtl/top/mhbs_top.sv').read_text());(d/'mhbs_common.sv').write_text(common)
 # Baseline and new sources use the same generalized observation harness.
 tb=ROOT/'tb/integration/tb_mhbs_stateful.sv' if label=='baseline' else src/'tb/integration/tb_mhbs_stateful.sv'
 sources=[src/f for f in (src/'manifests/v42_sources.txt').read_text().split() if f!='rtl/top/mhbs_top.sv']+[d/'mhbs_common.sv',tb]
 identity={str(f):sha(f) for f in sources};binary=d/'obj/Vtb_mhbs_stateful'
 if not binary.exists() or not (d/'identity.json').exists() or json.loads((d/'identity.json').read_text())!=identity:
  run(['verilator','--binary','--timing','-O3','-j','2','-Wno-fatal','-Wno-WIDTH','--top-module','tb_mhbs_stateful',f'-GLANES={l}',f'-GUNROLL={u}',f'-GPROFILE_ENABLE={stats}',f'-GSWAP={swap}','--Mdir',binary.parent,*sources],OUT/label/'logs'/f'{key}_compile.log',src)
  write(d/'identity.json',identity)
 return binary

def simulate(label,l,u,profiles=('slh_128f',),ops=(1,),stats=1,swap=0,options=(),suffix=''):
 binary=build(label,l,u,stats,swap);rows=[]
 for name in profiles:
  for op in ops:
   log=OUT/label/'logs'/f'L{l}U{u}_{name}_{op}_s{stats}_x{swap}{suffix}.log'
   run([binary,f'+VECTOR={OUT/"vectors"/name/str(op)}',*options],log)
   matches=re.findall(r'STATEFUL_PASS L\d+U\d+ op=(\d+) cycles=(\d+) total=(\d+) hashes=(\d+) permutations=(\d+)',log.read_text())
   if not matches:
    assert 'STATEFUL_FAULT_PASS' in log.read_text() or 'INDEX_REJECT_PASS' in log.read_text()
    rows.append(dict(profile=name,op=op,passed=True,log=str(log.relative_to(ROOT))));continue
   for match in matches:rows.append(dict(profile=name,op=int(match[0]),lanes=l,unroll=u,cycles=int(match[1]),total=int(match[2]),hashes=int(match[3]),permutations=int(match[4]),log=str(log.relative_to(ROOT))))
 write(OUT/label/f'L{l}U{u}_simulation_s{stats}_x{swap}{suffix}.json',rows)
 print('SIM_PASS',label,f'L{l}U{u}',len(rows),flush=True);return rows

def synth(label,l,u):
 validate(label);src=source(label);d=OUT/label/f'L{l}U{u}';d.mkdir(parents=True,exist_ok=True);w=BUILD/label/f'synth_L{l}U{u}';w.mkdir(parents=True,exist_ok=True)
 part=module(src/'scripts/v42_common_partition.py','synth_partition_'+label).partition
 common,_=part((src/'rtl/top/mhbs_top.sv').read_text(),stub=True);(d/'mhbs_common.sv').write_text(common)
 (d/'clock.xdc').write_text('create_clock -name clk -period 10 [get_ports clk]\n')
 lines=['set_param general.maxThreads 4','create_project -in_memory -part xc7a200tffg1156-3']
 lines += [f'read_verilog -sv {{{src/f}}}' for f in (src/'manifests/v42_sources.txt').read_text().split() if f!='rtl/top/mhbs_top.sv']
 lines += [f'read_verilog -sv {{{d/"mhbs_common.sv"}}}',f'read_xdc {{{d/"clock.xdc"}}}',f'synth_design -top mhbs_common -part xc7a200tffg1156-3 -mode out_of_context -flatten_hierarchy rebuilt -max_dsp 0 -generic LANES={l} -generic UNROLL={u} -generic PROFILE_ENABLE=0',f'report_utilization -file {{{d/"core_utilization.rpt"}}}',f'report_utilization -hierarchical -file {{{d/"core_hierarchical.rpt"}}}',f'report_timing_summary -file {{{d/"core_timing.rpt"}}}',f'write_checkpoint -force {{{w/"synth.dcp"}}}','puts "LU_SYNTH_PASS"','exit']
 (d/'synth.tcl').write_text('\n'.join(lines)+'\n');start=time.monotonic()
 with synth_slot():run(['vivado','-mode','batch','-nolog','-nojournal','-source',d/'synth.tcl'],d/'vivado.log',w)
 assert 'LU_SYNTH_PASS' in (d/'vivado.log').read_text()
 return collect_synth(label,l,u,time.monotonic()-start)

def collect_synth(label,l,u,elapsed=None):
 d=OUT/label/f'L{l}U{u}'
 assert 'LU_SYNTH_PASS' in (d/'vivado.log').read_text()
 report=(d/'core_utilization.rpt').read_text()
 def resource(names):
  for n in names:
   m=re.search(r'\|\s*'+re.escape(n)+r'\s*\|\s*([\d,.]+)',report)
   if m:return float(m[1].replace(',',''))
  raise ValueError(names)
 a=dict(lut=resource(['Slice LUTs*','Slice LUTs']),ff=resource(['Slice Registers']),lutram=resource(['LUT as Memory']),bram=resource(['Block RAM Tile']),dsp=resource(['DSPs']))
 a['equivalent_slice']=a['lut']/4+a['ff']/8+a['bram']*232.4+a['dsp']*102.4
 write(d/'synthesis.json',dict(area=a,elapsed=elapsed,evidence_sha256={f.name:sha(f) for f in d.iterdir() if f.is_file() and f.name!='synthesis.json'}))
 print('SYNTH_PASS',label,f'L{l}U{u}',a,flush=True);return a

def main():
 a=argparse.ArgumentParser();a.add_argument('action',choices=['vectors','freeze','sim','matrix','regress','synth']);a.add_argument('--label',default='structure');a.add_argument('--lanes',type=int,default=2);a.add_argument('--unroll',type=int,default=2);a.add_argument('--profile',default='slh_128f');a.add_argument('--op',type=int,default=1);args=a.parse_args()
 if args.action=='vectors':vectors();return
 if args.action=='freeze':freeze(args.label);return
 if args.action=='sim':simulate(args.label,args.lanes,args.unroll,[args.profile],[args.op]);return
 if args.action=='synth':synth(args.label,args.lanes,args.unroll);return
 from model.profiles import PROFILES
 points=[(1,1),(2,1),(1,2),(2,2)] if args.label=='baseline' else POINTS
 errors=[];states={};guard=threading.Lock()
 def state(point,status):
  with guard:
   states[f'L{point[0]}U{point[1]}']=status
   write(OUT/args.label/(args.action+'_status.json'),dict(complete=False,points=states,errors=errors))
 def work(point):
  l,u=point;state(point,'running')
  try:
   if args.action=='matrix':simulate(args.label,l,u);synth(args.label,l,u)
   else:simulate(args.label,l,u,list(PROFILES),range(3))
   state(point,'passed')
  except Exception as e:print('FAIL',args.label,point,e,flush=True);errors.append(dict(point=point,error=str(e)));state(point,'failed')
 with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:list(pool.map(work,points if args.action=='matrix' else (points if args.label=='baseline' else REPS)))
 write(OUT/args.label/(args.action+'_status.json'),dict(complete=True,passed=not errors,errors=errors))
 if errors:raise SystemExit(1)
if __name__=='__main__':main()
