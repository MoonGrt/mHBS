#!/usr/bin/env python3
"""Validate h10 empty-message Sign through frozen production RTL and C oracles."""
from concurrent.futures import ProcessPoolExecutor,as_completed
from pathlib import Path
import argparse,hashlib,json,os,re,subprocess,sys,time


def generate(task):
    source,backend,name,output=task
    sys.path.insert(0,source)
    from model.vectors import generate_profile
    config=json.loads((Path(source)/'model/default_jobs.json').read_text())[name]
    config['message']=''
    return generate_profile(name,config,output,backend)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--archive',type=Path,required=True)
    args=parser.parse_args();source=args.source.resolve();run=args.run.resolve();archive=args.archive.resolve()
    run.mkdir(parents=True,exist_ok=True);archive.mkdir(parents=True,exist_ok=True)
    state=dict(complete=False,passed=0,required=4,source=str(source),full_high_tree_tested=False,results={})
    def publish():
        text=json.dumps(state,indent=2)+'\n'
        (run/'VALIDATION.json').write_text(text);(archive/'EMPTY_MESSAGE_VALIDATION.json').write_text(text)
    publish();sys.path.insert(0,str(source))
    from scripts.build_stateful_reference import build
    from model.hash_trace import expected_trace
    build()  # Single builder; each worker below owns its native counters.
    tasks=[(str(source),b,n,str(run/'vectors'/b)) for b in ('shake','sha2') for n in ('xmss_h10','lms_h10')]
    with ProcessPoolExecutor(max_workers=2) as pool:
        futures={pool.submit(generate,t):t for t in tasks}
        for future in as_completed(futures):
            task=futures[future];_,backend,name,output=task;key=backend+'/'+name;start=time.monotonic()
            try:
                fixture=future.result();log=run/(backend+'_'+name+'.log')
                env=dict(os.environ,HASH_BACKEND=backend,VECTORS_DIR=output,SIM_FAST_OPT_SLOW='-O1',SIM_HASH_TRACE='1')
                with log.open('w') as stream:
                    status=subprocess.run(['bash','scripts/simulate_fast.sh',name,'sign','1','1'],cwd=source,env=env,
                        stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT)
                if status.returncode:raise RuntimeError(str(log))
                text=log.read_text();actual=json.loads(re.search(r'HASH_TRACE_METRICS (\{[^\n]+)',text)[1])
                if actual!=expected_trace(Path(output)/name/'sign',name,'sign',backend):
                    raise AssertionError('primitive trace mismatch')
                state['results'][key]=dict(passed=True,fixture=fixture,primitive_trace=actual,log=str(log),
                    log_sha256=hashlib.sha256(log.read_bytes()).hexdigest(),seconds=time.monotonic()-start)
            except Exception as error:state['results'][key]=dict(passed=False,error=str(error))
            state['passed']=sum(r['passed'] for r in state['results'].values());publish()
    state['complete']=True;state['acceptance_passed']=state['passed']==state['required'];publish()
    pins=source/'build/reference_native/manifest.json'
    if pins.exists():(archive/'NATIVE_REFERENCE.json').write_bytes(pins.read_bytes())
    if not state['acceptance_passed']:raise SystemExit(1)


if __name__=='__main__':main()
