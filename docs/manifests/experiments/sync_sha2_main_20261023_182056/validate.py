#!/usr/bin/env python3
"""Frozen SHA2 synchronization validation; no synthesis or routing."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import datetime, hashlib, json, os, re, subprocess, time

RUN=Path(__file__).resolve().parent
SOURCE=RUN/'source'
ARCHIVE=RUN.parents[2]/'docs/manifests/experiments/sync_sha2_main_20261023_182056'
JOBS=[]
def add(name,design,commands,**extra):
    JOBS.append(dict(name=name,design=design,commands=commands,**extra))
add('primitive_c','c',[['python3','-B','scripts/check_sha256.py','--pipeline','1','--unroll','1']])
for p,synth in [(1,False),(4,False),(1,True)]:
    add(f'prefix_c_P{p}'+('_synthesis' if synth else ''),'c',
        [['python3','-B','scripts/check_sha2_prefix_cache.py','--pipeline',str(p),'--unroll','1']+(['--synthesis'] if synth else [])])
for design in ('i','c','t'):
    add(f'recipes_{design}',design,[['python3','-B','scripts/check_recipes.py','--hash','sha2','--pipeline','1','--unroll','1']])
    cases=[(p,o) for p in ('slh_128f','xmss_h10','lms_h10') for o in ('keygen','sign','verify')]
    cases += [(p,'verify') for p in ('slh_128s','xmss_h20','lms_h20')]
    add(f'core_{design}',design,[['bash','scripts/simulate_fast.sh',p,o,'1','1'] for p,o in cases],cases=cases)
    add(f'shake_{design}',design,[['bash','scripts/simulate_fast.sh','slh_128f','sign','1','1']],backend='shake')
add('core_c_synthesis','c',[['bash','scripts/simulate_fast.sh','slh_128f','sign','1','1']],synthesis=True)
add('top_c_synthesis_signature','c',[['python3','-B','scripts/check_top_signature.py','--hash','sha2','--synthesis','1','--signature','1']])
state={j['name']:dict(status='pending',design=j['design']) for j in JOBS}

def run(job):
    name=job['name'];logpath=RUN/'logs'/f'{name}.log';logpath.parent.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ,MHBS_DESIGN=job['design'],HASH_BACKEND=job.get('backend','sha2'),
             SIM_FAST_OPT_SLOW='-O1',PYTHONDONTWRITEBYTECODE='1',SIM_HASH_TRACE='1')
    if job.get('synthesis'):env['SIM_SYNTHESIS']='1'
    else:env['SIM_SYNTHESIS']='0'
    started=time.time();state[name]=dict(status='running',design=job['design'],started_epoch=started,log=str(logpath))
    completed=[];rc=0
    with logpath.open('w') as log:
        for cmd in job['commands']:
            log.write('COMMAND '+json.dumps(cmd)+'\n');log.flush()
            p=subprocess.run(cmd,cwd=SOURCE,env=env,stdout=log,stderr=subprocess.STDOUT)
            completed.append(dict(command=cmd,returncode=p.returncode))
            if p.returncode:rc=p.returncode;break
    text=logpath.read_text(errors='replace')
    markers=[s for s in text.splitlines() if re.search(r'PASS|validation \d+/\d+|MACRO_METRICS|HASH_TRACE_METRICS',s)]
    state[name]=dict(status='passed' if not rc else 'failed',design=job['design'],elapsed_s=time.time()-started,
                     returncode=rc,log=str(logpath),commands=completed,markers=markers)
    return state[name]

def report(final=False):
    data=dict(upstream_commit='a4a09e6f6ef901585e63aa8f37175b4931fad1cf',updated_at=datetime.datetime.now().astimezone().isoformat(),
              complete=final,jobs=state,synthesis_started=False,routing_started=False,scope='i/c/t shared SHA2 backend migration')
    for p in (RUN/'STATE.json',ARCHIVE/'reports/SHA2_Main_Sync_20261023.json'):
        p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');tmp.replace(p)
    lines=['# SHA2 main修正同步到i／c／t','',f"更新时间：{data['updated_at']}；全部任务结束：{final}",'',
           '同步main a4a09e6f的SHA2配方与SHA256通道，保留i/c/t控制粒度。未启动综合或布局布线。','',
           '| 验证组 | 设计 | 状态 | 耗时/s |','|---|---|---|---:|']
    for name,row in list(state.items()):lines.append(f"| {name} | {row['design']} | {row['status']} | {row.get('elapsed_s',0):.1f} |")
    (ARCHIVE/'reports/SHA2_Main_Sync_20261023.md').write_text('\n'.join(lines)+'\n')

with ThreadPoolExecutor(max_workers=3) as pool:
    futures=[pool.submit(run,j) for j in JOBS]
    report()
    while not all(f.done() for f in futures):
        time.sleep(60)
        report()
    for f in futures:f.result()
report(final=True)
if any(v['status']!='passed' for v in state.values()):raise SystemExit(1)
