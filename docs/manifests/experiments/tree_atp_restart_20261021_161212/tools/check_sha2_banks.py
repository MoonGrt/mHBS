#!/usr/bin/env python3
"""Check digest/result bank sharing using independent SHA256 chain frames."""
from hashlib import sha256
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    work = ROOT / 'build/sha2_banks'
    work.mkdir(parents=True, exist_ok=True)
    obj = work / 'obj'
    sources = ['rtl/hash/keccak.sv', 'rtl/hash/shake-recipe.sv', 'rtl/hash/sha256.sv', 'rtl/hash/sha2-recipe.sv']
    command = ['verilator', '--binary', '--timing', '-O3', '-j', '2', '-Wno-fatal', '-DMHBS_SHA2',
               '--top-module', 'tb_pipeline', '--Mdir', str(obj), *sources, 'tb/tb_pipeline.sv']
    with (work / 'compile.log').open('w') as log:
        subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    sk, pub, ident = bytes(range(1, 33)), bytes(range(65, 97)), bytes(range(225, 241))
    result = []
    for family in range(3):
        rows, hashes, blocks = [], 0, 0
        n = 16 if family == 0 else 32
        def be(value, size=4):
            return value.to_bytes(size, 'big')
        def h(value):
            nonlocal hashes, blocks
            hashes += 1
            blocks += (len(value) + 9 + 63) // 64
            return sha256(value).digest()[:n]
        for row, (steps, capture_after, no_seed) in enumerate(((0, 0, 1), (15, 3, 0), (1, 1, 1), (7, 0, 0), (2, 0, 0), (0, 0, 1), (3, 3, 1), (1, 0, 0))):
            a = row + 1
            compressed = bytes([3]) + be(0x01234567) + be(0x89abcdef) + bytes([0x83]) + be(513) + be(a)
            prefix = pub[:n] + bytes(64-n)
            def masked(step, compound):
                return bytes(12) + b''.join(be(v) for v in (0x83, 513, a, step, compound))
            initial = bytes((19*row+k) & 255 for k in range(32))
            value = initial[:n]
            if not no_seed:
                if family == 0:
                    value = h(prefix + compressed + be(0) + sk[:n])
                elif family == 1:
                    value = h(be(4, 32) + sk + pub + masked(0, 0))
                else:
                    value = h(ident + be(513) + be(a, 2) + b'\xff' + sk)
            capture = value if capture_after == 0 else None
            for step in range(steps):
                if family == 0:
                    value = h(prefix + compressed + be(step) + value)
                elif family == 1:
                    key, mask = (h(be(3, 32) + pub + masked(step, c)) for c in (0, 1))
                    value = h(bytes(32) + key + bytes(x ^ y for x, y in zip(value, mask)))
                else:
                    value = h(ident + be(513) + be(a, 2) + bytes([step]) + value)
                if capture_after == step + 1:
                    capture = value
            assert capture is not None
            word = int.from_bytes(capture, 'little') | int.from_bytes(value, 'little') << 256
            word |= int.from_bytes(initial, 'little') << 512 | steps << 768 | capture_after << 773 | no_seed << 778
            rows.append(f'{word:0195x}\n')
        vector = work / f'family{family}.mem'
        vector.write_text(''.join(rows))
        process = subprocess.run([str(obj / 'Vtb_pipeline'), f'+VECTOR={vector}', f'+FAMILY={family}',
                                  f'+HASHES={hashes}', f'+PERMUTATIONS={blocks}'], cwd=ROOT, capture_output=True, text=True)
        (work / f'family{family}.log').write_text(process.stdout + process.stderr)
        if process.returncode or 'PIPELINE_PASS' not in process.stdout:
            raise RuntimeError(process.stdout + process.stderr)
        result.append({'family': family, 'requests': 8, 'hashes': hashes, 'blocks': blocks, 'passed': True})
        print(process.stdout.strip())
    (work / 'VALIDATION.json').write_text(json.dumps({'passed': True, 'results': result}, indent=2) + '\n')


if __name__ == '__main__':
    main()
