#!/usr/bin/env python3
"""Compare scalar fixed/stream recipes with independent hashlib byte frames."""
from hashlib import shake_256
import os
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]

def be(v, n=4):
    return v.to_bytes(n, 'big')

def h(data, n=32):
    return shake_256(data).digest(n)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pipeline',type=int,default=4)
    parser.add_argument('--unroll',type=int,default=1)
    parser.add_argument('--recipe-mask',type=lambda value:int(value,0),default=0xffff,
                        help='Compile-time recipe mask; e.g. 0x101e tests SLH without LMS list support')
    parser.add_argument('--synthesis',action='store_true',help='Verify the RTL view with diagnostic ports removed')
    args=parser.parse_args()
    if not 0 < args.recipe_mask <= 0xffff:
        parser.error('--recipe-mask must be between 1 and 0xffff')
    mask_suffix = '' if args.recipe_mask == 0xffff else f'_mask{args.recipe_mask:04x}'
    work = ROOT / (f'build/recipe_check/P{args.pipeline}U{args.unroll}' + mask_suffix + ('_synthesis' if args.synthesis else ''))
    work.mkdir(parents=True, exist_ok=True)
    sk, prf, pub, root, rand, left, right = [bytes(range(k, k+32)) for k in (1, 33, 65, 97, 129, 161, 193)]
    ident = bytes(range(225, 241))
    message = bytes((17+3*k) & 255 for k in range(87))
    nodes = [bytes((13*j+k) & 255 for k in range(32)) for j in range(136)]
    adr = b''.join(map(be, (3, 0, 0x01234567, 0x89abcdef, 0x83, 513, 67, 0x12345678)))
    def masked(compound, leaf=513):
        return bytes(12)+b''.join(map(be, (0x83, leaf, 67, 0x12345678, compound)))
    def frame(n, shape, arity, length, leaf=513):
        adr = b''.join(map(be, (3, 0, 0x01234567, 0x89abcdef, 0x83, leaf, 67, 0x12345678)))
        fixed, hashes = shape not in (3, 4, 6, 11, 12, 13), 1
        if shape == 1: data = pub[:n]+adr+sk[:n]
        elif shape == 2: data = pub[:n]+adr+left[:n]+(right[:n] if arity == 2 else b'')
        elif shape == 3: data = prf[:n]+rand[:n]+message[:length]
        elif shape == 4: data = rand[:n]+pub[:n]+root[:n]+message[:length]
        elif shape == 5: data = be(3, 32)+prf+be(leaf, 32)
        elif shape == 6: data = be(2, 32)+rand+root+be(leaf, 32)+message[:length]
        elif shape == 7: data = be(4, 32)+sk+pub+masked(0, leaf)
        elif shape == 8:
            key, m0 = h(be(3, 32)+pub+masked(0, leaf)), h(be(3, 32)+pub+masked(1, leaf))
            data = be(arity-1, 32)+key+bytes(a ^ b for a, b in zip(left, m0))
            if arity == 2:
                m1 = h(be(3, 32)+pub+masked(2, leaf))
                data += bytes(a ^ b for a, b in zip(right, m1))
            hashes = arity+2
        elif shape == 9: data = ident+be(leaf)+be(67, 2)+b'\xff'+sk
        elif shape == 10: data = ident+be(leaf)+be(67, 2)+b'\x78'+left
        elif shape == 11: data = ident+be(leaf)+b'\x81\x81'+rand+message[:length]
        elif shape == 12: data = pub[:n]+adr+b''.join(v[:n] for v in nodes[:arity])
        elif shape == 13: data = ident+be(leaf)+b'\x80\x80'+b''.join(nodes[:arity])
        elif shape == 14: data = ident+be(0x12345678)+b'\x82\x82'+left
        elif shape == 15: data = ident+be(0x12345678)+b'\x83\x83'+left+right
        else: raise ValueError(shape)
        result = h(data, 32)+bytes(17) if fixed else h(data, 49)
        perms = hashes if fixed else len(data)//136+1
        return result, hashes, perms, len(data)
    cases = []
    for n in (16, 24, 32):
        for shape in (1, 2):
            for arity in ((1, 2) if shape == 2 else (1,)):
                cases.append((n, shape, arity, 1))
        for shape in (3, 4):
            for length in (1, 7, 8, 15, 16, 17, 39, 40, 41, 63, 64, 65, 71, 72, 73, 81, 82, 83, 87):
                cases.append((n, shape, 1, length))
        for arity in (1, 2, 3, 4, 5, 7, 8, 9, 17, 33, 51, 67, 101, 133):
            cases.append((n, 12, arity, 1))
    for shape in (5, 7, 8, 9, 10, 14, 15):
        for arity in ((1, 2) if shape == 8 else (2,) if shape == 15 else (1,)):
            cases.append((32, shape, arity, 1))
    for shape in (6, 11):
        cases.extend((32, shape, 1, length) for length in range(1, 88))
    cases.extend((32, 13, arity, 1) for arity in (1, 2, 3, 4, 5, 7, 8, 9, 17, 33, 51, 67, 101, 133))
    cases=[(*c,513) for c in cases]
    for leaf in (1023,1024,32767,32768,65535,65536,1048575):
        cases.extend((32,shape,arity,1,leaf) for shape in (1,2,5,6,7,8,9,10,11,13,14,15)
                     for arity in ((1,2) if shape in (2,8) else (2,) if shape==15 else (67,) if shape==13 else (1,)))
    cases = [case for case in cases if args.recipe_mask & (1 << case[1])]
    if not cases:
        parser.error('--recipe-mask enables no tested recipe')
    values = []
    coverage = {'cases':len(cases),'pipeline':args.pipeline,'unroll':args.unroll,
                'recipe_mask':f'0x{args.recipe_mask:04x}','synthesis':args.synthesis,
                'frame_lengths':{},'shapes':{},'rate_boundary_cases':{}}
    for n, shape, arity, length, leaf in cases:
        result, hashes, perms, frame_length = frame(n, shape, arity, length, leaf)
        for key,value in (('frame_lengths',frame_length),('shapes',shape)):
            coverage[key][value] = coverage[key].get(value,0)+1
        if frame_length in (135,136,137):
            coverage['rate_boundary_cases'][frame_length] = coverage['rate_boundary_cases'].get(frame_length,0)+1
        value = int.from_bytes(result, 'little') | n << 392 | length << 398 | shape << 405 | arity << 409 | hashes << 417 | perms << 421 | leaf << 432
        values.append(f'{value:0113x}\n')
    vector = work / 'recipes.mem'
    vector.write_text(''.join(values))
    obj = work / 'obj'
    cmd = [os.environ.get('VERILATOR', 'verilator'), '--binary', '--timing', '-O3', '-j', '2', '-Wno-fatal', '--top-module', 'tb_recipe', f'-GPIPELINE={args.pipeline}', f'-GUNROLL={args.unroll}', f'-GRECIPE_MASK={args.recipe_mask}', '--Mdir', str(obj), 'rtl/hash/keccak.sv', 'rtl/hash/pipeline.sv', 'rtl/hash/recipe.sv', 'tb/tb_recipe.sv']
    if args.synthesis: cmd.append('-DSYNTHESIS')
    with (work / 'compile.log').open('w') as log:
        subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    result = subprocess.run([str(obj / 'Vtb_recipe'), f'+VECTOR={vector}', f'+COUNT={len(cases)}'], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (work / 'run.log').write_text(result.stdout)
    print(result.stdout, end='')
    result.check_returncode()
    coverage['passed'] = True
    (work / 'coverage.json').write_text(json.dumps(coverage,indent=2)+'\n')

if __name__ == '__main__':
    main()
