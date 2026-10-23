#!/usr/bin/env python3
"""Freeze adopted c RTL and run actual P1U1/33B SHAKE/SHA2 KAT profiling."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo
import argparse,hashlib,json,os,re,shutil,subprocess,tarfile,time
OUT=Path(__file__).resolve().parent
ROOT=next(p for p in OUT.parents if (p/'rtl/c/sources.txt').is_file())
SOURCE=OUT/'frozen_source'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def now():return datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds')
def write(p,v):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n');tmp.replace(p)
def freeze():
 if SOURCE.exists():
  assert (OUT/'SOURCE.json').is_file(),'Existing source lacks manifest'
  return
 manifest=(ROOT/'rtl/c/sources.txt').read_text();names=[n.strip() for n in manifest.splitlines() if n.strip() and not n.startswith('#')]
 names += [str(p.relative_to(ROOT)) for p in (ROOT/'rtl/c').rglob('*.svh')]
 names += ['rtl/c/sources.txt','tb/c/tb_fast.sv']
 for backend in ('shake','sha2'):
  names += [f'image/c/{backend}/slh_128f/{n}.mem' for n in ('program','template','descriptor')]
 production={n:sha(ROOT/n) for n in names}
 for n in names:
  target=SOURCE/n;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/n,target)
 (SOURCE/'sources.txt').write_text(manifest)
 core=(SOURCE/'rtl/c/executor/executor.sv').read_text();match=re.search(r'typedef\s+enum\s+logic\s*\[(\d+):0\]\s*\{(.*?)\}\s*state_t',core,re.S)
 assert match,'Cannot derive current c state enum'
 states={};value=0
 for entry in re.sub(r'//[^\n]*|/\*.*?\*/','',match[2],flags=re.S).split(','):
  entry=entry.strip()
  if not entry:continue
  assert '=' not in entry,'Explicit enum assignment requires parser update'
  states[entry]=value;value+=1
 assert all(n in states for n in ('IDLE','FAILED','FINISH'))
 tb=(SOURCE/'tb/c/tb_fast.sv').read_text();needle='output wire [7:0] trace_block_bytes,output wire [5:0] trace_result_bytes\n'
 assert tb.count(needle)==1
 tb=tb.replace(needle,needle.rstrip()+',\n output wire profile_hash,profile_round,profile_feedforward,profile_internal_transfer\n')
 active=re.compile(r' assign execution_active=[^;]+;')
 assert len(active.findall(tb))==1
 tb=active.sub(f' assign execution_active=dut.core.state!={states["IDLE"]} && dut.core.state!={states["FAILED"]};',tb)
 profile='''
// Diagnostic-only signals; FINISH is included in execution_active exactly as
// production core.cycles. Hash has priority; internal handoffs are not Transfer.
`ifdef MHBS_SHA2
 assign profile_round=!dut.core.lane.compression.stalled && dut.core.lane.compression.stages[0].source_valid;
 assign profile_feedforward=!dut.core.lane.compression.stalled && dut.core.lane.compression.finished;
 assign profile_hash=profile_round || profile_feedforward;
 assign profile_internal_transfer=(dut.core.lane.compression.input_valid && dut.core.lane.compression.input_ready) ||
   (dut.core.lane.compression.output_valid && dut.core.lane.compression.output_ready);
`else
 assign profile_round=dut.core.lane.scalar_execution.round_update;
 assign profile_feedforward=1'b0;
 assign profile_hash=profile_round;
 assign profile_internal_transfer=dut.core.lane.scalar_execution.take_fast || dut.core.lane.scalar_execution.take_stream ||
   dut.core.lane.scalar_execution.take_feedback || dut.core.lane.scalar_execution.finish_valid;
`endif
'''
 assert tb.count(' signature cache(')==1;tb=tb.replace(' signature cache(',profile+' signature cache(')
 (SOURCE/'tb_clock_profile.sv').write_text(tb)
 driver=ROOT/'tmp/sloth_ict_cycle_comparison/profile/c/frozen_source/clock_profile.cpp'
 shutil.copyfile(driver,SOURCE/'clock_profile.cpp')
 frozen={str(p.relative_to(SOURCE)):sha(p) for p in SOURCE.rglob('*') if p.is_file()}
 record={'design':'c','configuration':'P1U1','created_at':now(),'source_root':str(ROOT),'frozen_source':str(SOURCE),'production_sha256':production,'sha256':frozen,'state_enum':states,'execution_active_scope':'core state != IDLE && != FAILED; FINISH counted. C++ asserts observed active clocks == production cycles.','driver_origin':str(driver),'driver_origin_sha256':sha(driver),'wrapper_changes':'Only profiling ports/assignments and an enum-derived active predicate; original functional/cache/hash assertions retained.'}
 write(OUT/'SOURCE.json',record)
 with tarfile.open(OUT/'frozen_source.tar.gz','w:gz') as bundle:
  for n in frozen:bundle.add(SOURCE/n,arcname=n)
 write(OUT/'FROZEN_AUDIT.json',{'archive_sha256':sha(OUT/'frozen_source.tar.gz'),'production_equals_frozen':all(sha(SOURCE/n)==h for n,h in production.items()),'scope':'Current production c_control_pipeline, not earlier c or temporary worktree.'})
 for backend in ('shake','sha2'):
  work=OUT/backend;vector=work/'vector';vector.mkdir(parents=True,exist_ok=True)
  kat=ROOT/f'tmp/sloth_cycle_comparison/kat_inputs/{backend}/slh_128f/sign'
  origins={}
  for p in kat.iterdir():
   if p.is_file() and p.name not in ('program.mem','template.mem','descriptor.mem'):
    shutil.copyfile(p,vector/p.name);origins[p.name]=str(p)
  for n in ('program.mem','template.mem','descriptor.mem'):
   origin=SOURCE/f'image/c/{backend}/slh_128f'/n;shutil.copyfile(origin,vector/n);origins[n]=str(origin)
  cfg=[int(v,16) for v in (vector/'job.mem').read_text().split()];assert cfg[7]==1 and cfg[8]==33
  expected=bytes(int(v,16) for v in (vector/'expected.mem').read_text().split());(work/'kat_signature.bin').write_bytes(expected)
  write(work/'INPUT_SOURCE.json',{'message_bytes':33,'operation':'sign','profile':'slh_128f','signature_sha256':hashlib.sha256(expected).hexdigest(),'origins':origins,'sha256':{p.name:sha(p) for p in vector.iterdir() if p.is_file()}})
def run(backend):
 work=OUT/backend;obj=work/'obj';vector=work/'vector';start=time.monotonic();manifest=json.loads((OUT/'SOURCE.json').read_text());input_manifest=json.loads((work/'INPUT_SOURCE.json').read_text())
 assert all(sha(SOURCE/n)==h for n,h in manifest['sha256'].items())
 assert all(sha(vector/n)==h for n,h in input_manifest['sha256'].items())
 sources=[n.strip() for n in (SOURCE/'sources.txt').read_text().splitlines() if n.strip() and not n.startswith('#')]
 compile=[os.environ.get('VERILATOR','verilator'),'--cc','--exe','--build','-O3','-j','2','-Wno-fatal','--top-module','tb_fast','-GPIPELINE=1','-GUNROLL=1','--Mdir',str(obj),'-MAKEFLAGS','OPT_FAST=-O3 OPT_SLOW=-O1','-CFLAGS','-O3 -march=native']
 if backend=='sha2':compile.append('-DMHBS_SHA2')
 compile += [*sources,'tb_clock_profile.sv',str(SOURCE/'clock_profile.cpp')]
 execute=[str(obj/'Vtb_fast'),'+VECTOR='+str(vector),'+OUTPUT_BIN='+str(work/'signature.bin'),'+CACHE_BIN='+str(work/'signature_cache.bin')]
 write(work/'command.json',{'backend':backend,'design':'c','configuration':'P1U1','message_bytes':33,'cwd':str(SOURCE),'compile':compile,'run':execute,'threads':2,'OPT_SLOW':'-O1','script_sha256':sha(__file__),'started_at':now()})
 with (work/'compile.log').open('w') as stream:compiled=subprocess.run(compile,cwd=SOURCE,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT)
 assert compiled.returncode==0,backend+' compile failed'
 compile_end=time.monotonic()
 with (work/'run.log').open('w') as stream:executed=subprocess.run(execute,cwd=SOURCE,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT)
 assert executed.returncode==0,backend+' run failed'
 text=(work/'run.log').read_text();m=re.search(r'CLOCK_BREAKDOWN total=(\d+) hash=(\d+) transfer=(\d+) remaining=(\d+) rounds=(\d+) feedforward=(\d+) internal_handoff_overlap_diagnostic=(\d+)',text);p=re.search(r'STATEFUL_PASS P1U1 op=1 cycles=(\d+) total=(\d+) hashes=(\d+) permutations=(\d+).*logical_permutations=(\d+)',text)
 assert m and p,'Missing actual successful profile markers'
 total,hash_cycles,transfer,remaining,rounds,ff,overlap=map(int,m.groups());cycles,wrapper_total,hashes,blocks,logical_blocks=map(int,p.groups())
 expected=(work/'kat_signature.bin').read_bytes();actual=(work/'signature.bin').read_bytes();cache=(work/'signature_cache.bin').read_bytes()
 assert expected==actual==cache and total==cycles==hash_cycles+transfer+remaining and hash_cycles==rounds+ff and transfer==0
 assert all(sha(SOURCE/n)==h for n,h in manifest['sha256'].items())
 assert all(sha(ROOT/n)==h for n,h in manifest['production_sha256'].items())
 assert all(sha(vector/n)==h for n,h in input_manifest['sha256'].items())
 baseline=json.loads((ROOT/f'tmp/sloth_ict_cycle_comparison/profile/c/{backend}/result.json').read_text());assert hashes==baseline['hash_count'] and blocks==baseline['physical_blocks'] and logical_blocks==baseline['logical_blocks'] and hashlib.sha256(actual).hexdigest()==baseline['signature_sha256']
 result={'status':'passed','backend':backend,'design':'c','total':total,'hash':hash_cycles,'transfer':transfer,'remaining':remaining,'rounds':rounds,'feedforward':ff,'hash_count':hashes,'physical_blocks':blocks,'logical_blocks':logical_blocks,'signature_sha256':hashlib.sha256(actual).hexdigest(),'signature_cache_sha256':hashlib.sha256(cache).hexdigest(),'signature_cache_and_kat_match':True,'message_bytes':33,'configuration':'P1U1','signature_bytes':len(actual),'internal_handoff_overlap_diagnostic':overlap,'wrapper_total_cycles':wrapper_total,'source_unchanged':True,'input_unchanged':True,'compile_seconds':compile_end-start,'run_seconds':time.monotonic()-compile_end,'completed_at':now(),'scope':'Actual current production c_control_pipeline active cycles. Hash=primitive rounds plus SHA256 feed-forward; Transfer=non-overlapping MMIO occupancy, zero here; Remaining=complement including internal control/data movement. Internal handoffs are overlap diagnostics only.','source_manifest_sha256':sha(OUT/'SOURCE.json'),'input_manifest_sha256':sha(work/'INPUT_SOURCE.json')}
 write(work/'result.json',result);print(json.dumps(result),flush=True);return result
if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--backend',choices=('shake','sha2','both'),default='both');parser.add_argument('--freeze-only',action='store_true');args=parser.parse_args();freeze()
 if not args.freeze_only:
  try:
   backends=('shake','sha2') if args.backend=='both' else (args.backend,)
   with ThreadPoolExecutor(max_workers=len(backends)) as pool:results=list(pool.map(run,backends))
   write(OUT/'RESULTS.json',results);write(OUT/'RUN.json',{'complete':True,'passed':True,'results':{r['backend']:str(OUT/r['backend']/'result.json') for r in results}})
  except Exception as error:write(OUT/'RUN.json',{'complete':True,'passed':False,'error':repr(error)});raise
