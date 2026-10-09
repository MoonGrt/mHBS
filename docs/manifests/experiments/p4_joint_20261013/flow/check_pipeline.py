#!/usr/bin/env python3
"""Check tag recycling and retained captures against independent SHAKE chains."""
from hashlib import shake_256
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]

def main():
    work = ROOT / 'build/pipeline_check'
    work.mkdir(parents=True, exist_ok=True)
    sk, pub, ident = bytes(range(1, 33)), bytes(range(65, 97)), bytes(range(225, 241))
    def be(x, n=4): return x.to_bytes(n, 'big')
    def h(v): return shake_256(v).digest(32)
    obj = work / 'obj'
    command = [os.environ.get('VERILATOR', 'verilator'), '--binary', '--timing', '-O3', '-j', '2', '-Wno-fatal', '--top-module', 'tb_pipeline', '--Mdir', str(obj), 'rtl/hash/keccak.sv', 'rtl/hash/pipeline.sv', 'rtl/hash/recipe.sv', 'tb/tb_pipeline.sv']
    with (work/'compile.log').open('w') as log:
        subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    for family in range(3):
        rows, hashes = [], 0
        for row, (steps, capture_after, no_seed) in enumerate(((0, 0, 1), (15, 3, 0), (1, 1, 1), (7, 0, 0), (2, 0, 0), (0, 0, 1), (3, 3, 1), (1, 0, 0))):
            a = row+1
            adr = b''.join(map(be, (3, 0, 0x01234567, 0x89abcdef, 0x83, 513, a, 0)))
            def masked(step, compound):
                return bytes(12)+b''.join(map(be, (0x83, 513, a, step, compound)))
            initial = bytes((19*row+k) & 255 for k in range(32))
            value = initial
            if not no_seed:
                if family == 0: data = pub+adr+sk
                elif family == 1: data = be(4, 32)+sk+pub+masked(0, 0)
                else: data = ident+be(513)+be(a, 2)+b'\xff'+sk
                value = h(data);hashes += 1
            captured = value if capture_after == 0 else None
            for step in range(steps):
                if family == 0: value = h(pub+adr[:-4]+be(step)+value);hashes += 1
                elif family == 1:
                    key, mask = (h(be(3, 32)+pub+masked(step, c)) for c in (0, 1))
                    value = h(bytes(32)+key+bytes(x ^ y for x, y in zip(value, mask)));hashes += 3
                else: value = h(ident+be(513)+be(a, 2)+bytes([step])+value);hashes += 1
                if capture_after == step+1: captured = value
            assert captured is not None
            packed = int.from_bytes(captured, 'little') | int.from_bytes(value, 'little') << 256 | int.from_bytes(initial, 'little') << 512 | steps << 768 | capture_after << 773 | no_seed << 778
            rows.append(f'{packed:0195x}\n')
        vector = work/f'family{family}.mem';vector.write_text(''.join(rows))
        result = subprocess.run([str(obj/'Vtb_pipeline'), f'+VECTOR={vector}', f'+FAMILY={family}', f'+HASHES={hashes}'], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (work/f'family{family}.log').write_text(result.stdout)
        print(result.stdout, end='');result.check_returncode()

if __name__ == '__main__': main()
