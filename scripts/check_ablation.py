#!/usr/bin/env python3
"""Regenerate 60 ROM sets and replay 18 Verify cases from the shared root."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
BASELINES={'i':'image_optimization_20261021_182828','c':'macro_atp_acceptance_20261021_161437','t':'macro_atp_acceptance_20261021_164159'}
PROFILES=('slh_128f','xmss_h10','lms_h10')
STATIC_PROGRAM=r'''
import hashlib,json,os
from pathlib import Path
from model.mHBS import compile_image
profiles={'shake':('slh_128f','slh_192f','slh_256f','slh_128s','slh_192s','slh_256s','xmss_h10','xmss_h16','xmss_h20','lms_h10','lms_h15','lms_h20'),
          'sha2':('slh_128f','slh_128s','xmss_h10','xmss_h16','xmss_h20','lms_h10','lms_h15','lms_h20')}
records=[]
for backend,names in profiles.items():
 for name in names:
  image=compile_image(name,hash_backend=backend)
  image.decode(hash_backend=backend)
  folder=Path('image')/os.environ['MHBS_DESIGN']/backend/name
  hashes={}
  for field,words in zip(('program','template','descriptor'),(image.program,image.templates,image.descriptors)):
   actual=''.join(f'{word:016x}\n' for word in words).encode()
   fixture=folder/(field+'.mem')
   if actual!=fixture.read_bytes(): raise AssertionError((backend,name,field,'generated ROM differs'))
   hashes[field]=hashlib.sha256(actual).hexdigest()
  records.append(dict(backend=backend,profile=name,allocated=[len(image.program),len(image.templates),len(image.descriptors)],sha256=hashes))
print(json.dumps(dict(passed=True,images=records,full_tree_generation=False)))
'''


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--launch',action='store_true')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--run',type=Path,help=argparse.SUPPRESS)
    parser.add_argument('--jobs',type=int,default=3)
    parser.add_argument('--static-only',action='store_true')
    args=parser.parse_args()
    if not 1<=args.jobs<=3:parser.error('--jobs must be 1..3')
    output=(args.run or args.output or ROOT/'build/ablation_validation'/datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y%m%d_%H%M%S')).resolve()
    output.mkdir(parents=True,exist_ok=True)
    if args.launch:
        command=[sys.executable,str(Path(__file__).resolve()),'--output',str(output),'--jobs',str(args.jobs)]
        if args.static_only:command.append('--static-only')
        with (output/'runner.log').open('w') as log:
            process=subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        print(json.dumps(dict(pid=process.pid,output=str(output))));return 0
    state=dict(schema='mhbs.ablation.shared_layout.v1',complete=False,passed=False,images={},tests={},source_root=str(ROOT),full_tree_run=False,routing_run=False)
    def save():
        temporary=output/'VALIDATION_SUMMARY.tmp'
        temporary.write_text(json.dumps(state,indent=2)+'\n');temporary.replace(output/'VALIDATION_SUMMARY.json')
    save()
    for design in ('i','c','t'):
        result=subprocess.run([sys.executable,'-c',STATIC_PROGRAM],cwd=ROOT,env=dict(os.environ,MHBS_DESIGN=design),text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        (output/f'{design}_static.log').write_text(result.stdout)
        if result.returncode:raise RuntimeError(f'{design} static image generation failed: {result.stdout[-1500:]}')
        state['images'][design]=json.loads(result.stdout.splitlines()[-1]);save()
        print(f'{design}: 20 static image sets passed',flush=True)
    if not args.static_only:
        baselines={design:json.loads((ROOT/'docs/manifests/experiments'/name/'VALIDATION_SUMMARY.json').read_text()) for design,name in BASELINES.items()}
        def group(item):
            design,backend=item; records={}
            for profile in PROFILES:
                started=time.monotonic(); log=output/f'{design}_{backend}_{profile}_verify.log'
                command=['bash','scripts/ablation.sh',design,'simulate-fast',profile,'verify','1','1']
                env=dict(os.environ,HASH_BACKEND=backend,SIM_FAST_OPT_SLOW='-O1',SIM_HASH_TRACE='1')
                with log.open('w') as handle:result=subprocess.run(command,cwd=ROOT,env=env,stdout=handle,stderr=subprocess.STDOUT)
                text=log.read_text();key=f'{design}/{backend}/{profile}'
                try:
                    if result.returncode:raise AssertionError(f'compile/Verify failed; {log}')
                    match=re.search(r'STATEFUL_PASS P1U1 op=2 cycles=(\d+) total=(\d+) hashes=(\d+) permutations=(\d+)',text)
                    if not match:raise AssertionError('Missing byte-exact Verify PASS')
                    cycles,total,hashes,blocks=map(int,match.groups())
                    trace=json.loads(re.search(r'HASH_TRACE_METRICS (\{[^\n]+)',text)[1])
                    macro=json.loads(re.search(r'MACRO_METRICS (\{[^\n]+)',text)[1])
                    old=baselines[design]['tests'][f'{backend}/{profile}/verify']
                    if (cycles,total,hashes,blocks)!=(old['cycles'],old['total_cycles'],old['hashes'],old['permutations']):raise AssertionError('cycles or Hash work changed')
                    if trace!=old['primitive_trace'] or macro!=old['macro_metrics']:raise AssertionError('primitive fingerprint or dynamic metrics changed')
                    record=dict(status='passed',cycles=cycles,total_cycles=total,hashes=hashes,permutations=blocks,primitive_trace=trace,macro_metrics=macro,exact_baseline_match=True)
                except Exception as error:record=dict(status='failed',error=str(error))
                record.update(log=str(log),log_sha256=sha(log),seconds=time.monotonic()-started)
                records[key]=record
                print(key,record['status'],flush=True)
            return records
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            for records in pool.map(group,[(design,backend) for design in ('i','c','t') for backend in ('shake','sha2')]):
                state['tests'].update(records);save()
    state['complete']=True
    state['passed']=sum(len(record['images']) for record in state['images'].values())==60 and (args.static_only or len(state['tests'])==18 and all(row['status']=='passed' for row in state['tests'].values()))
    save();print(json.dumps(dict(passed=state['passed'],output=str(output))),flush=True)
    return 0 if state['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
