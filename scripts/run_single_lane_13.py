#!/usr/bin/env python3
"""Resumable 128f Sign P/U cycle and common-core synthesis matrix."""
import concurrent.futures, csv, hashlib, json, os, re, shutil, subprocess, tarfile, threading, time, signal, sys, fcntl
from datetime import datetime, timezone
from pathlib import Path
import experiment_support as support
import v42_external_flow as flow
from v42_common_partition import partition

ROOT=Path(__file__).resolve().parents[1]
TAG='single_lane_13_20261009_v2'
OUT=ROOT/'manifests/experiments'/TAG
BUILD=OUT/'work'
SOURCE=OUT/'source'
POINTS=[(p,1) for p in (1,2,3,4,6,8,12)]+[(p,2) for p in (1,2,3,4,6,12)]
LOCK=threading.Lock()
PART='xc7a200tffg1156-3'

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def now(): return datetime.now(timezone.utc).isoformat()
def write(p,d):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
 tmp=p.with_name(p.name+f'.{os.getpid()}.{threading.get_ident()}.tmp')
 tmp.write_text(json.dumps(d,indent=2,ensure_ascii=False,sort_keys=True)+'\n');tmp.replace(p)

def prepare():
 if (OUT/'status.json').exists():
  s=json.loads((OUT/'status.json').read_text())
  assert s['config_sha256']==sha(OUT/'config.json')
  return s
 OUT.mkdir(parents=True,exist_ok=True);BUILD.mkdir(parents=True,exist_ok=True)
 (OUT/'.gitignore').write_text('/source/\n/work/\n/run.lock\n')
 hashes=support.snapshot(OUT)
 inputs=json.loads((OUT/'inputs.json').read_text())
 inputs.pop('frequency_mhz_assumed',None)
 inputs['frequency_mhz_assumed_by_u']={'1':150,'2':110}
 write(OUT/'inputs.json',inputs)
 (OUT/'source.patch').write_bytes(subprocess.check_output(['git','diff','HEAD','--','rtl','scripts','tb'],cwd=ROOT))
 with tarfile.open(OUT/'source_snapshot.tar.gz') as t:t.extractall(SOURCE,filter='data')
 for f,h in hashes.items():assert sha(SOURCE/f)==h,f
 assert sha(OUT/'source_snapshot.tar.gz')==json.loads((OUT/'inputs.json').read_text())['snapshot_sha256']
 config=dict(schema='mhbs.single_lane_13.v1',created_at=now(),scope='128f Sign common-core synthesis',
  tested='fixed single lane; U1 P1/2/3/4/6/8/12; U2 P1/2/3/4/6/12',points=POINTS,git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),device=PART,clock_period_ns=6.666667,
  simulation_gate="Verilator full 128f sign; Icarus disabled by user",profile_enable_synthesis=0,max_parallel_points=13,vivado_threads_per_point=2,compile_threads_per_point=2,tool_timeout_seconds=7200,assumed_mhz_by_u={1:150,2:110},routed=False,
  source_sha256=hashes,snapshot_sha256=sha(OUT/'source_snapshot.tar.gz'),
  vivado=subprocess.check_output(['vivado','-version'],text=True).splitlines()[0],
  verilator=subprocess.check_output(['verilator','--version'],text=True).splitlines()[0])
 write(OUT/'config.json',config)
 status=dict(schema=config['schema'],state='prepared',pid=None,started_at=now(),updated_at=now(),
  config_sha256=sha(OUT/'config.json'),total=len(POINTS),completed=0,failed=0,
  points={f'P{p}U{u}':'pending' for p,u in POINTS},
  unsupported={})
 write(OUT/'status.json',status)
 return status

def update(name=None,value=None,**kwargs):
 with LOCK:
  s=json.loads((OUT/'status.json').read_text())
  if name:s['points'][name]=value
  s.update(kwargs);s['completed']=sum(v=='complete' for v in s['points'].values())
  s['failed']=sum(v=='failed' for v in s['points'].values());s['updated_at']=now()
  write(OUT/'status.json',s)

