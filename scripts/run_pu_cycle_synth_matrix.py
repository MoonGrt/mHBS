#!/usr/bin/env python3
"""Resumable 128f Sign P/U cycle and common-core synthesis matrix."""
import concurrent.futures, csv, hashlib, json, os, re, shutil, subprocess, tarfile, threading, time
from datetime import datetime, timezone
from pathlib import Path
import experiment_support as support
import v42_external_flow as flow
from v42_common_partition import partition

ROOT=Path(__file__).resolve().parents[1]
TAG='pu_single_lane_20261008_v1'
OUT=ROOT/'manifests/experiments'/TAG
BUILD=ROOT/'build'/TAG
SOURCE=BUILD/'source'
POINTS=[(p,u) for u in (1,2) for p in range(1,5)]
LOCK=threading.Lock()
PART='xc7a200tffg1156-3'

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def now(): return datetime.now(timezone.utc).isoformat()
def write(p,d):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
 tmp=p.with_name(p.name+f'.{os.getpid()}.tmp')
 tmp.write_text(json.dumps(d,indent=2,ensure_ascii=False,sort_keys=True)+'\n');tmp.replace(p)

def prepare():
 if (OUT/'status.json').exists():
  s=json.loads((OUT/'status.json').read_text())
  assert s['config_sha256']==sha(OUT/'config.json')
  return s
 OUT.mkdir(parents=True,exist_ok=True);BUILD.mkdir(parents=True,exist_ok=True)
 hashes=support.snapshot(OUT)
 with tarfile.open(OUT/'source_snapshot.tar.gz') as t:t.extractall(SOURCE,filter='data')
 for f,h in hashes.items():assert sha(SOURCE/f)==h,f
 assert sha(OUT/'source_snapshot.tar.gz')==json.loads((OUT/'inputs.json').read_text())['snapshot_sha256']
 config=dict(schema='mhbs.pu_cycle_synth.v1',created_at=now(),scope='128f Sign common-core synthesis',
  tested='fixed single lane,P1-P4,U1-U2',device=PART,clock_period_ns=6.666667,
  profile_enable_synthesis=0,max_parallel_points=4,vivado_threads_per_point=6,
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

def bind_snapshot():
 base=SOURCE/'manifests/experiments/unified_hbs_v4.2/external_job_message'
 flow.ROOT=SOURCE;flow.BASE=base;support.ROOT=SOURCE;support.BASE=base
 if not hasattr(bind_snapshot,'patched'):
  original_run=flow.run
  def frozen_run(cmd,log,cwd=SOURCE):
   cmd=list(cmd)
   if cmd and cmd[0]=='verilator' and '-j' in cmd:
    cmd[cmd.index('-j')+1]='6'
   return original_run(cmd,log,cwd)
  flow.run=frozen_run
  bind_snapshot.patched=True
 return base

def synth(name,p,u):
 d=OUT/name;d.mkdir(exist_ok=True)
 common,_=partition((SOURCE/'rtl/top/mhbs_top.sv').read_text(),stub=True)
 (d/'mhbs_common.sv').write_text(common)
 (d/'clock.xdc').write_text('create_clock -name clk -period 6.666667 [get_ports clk]\n')
 sources=(SOURCE/'manifests/v42_sources.txt').read_text().split()
 lines=['set_param general.maxThreads 6',f'create_project -in_memory -part {PART}']
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
 with (d/'vivado.log').open('w') as log:
  code=subprocess.run(['vivado','-mode','batch','-nolog','-nojournal','-source',str(d/'synth.tcl')],cwd=BUILD/name,stdout=log,stderr=subprocess.STDOUT).returncode
 if code or f'PU_SYNTH_PASS {name}' not in (d/'vivado.log').read_text():raise RuntimeError(f'Vivado exit={code}; see vivado.log')
 a=support.area(d/'core_utilization.rpt')
 files=('mhbs_common.sv','clock.xdc','synth.tcl','vivado.log','core_utilization.rpt','core_hierarchical.rpt','core_timing.rpt')
 write(d/'synthesis.json',dict(area=a,elapsed_seconds=time.monotonic()-start,evidence_sha256={f:sha(d/f) for f in files},post_synth_dcp_sha256=sha(BUILD/name/'post_synth.dcp')))
 return a

def point(p,u):
 name=f'P{p}U{u}';d=OUT/name;d.mkdir(exist_ok=True)
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
  row=dict(point=name,p=p,u=u,assumed_mhz=150,time_ms=r['sign_cycles']/150000,atp_slice_ms=a['equivalent_slice']*r['sign_cycles']/150000,simulation='pass',synthesis='pass',sign_cycles=r['sign_cycles'],total_cycles=r['total_cycles'],hashes=r['hashes'],permutations=r['permutations'],output_sha256=r['output_sha256'],**a,snapshot_sha256=sha(OUT/'source_snapshot.tar.gz'))
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
   failure=d/'failure.json';rows.append(dict(point=name,p=p,u=u,simulation='-',synthesis='-',error=json.loads(failure.read_text())['error'] if failure.exists() else 'incomplete'))
 outputs={r['output_sha256'] for r in rows if r.get('simulation')=='pass'}
 for r in rows:
  if r.get('simulation')=='pass':r['reference_agreement']='pass' if len(outputs)==1 else 'fail'
 write(OUT/'results.json',dict(scope='128f Sign common-core synthesis',rows=rows,output_agreement=len(outputs)==1,actual_frequency='not measured; synthesis only',unsupported=json.loads((OUT/'status.json').read_text())['unsupported']))
 keys=('point','p','u','simulation','synthesis','reference_agreement','sign_cycles','total_cycles','hashes','permutations','lut','ff','lutram','bram36','dsp','equivalent_slice','assumed_mhz','time_ms','atp_slice_ms','error')
 with (OUT/'results.csv').open('w') as f:
  w=csv.DictWriter(f,fieldnames=keys,extrasaction='ignore');w.writeheader();w.writerows(rows)
 lines=['# P/U 128f Sign cycle and synthesis matrix','','Device: xc7a200tffg1156-3; Vivado 2025.2; 6.666667 ns synthesis constraint; PROFILE_ENABLE=0.','Synthesis does not measure frequency. LUT includes LUTRAM. Common core excludes external ROM and signature cache.','One physical hash lane; only P and U are configurable.','','| Point | Cycles | LUT | FF | LUTRAM | BRAM36 | DSP | Eq. Slice | Status |','|---|---:|---:|---:|---:|---:|---:|---:|---|']
 for r in rows:
  show=lambda key:str(r[key]) if key in r else '-'
  lines.append(f'| {r["point"]} | {show("sign_cycles")} | {show("lut")} | {show("ff")} | {show("lutram")} | {show("bram36")} | {show("dsp")} | {show("equivalent_slice")} | {r["simulation"]}/{r["synthesis"]} |')
 (OUT/'report.md').write_text('\n'.join(lines)+'\n')
 write(OUT/'evidence_sha256.json',{str(f.relative_to(OUT)):sha(f) for f in OUT.rglob('*') if f.is_file() and f.name!='evidence_sha256.json' and f.suffix!='.dcp'})
 complete=all(r.get('simulation')=='pass' and r.get('synthesis')=='pass' for r in rows) and len(outputs)==1
 update(state='complete' if complete else 'complete_with_failures',ended_at=now())
 (OUT/'DONE').write_text(json.loads((OUT/'status.json').read_text())['state']+'\n')

def main():
 global TAG,OUT,BUILD,SOURCE
 import argparse
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('action',choices=('prepare','run'));ap.add_argument('--tag',default=TAG);a=ap.parse_args()
 if not re.fullmatch(r'[A-Za-z0-9_-]+',a.tag):ap.error('invalid experiment tag')
 TAG=a.tag;OUT=ROOT/'manifests/experiments'/TAG;BUILD=ROOT/'build'/TAG;SOURCE=BUILD/'source'
 if a.action=='prepare':prepare();print(OUT/'status.json');return
 prepare();bind_snapshot();update(state='running',pid=os.getpid())
 for first in range(0,len(POINTS),4):
  update(batch=f'{first//4+1}/{(len(POINTS)+3)//4}',batch_points=[f'P{p}U{u}' for p,u in POINTS[first:first+4]])
  with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
   for f in concurrent.futures.as_completed([pool.submit(point,p,u) for p,u in POINTS[first:first+4]]):f.result()
 finish()
if __name__=='__main__':main()
