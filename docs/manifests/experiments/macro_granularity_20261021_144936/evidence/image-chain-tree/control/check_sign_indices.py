#!/usr/bin/env python3
"""Run complete h10 Sign at q=1 and the final leaf against native C fixtures."""
from concurrent.futures import ProcessPoolExecutor,ThreadPoolExecutor,as_completed
from pathlib import Path
import argparse,hashlib,json,os,re,subprocess,sys,threading,time


def generate(task):
    source,backend,name,q,output=task
    sys.path.insert(0,source)
    from model.vectors import generate_profile
    config=json.loads((Path(source)/'model/default_jobs.json').read_text())[name]
    config['q']=q
    return generate_profile(name,config,output,backend)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--archive',type=Path,required=True)
    args=parser.parse_args();source=args.source.resolve();run=args.run.resolve();archive=args.archive.resolve()
    run.mkdir(parents=True,exist_ok=True);archive.mkdir(parents=True,exist_ok=True);(run/'READY').mkdir(exist_ok=True)
    state=dict(complete=False,passed=0,required=8,source=str(source),full_high_tree_tested=False,
               configuration='K1U1',indices=[1,1023],results={})
    lock=threading.RLock()
    def publish():
        with lock:
            state['passed']=sum(r.get('passed',False) for r in state['results'].values())
            text=json.dumps(state,indent=2)+'\n'
            for path in (run/'VALIDATION.json',archive/'SIGN_INDEX_VALIDATION.json'):
                temp=path.with_name(path.name+'.tmp');temp.write_text(text);temp.replace(path)
    publish();sys.path.insert(0,str(source))
    from scripts.build_stateful_reference import build
    from model.hash_trace import expected_trace
    build()
    # Every case of a backend shares one immutable executable. Direct execution
    # avoids the shell wrapper's per-profile log name when q cases overlap.
    binaries={}
    for backend in ('shake','sha2'):
        env=dict(os.environ,HASH_BACKEND=backend,SIM_FAST_OPT_SLOW='-O1',SIM_COMPILE_ONLY='1')
        with (run/(backend+'_compile.log')).open('w') as stream:
            subprocess.run(['bash','scripts/simulate_fast.sh','xmss_h10','sign','1','1'],cwd=source,
                           env=env,stdout=stream,stderr=subprocess.STDOUT,check=True)
        suffix='_sha2' if backend=='sha2' else ''
        binaries[backend]=source/f'build/sim/P1U1_fast_o3_synthesis0_slow_O1{suffix}/obj/Vtb_fast'
    tasks=[(str(source),b,n,q,str(run/'vectors'/b/f'q{q}'))
           for b in ('shake','sha2') for n in ('xmss_h10','lms_h10') for q in (1,1023)]
    def simulate(task,fixture):
        _,backend,name,q,output=task;key=f'{backend}/{name}/q{q}';start=time.monotonic()
        with lock:state['results'][key]=dict(status='running');publish()
        try:
            vector=Path(output)/name/'sign';log=run/f'{backend}_{name}_q{q}.log'
            with log.open('w') as stream:
                status=subprocess.run([str(binaries[backend]),f'+VECTOR={vector}','+HASH_TRACE=1'],cwd=source,
                                      stdout=stream,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
            if status.returncode:raise RuntimeError(str(log))
            text=log.read_text();actual=json.loads(re.search(r'HASH_TRACE_METRICS (\{[^\n]+)',text)[1])
            expected=expected_trace(vector,name,'sign',backend)
            if actual!=expected:raise AssertionError('primitive task multiset mismatch')
            match=re.search(r'cycles=(\d+) total=(\d+) hashes=(\d+) permutations=(\d+)',text)
            result=dict(passed=True,status='passed',q=q,message_hex=fixture['message_hex'],fixture=fixture,
                primitive_trace=actual,cycles=int(match[1]),total_cycles=int(match[2]),hashes=int(match[3]),
                permutations=int(match[4]),log=str(log),log_sha256=hashlib.sha256(log.read_bytes()).hexdigest(),
                seconds=time.monotonic()-start)
        except Exception as error:result=dict(passed=False,status='failed',error=str(error))
        with lock:state['results'][key]=result;publish()
    with ProcessPoolExecutor(max_workers=2) as generators,ThreadPoolExecutor(max_workers=4) as simulations:
        pending={generators.submit(generate,t):t for t in tasks};running=[]
        for future in as_completed(pending):
            task=pending[future];_,backend,name,q,output=task
            try:
                fixture=future.result();vector=Path(output)/name/'sign'
                ready=dict(backend=backend,profile=name,q=q,vector=str(vector),fixture=fixture,
                           sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in vector.glob('*.mem')})
                path=run/'READY'/f'{backend}_{name}_q{q}.json';path.write_text(json.dumps(ready,indent=2)+'\n')
                print('SIGN_FIXTURE_READY',str(path),flush=True)
                running.append(simulations.submit(simulate,task,fixture))
            except Exception as error:
                with lock:state['results'][f'{backend}/{name}/q{q}']=dict(passed=False,status='failed',error=str(error));publish()
        for future in as_completed(running):future.result()
    state['complete']=True;state['acceptance_passed']=state['passed']==state['required'];publish()
    if not state['acceptance_passed']:raise SystemExit(1)


if __name__=='__main__':main()
