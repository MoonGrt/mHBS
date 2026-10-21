from pathlib import Path
import subprocess,sys,json,time,hashlib,os,traceback
run=Path(__file__).resolve().parent;root=run.parents[2]
sys.path[:0]=[str(root),str(root/'scripts')]
import run_hash_backends as flow
handoff=json.loads((run/'PARALLEL_HANDOFF.json').read_text())
early=run/'early_default';receipt=json.loads((early/'rtl.json').read_text());identity=flow.source_identity()
assert identity==receipt['source_sha256']
flow.require_models(early,identity)
commands=[('synthesis',[sys.executable,'scripts/check_statistics.py','--run',str(early),'--out',str(run/'synthesis_mode'),'--profile','all','--jobs','6'])]
for profile in ('slh_128f','xmss_h10','lms_h10'):
    commands.append(('top_'+profile,[sys.executable,'scripts/check_top_signature.py','--profile',profile,
        '--image',str(run/'images'/profile),'--vector',str(run/'vectors'/profile/'sign'),
        '--out',str(run/'top_equivalence'/profile),'--jobs','2']))
children=[]
try:
    for index,(label,command) in enumerate(commands,1):
        log=(run/f'stage{index}.log').open('w')
        proc=subprocess.Popen(command,cwd=root,stdout=log,stderr=subprocess.STDOUT)
        children.append(dict(label=label,pid=proc.pid,proc=proc,log=log,command=command,stage=index))
    extended_done=False;expected=107 if root.name.endswith('chain-tree') else 97
    while True:
        results={c['label']:dict(pid=c['pid'],returncode=c['proc'].poll(),stage=c['stage']) for c in children}
        if any(row['returncode'] not in (None,0) for row in results.values()):
            raise RuntimeError('parallel validation failed: '+str(results))
        if (run/'rtl.json').exists():
            gate=json.loads((run/'rtl.json').read_text())
            assert gate.get('passed') is True and gate['source_sha256']==identity
            assert len(gate['cases'])==expected,(len(gate['cases']),expected)
            assert set(receipt['cases'])<=set(gate['cases'])
            assert all(row.get('passed') is True for row in gate['cases'].values())
            assert len([k for k in gate['cases'] if k.startswith('stateful_')])==18
            extended_done=True
        if not extended_done:
            stat=Path('/proc')/str(handoff['original_extended_pid'])/'stat'
            if not stat.exists() or stat.read_text().partition(')')[2].strip().split()[0]=='Z':
                raise RuntimeError('original extended process ended without its complete RTL gate')
        done=extended_done and all(row['returncode']==0 for row in results.values())
        flow.write(run/'DRIVER_STATUS.json',dict(status='passed' if done else 'running',stage='parallel_completed' if done else 'parallel_validation',
            early_normal_scope='28 default cases; parse-only replay of original completed normal logs; normal was not rerun',
            complete_rtl_gate_scope=f'{expected} cases, including all old extensions and 18 stateful extensions',
            extended_gate_passed=extended_done,parallel_tasks=results,supervisor_pid=os.getpid(),
            original_extended_pid=handoff['original_extended_pid'],updated=time.time()))
        if done:break
        time.sleep(5)
    flow.write(run/'PARALLEL_VALIDATION.json',dict(passed=True,scope='original complete RTL gate plus source-matched default28 SYNTHESIS and three top checks',
        source_sha256=identity,complete_rtl_sha256=flow.sha(run/'rtl.json'),early_default_rtl_sha256=flow.sha(early/'rtl.json'),
        synthesis_sha256=flow.sha(run/'synthesis_mode/results.json'),
        top_sha256={p:flow.sha(run/'top_equivalence'/p/'results.json') for p in ('slh_128f','xmss_h10','lms_h10')},
        normal_rerun=False,updated=time.time()))
except BaseException as error:
    flow.write(run/'DRIVER_STATUS.json',dict(status='failed',stage='parallel_validation',error=str(error),traceback=traceback.format_exc(),updated=time.time()))
    raise
finally:
    for child in children:child['log'].close()
