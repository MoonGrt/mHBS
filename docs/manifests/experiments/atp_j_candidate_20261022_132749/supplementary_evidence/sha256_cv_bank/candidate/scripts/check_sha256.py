#!/usr/bin/env python3
"""Cross-check the SHA256 compression lane, tags, stalls and reset replay."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import argparse
import json
import os
from pathlib import Path
import random
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
IV = bytes.fromhex('6a09e667 bb67ae85 3c6ef372 a54ff53a 510e527f 9b05688c 1f83d9ab 5be0cd19')
K = tuple(int(word, 16) for word in '''
428a2f98 71374491 b5c0fbcf e9b5dba5 3956c25b 59f111f1 923f82a4 ab1c5ed5
d807aa98 12835b01 243185be 550c7dc3 72be5d74 80deb1fe 9bdc06a7 c19bf174
e49b69c1 efbe4786 0fc19dc6 240ca1cc 2de92c6f 4a7484aa 5cb0a9dc 76f988da
983e5152 a831c66d b00327c8 bf597fc7 c6e00bf3 d5a79147 06ca6351 14292967
27b70a85 2e1b2138 4d2c6dfc 53380d13 650a7354 766a0abb 81c2c92e 92722c85
a2bfe8a1 a81a664b c24b8b70 c76c51a3 d192e819 d6990624 f40e3585 106aa070
19a4c116 1e376c08 2748774c 34b0bcb5 391c0cb3 4ed8aa4a 5b9cca4f 682e6ff3
748f82ee 78a5636f 84c87814 8cc70208 90befffa a4506ceb bef9a3f7 c67178f2
'''.split())
MASK = 0xffffffff


def rotate(value, amount):
    return ((value >> amount) | (value << (32-amount))) & MASK


def compress(cv, block):
    """Independent array-based schedule, checked against hashlib below."""
    initial = [int.from_bytes(cv[i:i+4], 'big') for i in range(0, 32, 4)]
    words = [int.from_bytes(block[i:i+4], 'big') for i in range(0, 64, 4)]
    for i in range(16, 64):
        x, y = words[i-15], words[i-2]
        s0 = rotate(x, 7) ^ rotate(x, 18) ^ (x >> 3)
        s1 = rotate(y, 17) ^ rotate(y, 19) ^ (y >> 10)
        words.append((words[i-16] + s0 + words[i-7] + s1) & MASK)
    a, b, c, d, e, f, g, h = initial
    for constant, word in zip(K, words):
        s0 = rotate(a, 2) ^ rotate(a, 13) ^ rotate(a, 22)
        s1 = rotate(e, 6) ^ rotate(e, 11) ^ rotate(e, 25)
        t1 = (h + s1 + ((e & f) ^ (~e & g)) + constant + word) & MASK
        t2 = (s0 + ((a & b) ^ (a & c) ^ (b & c))) & MASK
        a, b, c, d, e, f, g, h = (t1+t2) & MASK, a, b, c, (d+t1) & MASK, e, f, g
    return b''.join(((x+y) & MASK).to_bytes(4, 'big')
                    for x, y in zip(initial, (a, b, c, d, e, f, g, h)))


def make_vectors():
    randomizer = random.Random(0x2562026)
    lengths = (0, 1, 3, 54, 55, 56, 63, 64, 65, 86, 119, 120, 127, 128, 129, 255, 1024, 2166)
    rows = []
    for length in lengths:
        message = b'abc' if length == 3 else randomizer.randbytes(length)
        padded = message + b'\x80'
        padded += bytes((56-len(padded)) % 64) + (length*8).to_bytes(8, 'big')
        cv = IV
        for offset in range(0, len(padded), 64):
            block = padded[offset:offset+64]
            result = compress(cv, block)
            rows.append((cv+block+result).hex())
            cv = result
        assert cv == sha256(message).digest(), f'Python compression oracle mismatch: {length}'
    for _ in range(96):
        cv, block = randomizer.randbytes(32), randomizer.randbytes(64)
        rows.append((cv+block+compress(cv, block)).hex())
    return rows, lengths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pipeline', type=int, default=4)
    parser.add_argument('--unroll', type=int, default=1)
    parser.add_argument('--all', action='store_true', help='Test all 30 existing legal P/U pairs')
    parser.add_argument('--jobs', type=int, default=2, help='Parallel test builds, each uses 2 compiler threads')
    parser.add_argument('--synthesis', action='store_true')
    args = parser.parse_args()
    configurations = [(p, u) for p in range(1, 25) for u in range(1, 25)
                      if p*u <= 24 and 24 % (p*u) == 0] if args.all else [(args.pipeline, args.unroll)]
    if args.jobs < 1 or args.jobs > 4:
        parser.error('--jobs must be between 1 and 4')
    for p, u in configurations:
        if p < 1 or u < 1 or p*u > 24 or 24 % (p*u):
            parser.error('Require positive P/U and P*U dividing 24')
    work = ROOT / 'build' / ('sha256_check_synthesis' if args.synthesis else 'sha256_check')
    work.mkdir(parents=True, exist_ok=True)
    rows, lengths = make_vectors()
    vector = work/'vectors.mem'
    vector.write_text('\n'.join(rows)+'\n')
    sources = ['rtl/hash/sha256.sv', 'tb/tb_sha256.sv', 'scripts/check_sha256.py']
    source_sha = {name: sha256((ROOT/name).read_bytes()).hexdigest() for name in sources}
    verilator = os.environ.get('VERILATOR', 'verilator')

    def run(configuration):
        p, u = configuration
        folder = work/f'P{p}U{u}'
        folder.mkdir(parents=True, exist_ok=True)
        command = [verilator, '--binary', '--timing', '-O3', '-j', '2', '-Wno-fatal',
                   '--top-module', 'tb_sha256', f'-GPIPELINE={p}', f'-GUNROLL={u}',
                   '--Mdir', str(folder/'obj'), 'rtl/hash/sha256.sv', 'tb/tb_sha256.sv']
        if args.synthesis:
            command.append('-DSYNTHESIS')
        started = time.monotonic()
        with (folder/'compile.log').open('w') as log:
            build = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        if build.returncode:
            return dict(pipeline=p, unroll=u, passed=False, stage='compile', log=str(folder/'compile.log'))
        result = subprocess.run([str(folder/'obj/Vtb_sha256'), f'+VECTOR={vector}', f'+COUNT={len(rows)}'],
                                cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (folder/'run.log').write_text(result.stdout)
        passed = result.returncode == 0 and 'SHA256_PASS ' in result.stdout
        print(result.stdout.strip(), flush=True)
        return dict(pipeline=p, unroll=u, passed=passed, vectors=len(rows),
                    elapsed_seconds=time.monotonic()-started, log=str(folder/'run.log'))

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(run, configurations))
    unchanged = all(sha256((ROOT/name).read_bytes()).hexdigest() == digest
                    for name, digest in source_sha.items())
    report = dict(schema='mhbs.sha256.primitive.v1', passed=sum(r['passed'] for r in results),
                  total=len(results), source_unchanged=unchanged, source_sha256=source_sha,
                  synthesis=args.synthesis, vectors=len(rows), message_lengths=lengths,
                  oracle='Independent Python full message schedule, cross-checked with hashlib SHA256',
                  results=results)
    (work/'VALIDATION.json').write_text(json.dumps(report, indent=2)+'\n')
    print(f"SHA256 validation {report['passed']}/{report['total']}; {work/'VALIDATION.json'}", flush=True)
    if not unchanged or not all(r['passed'] for r in results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
