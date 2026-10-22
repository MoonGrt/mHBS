#!/usr/bin/env python3
"""Replay certified q-boundary and empty-message h10 Sign vectors on frozen RTL.

This checker never generates a tree or invokes a software Hash oracle. It first
checks every .mem against a previously certified record, then replays those exact
files and compares full primitive input/result multiset fingerprints and counts.
"""
import argparse
import concurrent.futures as cf
import hashlib
import json
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def now():
    return datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    temp.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'run', 'archive', 'baseline'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.jobs <= 4:
        parser.error('--jobs must be 1..4')
    source, run, archive, baseline = (
        getattr(args, name).resolve() for name in ('source', 'run', 'archive', 'baseline')
    )
    run.mkdir(parents=True, exist_ok=True)
    archive.mkdir(parents=True, exist_ok=True)
    production = [line.strip() for line in (source / 'sources.txt').read_text().splitlines() if line.strip()]
    headers = ['rtl/executor/instructions.svh'] if (source / 'rtl/executor/instructions.svh').exists() else []
    inputs = production + headers + ['tb/tb_fast.sv', 'tb/fast_main.cpp']
    source_hashes = {name: sha(source / name) for name in inputs}
    version = subprocess.check_output(['verilator', '--version'], text=True)
    binaries = {}
    for backend in ('shake', 'sha2'):
        suffix = '_sha2' if backend == 'sha2' else ''
        folder = source / ('build/sim/P1U1_fast_o3_synthesis0_slow_O1' + suffix)
        binary = folder / 'obj/Vtb_fast'
        identity_input = ''.join(f'{source_hashes[name]}  {name}\n' for name in inputs)
        identity_input += f'OPT_FAST=-O3\nOPT_SLOW=-O1\nSYNTHESIS=0\nHASH_BACKEND={backend}\n' + version
        identity = hashlib.sha256(identity_input.encode()).hexdigest()
        saved = (folder / 'source.sha256').read_text().strip()
        if saved != identity:
            raise AssertionError(f'{backend}: existing executable source identity mismatch')
        binaries[backend] = dict(path=str(binary), sha256=sha(binary), source_identity=identity)
    tool = Path(__file__).resolve()
    tool_copy = archive / 'tools/check_reused_sign_supplements.py'
    tool_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(tool, tool_copy)
    identity = dict(
        frozen_source=str(source), inputs_sha256=source_hashes,
        tool_path=str(tool_copy.relative_to(archive)), tool_sha256=sha(tool),
        binary_identity=binaries, verilator_version=version.strip(),
        trace_comparison='count/SUM256/XOR256 of SHA256(padded input blocks || full Hash result); probabilistic multiset check',
        full_high_tree_tested=False, reference_generation_performed=False,
    )
    write(archive / 'SIGN_SUPPLEMENTS_SOURCE.json', identity)
    groups = {}
    tasks = []
    for kind, filename, required in (
        ('indices', 'SIGN_INDEX_VALIDATION.json', 8),
        ('empty', 'EMPTY_MESSAGE_VALIDATION.json', 4),
    ):
        record_path = baseline / filename
        old = json.loads(record_path.read_text())
        if not old['complete'] or old['passed'] != required:
            raise AssertionError(f'Baseline is not certified: {record_path}')
        state = dict(
            schema='mhbs.reused_sign_supplements.v1', started_at=now(), complete=False,
            required=required, passed=0, baseline=str(record_path), baseline_sha256=sha(record_path),
            configuration='K1U1', frozen_source=str(source), source_identity='SIGN_SUPPLEMENTS_SOURCE.json',
            full_high_tree_tested=False, reference_generation_performed=False,
            results={key: dict(status='pending') for key in old['results']},
        )
        groups[kind] = (filename, state)
        for key, reference in old['results'].items():
            reference = dict(reference)
            backend, profile = key.split('/')[:2]
            fixture = reference.get('fixture', {})
            fixture_sign = next((r for r in fixture.get('operations', []) if r['operation'] == 'sign'), {})
            log_path = Path(reference.get('rtl_log', reference.get('log', '')))
            if not log_path.is_file() or sha(log_path) != reference.get('rtl_log_sha256', reference.get('log_sha256')):
                raise AssertionError(f'Certified baseline log changed: {log_path}')
            log_text = log_path.read_text()
            baseline_pass = re.search(r'STATEFUL_PASS P1U1 op=(\d+) cycles=(\d+) total=(\d+) hashes=(\d+) permutations=(\d+)', log_text)
            if not baseline_pass:
                raise AssertionError('Missing baseline byte/cache/count PASS')
            _, old_cycles, old_total, old_hashes, old_blocks = map(int, baseline_pass.groups())
            reference.update(
                backend=backend, profile=profile, q=reference.get('q', fixture.get('q', 0)),
                message_bytes=reference.get('message_bytes', len(fixture.get('message_hex', '')) // 2),
                rtl_log=str(log_path), cycles=old_cycles, hashes=old_hashes, permutations=old_blocks,
                output_bytes=reference.get('output_bytes', fixture_sign.get('output_bytes')),
                final_vector_sha256=reference.get('final_vector_sha256', fixture_sign.get('sha256')),
                macro_metrics=reference.get('macro_metrics', json.loads(re.search(r'MACRO_METRICS (\{[^\n]+)', log_text)[1])),
            )
            tasks.append((kind, key, reference))
    lock = threading.RLock()

    def publish():
        with lock:
            for filename, state in groups.values():
                state['passed'] = sum(r.get('status') == 'passed' for r in state['results'].values())
                write(run / filename, state)
                write(archive / filename, state)

    def simulate(task):
        kind, key, old = task
        backend, profile = old['backend'], old['profile']
        q = old['q']
        old_vector = Path(old['rtl_log']).parent / 'vectors' / backend
        if kind == 'indices':
            old_vector /= f'q{q}'
        old_vector = old_vector / profile / 'sign'
        started = time.monotonic()
        with lock:
            groups[kind][1]['results'][key] = dict(status='running', started_at=now())
            publish()
        try:
            vector_hashes = {p.name: sha(p) for p in old_vector.glob('*.mem')}
            if not vector_hashes or vector_hashes != old['final_vector_sha256']:
                raise AssertionError(f'Certified vector identity mismatch: {old_vector}')
            vector = run / 'vectors' / kind / backend / f'q{q}' / profile / 'sign'
            vector.mkdir(parents=True, exist_ok=True)
            for name in vector_hashes:
                shutil.copy2(old_vector / name, vector / name)
            if {p.name: sha(p) for p in vector.glob('*.mem')} != vector_hashes:
                raise AssertionError('Copied vector identity mismatch')
            binary = Path(binaries[backend]['path'])
            if sha(binary) != binaries[backend]['sha256']:
                raise AssertionError('Executable changed after source certification')
            log = run / f'{kind}_{backend}_{profile}_q{q}.log'
            with log.open('w') as stream:
                status = subprocess.run(
                    [str(binary), '+VECTOR=' + str(vector), '+HASH_TRACE=1'], cwd=source,
                    stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                )
            if status.returncode:
                raise RuntimeError(f'RTL exit {status.returncode}: {log}')
            text = log.read_text()
            match = re.search(r'STATEFUL_PASS P1U1 op=(\d+) cycles=(\d+) total=(\d+) hashes=(\d+) permutations=(\d+)', text)
            trace_match = re.search(r'HASH_TRACE_METRICS (\{[^\n]+)', text)
            macro_match = re.search(r'MACRO_METRICS (\{[^\n]+)', text)
            if not match or not trace_match or not macro_match:
                raise AssertionError('Missing byte/cache/count PASS or actual primitive trace')
            operation, cycles, total, hashes, blocks = map(int, match.groups())
            trace = json.loads(trace_match[1])
            macro = json.loads(macro_match[1])
            if operation != 1 or hashes != old['hashes'] or blocks != old['permutations'] or trace != old['primitive_trace']:
                raise AssertionError('Cryptographic workload or primitive input/result fingerprint mismatch')
            if macro != old['macro_metrics']:
                raise AssertionError('Dynamic macro/control instruction counts changed')
            result = dict(
                status='passed', passed=True, backend=backend, profile=profile, operation='sign',
                q=q, message_bytes=old['message_bytes'], cycles=cycles, total_cycles=total,
                baseline_cycles=old['cycles'], hashes=hashes, permutations=blocks,
                output_bytes=old['output_bytes'], byte_exact_output=True, byte_exact_signature_cache=True,
                full_hash_and_permutation_count=True, primitive_trace=trace,
                primitive_trace_matches_certified_baseline=True, macro_metrics=macro,
                certified_vector=str(old_vector), vector=str(vector), final_vector_sha256=vector_hashes,
                baseline_vector_identity_equal=True, binary=binaries[backend], rtl_log=str(log),
                rtl_log_sha256=sha(log), seconds=time.monotonic()-started, completed_at=now(),
            )
        except Exception as error:
            result = dict(status='failed', passed=False, error=str(error), seconds=time.monotonic()-started)
        with lock:
            groups[kind][1]['results'][key] = result
            publish()
        print(kind, key, result['status'], flush=True)

    publish()
    with cf.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        list(pool.map(simulate, tasks))
    unchanged = all(sha(source/name) == digest for name, digest in source_hashes.items())
    success = unchanged
    for _, state in groups.values():
        state['complete'] = True
        state['finished_at'] = now()
        state['source_unchanged'] = unchanged
        state['acceptance_passed'] = unchanged and state['passed'] == state['required']
        success &= state['acceptance_passed']
    publish()
    if not success:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
