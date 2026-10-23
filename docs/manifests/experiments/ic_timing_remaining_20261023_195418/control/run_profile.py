#!/usr/bin/env python3
"""Profile i/P1U1 Sign from an input freeze without modifying that package.

Example:
 python3 run_profile.py --source /absolute/frozen/package --output /absolute/results --design i

The package supplies rtl/i and tb/i/tb_fast.sv; its image/i ROMs override the
original KAT program when present. Algorithm inputs remain the same 33-byte KAT.
The driver includes complete output/cache/hash/block and partition assertions.
"""
from pathlib import Path
import argparse,concurrent.futures,hashlib,json,subprocess,re,shutil,time,os
HERE=Path(__file__).resolve().parent
ROOT=Path.cwd().resolve()
p=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument('--source',required=True,type=Path,help='Complete frozen package root')
p.add_argument('--output',required=True,type=Path,help='New output directory (source subdirectory must not exist)')
p.add_argument('--design',choices=['i'],default='i')
p.add_argument('--backend',choices=['both','shake','sha2'],default='both')
p.add_argument('--kat-source',type=Path,default=ROOT/'tmp/sloth_ict_cycle_comparison/profile/i',help='Original measured 33B KAT profile containing shake/vector and sha2/vector')
a=p.parse_args();INPUT=a.source.resolve();BASE=a.output.resolve();OLD=a.kat_source.resolve();SOURCE=BASE/'source';DESIGN=a.design
sha=lambda x:hashlib.sha256(x.read_bytes()).hexdigest()
def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def state_enum(path):
 text=path.read_text()
 m=re.search(r'typedef\s+enum\s+logic\s*\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*\{(.*?)\}\s*state_t\s*;',text,re.S)
 if not m:raise SystemExit('Cannot parse frozen state_t enum: '+str(path))
 width=int(m[1])-int(m[2])+1
 if width<1 or width>8:raise SystemExit('Profiler supports state widths 1..8: '+str(path))
 body=re.sub(r'/\*.*?\*/|//[^\n]*','',m[3],flags=re.S)
 states={};value=0
 for item in body.split(','):
  item=item.strip()
  if not item:continue
  pair=item.split('=',1);name=pair[0].strip()
  if not re.fullmatch(r'[A-Za-z_]\w*',name):raise SystemExit('Invalid enum item '+item)
  if len(pair)>1:
   literal=pair[1].strip().replace('_','')
   sv=re.fullmatch(r"(?:\d+)?'[sS]?([dDhHbBoO])([0-9a-fA-F]+)",literal)
   if sv:value=int(sv[2],{'d':10,'h':16,'b':2,'o':8}[sv[1].lower()])
   elif re.fullmatch(r'\d+',literal):value=int(literal)
   else:raise SystemExit('Unsupported explicit enum expression '+item)
  if value>=1<<width:raise SystemExit('Enum value exceeds declared width '+item)
  states[name]=value;value+=1
 return {'path':str(path),'sha256':sha(path),'width':width,'states':states,'parser':'frozen explicit state_t enumeration, declaration order plus literal overrides'}
BASE.mkdir(parents=True,exist_ok=True)
if SOURCE.exists():raise SystemExit('Refusing to overwrite existing output freeze: '+str(SOURCE))
if not (INPUT/'rtl/i/sources.txt').is_file():raise SystemExit('--source lacks rtl/i/sources.txt')
if not (INPUT/'tb/i/tb_fast.sv').is_file():raise SystemExit('--source lacks tb/i/tb_fast.sv')
shutil.copytree(INPUT/'rtl/i',SOURCE/'rtl/i');(SOURCE/'tb/i').mkdir(parents=True)
shutil.copy2(INPUT/'tb/i/tb_fast.sv',SOURCE/'tb/i/tb_fast.sv')
input_hashes={str(x.relative_to(INPUT)):sha(x) for x in (INPUT/'rtl/i').rglob('*') if x.is_file()}
input_hashes['tb/i/tb_fast.sv']=sha(INPUT/'tb/i/tb_fast.sv')
core_enum=state_enum(INPUT/'rtl/i/executor/executor.sv')
seq_enum=state_enum(INPUT/'rtl/i/executor/sequencer.sv')
for name in ['IDLE','FAILED','FETCH','TRANSFORM','EMIT','EMIT_NEXT','OUTPUT_CHUNK','CONTROL_OUTPUT','MESSAGE','LAUNCH','DRAIN','FINISH']:
 if name not in core_enum['states']:raise SystemExit('Frozen core lacks required state '+name)
