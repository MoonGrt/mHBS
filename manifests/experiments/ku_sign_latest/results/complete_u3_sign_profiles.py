#!/usr/bin/env python3
"""Fill the six missing U3 Sign cases and publish the report without Vivado."""
import argparse
import concurrent.futures
import fcntl
import json
import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import v42_external_flow as flow
import sign_timing_scan as control

RUN = flow.ROOT / 'build/v4.2/sign_u3_profile_completion_v1'
MAIN = flow.ROOT.parents[2]
REPORT_SCRIPT = MAIN / 'scripts/report_ku_sign_atp.py'
TAGS = {1: 'signscan_k1u3_v1', 2: 'signfixed_k2u3_50m_v1', 4: 'signscan_k4u3_v1'}
PROFILES = ('slh_192f', 'slh_256f')
LOCK = threading.RLock()


def now():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def save(state):
    state['updated_at'] = now()
    control.atomic(RUN / 'state.json', state)
    completed = sum(job['status'] == 'passed' for job in state['jobs'].values())
    active = [key for key, job in state['jobs'].items() if job['status'] == 'running']
    text = '\n'.join(['# U3 192f / 256f Sign 补测', '', '状态：' + state['status'],
                       f'参考输出比对通过：{completed}/6',
                       '当前任务：' + ('、'.join(active) or '-'), '更新：' + state['updated_at'],
                       '报告：' + str(MAIN / 'docs/v4.2/KU_Sign_ATP_151_112_67_48.md'), ''])
    pending = RUN / 'STATUS.md.pending'
    pending.write_text(text)
    os.replace(pending, RUN / 'STATUS.md')


def initialize():
    if (RUN / 'state.json').exists():
        return
    jobs, inputs = {}, {}
    for k, tag in TAGS.items():
        folder = flow.capture(tag, lanes=k, unroll=3)
        inputs[tag] = control.load(folder / 'inputs.json')
        for profile in PROFILES:
            jobs[f'K{k}U3/{profile}'] = dict(k=k, profile=profile, tag=tag, status='pending')
    save(dict(schema='mhbs.u3_sign_profiles.v1', status='ready', jobs=jobs, inputs=inputs,
              config=dict(maximum_parallel_simulations=3, rtl_sha256=flow.identity(),
                          helper_sha256=flow.sha(Path(__file__)), report_script=str(REPORT_SCRIPT),
                          vivado_enabled=False)))


def run():
    state = control.load(RUN / 'state.json')
    state.update(status='running', driver=dict(pid=os.getpid(), start_ticks=control.pid_start(os.getpid())))
    for job in state['jobs'].values():
        if job['status'] == 'running':
            job['status'] = 'pending'
    save(state)
    baseline = control.load(flow.BASE / 'candidates/program16_20260927_v1/simulation.json')['cases']

    def one(key):
        job = state['jobs'][key]
        if job['status'] == 'passed':
            return
        k, profile, tag = job['k'], job['profile'], job['tag']
        shell = profile + '_sign'
        folder = flow.BUILD / tag
        try:
            inputs = state['inputs'][tag]
            assert flow.identity() == state['config']['rtl_sha256'] == inputs['rtl_sha256']
            assert flow.sha(folder / 'source_snapshot.tar.gz') == inputs['snapshot_sha256']
            for source, digest in inputs['source_sha256'].items():
                assert flow.sha(flow.ROOT / source) == digest, source
            with LOCK:
                job.update(status='running', started_at=now())
                save(state)
            _, case = flow.simulate_case(folder, shell, flow.BASE / 'vectors' / profile / 'sign',
                                         lanes=k, unroll=3)
            ref = baseline[shell]
            assert case['passed'] and case['output_sha256'] == ref['output_sha256'], key
            assert (case['hashes'], case['permutations']) == (ref['hashes'], ref['permutations']), key
            with LOCK:
                path = folder / 'supplemental_sign_profiles.json'
                supplement = control.load(path) if path.exists() else dict(
                    schema='mhbs.supplemental_sign_profiles.v1', lanes=k, unroll=3,
                    rtl_sha256=inputs['rtl_sha256'], snapshot_sha256=inputs['snapshot_sha256'],
                    software_gate_sha256=inputs['software_gate_sha256'], cases={})
                supplement['cases'][shell] = case
                supplement['passed'] = all(p + '_sign' in supplement['cases'] for p in PROFILES)
                supplement['updated_at'] = now()
                control.atomic(path, supplement)
                job.update(status='passed', finished_at=now(), cycles=case['sign_cycles'],
                           hashes=case['hashes'], permutations=case['permutations'],
                           output_sha256=case['output_sha256'], evidence=str(path))
                save(state)
            print('PROFILE_COMPLETION_PASS', key, case['sign_cycles'], flush=True)
        except Exception as error:
            with LOCK:
                job.update(status='failed', finished_at=now(), failure=repr(error))
                save(state)
            print('PROFILE_COMPLETION_FAILED', key, repr(error), flush=True)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(one, list(state['jobs'])))
        subprocess.run([sys.executable, str(REPORT_SCRIPT), '--worktree', str(flow.ROOT)],
                       cwd=MAIN, check=True)
        passed = all(job['status'] == 'passed' for job in state['jobs'].values())
        state.update(status='finished_all_passed' if passed else 'finished_with_failures',
                     report_updated=True, finished_at=now())
        control.atomic(RUN / 'FINISHED.json', dict(status=state['status'], finished_at=state['finished_at'],
                       report=str(MAIN / 'docs/v4.2/KU_Sign_ATP_151_112_67_48.md')))
    except Exception as error:
        state.update(status='failed', failure=repr(error))
        print('PROFILE_COMPLETION_ERROR', repr(error), flush=True)
    finally:
        state.pop('driver', None)
        save(state)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('start', 'resume', 'run', 'status', 'stop'))
    parser.add_argument('--lock-fd', type=int)
    args = parser.parse_args()
    RUN.mkdir(parents=True, exist_ok=True)
    if args.action in ('status', 'stop'):
        state = control.load(RUN / 'state.json')
        if args.action == 'stop':
            control.terminate(state.get('driver'))
            state = control.load(RUN / 'state.json')
            state.update(status='stopped')
            state.pop('driver', None)
            for job in state['jobs'].values():
                if job['status'] == 'running':
                    job['status'] = 'pending'
            save(state)
        print((RUN / 'STATUS.md').read_text())
        return
    stream = os.fdopen(args.lock_fd, 'a+') if args.lock_fd is not None else (RUN / 'driver.lock').open('a+')
    with stream as guard:
        try:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('ALREADY_RUNNING', RUN)
            return
        if args.action == 'run':
            run()
            return
        initialize()
        state = control.load(RUN / 'state.json')
        if state['status'] == 'finished_all_passed':
            print('ALREADY_FINISHED', RUN / 'FINISHED.json')
            return
        with (RUN / 'driver.log').open('a') as log:
            child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'run',
                                      '--lock-fd', str(guard.fileno())], cwd=flow.ROOT,
                                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                                     pass_fds=(guard.fileno(),))
        control.atomic(RUN / 'launched.json', dict(pid=child.pid, start_ticks=control.pid_start(child.pid)))
        print(json.dumps(dict(pid=child.pid, status=str(RUN / 'STATUS.md'), log=str(RUN / 'driver.log'))))


if __name__ == '__main__':
    main()
