#!/usr/bin/env python3
"""Validate the frozen SHAKE timing candidate without production edits."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent/'candidate_212542'
RUN = ROOT / 'build/shake_timing_optimization/candidate_20261019_212542'
SOURCE = RUN / 'source'
MANIFEST = RUN / 'SOURCE.json'
META = json.loads(MANIFEST.read_text())
EXPECTED = META['sha256']
LOCK = threading.Lock()
RESULTS = []
START = time.time()
TOTAL = 46
SCOPE = 'P4U1/P12U1 three-profile Verify stall/reset/replay/truncation/tamper and scalar/batch/FSM faults; P4/P12 SYNTHESIS recipes; P2U12/P4U2 recipe smoke. Full Sign run independently by candidate runner; no h20 Keygen/Sign.'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def mismatches():
    return [name for name, digest in EXPECTED.items()
            if not (SOURCE/name).is_file() or sha(SOURCE/name) != digest]

def publish(complete=False):
    with LOCK:
        failures = [x for x in RESULTS if not x['passed']]
        changed = mismatches()
        data = dict(schema='mhbs.shake_timing.functional_validation.v1',
                    candidate_run=str(RUN), source_root=str(SOURCE),
                    source_manifest=str(MANIFEST), source_manifest_sha256=sha(MANIFEST),
                    rtl_sha256={k:v for k,v in EXPECTED.items() if k.startswith('rtl/')},
                    recipe_sha256=EXPECTED['rtl/hash/shake-recipe.sv'],
                    hash_backend='shake', complete=complete,
                    status='failed' if failures or changed else 'passed' if complete else 'running',
                    passed=len(RESULTS)-len(failures), failed=len(failures),
                    total_planned=TOTAL, source_unchanged=not changed,
                    source_mismatches=changed, elapsed_seconds=time.time()-START,
                    scope=SCOPE,
                    tests=list(RESULTS))
        tmp = OUT/'VALIDATION.json.tmp'
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')
        tmp.replace(OUT/'VALIDATION.json')

def run_case(name, command, kind, **meta):
    started = time.time()
    log = OUT/'logs'/f'{name}.log'
    env = os.environ.copy()
    env.update(HASH_BACKEND='shake', SIM_SYNTHESIS='0', KECCAK_LUT6='0')
    env.pop('PROFILE_ENABLE', None)
    with log.open('w') as stream:
        try:
            process = subprocess.run(command, cwd=SOURCE, env=env,
                                     stdout=stream, stderr=subprocess.STDOUT,
                                     timeout=1800)
            code = process.returncode
            error = None
        except Exception as exc:
            code = -1
            error = repr(exc)
    result = dict(name=name, kind=kind, command=command, passed=code==0,
                  returncode=code, elapsed_seconds=time.time()-started,
                  log=str(log), log_sha256=sha(log), **meta)
    if error: result['error']=error
    if code==0:
        result['pass_markers']=[line for line in log.read_text(errors='replace').splitlines()
                                if any(marker in line for marker in
                                       ('STATEFUL_PASS', 'STATEFUL_FAULT_PASS', 'RECIPE_PASS', 'INDEX_REJECT_PASS'))]
    with LOCK:
        RESULTS.append(result)
    publish()
    print(f"{'PASS' if code==0 else 'FAIL'} {name} {result['elapsed_seconds']:.1f}s", flush=True)
    if code:
        print(log.read_text(errors='replace')[-8000:], flush=True)
    return code==0

def core_group(p):
    for profile in ('slh_128f', 'xmss_h10', 'lms_h10'):
        common = ['bash', 'scripts/simulate.sh', profile, 'verify', str(p), '1']
        run_case(f'verify_P{p}U1_{profile}_stall_replay_reset_cut',
                 common+['+STALL=1', '+REPLAYS=2', '+INTERRUPT=1', '+CUT=1'],
                 'verify', p=p, u=1, profile=profile, coverage=['stall','replays','inflight_reset','truncation_recovery'])
        for tamper in range(1,6):
            run_case(f'verify_P{p}U1_{profile}_tamper{tamper}',
                     common+['+STALL=1',f'+TAMPER={tamper}'],
                     'tamper', p=p,u=1, profile=profile, tamper=tamper)
    for fault in (1,2,3):
        run_case(f'fault_P{p}U1_xmss_h10_{fault}',
                 ['bash','scripts/simulate.sh','xmss_h10','verify',str(p),'1',f'+FAULT={fault}'],
                 'fault',p=p,u=1, profile='xmss_h10',fault=fault)

def recipe_group():
    for p,u,synthesis in ((4,1,True),(12,1,True),(2,12,False),(4,2,False)):
        run_case(f'recipes_P{p}U{u}_synthesis{int(synthesis)}',
                 ['python3','scripts/check_recipes.py','--hash','shake',
                  '--pipeline',str(p),'--unroll',str(u)]+(['--synthesis'] if synthesis else []),
                 'recipes',p=p,u=u,synthesis=synthesis)

if __name__=='__main__':
    (OUT/'logs').mkdir(parents=True,exist_ok=True)
    assert not mismatches(), 'Frozen candidate source mismatch before tests'
    publish()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures=[executor.submit(core_group,4), executor.submit(core_group,12), executor.submit(recipe_group)]
        for future in concurrent.futures.as_completed(futures): future.result()
    publish(complete=True)
    print(json.dumps({k:v for k,v in json.loads((OUT/'VALIDATION.json').read_text()).items()
                      if k in ('status','passed','failed','elapsed_seconds','source_unchanged')},indent=2),flush=True)
