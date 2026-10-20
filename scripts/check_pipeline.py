#!/usr/bin/env python3
"""Check tag recycling and retained captures against independent SHAKE chains."""
from hashlib import shake_256, sha256
import argparse
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hash', dest='hash_backend', choices=('shake','sha2'), default='shake')
    parser.add_argument('--pipeline', type=int, default=4)
    parser.add_argument('--unroll', type=int, default=1)
    parser.add_argument('--synthesis',action='store_true',help='Verify the RTL view with diagnostic ports removed')
    args=parser.parse_args()
    work = ROOT / ('build/pipeline_check_synthesis' if args.synthesis else 'build/pipeline_check')
    if args.pipeline < 4 or args.pipeline*args.unroll > 24 or 24 % (args.pipeline*args.unroll):
        parser.error('This four-live-tag test requires P>=4 and P*U dividing 24')
    work = work / f'{args.hash_backend}_P{args.pipeline}U{args.unroll}'
    work.mkdir(parents=True, exist_ok=True)
    sk, pub, ident = bytes(range(1, 33)), bytes(range(65, 97)), bytes(range(225, 241))
    def be(x, n=4): return x.to_bytes(n, 'big')
    def h(v): return shake_256(v).digest(32)
    obj = work / 'obj'
    command = [os.environ.get('VERILATOR', 'verilator'), '--binary', '--timing', '-O3', '-j', '2', '-Wno-fatal', '--top-module', 'tb_pipeline', '--Mdir', str(obj), 'rtl/hash/keccak.sv', 'rtl/hash/shake-recipe.sv', 'rtl/hash/sha256.sv', 'rtl/hash/sha2-recipe.sv', 'tb/tb_pipeline.sv']
    command += [f'-GPIPELINE={args.pipeline}', f'-GUNROLL={args.unroll}']
    if args.synthesis: command.append('-DSYNTHESIS')
    if args.hash_backend == 'sha2': command.append('-DMHBS_SHA2')
    with (work/'compile.log').open('w') as log:
        subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    for family,leaf in ((f,q) for f in range(3) for q in (513,1024,65536,1048575)):
        rows, hashes = [], 0
        permutations = 0
        n = 16 if args.hash_backend=='sha2' and family==0 else 32
        def h(value):
            nonlocal permutations
            permutations += (len(value)+9+63)//64 if args.hash_backend=='sha2' else len(value)//136+1
            return sha256(value).digest()[:n] if args.hash_backend=='sha2' else shake_256(value).digest(32)
        def slh_frame(address, payload):
            if args.hash_backend=='shake': return pub+address+payload
            compressed=address[3:4]+address[8:16]+address[19:20]+address[20:32]
            return pub[:n]+bytes(64-n)+compressed+payload[:n]
        for row, (steps, capture_after, no_seed) in enumerate(((0, 0, 1), (15, 3, 0), (1, 1, 1), (7, 0, 0), (2, 0, 0), (0, 0, 1), (3, 3, 1), (1, 0, 0))):
            a = row+1
            adr = b''.join(map(be, (3, 0, 0x01234567, 0x89abcdef, 0x83, leaf, a, 0)))
            def masked(step, compound):
                return bytes(12)+b''.join(map(be, (0x83, leaf, a, step, compound)))
            initial = bytes((19*row+k) & 255 for k in range(n))
            value = initial
            if not no_seed:
                if family == 0: data = slh_frame(adr,sk)
                elif family == 1: data = be(4, 32)+sk+pub+masked(0, 0)
                else: data = ident+be(leaf)+be(a, 2)+b'\xff'+sk
                value = h(data);hashes += 1
            captured = value if capture_after == 0 else None
            for step in range(steps):
                if family == 0: value = h(slh_frame(adr[:-4]+be(step),value));hashes += 1
                elif family == 1:
                    key, mask = (h(be(3, 32)+pub+masked(step, c)) for c in (0, 1))
                    value = h(bytes(32)+key+bytes(x ^ y for x, y in zip(value, mask)));hashes += 3
                else: value = h(ident+be(leaf)+be(a, 2)+bytes([step])+value);hashes += 1
                if capture_after == step+1: captured = value
            assert captured is not None
            packed = int.from_bytes(captured, 'little') | int.from_bytes(value, 'little') << 256 | int.from_bytes(initial, 'little') << 512 | steps << 768 | capture_after << 773 | no_seed << 778
            rows.append(f'{packed:0195x}\n')
        vector = work/f'family{family}_q{leaf}.mem';vector.write_text(''.join(rows))
        result = subprocess.run([str(obj/'Vtb_pipeline'), f'+VECTOR={vector}', f'+FAMILY={family}', f'+LEAF={leaf}', f'+HASHES={hashes}', f'+PERMUTATIONS={permutations}'], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (work/f'family{family}_q{leaf}.log').write_text(result.stdout)
        print(result.stdout, end='');result.check_returncode()
    (work/'coverage.json').write_text(json.dumps(dict(hash_backend=args.hash_backend, pipeline=args.pipeline, unroll=args.unroll, synthesis=args.synthesis, passed=True, groups=12, active_tags=[0,1,2,3], full_context_occupancy=args.pipeline==4, scope='Four live tags; P>4 does not claim all contexts occupied'),indent=2)+'\n')

if __name__ == '__main__': main()
