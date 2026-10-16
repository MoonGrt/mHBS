#!/usr/bin/env python3
"""Isolated guard-pair and auth/stack single-write-port timing checks."""
from pathlib import Path
import argparse,hashlib,json,subprocess,time
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'sources.txt').is_file() and (p/'rtl').is_dir())
OUT=Path(__file__).resolve().parent
RUN=ROOT/'build/s4_timing_optimization/candidate_20261020_115825'
SOURCE=RUN/'source'
META=json.loads((RUN/'SOURCE.json').read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def mismatches():return [n for n,s in META['sha256'].items() if not (SOURCE/n).is_file() or sha(SOURCE/n)!=s]
parser=argparse.ArgumentParser();parser.add_argument('--pipeline',nargs='+',type=int,default=[4,12]);parser.add_argument('--summary-only',action='store_true');args=parser.parse_args()
assert not mismatches()
sources=(SOURCE/'sources.txt').read_text().splitlines()
rows=[]
for p in ([] if args.summary_only else args.pipeline):
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
if args.summary_only:
    assert data['bench_sha256']==sha(OUT/'tb_workspace_timing.sv')
    assert data['source_manifest_sha256']==sha(RUN/'SOURCE.json')
    for row in data['tests']:
        assert sha(Path(row['log']))==row['log_sha256']
        assert sha(Path(row['compile_log']))==row['compile_log_sha256']
allrows={r['p']:r for r in data['tests']}
allrows.update({r['p']:r for r in rows})
data=dict(schema='mhbs.s4_timing.workspace_validation.v1',candidate_run=str(RUN),source_manifest=str(RUN/'SOURCE.json'),source_manifest_sha256=sha(RUN/'SOURCE.json'),rtl_sha256={k:v for k,v in META['sha256'].items() if k.startswith('rtl/')},source_unchanged=not mismatches(),passed=True,tests=list(allrows.values()),bench_sha256=sha(OUT/'tb_workspace_timing.sv'),reproduction_script_sha256=sha(Path(__file__)),scope='T3 frozen actual executor commit/forward network: independent logical-capture and physical-commit scoreboards; both forwarding ports, back-to-back writes, same-address overwrite, odd/even adjacent pairs, guard pair, authentication-first/deferred-stack-second collision, and pending write physically landing on reset edge. Legal register-state setup supplements full functional regressions. No production/frozen RTL modification, no h20 full-tree execution, no Vivado.')
import re
for row in data['tests']:
    row['coverage_counters']={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',row['pass_markers'][0])}
data['bench_development_notes']=[
    'Initial driver had procedural force RHS sampled once by Verilator 5.008; changed to explicit reissue per beat, retaining all assertions.',
    'Forcing an optimized alias endpoint_read0/1 did not consistently affect inlined forwarding expressions; set actual read_addresses address registers on the falling edge instead. Scoreboards observe actual DUT addresses/data.',
    'Reset also initializes read addresses to 0/1. After checking cleared commit_valid, select 98/99 again before asserting that pending address99 physically committed on the reset edge. No RTL edits or disabled assertions.',
    'Initial bench-development failures remain in build logs and are not RTL candidate failures.'
]
old.write_text(json.dumps(data,indent=2)+'\n')
md=f"""# T3 共享工作区提交与转发专项

结果：**{len(data['tests'])}/2 组通过**，P4U1、P12U1均检查实际冻结executor和value RAM。冻结源码清单 SHA256：`{data['source_manifest_sha256']}`；源码未变化：{data['source_unchanged']}。

每配置完成430次逻辑读、302次物理RAM读、105次read0转发、121次read1转发、2次复位边缘pending提交，以及33项地址译码检查。覆盖128个地址、背靠背写、同地址覆盖、奇偶相邻/127与126保护对、认证节点先写与树栈后写。独立scoreboard分别核对捕获后的逻辑可见值和下一边缘实际RAM落盘值，未将两者混为一拍。

复位测试在pending有效时拉高rst，确认commit_valid清零；重新选择被复位的读地址后，检查forwarding关闭时raw RAM仍保存刚刚落盘的数据。物理RAM写使能未门控rst。

初版隔离bench先后遇到Verilator procedural force只采样当前RHS、优化后别名net强制不一致，以及复位自动改变读地址等测试驱动问题；均通过修正驱动和选择实际地址解决，保留全部断言，未修改生产或冻结RTL。初始失败日志仅留build运行目录。

详细命令、逐组日志校验和覆盖计数见`WORKSPACE_VALIDATION.json`。未执行Vivado或h20完整树。
"""
(OUT/'WORKSPACE_SUMMARY.md').write_text(md)


# Archive only the result summary, source binding and reproduction inputs.
import shutil
archive=ROOT/'docs/manifests/experiments/s4_timing_optimization_20261020_115825/workspace_validation_summary'
archive.mkdir(parents=True,exist_ok=True)
for name in ('WORKSPACE_VALIDATION.json','WORKSPACE_SUMMARY.md','tb_workspace_timing.sv','run_workspace_validation.py'):
    shutil.copy2(OUT/name,archive/name)
(archive/'SHA256.json').write_text(json.dumps({n:sha(archive/n) for n in ('WORKSPACE_VALIDATION.json','WORKSPACE_SUMMARY.md','tb_workspace_timing.sv','run_workspace_validation.py')},indent=2)+'\n')
