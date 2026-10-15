#!/usr/bin/env python3
"""Validate an already-frozen timing candidate; this script never freezes production RTL."""
from pathlib import Path
import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import traceback

PROFILES = ('slh_128f', 'xmss_h10', 'lms_h10')
CONFIGS = ((4, 1), (4, 2), (12, 1))
METRICS = ('cycles', 'total_cycles', 'hashes', 'permutations')
PATTERN = r'STATEFUL_PASS P\d+U\d+ op=(\d+) cycles=(\d+) total=(\d+) hashes=(\d+) permutations=(\d+)'

def tasks():
    result = []
    for p, u in (*CONFIGS, (1, 1), (2, 1), (2, 2), (12, 2), (24, 1)):
        for synthesis in (False, True):
            result.append(dict(name=f'recipes_P{p}U{u}_syn{int(synthesis)}', kind='recipes',
                p=p, u=u, synthesis=synthesis,
                command=['python3', 'scripts/check_recipes.py', '--pipeline', str(p), '--unroll', str(u)]
                + (['--synthesis'] if synthesis else [])))
    for p, u in CONFIGS:
        for synthesis in (False, True):
            result.append(dict(name=f'pipeline_P{p}U{u}_syn{int(synthesis)}', kind='pipeline',
                p=p, u=u, synthesis=synthesis,
                command=['python3', 'scripts/check_pipeline.py'] + (['--synthesis'] if synthesis else [])))
    for profile in PROFILES:
        result.append(dict(name=f'verify_P4U1_{profile}_stall_reset_cut', kind='verify',
            profile=profile, p=4, u=1, synthesis=False,
            command=['bash', 'scripts/simulate.sh', profile, 'verify', '4', '1',
                '+STALL=1', '+REPLAYS=2', '+INTERRUPT=1', '+CUT=1']))
    for fault in (1, 2, 3):
        result.append(dict(name=f'fault_P4U1_xmss_h10_{fault}', kind='fault', profile='xmss_h10',
            p=4, u=1, synthesis=False,
            command=['bash', 'scripts/simulate.sh', 'xmss_h10', 'verify', '4', '1', f'+FAULT={fault}']))
    for p, u, synthesis in ((4, 1, False), (4, 2, False), (12, 1, False), (4, 1, True)):
        for profile in PROFILES:
            result.append(dict(name=f'sign_P{p}U{u}_{profile}_syn{int(synthesis)}', kind='sign',
                profile=profile, p=p, u=u, synthesis=synthesis,
                command=['bash', 'scripts/simulate_fast.sh', profile, 'sign', str(p), str(u)]))
    return result

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, help='Existing run directory with SOURCE.json and source/')
    parser.add_argument('--baseline', type=Path, default=Path('build/timing_interface_20261015/VALIDATION.json'))
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--allow-cycle-change', action='store_true', help='Still require identical Hash/permutation counts')
    parser.add_argument('--list', action='store_true', help='Print only the plan, without source reads or subprocesses')
    args = parser.parse_args()
    plan = tasks()
    if args.list:
        print(json.dumps({'total':len(plan), 'tasks':plan}, indent=2)); return
    if args.run is None:
        parser.error('--run is required when executing')
    run = args.run.resolve(); source = run/'source'; logs = run/'logs'; logs.mkdir(exist_ok=True)
    manifest_path = run/'SOURCE.json'; manifest = json.loads(manifest_path.read_text())
    expected_sources = manifest['sha256']; manifest_sha = sha(manifest_path)
    rtl_sha = {p:expected_sources[p] for p in (source/'sources.txt').read_text().splitlines() if p.strip()}
    assert all(sha(source/p)==h for p,h in expected_sources.items()), 'Frozen source mismatch at start'
    baseline_path = args.baseline.resolve(); baseline = json.loads(baseline_path.read_text())
    assert baseline['complete'] and baseline['status']=='passed', 'Baseline validation must be complete/passed'
    baseline_sha = sha(baseline_path); baseline_tests = {t['name']:t for t in baseline['tests']}
    started = time.time(); results = []; lock = threading.Lock()

    def report(complete):
        mismatches = [p for p,h in expected_sources.items() if not (source/p).exists() or sha(source/p)!=h]
        passed = sum(t['passed'] for t in results); failed = len(results)-passed
        data = dict(complete=complete, status='failed' if failed or mismatches else 'passed' if complete else 'running',
            total=len(plan), passed=passed, failed=failed, tests=results,
            recipe_sha256=rtl_sha['rtl/hash/recipe.sv'], rtl_sha256=rtl_sha,
            source_manifest=str(manifest_path), source_manifest_sha256=manifest_sha,
            source_unchanged=not mismatches and sha(manifest_path)==manifest_sha,
            source_mismatches=mismatches, baseline_validation=str(baseline_path),
            baseline_validation_sha256=baseline_sha, baseline_rtl_sha256=baseline['rtl_sha256'],
            elapsed_seconds=time.time()-started, SIM_FAST_OPT_SLOW='-O1',
            cycle_policy='reported' if args.allow_cycle_change else 'exact',
            validation_scope='Recipe byte/hash oracle; four-active-tag mixed chains with poison/stall/capture/reuse; complete Sign byte and cache checks; Verify stall/reset/truncate; scalar/batch/illegal-state error injection.')
        temporary=run/'VALIDATION.tmp';temporary.write_text(json.dumps(data,indent=2)+'\n');temporary.replace(run/'VALIDATION.json')

    def pipeline_variant(task):
        # Existing bench exercises four tags. Only its DUT P/U is adapted; the
        # original eight requests and expected digests/captures remain unchanged.
        # P12 coverage is four active tags in a twelve-slot engine, not full occupancy.
        variant = run/'pipeline_variants'/task['name']/'source'
        paths = ['rtl/hash/keccak.sv','rtl/hash/recipe.sv','tb/tb_pipeline.sv','scripts/check_pipeline.py']
        for path in paths:
            destination=variant/path;destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source/path,destination)
        tb_path=variant/'tb/tb_pipeline.sv';before=tb_path.read_text()
        needle='.PIPELINE(4),.UNROLL(1)';assert before.count(needle)==1
        after=before.replace(needle,f".PIPELINE({task['p']}),.UNROLL({task['u']})")
        tb_path.write_text(after)
        evidence=dict(original_bench_sha256=sha(source/'tb/tb_pipeline.sv'),
            adapted_bench_sha256=sha(tb_path), configuration=f"P{task['p']}U{task['u']}",
            active_tags=4, requests=8,
            sha256={path:sha(variant/path) for path in paths})
        derived_manifest=variant.parent/'SOURCE.json';derived_manifest.write_text(json.dumps(evidence,indent=2)+'\n')
        return variant, {'path':str(derived_manifest),'sha256':sha(derived_manifest)}

    def run_task(task):
        begin=time.time();log=logs/(task['name']+'.log');result={**task,'passed':False};cwd=source
        env={**os.environ,'VERILATOR':manifest['verilator'],'SIM_FAST_OPT_SLOW':'-O1','SIM_SYNTHESIS':str(int(task['synthesis']))}
        env.pop('PROFILE_ENABLE',None)
        try:
            if task['kind']=='pipeline':
                cwd,derived=pipeline_variant(task);result['derived_test_source']=derived
            with log.open('w') as stream:
                process=subprocess.run(task['command'],cwd=cwd,env=env,stdout=stream,stderr=subprocess.STDOUT)
            text=log.read_text();result['exit_code']=process.returncode
            metrics=[dict(zip(('operation',*METRICS),map(int,x))) for x in re.findall(PATTERN,text)]
            result['metrics']=metrics
            if task['kind']=='recipes':
                result['cases']=459;result['passed']=process.returncode==0 and 'RECIPE_PASS cases=459' in text
            elif task['kind']=='pipeline':
                records=[line for line in text.splitlines() if line.startswith('PIPELINE_PASS')]
                coverage=[dict((k,int(v)) for k,v in re.findall(r'(family|requests|returns|simultaneous|unordered|hashes|poisoned|poison_cycles)=(\d+)',line)) for line in records]
                result['coverage']=coverage;result['active_tags']=4
                result['passed']=process.returncode==0 and len(records)==12 and all(c['simultaneous']>0 and c['unordered']>0 and c['poisoned']==8 and c['poison_cycles']>=8 for c in coverage)
            elif task['kind']=='fault':
                result['passed']=process.returncode==0 and 'STATEFUL_FAULT_PASS' in text
            else:
                expected=baseline_tests[task['name']]['metrics'];result['baseline_metrics']=expected
                result['same_workload']=len(metrics)==len(expected) and all(all(x[k]==y[k] for k in ('hashes','permutations')) for x,y in zip(metrics,expected))
                result['all_metrics_equal_baseline']=len(metrics)==len(expected) and all(all(x[k]==y[k] for k in METRICS) for x,y in zip(metrics,expected))
                result['cycle_delta']=[x['cycles']-y['cycles'] for x,y in zip(metrics,expected)]
                result['total_cycle_delta']=[x['total_cycles']-y['total_cycles'] for x,y in zip(metrics,expected)]
                result['passed']=process.returncode==0 and result['same_workload'] and (args.allow_cycle_change or result['all_metrics_equal_baseline'])
            result['logs']=[{'path':str(log),'sha256':sha(log)}]
        except Exception as error:
            result['exception']=str(error);result['traceback']=traceback.format_exc()
        result['elapsed_seconds']=time.time()-begin
        with lock:results.append(result);report(False)
        print(task['name'],'PASS' if result['passed'] else 'FAIL',flush=True)

    report(False)
    gate = [task for task in plan if task['kind'] in ('recipes', 'pipeline')]
    remaining = [task for task in plan if task['kind'] not in ('recipes', 'pipeline')]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for future in [pool.submit(run_task,task) for task in gate]:future.result()
        gate_result = dict(complete=True, passed=all(t['passed'] for t in results), total=len(gate),
            passed_count=sum(t['passed'] for t in results), rtl_sha256=rtl_sha,
            source_manifest=str(manifest_path), source_manifest_sha256=manifest_sha)
        (run/'GATE.json').write_text(json.dumps(gate_result,indent=2)+'\n')
        print('QUICK_GATE', 'PASS' if gate_result['passed'] else 'FAIL', len(gate), flush=True)
        if gate_result['passed']:
            for future in [pool.submit(run_task,task) for task in remaining]:future.result()
        else:
            print('Full Sign was not started because quick gate failed', flush=True)
    report(True)

if __name__=='__main__':
    main()