def tool_run(cmd,log,cwd=SOURCE):
 log=Path(log);log.parent.mkdir(parents=True,exist_ok=True)
 with log.open('w') as stream:
  proc=subprocess.Popen(list(map(str,cmd)),cwd=cwd,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
  try:code=proc.wait(timeout=7200)
  except subprocess.TimeoutExpired:
   os.killpg(proc.pid,signal.SIGTERM)
   try:proc.wait(timeout=10)
   except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
   raise RuntimeError(f'tool timeout after 7200 seconds: {log}')
 if code:raise RuntimeError(f'tool exit={code}: {log}; '+log.read_text(errors='replace')[-1200:])

def bind_snapshot():
 config=json.loads((OUT/'config.json').read_text())
 assert sha(OUT/'source_snapshot.tar.gz')==config['snapshot_sha256'],'snapshot archive changed'
 for f,h in config['source_sha256'].items():assert sha(SOURCE/f)==h,f
 base=SOURCE/'manifests/experiments/unified_hbs_v4.2/external_job_message'
 flow.ROOT=SOURCE;flow.BASE=base;support.ROOT=SOURCE;support.BASE=base
 def frozen_run(cmd,log,cwd=SOURCE):
  cmd=list(cmd)
  if cmd and cmd[0]=='verilator' and '-j' in cmd:cmd[cmd.index('-j')+1]='2'
  return tool_run(cmd,log,cwd)
 flow.run=frozen_run
 return base

def synth(name,p,u):
 d=OUT/name;d.mkdir(exist_ok=True)
 common,_=partition((SOURCE/'rtl/top/mhbs_top.sv').read_text(),stub=True)
 (d/'mhbs_common.sv').write_text(common)
 (d/'clock.xdc').write_text('create_clock -name clk -period 6.666667 [get_ports clk]\n')
 sources=(SOURCE/'manifests/v42_sources.txt').read_text().split()
 lines=['set_param general.maxThreads 2',f'create_project -in_memory -part {PART}']
 lines += [f'read_verilog -sv {{{SOURCE/f}}}' for f in sources if f!='rtl/top/mhbs_top.sv']
 lines += [f'read_verilog -sv {{{d/"mhbs_common.sv"}}}',f'read_xdc {{{d/"clock.xdc"}}}',
  f'synth_design -top mhbs_common -part {PART} -mode out_of_context -flatten_hierarchy rebuilt -max_dsp 0 -generic PIPELINE={p} -generic UNROLL={u} -generic PROFILE_ENABLE=0',
  f'report_utilization -file {{{d/"core_utilization.rpt"}}}',
  f'report_utilization -hierarchical -file {{{d/"core_hierarchical.rpt"}}}',
  f'report_timing_summary -file {{{d/"core_timing.rpt"}}}',
  'set bad {}',
  'foreach c [get_cells -hier -filter {IS_PRIMITIVE == 1}] {if {[string match FD* [get_property REF_NAME $c]] && [regexp {(cycles|hash_count|permutation_count|hash_base|permutation_base)_reg} $c]} {lappend bad $c}}',
  'if {[llength $bad]} {error "Statistics registers remain: $bad"}',
  f'write_checkpoint -force {{{BUILD/name/"post_synth.dcp"}}}',f'puts "PU_SYNTH_PASS {name}"','exit']
 (d/'synth.tcl').write_text('\n'.join(lines)+'\n')
 (BUILD/name).mkdir(parents=True,exist_ok=True);start=time.monotonic()
 for attempt in range(2):
  try:
   tool_run(['vivado','-mode','batch','-nolog','-nojournal','-source',d/'synth.tcl'],d/'vivado.log',BUILD/name)
   if f'PU_SYNTH_PASS {name}' not in (d/'vivado.log').read_text():raise RuntimeError('Missing synthesis completion marker')
   break
  except Exception:
   transient=bool(re.search(r'license.*(unavailable|checkout failed)|segmentation|internal exception|killed', (d/'vivado.log').read_text(errors='replace'),re.I))
   if attempt or not transient:raise
   shutil.copy2(d/'vivado.log',d/'vivado_attempt0.log')
 a=support.area(d/'core_utilization.rpt')
 files=('mhbs_common.sv','clock.xdc','synth.tcl','vivado.log','core_utilization.rpt','core_hierarchical.rpt','core_timing.rpt')
 write(d/'synthesis.json',dict(area=a,elapsed_seconds=time.monotonic()-start,evidence_sha256={f:sha(d/f) for f in files},post_synth_dcp_sha256=sha(BUILD/name/'post_synth.dcp')))
 return a

def point(p,u):
 name=f'P{p}U{u}';d=OUT/name;d.mkdir(exist_ok=True)
 if (d/'failure.json').exists():update(name,'failed');return
 try:
  target=d/'result.json'
  if target.exists() and json.loads(target.read_text())['snapshot_sha256']==sha(OUT/'source_snapshot.tar.gz'):
   update(name,'complete');return
  base=SOURCE/'manifests/experiments/unified_hbs_v4.2/external_job_message';simulation=d/'simulation.json'
  if simulation.exists():r=json.loads(simulation.read_text())
  else:
   update(name,'simulating')
   _,r=flow.simulate_case(BUILD/'simulation',name,base/'vectors/slh_128f/sign',pipeline=p,unroll=u)
   if (r['hashes'],r['permutations'])!=(104937,105641):raise AssertionError(f'wrong count {r["hashes"]}/{r["permutations"]}')
   write(simulation,r)
   for ext in ('.log','.actual.mem'):
    shutil.copy2(BUILD/'simulation/logs'/(name+ext),d/(name+ext))
  if (d/'synthesis.json').exists():a=json.loads((d/'synthesis.json').read_text())['area']
  else:update(name,'synthesizing');a=synth(name,p,u)
  if a['lut']>134600 or a['ff']>269200 or a['bram36']>365 or a['dsp']>740:raise RuntimeError('Synthesis completed but device resource capacity exceeded')
  mhz=150 if u==1 else 110
  row=dict(point=name,p=p,u=u,assumed_mhz=mhz,time_ms=r['sign_cycles']/(mhz*1000),atp_slice_ms=a['equivalent_slice']*r['sign_cycles']/(mhz*1000),simulation='pass',synthesis='pass',sign_cycles=r['sign_cycles'],total_cycles=r['total_cycles'],hashes=r['hashes'],permutations=r['permutations'],output_sha256=r['output_sha256'],**a,snapshot_sha256=sha(OUT/'source_snapshot.tar.gz'))
  write(target,row);update(name,'complete');print('POINT_PASS',name,row['sign_cycles'],row['lut'],flush=True)
 except Exception as exc:
  write(d/'failure.json',dict(point=name,error=repr(exc),at=now()))
  update(name,'failed');print('POINT_FAIL',name,repr(exc),flush=True)

def finish():
 rows=[]
 for p,u in POINTS:
  name=f'P{p}U{u}';d=OUT/name
  if (d/'result.json').exists():rows.append(json.loads((d/'result.json').read_text()))
  else:
   failure=d/'failure.json';row=dict(point=name,p=p,u=u,simulation='-',synthesis='failed' if failure.exists() else 'incomplete',error=json.loads(failure.read_text())['error'] if failure.exists() else 'incomplete')
   if (d/'simulation.json').exists():
    sim=json.loads((d/'simulation.json').read_text())
    row.update(simulation='pass',**{key:sim[key] for key in ('sign_cycles','total_cycles','hashes','permutations','output_sha256')})
   rows.append(row)
 ranked=sorted([r for r in rows if r.get('synthesis')=='pass'],key=lambda r:r['atp_slice_ms'])
 for rank,r in enumerate(ranked,1):r['rank']=rank
 rows=ranked+[r for r in rows if r.get('synthesis')!='pass']
 outputs={r['output_sha256'] for r in rows if r.get('simulation')=='pass'}
 for r in rows:
  if r.get('simulation')=='pass':r['reference_agreement']='pass' if len(outputs)==1 else 'fail'
 write(OUT/'results.json',dict(scope='128f Sign common-core synthesis',rows=rows,output_agreement=len(outputs)==1,actual_frequency='not measured; synthesis only',unsupported=json.loads((OUT/'status.json').read_text())['unsupported']))
 keys=('rank','point','p','u','simulation','synthesis','reference_agreement','sign_cycles','total_cycles','hashes','permutations','lut','ff','lutram','bram36','dsp','equivalent_slice','assumed_mhz','time_ms','atp_slice_ms','error')
 with (OUT/'results.csv').open('w') as f:
  w=csv.DictWriter(f,fieldnames=keys,extrasaction='ignore',lineterminator='\n');w.writeheader();w.writerows(rows)
 lines=['# P/U 128f Sign cycle and synthesis matrix','','Device: xc7a200tffg1156-3; Vivado 2025.2; 6.666667 ns synthesis constraint; PROFILE_ENABLE=0.','Synthesis does not measure frequency. LUT includes LUTRAM. Common core excludes external ROM and signature cache.','One physical hash lane; only P and U are configurable. Assumed frequency: U1=150 MHz, U2=110 MHz; no routed frequency measurement.','','| Rank | Point | Cycles | Total cycles | LUT | FF | LUTRAM | BRAM36 | DSP | Eq. Slice | MHz | Time ms | ATP | Status |','|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|']
 for r in rows:
  show=lambda key:str(r[key]) if key in r else '-'
  lines.append(f'| {show("rank")} | {r["point"]} | {show("sign_cycles")} | {show("total_cycles")} | {show("lut")} | {show("ff")} | {show("lutram")} | {show("bram36")} | {show("dsp")} | {show("equivalent_slice")} | {show("assumed_mhz")} | {show("time_ms")} | {show("atp_slice_ms")} | {r["simulation"]}/{r["synthesis"]} |')
 (OUT/'report.md').write_text('\n'.join(lines)+'\n')
 write(OUT/'evidence_sha256.json',{str(f.relative_to(OUT)):sha(f) for f in OUT.rglob('*') if f.is_file() and not {'work','source'}.intersection(f.relative_to(OUT).parts) and f.name not in ('evidence_sha256.json','status.json','run.lock','service.log') and f.suffix!='.dcp'})
 complete=all(r.get('simulation')=='pass' and r.get('synthesis')=='pass' for r in rows) and len(outputs)==1
 update(state='complete' if complete else 'complete_with_failures',ended_at=now())
 (OUT/'DONE').write_text(json.loads((OUT/'status.json').read_text())['state']+'\n')

def main():
 global OUT,BUILD,SOURCE
 import argparse
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('action',choices=('prepare','run'));ap.add_argument('--directory',type=Path,default=OUT);a=ap.parse_args()
 OUT=a.directory.resolve();BUILD=OUT/'work';SOURCE=OUT/'source'
 if a.action=='prepare':prepare();print('PREPARED',OUT/'status.json');return
 # Run only the frozen script, so later worktree changes cannot affect measurements.
 assert Path(__file__).resolve()==SOURCE/'scripts/run_single_lane_13.py','Run the frozen source script'
 with (OUT/'run.lock').open('w') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  try:
   prepare();bind_snapshot();update(state='running',pid=os.getpid())
   update(state='matrix')
   with concurrent.futures.ThreadPoolExecutor(max_workers=13) as pool:
    list(pool.map(lambda x:point(*x),POINTS))
   finish()
  except Exception as exc:
   write(OUT/'service_failure.json',dict(error=str(exc),at=now()))
   update(state='failed',error=str(exc));raise
if __name__=='__main__':main()
