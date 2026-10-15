#!/usr/bin/env python3
"""Gate explicitly authorized candidate routing on frozen functional results."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import time
from zoneinfo import ZoneInfo
from experiment_archive import atomic

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = ('P1U1', 'P4U1', 'P4U2', 'P12U1')
PROFILES = ('slh_128f', 'xmss_h10', 'lms_h10')


def read(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def now():
    return datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds')


def native_vivado():
    result = []
    for line in subprocess.check_output(['ps', '-eo', 'comm=,args='], text=True).splitlines():
        fields = line.split(None, 1)
        if (len(fields) == 2 and fields[0] == 'vivado'
                and '/bin/unwrapped/lnx64.o/vivado -mode batch' in fields[1]):
            result.append(fields[1])
    return result


def measurement_gate(meta, baseline, tasks):
    """Keep functional correctness separate from optional performance budgets."""
    reference = baseline.get('tasks', {})
    signs = [f'sim/{cfg}/{profile}' for cfg in CONFIGS for profile in PROFILES]
    if any(tasks.get(k, {}).get('status') == 'failed' for k in signs):
        return 'blocked_by_functional_failure'
    if not all(tasks.get(k, {}).get('status') == 'passed' for k in signs):
        return 'waiting_for_twelve_sign_cases'
    if not all(reference.get(k, {}).get('status') == 'passed' for k in signs):
        return 'waiting_for_baseline_sign_cases'
    if not all(tasks[k].get(field) is not None
               and tasks[k][field] == reference[k].get(field)
               for k in signs for field in ('hashes', 'permutations')):
        return 'blocked_by_workload_change'
    for key in signs:
        for field in ('cycles', 'total_cycles'):
            old, new = reference[key].get(field), tasks[key].get(field)
            if old is None or new is None or old <= 0:
                return 'blocked_by_missing_cycle_measurement'
            if meta.get('allow_cycle_changes', False):
                if (new-old)*100 > old*meta.get('max_cycle_increase_pct', 5.0):
                    return 'blocked_by_cycle_budget'
            elif new != old:
                return 'blocked_by_cycle_change'
    synths = [f'synth/{cfg}/common' for cfg in CONFIGS]
    if any(tasks.get(k, {}).get('status') == 'failed' for k in synths):
        return 'blocked_by_synthesis_failure'
    # Area budgets are reported independently. A slow synthesis must not hold
    # up routing of completed points; each route waits for its own exact DCP.
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-root', type=Path, required=True)
    args = parser.parse_args()
    run = args.run_root.resolve()
    state = dict(started_at=now(), complete=False, authorized_routing_launched=[])
    while True:
        meta = read(run/'EXPERIMENT.json')
        if not meta.get('user_authorized_routing'):
            raise RuntimeError('No explicit user authorization recorded for this experiment')
        baseline = read(Path(meta['baseline_run'])/'status.json')
        for stage in meta['stages']:
            if not stage.get('route_after_validation') or stage.get('route'):
                continue
            candidate = Path(stage['run'])
            candidate_state = read(candidate/'status.json')
            tasks = candidate_state.get('tasks', {})
            gate = measurement_gate(meta, baseline, tasks)
            if gate:
                stage['automatic_routing_status'] = gate
                continue
            evidence = [read(run/'validation'/(name+'.json'))
                        for name in stage.get('required_validation', [])]
            manifest_sha = hashlib.sha256((candidate/'SOURCE.json').read_bytes()).hexdigest()
            if any(item and item.get('source_manifest_sha256') != manifest_sha for item in evidence):
                stage['automatic_routing_status'] = 'blocked_by_validation_source_mismatch'
                continue
            if any(item.get('failed', 0) or item.get('status') == 'failed'
                   or item.get('source_unchanged') is False or item.get('rtl_unchanged') is False
                   for item in evidence):
                stage['automatic_routing_status'] = 'blocked_by_extended_validation_failure'
                continue
            if not all(item.get('complete') for item in evidence):
                stage['automatic_routing_status'] = 'waiting_for_extended_validation'
                continue
            if any(tasks.get(f'synth/{cfg}/common', {}).get('status') == 'failed' for cfg in CONFIGS):
                stage['automatic_routing_status'] = 'blocked_by_synthesis_failure'
                continue
            live = native_vivado()
            # Reserve even the candidate syntheses that have not spawned yet.
            # The older pools already submitted every synthesis; their remaining
            # routes replace exiting synthesis processes, rather than expanding
            # the bound. Starting four new routes must still fit within twelve.
            remaining = sum(tasks.get(f'synth/{cfg}/common', {}).get('status') in ('pending', 'running')
                            for cfg in CONFIGS)
            own_script = str(candidate/'source/scripts/synth_pu_sign_matrix.tcl')
            own_live = sum(own_script in command for command in live)
            reserve = max(0, remaining-own_live)
            for other_stage in meta['stages']:
                if other_stage['run'] != stage['run']:
                    other_tasks = read(Path(other_stage['run'])/'status.json').get('tasks', {})
                    reserve += sum(v.get('status') == 'pending' for k, v in other_tasks.items()
                                   if k.startswith('synth/'))
            if len(live) + reserve + len(CONFIGS) + meta.get('vivado_headroom', 0) > 12:
                stage['automatic_routing_status'] = 'waiting_for_vivado_capacity'
                continue
            command = ['python3', str(ROOT/'scripts/run_pu_route_matrix.py'), '--launch',
                       '--authorize-routing', '--synthesis-run', str(candidate), '--configs', *CONFIGS,
                       '--max-implementations', str(meta.get('route_max_implementations', 6))]
            launched = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
            (run/(stage['name']+'_route_launch.log')).write_text(launched.stdout+launched.stderr)
            if launched.returncode:
                stage['automatic_routing_status'] = 'launch_failed_see_log'
                stage['route_after_validation'] = False
                continue
            result = json.loads(launched.stdout)
            stage['route'] = result['root']
            stage['automatic_routing_status'] = 'launched'
            stage['route_after_validation'] = False
            state['authorized_routing_launched'].append(dict(name=stage['name'], time=now(), **result))
            print(now(), 'CANDIDATE_ROUTE_LAUNCHED', result, flush=True)
            # Let the detached runner publish/spawn before considering another
            # candidate. It has its own capacity guard for each real process.
            break
        atomic(run/'EXPERIMENT.json', json.dumps(meta, ensure_ascii=False, indent=2)+'\n')
        state['updated_at'] = now()
        pending = any(s.get('route_after_validation') and not s.get('route') for s in meta['stages'])
        state['complete'] = not pending
        atomic(run/'COORDINATOR.json', json.dumps(state, ensure_ascii=False, indent=2)+'\n')
        if not pending:
            return
        time.sleep(15)


if __name__ == '__main__':
    main()