for name in ['FETCH','LOAD','WAIT_CONTROL']:
 if name not in seq_enum['states']:raise SystemExit('Frozen sequencer lacks required state '+name)
enum_parameters='\n// Values derived from frozen state_t enums; see STATE_ENUMS.json.\n'
for prefix,info in [('CORE',core_enum),('SEQ',seq_enum)]:
 for name,value in info['states'].items():enum_parameters+=f" localparam logic [{info['width']-1}:0] PROFILE_{prefix}_{name}={info['width']}'d{value};\n"
write(BASE/'STATE_ENUMS.json',{'core':core_enum,'sequencer':seq_enum,'generated_localparams':enum_parameters})
tb=(SOURCE/'tb/i/tb_fast.sv').read_text()
if 'Hash recipe lacked explicit HASH authorization' not in tb:raise SystemExit('Frozen i wrapper must preserve per-HASH authorization assertion')
needle='output wire [7:0] trace_block_bytes,output wire [5:0] trace_result_bytes\n'
assert needle in tb,'Unexpected frozen wrapper port layout'
tb=tb.replace(needle,needle.rstrip()+''',
 output wire profile_hash,profile_round,profile_feedforward,profile_internal_transfer,profile_active,
 output wire [CORE_STATE_BITS_MINUS_ONE:0] profile_executor_state,
 output wire [4:0] profile_control_op,profile_fetch_op,
 output wire [SEQ_STATE_BITS_MINUS_ONE:0] profile_sequencer_state,
 output wire [1:0] profile_token_kind,profile_fetch_kind,
 output wire [7:0] profile_lane_state,profile_lane_phase,
 output wire [3:0] profile_macro_op,profile_recipe_shape,
 output wire profile_template_complete,profile_recipe_complete,
 output wire profile_seq_fetch,profile_seq_load,profile_seq_control_wait,
 output wire profile_is_transform,profile_is_output,profile_is_lifecycle
''')
tb=tb.replace('CORE_STATE_BITS_MINUS_ONE',str(core_enum['width']-1)).replace('SEQ_STATE_BITS_MINUS_ONE',str(seq_enum['width']-1))
# Preserve original assertions; normalize their FETCH-state event to the enum.
tb=tb.replace('dut.core.state==3','dut.core.state==PROFILE_CORE_FETCH')
profile='''
 // Match the actual production cycle counter, including FINISH and excluding FAILED.
 assign profile_active=dut.core.state!=PROFILE_CORE_IDLE && dut.core.state!=PROFILE_CORE_FAILED;
 assign profile_executor_state=dut.core.state;
 assign profile_sequencer_state=dut.core.sequencer.state;
 assign profile_seq_fetch=dut.core.sequencer.state==PROFILE_SEQ_FETCH;
 assign profile_seq_load=dut.core.sequencer.state==PROFILE_SEQ_LOAD;
 assign profile_seq_control_wait=dut.core.sequencer.state==PROFILE_SEQ_WAIT_CONTROL;
 assign profile_is_transform=dut.core.state==PROFILE_CORE_TRANSFORM;
 assign profile_is_output=dut.core.state==PROFILE_CORE_EMIT || dut.core.state==PROFILE_CORE_EMIT_NEXT ||
     dut.core.state==PROFILE_CORE_OUTPUT_CHUNK || dut.core.state==PROFILE_CORE_CONTROL_OUTPUT;
 assign profile_is_lifecycle=dut.core.state==PROFILE_CORE_MESSAGE || dut.core.state==PROFILE_CORE_LAUNCH ||
     dut.core.state==PROFILE_CORE_DRAIN || dut.core.state==PROFILE_CORE_FINISH;
 assign profile_control_op=dut.core.control[61:57];
 assign profile_token_kind=dut.core.sequencer.kind;
 assign profile_fetch_op=program_data[61:57];
 assign profile_fetch_kind=program_data[63:62];
 assign profile_macro_op=dut.core.macro_op;
 assign profile_recipe_shape=dut.core.task_recipe[59:56];
 assign profile_template_complete=dut.core.seq_complete;
 assign profile_recipe_complete=dut.core.lane.response_valid && dut.core.lane.response_ready;
`ifdef MHBS_SHA2
 assign profile_round=!dut.core.lane.compression.stalled && dut.core.lane.compression.stages[0].source_valid;
 assign profile_feedforward=!dut.core.lane.compression.stalled && dut.core.lane.compression.finished;
 assign profile_hash=profile_round || profile_feedforward;
 assign profile_internal_transfer=(dut.core.lane.compression.input_valid && dut.core.lane.compression.input_ready) ||
     (dut.core.lane.compression.output_valid && dut.core.lane.compression.output_ready);
 assign profile_lane_state={5'd0,dut.core.lane.formatter};
 assign profile_lane_phase={4'd0,dut.core.lane.phase[0]};
`else
 assign profile_round=dut.core.lane.scalar_execution.round_update;
 assign profile_feedforward=1'b0;
 assign profile_hash=profile_round;
 assign profile_internal_transfer=dut.core.lane.scalar_execution.take_fast || dut.core.lane.scalar_execution.take_stream ||
     dut.core.lane.scalar_execution.take_feedback || dut.core.lane.scalar_execution.finish_valid;
 assign profile_lane_state={5'd0,dut.core.lane.scalar_execution.state};
 assign profile_lane_phase={6'd0,dut.core.lane.scalar_execution.hash_state};
`endif
'''
assert ' signature cache(' in tb;tb=tb.replace(' signature cache(',enum_parameters+profile+' signature cache(')
(SOURCE/'tb_clock_profile.sv').write_text(tb)
shutil.copy2(HERE/'profile_driver.cpp',SOURCE/'clock_profile.cpp')
source_hashes={str(x.relative_to(SOURCE)):sha(x) for x in SOURCE.rglob('*') if x.is_file()}
sources=[x.strip() for x in (SOURCE/'rtl/i/sources.txt').read_text().splitlines() if x.strip() and not x.startswith('#')]
write(BASE/'SOURCE.json',{'input_source':str(INPUT),'kat_source':str(OLD),'input_sha256':input_hashes,'sha256':source_hashes,'wrapper_adaptation':'Diagnostic-only ports; same full signature/cache/Hash assertions; symbolic enum cycle/classification predicates; no RTL edits.','state_enum_manifest':'STATE_ENUMS.json','core_state_width':core_enum['width'],'sequencer_state_width':seq_enum['width'],'driver_sha256':sha(HERE/'profile_driver.cpp'),'runner_sha256':sha(Path(__file__))})
def run(backend):
 out=BASE/backend;out.mkdir(exist_ok=True);shutil.copytree(OLD/backend/'vector',out/'vector',dirs_exist_ok=True)
 rom_origins={}
 for name in ['program.mem','template.mem','descriptor.mem']:
  candidate=INPUT/'image/i'/backend/'slh_128f'/name
  if candidate.is_file():shutil.copy2(candidate,out/'vector'/name);rom_origins[name]=str(candidate)
  else:rom_origins[name]=str(OLD/backend/'vector'/name)
 expected=bytes(int(s,16) for s in (out/'vector/expected.mem').read_text().split());(out/'kat_signature.bin').write_bytes(expected)
 assert int((out/'vector/job.mem').read_text().split()[8],16)==33
 defines=['-DMHBS_SHA2'] if backend=='sha2' else []
 compile=[os.environ.get('VERILATOR','verilator'),'--cc','--exe','--build','-O3','-j','2','-Wno-fatal','--top-module','tb_fast','-GPIPELINE=1','-GUNROLL=1',*defines,'--Mdir',str(out/'obj'),'-MAKEFLAGS','OPT_FAST=-O3 OPT_SLOW=-O1','-CFLAGS','-O3 -march=native',*sources,'tb_clock_profile.sv',str(SOURCE/'clock_profile.cpp')]
 execute=[str(out/'obj/Vtb_fast'),'+VECTOR='+str(out/'vector'),'+OUTPUT_BIN='+str(out/'signature.bin'),'+CACHE_BIN='+str(out/'signature_cache.bin'),'+HISTOGRAM='+str(out/'histogram.json')]
 write(out/'command.json',{'backend':backend,'design':DESIGN,'configuration':'P1U1','message_bytes':33,'cwd':str(SOURCE),'compile':compile,'run':execute,'compile_threads':2,'OPT_SLOW':'-O1','rom_origins':rom_origins,'vector_sha256':{x.name:sha(x) for x in (out/'vector').iterdir() if x.is_file()}})
 start=time.time()
 with (out/'compile.log').open('w') as log:r=subprocess.run(compile,cwd=SOURCE,stdout=log,stderr=subprocess.STDOUT)
 if r.returncode:write(out/'result.json',{'status':'compile_failed','returncode':r.returncode});return False
 with (out/'run.log').open('w') as log:r=subprocess.run(execute,cwd=SOURCE,stdout=log,stderr=subprocess.STDOUT)
 if r.returncode:write(out/'result.json',{'status':'run_failed','returncode':r.returncode});return False
 log=(out/'run.log').read_text();breakdown=re.search(r'CLOCK_BREAKDOWN (.*)',log);passed=re.search(r'STATEFUL_PASS (.*)',log);assert breakdown and passed and 'ATTRIBUTION_PASS' in log,log
 metrics={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',breakdown[1])};pm={k:v for k,v in re.findall(r'(\w+)=([\w.]+)',passed[1])}
 original=json.loads((OLD/backend/'result.json').read_text());signature=(out/'signature.bin').read_bytes();cache=(out/'signature_cache.bin').read_bytes()
 assert signature==cache==expected
 assert all(sha(SOURCE/f)==h for f,h in source_hashes.items())
 assert all(sha(INPUT/f)==h for f,h in input_hashes.items()),'Input freeze changed during measurement'
 histogram=json.loads((out/'histogram.json').read_text());assert sum(histogram['categories'].values())==metrics['remaining'];assert sum(x['cycles'] for x in histogram['joint_histogram'])==metrics['remaining']
 result={'backend':backend,'design':DESIGN,'configuration':'P1U1','message_bytes':33,'status':'passed',**metrics,'hash_count':int(pm['hashes']),'physical_blocks':int(pm['permutations']),'logical_blocks':int(pm['logical_permutations']),'signature_sha256':hashlib.sha256(signature).hexdigest(),'signature_cache_sha256':hashlib.sha256(cache).hexdigest(),'kat_signature_match':True,'signature_cache_and_kat_match':True,'signature_bytes':len(signature),'original_baseline_clock_partitions_match':all(metrics[k]==original[k] for k in ['total','hash','remaining','rounds','feedforward']),'original_baseline_hash_blocks_match':int(pm['hashes'])==original['hash_count'] and int(pm['permutations'])==original['physical_blocks'],'source_unchanged':True,'attribution':histogram,'seconds':time.time()-start,'definitions':{'hash':'Keccak round_update or SHA256 round/feed-forward; attribution priority.','transfer':'0; no non-overlapping MMIO occupancy.','profile_active':'Symbolic core.IDLE/core.FAILED exclusion matching core.cycles; FINISH included.','hash_template_nonhash':'Accepted explicit HASH command through sampled command_done inclusive, excluding Hash.','recipe_nonhash':'Accepted scalar request through consumed response inclusive, excluding Hash; subset of template clocks.','control_fetch':'Sequencer FETCH opcode from current program_data, not stale token.','control_issue':'Sequencer LOAD current control token.','control_wait':'WAIT_CONTROL, including actual RAM/I/O completion.','joint_histogram':'Remaining clocks only, sampled before positive clock edge. State IDs diagnostic; categories use enum-based semantic predicates.'}}
 write(out/'result.json',result);print(backend,'PASS',metrics,'categories',histogram['categories'],flush=True);return True
backends=['shake','sha2'] if a.backend=='both' else [a.backend]
with concurrent.futures.ThreadPoolExecutor(max_workers=len(backends)) as pool:results=list(pool.map(run,backends))
write(BASE/'RUN_STATUS.json',{'complete':True,'passed':all(results),'results':dict(zip(backends,results))})
raise SystemExit(not all(results))
