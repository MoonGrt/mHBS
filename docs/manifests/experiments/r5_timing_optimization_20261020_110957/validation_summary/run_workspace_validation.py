#!/usr/bin/env python3
"""Isolated guard-pair and auth/stack single-write-port timing checks."""
from pathlib import Path
import argparse,hashlib,json,subprocess,time
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'sources.txt').is_file() and (p/'rtl').is_dir())
OUT=Path(__file__).resolve().parent
RUN=ROOT/'build/r5_timing_optimization/candidate_20261020_110957'
SOURCE=RUN/'source'
META=json.loads((RUN/'SOURCE.json').read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def mismatches():return [n for n,s in META['sha256'].items() if not (SOURCE/n).is_file() or sha(SOURCE/n)!=s]
parser=argparse.ArgumentParser();parser.add_argument('--pipeline',nargs='+',type=int,default=[4,12]);args=parser.parse_args()
assert not mismatches()
sources=(SOURCE/'sources.txt').read_text().splitlines()
rows=[]
for p in args.pipeline:
    start=time.time()
    command=['verilator','--binary','--timing','-O3','-j','2','-Wno-fatal','--top-module','tb_workspace_timing',f'-GPIPELINE={p}','--Mdir',str(OUT/f'workspace_P{p}_obj')]+sources+[str(OUT/'tb_workspace_timing.sv')]
    clog=OUT/f'workspace_P{p}_compile.log';rlog=OUT/f'workspace_P{p}_run.log'
    with clog.open('w') as f:
        c=subprocess.run(command,cwd=SOURCE,stdout=f,stderr=subprocess.STDOUT)
    assert c.returncode==0,clog
    with rlog.open('w') as f:
        r=subprocess.run([str(OUT/f'workspace_P{p}_obj/Vtb_workspace_timing')],cwd=SOURCE,stdout=f,stderr=subprocess.STDOUT)
    assert r.returncode==0,rlog
    markers=[x for x in rlog.read_text().splitlines() if 'WORKSPACE_TIMING_PASS' in x]
    assert markers
    rows.append(dict(p=p,u=1,passed=True,command=command,elapsed_seconds=time.time()-start,pass_markers=markers,compile_log=str(clog),compile_log_sha256=sha(clog),log=str(rlog),log_sha256=sha(rlog)))
    print(markers[0],flush=True)
old=OUT/'WORKSPACE_VALIDATION.json'
data=json.loads(old.read_text()) if old.exists() else dict(tests=[])
allrows={r['p']:r for r in data['tests']}
allrows.update({r['p']:r for r in rows})
data=dict(schema='mhbs.r5_timing.workspace_validation.v1',candidate_run=str(RUN),source_manifest=str(RUN/'SOURCE.json'),source_manifest_sha256=sha(RUN/'SOURCE.json'),rtl_sha256={k:v for k,v in META['sha256'].items() if k.startswith('rtl/')},source_unchanged=not mismatches(),passed=True,tests=list(allrows.values()),bench_sha256=sha(OUT/'tb_workspace_timing.sv'),reproduction_script_sha256=sha(Path(__file__)),scope='Direct legal register-state setup to exercise 126/127 and 127/126 protection, authentication write priority, next-cycle deferred stack write, and retained RAM data after reset. No full-tree generation or RTL modification.')
old.write_text(json.dumps(data,indent=2)+'\n')
