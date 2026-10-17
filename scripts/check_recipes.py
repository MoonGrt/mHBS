#!/usr/bin/env python3
"""Check the single-request SHAKE lanes against independent hashlib vectors."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ["rtl/hash/keccak.sv", "rtl/hash/shake-recipe.sv", "tb/tb_recipe.sv"]


def cases(mask: int) -> list[int]:
    rows = []
    message = bytes((i * 3 + 1) & 255 for i in range(87))
    data = [bytes(range(base, base + 32)) for base in range(0, 224, 32)]
    secret, prf, public, randomizer, root, left, right = data

    identifier = bytes(range(0, 256, 16))
    runtime_index = 0xabcde

    def add(n: int, shape: int, arity: int = 1, length: int = 0, domain: int = 3,
            address_type: int = 0, leaf: int | None = None, a: int = 37,
            b: int = 0x89abcdef, index: int = runtime_index):
        if leaf is None:
            leaf = 0xabcde if 5 <= shape <= 15 and shape != 12 else 341
        address = b"".join(v.to_bytes(4, "big") for v in
                           [9, 0, 0xfedcba98, 0x76543210, domain, leaf, a, b])
        standard = 5 <= shape <= 15 and shape != 12
        error = (shape == 0 or not mask & (1 << shape)
                 or n not in (16, 24, 32) or (shape == 2 and arity not in (1, 2))
                 or (shape == 12 and not 1 <= arity <= 128)
                 or (shape in (3, 4, 8, 11) and length > 87)
                 or (standard and n != 32)
                 or (shape == 5 and (domain > 4 or arity != 1 or address_type > 2))
                 or (shape in (6, 8, 9, 10, 11, 13) and (domain != 0 or arity != 1))
                 or (shape in (7, 14) and (domain != 0 or arity != 2))
                 or (shape == 15 and (domain != 0 or arity != 67)))
        permutations, expected = 0, 0
        if not error:
            if shape == 1:
                frame = public[:n] + address + secret[:n]
            elif shape == 2:
                frame = public[:n] + address + left[:n] + (right[:n] if arity == 2 else b"")
            elif shape == 3:
                frame = prf[:n] + randomizer[:n] + message[:length]
            elif shape == 4:
                frame = randomizer[:n] + public[:n] + root[:n] + message[:length]
            elif shape == 12:
                nodes = [bytes((i * 29 + j * 7 + 3) & 255 for j in range(n)) for i in range(arity)]
                frame = public[:n] + address + b"".join(nodes)
            elif shape == 5:
                # NIST SP 800-208 sections 5.3 and 6.2, not the older
                # RFC8391 optional secret-generation construction.
                xmss_address = b"".join(v.to_bytes(4, "big") for v in
                    [9, 0xfedcba98, 0x76543210, address_type,
                     0 if address_type == 2 else leaf, a, b,
                     domain - 2 if domain >= 2 else 0])
                if domain == 0:
                    frame = (4).to_bytes(32, "big") + secret + public + xmss_address
                elif domain == 1:
                    frame = (3).to_bytes(32, "big") + prf + index.to_bytes(32, "big")
                else:
                    frame = (3).to_bytes(32, "big") + public + xmss_address
            elif shape == 6:
                frame = (0).to_bytes(32, "big") + prf + left
            elif shape == 7:
                frame = (1).to_bytes(32, "big") + prf + left + right
            elif shape == 8:
                frame = (2).to_bytes(32, "big") + randomizer + root + index.to_bytes(32, "big") + message[:length]
            elif shape in (9, 10):
                frame = (identifier + leaf.to_bytes(4, "big") + a.to_bytes(2, "big")
                         + bytes([255 if shape == 9 else b & 255]) + (secret if shape == 9 else left))
            elif shape == 11:
                frame = identifier + index.to_bytes(4, "big") + b"\x81\x81" + randomizer + message[:length]
            elif shape in (13, 14):
                frame = identifier + b.to_bytes(4, "big") + (b"\x82\x82" if shape == 13 else b"\x83\x83") + left
                if shape == 14:
                    frame += right
            elif shape == 15:
                nodes = [bytes((i * 29 + j * 7 + 3) & 255 for j in range(32)) for i in range(67)]
                frame = identifier + leaf.to_bytes(4, "big") + b"\x80\x80" + b"".join(nodes)
            permutations = len(frame) // 136 + 1
            expected = int.from_bytes(hashlib.shake_256(frame).digest(49), "little")
        rows.append((index << 509) | (leaf << 489) | (a << 482) | (b << 450)
                    | (address_type << 448) | (n << 442) | (shape << 438) | (arity << 430) | (domain << 422)
                    | (length << 415) | (permutations << 407) | (int(error) << 406) | expected)

    for n in (32, 16, 24):
        add(n, 1)
        add(n, 2)
        add(n, 2, 2, domain=2)
        for shape in (3, 4):
            for length in (0, 1, 15, 16, 17, 39, 40, 41, 55, 63, 64, 65, 71, 72, 73, 87):
                add(n, shape, length=length)
        for arity in (1, 2, 3, 17, 35, 51, 67, 128):
            add(n, 12, arity, domain=1)
    for shape in (0, 5, 15):
        add(32, shape)
    for n in (0, 8, 33):
        add(n, 1)
    for shape in (3, 4):
        add(32, shape, length=88)
        add(32, shape, length=127)
    add(32, 2, arity=0)
    add(32, 2, arity=3)
    add(32, 12, arity=0)
    add(32, 12, arity=129)
    for address_type in (0, 1, 2):
        for domain in (0, 1, 2, 3, 4):
            add(32, 5, domain=domain, address_type=address_type)
    add(32, 6, domain=0)
    add(32, 7, 2, domain=0)
    for shape in (8, 11):
        for length in (0, 1, 2, 7, 8, 9, 39, 40, 54, 55, 79, 80, 81, 82, 83, 86, 87):
            add(32, shape, length=length, domain=0)
        for length in (88, 127):
            add(32, shape, length=length, domain=0)
    for shape in (9, 10, 13):
        add(32, shape, domain=0)
    add(32, 14, 2, domain=0)
    add(32, 15, 67, domain=0)
    # New-family shape/arity/domain permissions are independent of the
    # processor's own recipe validator and must reject before starting SHAKE.
    for shape in (5, 6, 7, 8, 9, 10, 11, 13, 14, 15):
        add(24, shape, 2 if shape in (7, 14) else 67 if shape == 15 else 1, domain=0)
        add(32, shape, arity=0, domain=0)
    add(32, 5, domain=5)
    add(32, 5, domain=2, address_type=3)
    add(32, 15, 66, domain=0)
    for step in range(16):
        add(32, 10, domain=0, leaf=0xfffff, a=66, b=step)
        add(32, 5, domain=2 + step % 3, leaf=0xfffff, a=66, b=step)
    for q in (0, 1, 1023, 1024, 32767, 32768, 65535, 65536, (1 << 20) - 1, (1 << 20), 0xffffffff):
        add(32, 5, domain=1, index=q)
        add(32, 8, domain=0, index=q, length=87)
        add(32, 11, domain=0, index=q, length=87)
    for leaf in (0, 1, 1023, 1024, 32767, 32768, 65535, 65536, (1 << 20) - 1):
        add(32, 5, domain=0, leaf=leaf)
        add(32, 9, domain=0, leaf=leaf, a=66)
    for heap in (1, 1023, 1024, 32767, 32768, 65535, 65536, (1 << 20) - 1, 1 << 20, (1 << 21) - 1):
        add(32, 13, domain=0, b=heap)
        add(32, 14, 2, domain=0, b=heap)
    return rows


def xmss_chain_oracle() -> list[int]:
    public=bytes(range(64,96));left=bytes(range(160,192))
    values=[]
    for keymask in (0,1):
        adrs=b"".join(v.to_bytes(4,"big") for v in
            (9,0xfedcba98,0x76543210,0,0xabcde,37,0x89abcdef,keymask))
        values.append(hashlib.shake_256((3).to_bytes(32,"big")+public+adrs).digest(49))
    masked=bytes(x^y for x,y in zip(left,values[1][:32]))
    values.append(hashlib.shake_256(bytes(32)+values[0][:32]+masked).digest(49))
    return [int.from_bytes(value,"little") for value in values]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unroll", type=int, nargs="+", default=[1])
    parser.add_argument("--mask", type=lambda x: int(x, 0), nargs="+", default=[0x101e,0x0006,0xfffe])
    parser.add_argument("--profile", type=int, choices=[0,1], nargs="+", default=[1])
    parser.add_argument("--synthesis", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    results=[]
    with tempfile.TemporaryDirectory(prefix="mhbs-single-hash-") as directory:
        build = Path(directory)
        chain_file=build / "xmss_chain.mem"
        chain_file.write_text("".join(f"{row:098x}\n" for row in xmss_chain_oracle()))
        for mask in args.mask:
            vectors = cases(mask)
            vector_file = build / f"vectors_{mask:04x}.mem"
            vector_file.write_text("".join(f"{row:0136x}\n" for row in vectors))
            for unroll in args.unroll:
                for profile in args.profile:
                    exe = build / f"lane_{mask:04x}_u{unroll}_profile{profile}.vvp"
                    subprocess.run(["iverilog", "-g2012", "-s", "tb_recipe",
                                    *(["-DSYNTHESIS"] if args.synthesis else []),
                                    f"-Ptb_recipe.UNROLL={unroll}",
                                    f"-Ptb_recipe.PROFILE={profile}",
                                    f"-Ptb_recipe.MASK={mask}", "-o", str(exe),
                                    *SOURCES], cwd=ROOT, check=True)
                    subprocess.run(["vvp", str(exe), f"+VECTORS={vector_file}", f"+COUNT={len(vectors)}",f"+XMSS_CHAIN={chain_file}"],
                                   cwd=ROOT, check=True)
                    results.append(dict(mask=mask,unroll=unroll,profile=profile,cases=len(vectors),status="passed"))
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(dict(status="passed",synthesis=args.synthesis,results=results),indent=2)+"\n")



if __name__ == "__main__":
    main()
