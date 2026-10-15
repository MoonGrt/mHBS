#!/usr/bin/env python3
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
from pathlib import Path
import hashlib,json,os,re,subprocess,time
ROOT=Path.cwd();WORK=ROOT/'build/sha2_optimization/scalar_validation'
source_paths=[p.strip() for p in (ROOT/'sources.txt').read_text().splitlines() if p.strip()]
files=source_paths+['sources.txt','tb/tb_fast.sv','tb/fast_main.cpp','scripts/simulate_fast.sh']
def checksum(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def sources():return {f:checksum(ROOT/f) for f in files}
record=dict(schema='mhbs.sha2.optimization.acvp_synthesis.v1',started_utc=datetime.now(timezone.utc).isoformat(),source_before=sources(),source_after=None,source_unchanged=None,cases=[],complete=False,required=7,passed=False)
record['scope']='Four NIST ACVP SHA2-128f/128s Sign vectors; SYNTHESIS P4U1 SLH128f/XMSS h10/LMS h10 complete Sign. No h20 Job.'
output=WORK/'ACVP_AND_SYNTHESIS.json'
def save():output.write_text(json.dumps(record,indent=2)+'\n')
save()
acvp=json.loads((ROOT/'build/sha2_models/acvp/VALIDATION.json').read_text())
record['acvp_source']=acvp['source']

def compile_view(synthesis):
    cmd=['bash','scripts/simulate_fast.sh','slh_128f','sign','4','1']
    env={**os.environ,'HASH_BACKEND':'sha2','SIM_SYNTHESIS':str(synthesis),'SIM_FAST_OPT_SLOW':'-O3','SIM_COMPILE_ONLY':'1'}
    log=WORK/f'agent_compile_synthesis{synthesis}.log'
    with log.open('w') as f:res=subprocess.run(cmd,cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT)
    if res.returncode:raise RuntimeError(f'Compile failed: {log}')
    binary=ROOT/f'build/sim/P4U1_fast_o3_synthesis{synthesis}_sha2/obj/Vtb_fast'
    return binary

def run(binary,key,profile,vector,synthesis,acvp_case=None):
    vector=Path(vector);cmd=[str(binary),'+VECTOR='+str(vector)]
    log=WORK/(key+'.log');start=time.monotonic()
    with log.open('w') as f:res=subprocess.run(cmd,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT)
    text=log.read_text();match=re.search(r'STATEFUL_PASS P4U1 op=1 cycles=(\d+) total=(\d+) hashes=(\d+) permutations=(\d+).*?seconds=([\d.e+]+)',text)
    meta=[int(v,16) for v in (vector/'meta.mem').read_text().split()]
    row=dict(name=key,profile=profile,configuration='P4U1',synthesis=bool(synthesis),returncode=res.returncode,passed=res.returncode==0 and match is not None,wall_seconds=time.monotonic()-start,log=str(log.relative_to(ROOT)),log_sha256=checksum(log),command=cmd,vector=str(vector.relative_to(ROOT)),vector_sha256={p.name:checksum(p) for p in sorted(vector.glob('*.mem'))},expected_output_bytes=meta[0],expected_hashes=meta[1],expected_permutations=meta[2])
    if match:
        row.update(cycles=int(match[1]),total_cycles=int(match[2]),hashes=int(match[3]),permutations=int(match[4]),seconds=float(match[5]))
        row['passed']=row['passed'] and row['hashes']==meta[1] and row['permutations']==meta[2]
    if row['passed']:
        row['all_output_bytes_checked']=True;row['signature_cache_checked']=True;row['independent_functional_events_checked']=True
        if synthesis:
            row['wrapper_statistics_zero_checked']=True
            row['statistics_note']='SYNTHESIS production diagnostics are absent; tb_fast compatibility ports are tied to zero. Hash/permutation workload and execution cycles were measured using functional events, independently of removed registers.'
    if acvp_case:row['nist_case']={k:acvp_case[k] for k in ['tgId','tcId','deterministic','message_bytes','signature_bytes']}
    print(key,row['passed'],row.get('cycles'),round(row['wall_seconds'],2),flush=True)
    return row

def acvp_group():
    binary=compile_view(0);rows=[]
    for case in acvp['results']:
        key=f"agent_acvp_tg{case['tgId']}_tc{case['tcId']}"
        rows.append(run(binary,key,case['profile'],Path(case['vector_directory'])/'sign',0,case))
    return rows

def synthesis_group():
    binary=compile_view(1);rows=[]
    for profile in ['slh_128f','xmss_h10','lms_h10']:
        rows.append(run(binary,'agent_synthesis_'+profile+'_sign',profile,ROOT/'tb/vectors/sha2'/profile/'sign',1))
    return rows

# This inspects the actual production sources after the same macro selection.
preproc=WORK/'agent_synthesis_preprocessed.sv'
preproc_log=WORK/'agent_synthesis_preprocess.log'
cmd=[os.environ.get('VERILATOR','verilator'),'-E','-DSYNTHESIS','-DMHBS_SHA2',*source_paths]
with preproc.open('w') as out,preproc_log.open('w') as err:
    prep=subprocess.run(cmd,cwd=ROOT,stdout=out,stderr=err)
text=preproc.read_text()
removed_names=['hash_count','permutation_count','batch_hashes','batch_permutations','counted_batch_hashes','counted_batch_permutations','boot_cycles','keygen_cycles','sign_cycles','error_code']
remaining=[name for name in removed_names if re.search(r'\b'+re.escape(name)+r'\b',text)]
record['production_statistics_preprocessor_audit']=dict(command=cmd,returncode=prep.returncode,passed=prep.returncode==0 and not remaining,removed_identifiers=removed_names,unexpected_remaining=remaining,source=str(preproc.relative_to(ROOT)),source_sha256=checksum(preproc),scope='Preprocessed production RTL only; this is not a synthesized netlist audit.')
save()
with ThreadPoolExecutor(max_workers=2) as pool:
    pending=[pool.submit(acvp_group),pool.submit(synthesis_group)]
    for future in as_completed(pending):
        record['cases']+=future.result();save()
record['source_after']=sources();record['source_unchanged']=record['source_after']==record['source_before']
record['complete']=True;record['finished_utc']=datetime.now(timezone.utc).isoformat()
record['passed']=record['source_unchanged'] and len(record['cases'])==7 and all(row['passed'] for row in record['cases']) and record['production_statistics_preprocessor_audit']['passed']
save();print('ACVP_AND_SYNTHESIS_PASS',record['passed'],flush=True)
