#!/usr/bin/env python3
"""Source-bound frozen U2 write-owner/memory scoreboard checks, no RTL edits."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import argparse,hashlib,json,re,shutil,subprocess,time
OUT=Path(__file__).resolve().parent
RUN=OUT.parent
ROOT=next(p for p in RUN.parents if (p/'sources.txt').is_file())
SOURCE=RUN/'source'
META=json.loads((RUN/'SOURCE.json').read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def mismatches():return [n for n,s in META['sha256'].items() if not (SOURCE/n).is_file() or sha(SOURCE/n)!=s]
parser=argparse.ArgumentParser();parser.add_argument('--pipeline',nargs='+',type=int,default=[1,4,12]);args=parser.parse_args()
assert not mismatches()
sources=(SOURCE/'sources.txt').read_text().splitlines()
def one(p):
    start=time.time();obj=OUT/f'P{p}_obj';clog=OUT/f'P{p}_compile.log';rlog=OUT/f'P{p}_run.log'
    command=['verilator','--binary','--timing','-O3','-j','2','-Wno-fatal','--top-module','tb_writeback_ownership',f'-GPIPELINE={p}','--Mdir',str(obj),*sources,str(OUT/'tb_writeback_ownership.sv')]
    with clog.open('w') as f:c=subprocess.run(command,cwd=SOURCE,stdout=f,stderr=subprocess.STDOUT)
    if c.returncode: return dict(p=p,passed=False,stage='compile',compile_log=str(clog),compile_log_sha256=sha(clog),elapsed_seconds=time.time()-start)
    with rlog.open('w') as f:r=subprocess.run([str(obj/'Vtb_writeback_ownership')],cwd=SOURCE,stdout=f,stderr=subprocess.STDOUT)
    markers=[x for x in rlog.read_text().splitlines() if 'WRITEBACK_OWNERSHIP_PASS' in x]
    row=dict(p=p,u=1,passed=r.returncode==0 and bool(markers),command=command,elapsed_seconds=time.time()-start,pass_markers=markers,compile_log=str(clog),compile_log_sha256=sha(clog),log=str(rlog),log_sha256=sha(rlog))
    if markers:row['coverage_counters']={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',markers[0])}
    print(json.dumps(row),flush=True);return row
with ThreadPoolExecutor(max_workers=2) as ex:rows=list(ex.map(one,args.pipeline))
data=dict(schema='mhbs.t2_atp.writeback_validation.v1',candidate_run=str(RUN),source_manifest=str(RUN/'SOURCE.json'),source_manifest_sha256=sha(RUN/'SOURCE.json'),rtl_sha256={k:v for k,v in META['sha256'].items() if k.startswith('rtl/')},source_unchanged=not mismatches(),passed=all(r['passed'] for r in rows),tests=rows,bench_sha256=sha(OUT/'tb_writeback_ownership.sv'),reproduction_script_sha256=sha(Path(__file__)),scope='Frozen U2 actual executor parallel write mux and original-priority debug oracle. Independent hand-planned write scoreboard covers every128 workspace address, authentication-priority/PUSH_STACK-next-edge collision, FORS leaf/parent, Ltree, direct/rolling, scalar P1, root, 67-node in-place waves and5 odd-tail copies,127/126 bank guard, reset while writing with no stale phase. Separate unchanged generic value DEPTH136 covers all136 addresses and135/134 tail parity. Does not replace cryptographic full Sign or throughput/STA validation; no Vivado, no h20 full tree, no production/frozen RTL modifications.')
data['bench_development_notes']=['Initial force of pipe_valid violated the recipe published-response ownership invariant; corrected bench to prepare a legal busy/complete/held-digest snapshot and kept all RTL assertions enabled.', 'Initial root-route force on an alias of a constant descriptor input was optimized inconsistently by Verilator; drive the actual variable descriptor input instead.', 'Generic136 initial schedule produced270 reads below the explicit coverage floor; added136 full-range read pairs rather than reducing the floor. No RTL or assertion changes.']
(OUT/'WORKSPACE_VALIDATION.json').write_text(json.dumps(data,indent=2)+'\n')
(OUT/'WORKSPACE_SUMMARY.md').write_text('# U2 写回互斥与工作区专项\n\n'+f"结果：{sum(r['passed'] for r in rows)}/{len(rows)} 组通过。冻结源码清单 SHA256：`{data['source_manifest_sha256']}`，源码未变：{data['source_unchanged']}。\n\n"+data['scope']+'\n\n当前executor容量128，因此只测试合法127/126；135/134由同一冻结value.sv的独立DEPTH136实例覆盖，未向executor注入越界访问。所有写入由测试计划独立指定使能、地址、数据，原优先级oracle和onehot0断言同时保持开启。\n')
archive=ROOT/'docs/manifests/experiments'/RUN.name.replace('candidate_','t2_atp_optimization_')/'workspace_validation_summary'
archive.mkdir(parents=True,exist_ok=True)
names=['WORKSPACE_VALIDATION.json','WORKSPACE_SUMMARY.md','tb_writeback_ownership.sv','run_workspace_validation.py']
for n in names:shutil.copy2(OUT/n,archive/n)
(archive/'SHA256.json').write_text(json.dumps({n:sha(archive/n) for n in names},indent=2)+'\n')
if not data['passed']:raise SystemExit(1)
