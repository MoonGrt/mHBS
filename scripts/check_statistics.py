#!/usr/bin/env python3
"""Exercise the production preprocessor branch with the normal integration oracle.

The core is built with SYNTHESIS defined, K1U1 fixed explicitly, profiling on,
and physical lane swap off. Only observation aliases may differ from the normal
simulation build. Complete output bytes, total cycle and instruction counters,
and every committed Hash trace must match the normal build.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'scripts')]
import run_hash_backends as flow

FORMAT = 'hbs_synthesis_mode_v1'
OPERATIONS = flow.OPERATIONS
COMPARE_FIELDS = ('operation','n','bytes','nodes','hashes','permutations','cycles','waits','swap','stats',
    'instructions','hash_wait_cycles','overlap_instructions','lane0_round_cycles','lane1_round_cycles',
    'lane_round_utilization','hash_trace_sha256','image_sha256','vector_sha256',
    'macro_count','macro_busy_cycles','macro_hashes')
FLAGS = ('-DSYNTHESIS','-GPROFILE_ENABLE=1','-GSWAP=0')
CONFIG = dict(LANES=1,UNROLL=1,PROFILE_ENABLE=True,SWAP_PHYSICAL_LANES=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,default=ROOT/'build/hashflow/image_chain')
    parser.add_argument('--out',type=Path)
    parser.add_argument('--profile',choices=('slh_128f','all'),default='slh_128f')
    parser.add_argument('--verilator',default='verilator')
    parser.add_argument('--jobs',type=int,default=4)
    args=parser.parse_args()
    if args.jobs<1: parser.error('--jobs must be positive')
    run=args.run.resolve(); out=(args.out or run/'synthesis_mode').resolve()
    identity=flow.source_identity()
    model_gate=flow.require_models(run,identity)
    normal=json.loads((run/'rtl.json').read_text())
    if normal.get('passed') is not True or normal.get('source_sha256')!=identity:
        raise ValueError('standard RTL evidence is incomplete or stale')
    profiles=flow.SLH_NAMES if args.profile=='all' else ('slh_128f',)
    if not set(profiles)<=set(model_gate['profiles']):
        raise ValueError('requested profile is missing from model evidence')
    inputs=flow.model_inputs(run)
    bindings=dict(identity)
    bindings['scripts/check_statistics.py']=flow.sha(Path(__file__).resolve())
    binary=flow.build_binary(out,stats=True,synthesis=True)
    command=['source-bound build_binary', '-DSYNTHESIS', '-GPROFILE_ENABLE=1', '-GSWAP=0']
    rows={}
    tasks=[(profile,operation) for profile in profiles for operation in OPERATIONS]
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
        pending={(profile,operation):pool.submit(flow.simulate,out,profile,operation,binary,
            image_folder=run/'images',vector_folder=run/'vectors') for profile,operation in tasks}
        for (profile,operation),future in pending.items():
            row=future.result(); key=profile+'/'+operation
            baseline=normal['cases'][key]
            if any(row[field]!=baseline[field] for field in COMPARE_FIELDS):
                raise ValueError('SYNTHESIS mode differs from normal integration build: '+key)
            rows[key]=row
    if flow.source_identity()!=identity or flow.model_inputs(run)!=inputs or flow.sha(Path(__file__).resolve())!=bindings['scripts/check_statistics.py']:
        raise ValueError('sources or oracle inputs changed during SYNTHESIS-mode verification')
    logs={str(path.relative_to(out)):flow.sha(path) for path in sorted((out/'logs').glob('*.log'))}
    compile_log=binary.parents[1]/'compile.log'
    logs['compile.log']=flow.sha(compile_log)
    result=dict(format=FORMAT,passed=True,defines=['SYNTHESIS'],configuration=CONFIG,cases=rows,
        source_sha256=bindings,input_sha256=inputs,standard_rtl_sha256=flow.sha(run/'rtl.json'),
        models_sha256=flow.sha(run/'models.json'),binary_sha256=flow.sha(binary),logs=logs,
        compile_command=command,
        verilator_version=subprocess.check_output([args.verilator,'--version'],text=True).strip())
    flow.write(out/'results.json',result)
    print('MICRO_SYNTHESIS_MODE_PASS',len(rows),'cases; explicit K1U1 PROFILE_ENABLE=1; -DSYNTHESIS',out,flush=True)


if __name__=='__main__': main()
