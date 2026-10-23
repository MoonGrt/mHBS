#!/usr/bin/env python3
"""Measure frozen t P1U1 Sign clock partitions against the shared 33-byte KAT."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import time

OUT = Path(__file__).resolve().parent
SRC = OUT / 'source'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def measure(backend):
    work = OUT / backend
    vector = work / 'vectors'
    files = [x.strip() for x in (SRC / 'rtl/t/sources.txt').read_text().splitlines()
             if x.strip() and not x.startswith('#')]
    command = [os.environ.get('VERILATOR', 'verilator'), '--cc', '--exe', '--build',
               '-O3', '-j', '2', '-Wno-fatal', '--top-module', 'tb_fast',
               '-GPIPELINE=1', '-GUNROLL=1', '--Mdir', str(work / 'obj'),
               '-MAKEFLAGS', 'OPT_FAST=-O3 OPT_SLOW=-O1', '-CFLAGS', '-O3 -march=native']
    if backend == 'sha2':
        command.append('-DMHBS_SHA2')
    command += files + [str(SRC / 'tb_clock_profile.sv'), str(SRC / 'clock_profile.cpp')]
    run_command = [str(work / 'obj/Vtb_fast'), f'+VECTOR={vector}',
                   f'+OUTPUT_BIN={work / "rtl_signature.bin"}',
                   f'+CACHE_BIN={work / "rtl_cache.bin"}']
    (work / 'command.json').write_text(json.dumps(dict(compile=command, run=run_command,
        cwd=str(SRC), configuration='P1U1', message_bytes=33), indent=2) + '\n')
    started = time.monotonic()
    with (work / 'compile.log').open('w') as log:
        result = subprocess.run(command, cwd=SRC, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f'{backend} compile failed: {work / "compile.log"}')
    compiled = time.monotonic()
    print(backend, 'compile finished; starting complete Sign', flush=True)
    with (work / 'run.log').open('w') as log:
        result = subprocess.run(run_command, cwd=SRC, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f'{backend} Sign failed: {work / "run.log"}')
    output = (work / 'run.log').read_text()
    line = re.search(r'CLOCK_BREAKDOWN total=(\d+) hash=(\d+) transfer=(\d+) remaining=(\d+) '
                     r'rounds=(\d+) feedforward=(\d+) internal_handoff_overlap_diagnostic=(\d+)', output)
    stats = re.search(r'STATEFUL_PASS P1U1 op=1 cycles=(\d+) total=(\d+) hashes=(\d+) '
                      r'permutations=(\d+) tamper=0 logical_permutations=(\d+)', output)
    if not line or not stats:
        raise RuntimeError(f'{backend} missing full Sign/clock partition PASS markers')
    total, hashed, transfer, remaining, rounds, feedforward, internal = map(int, line.groups())
    cycles, observed_ticks, hashes, blocks, logical_blocks = map(int, stats.groups())
    expected = bytes(int(x, 16) for x in (vector / 'expected.mem').read_text().split())
    signature = (work / 'rtl_signature.bin').read_bytes()
    cache = (work / 'rtl_cache.bin').read_bytes()
    kat = (work / 'kat_signature.bin').read_bytes()
    assert signature == cache == kat == expected
    assert total == cycles == hashed + transfer + remaining
    assert transfer == 0 and hashed == rounds + feedforward
    assert rounds == blocks * (64 if backend == 'sha2' else 24)
    assert feedforward == (blocks if backend == 'sha2' else 0)
    report = dict(backend=backend, design='t', total=total, hash=hashed, transfer=transfer,
        remaining=remaining, rounds=rounds, feedforward=feedforward, hash_count=hashes,
        physical_blocks=blocks, logical_blocks=logical_blocks,
        signature_sha256=sha(work / 'rtl_signature.bin'),
        signature_cache_sha256=sha(work / 'rtl_cache.bin'), kat_signature_sha256=sha(work / 'kat_signature.bin'),
        signature_cache_and_kat_match=True, signature_bytes=len(signature),
        message_bytes=33, configuration='P1U1', observed_total_ticks=observed_ticks,
        internal_handoff_overlap_diagnostic=internal,
        compile_seconds=compiled-started, run_seconds=time.monotonic()-compiled,
        partition='Disjoint active signing clocks: Hash rounds/feed-forward; Transfer is non-overlapping MMIO (none); Remaining is all other active clocks.',
        source_identity='../SOURCE.json', passed=True)
    (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)
    return report


if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(measure, ('shake', 'sha2')))
    (OUT / 'SUMMARY.json').write_text(json.dumps(dict(passed=True, results=results), indent=2) + '\n')
