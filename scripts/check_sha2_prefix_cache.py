#!/usr/bin/env python3
"""Independently check SHA2 SLH raw-prefix reuse and cache lifetime boundaries."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pipeline', type=int, default=4)
    parser.add_argument('--unroll', type=int, default=1)
    parser.add_argument('--synthesis', action='store_true')
    args = parser.parse_args()
    if args.pipeline <= 0 or args.unroll <= 0 or args.pipeline*args.unroll > 24 or 24 % (args.pipeline*args.unroll):
        parser.error('P*U must divide 24')
    work = ROOT/f'build/sha2_prefix_cache/P{args.pipeline}U{args.unroll}'
    if args.synthesis:
        work = work.parent/(work.name+'_synthesis')
    work.mkdir(parents=True, exist_ok=True)
    be = lambda value, size=4: value.to_bytes(size, 'big')
    sk, prf, pub_a, root, rand, left, right = [bytes(range(k, k+32)) for k in (1, 33, 65, 97, 129, 161, 193)]
    pub_b = bytes(value ^ 0xa5 for value in pub_a)
    pub_upper = pub_a[:16]+bytes(value ^ 0x5a for value in pub_a[16:])
    ident = bytes(range(225, 241))
    message = bytes((17+3*k) & 255 for k in range(87))
    nodes = [bytes((13*j+k) & 255 for k in range(32)) for j in range(136)]

    def scalar(shape, arity, length, output, public):
        hashes = blocks = 0
        def h(data):
            nonlocal hashes, blocks
            hashes += 1
            blocks += (len(data)+72)//64
            return hashlib.sha256(data).digest()
        address = b''.join(be(x) for x in (3, 0, 0x01234567, 0x89abcdef, 0x83, 65536, 67, 0x12345678))
        compressed = address[3:4]+address[8:16]+address[19:20]+address[20:32]
        prefix = public[:16]+bytes(48)
        def masked(compound):
            return bytes(12)+b''.join(be(x) for x in (0x83, 65536, 67, 0x12345678, compound))
        if shape == 1:
            result = h(prefix+compressed+sk[:16])
        elif shape == 2:
            result = h(prefix+compressed+left[:16]+(right[:16] if arity == 2 else b''))
        elif shape == 3:
            key = prf[:16]+bytes(48)
            inner = h(bytes(x ^ 0x36 for x in key)+rand[:16]+message[:length])
            result = h(bytes(x ^ 0x5c for x in key)+inner)
        elif shape == 4:
            inner = h(rand[:16]+public[:16]+root[:16]+message[:length])
            result = b''.join(h(rand[:16]+public[:16]+inner+be(i)) for i in range((output+31)//32))
        elif shape == 5:
            result = h(be(3, 32)+prf+be(65536,32))
        elif shape == 7:
            result = h(be(4, 32)+sk+public+masked(0))
        elif shape == 8:
            key, mask0, mask1 = (h(be(3, 32)+public+masked(i)) for i in range(3))
            result = h(be(1, 32)+key+bytes(x ^ y for x, y in zip(left, mask0))+bytes(x ^ y for x, y in zip(right, mask1)))
        elif shape == 9:
            result = h(ident+be(65536)+be(67, 2)+b'\xff'+sk)
        elif shape == 10:
            result = h(ident+be(65536)+be(67, 2)+b'\x78'+left)
        elif shape == 12:
            result = h(prefix+compressed+b''.join(x[:16] for x in nodes[:arity]))
        elif shape == 13:
            result = h(ident+be(65536)+b'\x80\x80'+b''.join(nodes[:arity]))
        else:
            raise ValueError(shape)
        return result[:output].ljust(49, b'\0'), hashes, blocks

    # Each row specifies the expected cold-fill count independently of RTL
    # cache signals. The cancel row resets an accepted, in-flight prefix.
    specs = [
        (1, 1, 1, 16, pub_a, 1, 1, 0),
        (1, 1, 1, 16, pub_a, 0, 0, 0),
        (2, 1, 1, 16, pub_a, 0, 0, 0),
        (2, 2, 1, 16, pub_a, 0, 0, 0),
        (12, 67, 1, 16, pub_a, 0, 0, 0),
        (3, 1, 56, 16, pub_a, 0, 0, 0),
        (4, 1, 87, 34, pub_a, 0, 0, 0),
        (7, 1, 1, 32, pub_a, 0, 0, 0),
        (8, 2, 1, 32, pub_a, 0, 0, 0),
        (9, 1, 1, 32, pub_a, 0, 0, 0),
        (10, 1, 1, 32, pub_a, 0, 0, 0),
        (13, 67, 1, 32, pub_a, 0, 0, 0),
        (1, 1, 1, 16, pub_a, 0, 0, 0),
        (1, 1, 1, 16, pub_b, 1, 0, 0),
        (2, 2, 1, 16, pub_b, 0, 0, 0),
        (1, 1, 1, 16, pub_a, 1, 0, 0),
        (1, 1, 1, 16, pub_a, 1, 1, 1),
        (2, 2, 1, 16, pub_a, 0, 0, 0),
        # SLH ignores the upper half of PK.seed; XMSS consumes all 32 bytes.
        (2, 2, 1, 16, pub_upper, 0, 0, 0),
        (8, 2, 1, 32, pub_upper, 0, 0, 0),
        (8, 2, 1, 32, pub_upper, 0, 0, 0),
        (8, 2, 1, 32, pub_a, 0, 0, 0),
        (5, 1, 1, 32, pub_a, 0, 0, 0),
        (7, 1, 1, 32, pub_a, 0, 0, 0),
        (8, 2, 1, 32, pub_a, 0, 0, 0),
        (8, 2, 1, 32, pub_a, 0, 1, 1),
        (8, 2, 1, 32, pub_a, 0, 0, 0),
        (1, 1, 1, 16, pub_a, 0, 0, 0),
        (1, 1, 1, 16, pub_a, 0, 0, 0),
    ]
    scalar_rows, scalar_counts = [], []
    cached_prefix = None
    for shape, arity, length, output, public, misses, reset, cancel in specs:
        result, hashes, blocks = scalar(shape, arity, length, output, public)
        if reset or cancel:
            cached_prefix = None
        prefix_hashes = arity+1 if shape == 8 else int(shape in (1, 2, 12))
        prefix = be(3,32)+public if shape == 8 else public[:16]+bytes(48)
        misses = int(bool(prefix_hashes) and cached_prefix != prefix)
        if prefix_hashes:
            cached_prefix = prefix
        value = int.from_bytes(result, 'little') | int.from_bytes(public, 'little') << 392
        value |= int.from_bytes(left, 'little') << 648 | int.from_bytes(right, 'little') << 904
        value |= shape << 1160 | arity << 1164 | length << 1172 | output << 1179
        value |= hashes << 1185 | blocks << 1193 | prefix_hashes << 1201 | misses << 1209
        value |= reset << 1217 | cancel << 1218
        scalar_rows.append(f'{value:0305x}\n')
        scalar_counts.append(dict(shape=shape, hashes=hashes, logical_blocks=blocks,
                                  physical_blocks=blocks-prefix_hashes+misses, prefix_fills=misses,
                                  reset=bool(reset), cancel_and_replay=bool(cancel)))
    (work/'scalar.mem').write_text(''.join(scalar_rows))

    batch_rows, batch_counts = [], []
    for group, (family, public) in enumerate(((0, pub_a), (0, pub_a), (0, pub_b), (1, pub_b), (2, pub_b), (0, pub_b))):
        group_hashes = group_blocks = 0
        for tag in range(args.pipeline):
            steps = 1+tag % 4
            capture_after = steps//2
            hashes = blocks = 0
            def h(data):
                nonlocal hashes, blocks
                hashes += 1
                blocks += (len(data)+72)//64
                return hashlib.sha256(data).digest()[:16] if family == 0 else hashlib.sha256(data).digest()
            def address(step):
                return b''.join(be(x) for x in (3, 0, 0x01234567, 0x89abcdef, 0x83, 65536, tag+1, step))
            def slh(data, step):
                a = address(step)
                return public[:16]+bytes(48)+a[3:4]+a[8:16]+a[19:20]+a[20:32]+data[:16]
            def masked(step, compound):
                return bytes(12)+b''.join(be(x) for x in (0x83, 65536, tag+1, step, compound))
            if family == 0:
                value = h(slh(sk, 0))
            elif family == 1:
                value = h(be(4, 32)+sk+public+masked(0, 0))
            else:
                value = h(ident+be(65536)+be(tag+1, 2)+b'\xff'+sk)
            captured = value if capture_after == 0 else None
            for step in range(steps):
                if family == 0:
                    value = h(slh(value, step))
                elif family == 1:
                    key, mask = (h(be(3, 32)+public+masked(step, c)) for c in (0, 1))
                    value = h(bytes(32)+key+bytes(x ^ y for x, y in zip(value, mask)))
                else:
                    value = h(ident+be(65536)+be(tag+1, 2)+bytes([step])+value)
                if capture_after == step+1:
                    captured = value
            packed = int.from_bytes(captured, 'little') | int.from_bytes(value, 'little') << 256
            packed |= steps << 768 | capture_after << 773 | hashes << 778 | blocks << 794
            batch_rows.append(f'{packed:0203x}\n')
            group_hashes += hashes
            group_blocks += blocks
        fills = int(group in (0, 2, 3, 5))
        eligible_hashes = group_hashes if family == 0 else 2*sum(1+tag % 4 for tag in range(args.pipeline)) if family == 1 else 0
        batch_counts.append(dict(family=family, hashes=group_hashes, logical_blocks=group_blocks,
            physical_blocks=group_blocks-eligible_hashes+fills, prefix_fills=fills))
    (work/'batch.mem').write_text(''.join(batch_rows))
    obj = work/'obj'
    command = [os.environ.get('VERILATOR', 'verilator'), '--binary', '--timing', '-O3', '-j', '2', '-Wno-fatal',
               '-DMHBS_SHA2', '--top-module', 'tb_sha2_prefix_cache', f'-GPIPELINE={args.pipeline}', f'-GUNROLL={args.unroll}',
               '--Mdir', str(obj), 'rtl/hash/sha256.sv', 'rtl/hash/sha2-recipe.sv', 'tb/tb_sha2_prefix_cache.sv']
    if args.synthesis:
        command.append('-DSYNTHESIS')
    with (work/'compile.log').open('w') as log:
        subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    result = subprocess.run([str(obj/'Vtb_sha2_prefix_cache'), f'+SCALAR={work}/scalar.mem', f'+BATCH={work}/batch.mem',
                             f'+COUNT={len(specs)}'], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (work/'run.log').write_text(result.stdout)
    print(result.stdout, end='')
    result.check_returncode()
    (work/'coverage.json').write_text(json.dumps(dict(passed=True, pipeline=args.pipeline, unroll=args.unroll,
        synthesis=args.synthesis, scalar_cases=len(specs), batch_groups=6, contexts_per_group=args.pipeline,
        scalar_counts=scalar_counts, batch_counts=batch_counts,
        oracle='hashlib full-message SHA256; independently counted accepted prefix blocks',
        cases=['cold fill', 'warm reuse', 'seed change and restore', 'reset of in-flight compression',
               'held scalar and batch responses', 'concurrent cold fill', 'all context tags',
               'XMSS masked pair', 'XMSS warm and changed 32-byte seed',
               'shared prefix kind replacement', 'SLH ignores upper seed half',
               'uncached index and keygen PRF preservation', 'LMS 34-block list',
               'SLH 67-node list', 'HMAC and MGF1']), indent=2)+'\n')


if __name__ == '__main__':
    main()
