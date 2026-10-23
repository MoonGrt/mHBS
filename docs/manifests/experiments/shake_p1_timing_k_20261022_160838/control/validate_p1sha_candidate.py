#!/usr/bin/env python3
"""Source-bound recipe, scheduling and Verify checks for a frozen P1/SHA candidate."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-root', type=Path, required=True)
    args = parser.parse_args()
    run = args.run_root.resolve()
    meta = json.loads((run / 'SOURCE.json').read_text())
    assert meta['schema'] == 'mhbs.p1sha_atp.source.v1'
    source, output = Path(meta['source_root']), run / 'functional_validation'
    output.mkdir(parents=True, exist_ok=False)
    (output / 'logs').mkdir()
    shutil.copyfile(__file__, output / 'validator.py')
    cases = []
    for backend, configs in [('shake', ((1, 1), (1, 2))),
                             ('sha2', ((1, 1), (1, 2), (4, 1), (4, 2), (12, 1)))]:
        for p, u in configs:
            for synthesis in (False, True):
                command = ['python3', 'scripts/check_recipes.py', '--hash', backend,
                           '--pipeline', str(p), '--unroll', str(u)]
                if synthesis:
                    command += ['--synthesis']
                cases.append((f'recipes_{backend}_P{p}U{u}_syn{int(synthesis)}', backend, synthesis, command, 'RECIPE_PASS'))
    for p, u in ((4, 1), (4, 2)):
        for synthesis in (False, True):
            command = ['python3', 'scripts/check_pipeline.py', '--hash', 'sha2',
                       '--pipeline', str(p), '--unroll', str(u)]
            if synthesis:
                command += ['--synthesis']
            cases.append((f'batch_sha2_P{p}U{u}_syn{int(synthesis)}', 'sha2', synthesis, command, 'PIPELINE_PASS'))
    for backend, configs in [('shake', ((1, 1), (1, 2))), ('sha2', ((1, 1), (1, 2), (4, 1)))]:
        for p, u in configs:
            for profile in ('slh_128f', 'xmss_h10', 'lms_h10'):
                command = ['bash', 'scripts/simulate.sh', profile, 'verify', str(p), str(u),
                           '+STALL=1', '+REPLAYS=2', '+INTERRUPT=1']
                cases.append((f'verify_{backend}_P{p}U{u}_{profile}_replay_reset', backend, False, command, 'STATEFUL_PASS'))
    for backend, p, u, profile in [('shake', 1, 1, 'xmss_h10'), ('sha2', 1, 1, 'slh_128f'), ('sha2', 4, 2, 'lms_h10')]:
        command = ['bash', 'scripts/simulate.sh', profile, 'verify', str(p), str(u), '+STALL=1']
        cases.append((f'verify_{backend}_P{p}U{u}_{profile}_synthesis', backend, True, command, 'STATEFUL_PASS'))
    results, lock, started = [], threading.Lock(), time.monotonic()

    def publish(complete=False):
        changed = [n for n, h in meta['sha256'].items() if sha(source / n) != h]
        data = dict(schema='mhbs.p1sha.functional_validation.v1', complete=complete,
            candidate_run=str(run), source_manifest=str(run / 'SOURCE.json'),
            source_manifest_sha256=sha(run / 'SOURCE.json'),
            rtl_sha256={n: h for n, h in meta['sha256'].items() if n.startswith('rtl/')},
            validator_sha256=sha(output / 'validator.py'), total_planned=len(cases),
            passed=sum(t['passed'] for t in results), failed=sum(not t['passed'] for t in results),
            source_unchanged=not changed, source_mismatches=changed,
            elapsed_seconds=time.monotonic()-started, tests=list(results),
            scope='Frozen RTL only; independent recipe bytes/counts, four-tag batch capture and recycling, '
                  'three-profile Verify stalls/replay/in-flight reset, normal and SYNTHESIS views. '
                  'Complete Sign and common synthesis are measured separately. No h20 Keygen/Sign.')
        temporary = output / 'VALIDATION.json.tmp'
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
        temporary.replace(output / 'VALIDATION.json')

    def execute(case):
        name, backend, synthesis, command, marker = case
        log, start = output / 'logs' / (name + '.log'), time.monotonic()
        env = dict(os.environ, HASH_BACKEND=backend, SIM_SYNTHESIS=str(int(synthesis)),
                   KECCAK_LUT6='0', SIM_VCD='0')
        env.pop('PROFILE_ENABLE', None)
        env.pop('VECTORS_DIR', None)
        with log.open('w') as stream:
            process = subprocess.run(command, cwd=source, env=env, stdin=subprocess.DEVNULL,
                                     stdout=stream, stderr=subprocess.STDOUT)
        text = log.read_text(errors='replace')
        result = dict(name=name, hash_backend=backend, synthesis=synthesis, command=command,
            passed=process.returncode == 0 and marker in text, returncode=process.returncode,
            elapsed_seconds=time.monotonic()-start, log=str(log), log_sha256=sha(log),
            pass_markers=[line for line in text.splitlines() if marker in line])
        with lock:
            results.append(result)
            publish()
        print(name, 'PASS' if result['passed'] else 'FAIL', flush=True)

    publish()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(execute, cases))
    publish(True)
    data = json.loads((output / 'VALIDATION.json').read_text())
    return int(data['failed'] != 0 or not data['source_unchanged'])


if __name__ == '__main__':
    raise SystemExit(main())
