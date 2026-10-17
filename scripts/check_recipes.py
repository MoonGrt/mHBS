#!/usr/bin/env python3
"""Check the single-request SHAKE lanes against independent hashlib vectors."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ["rtl/hash/keccak.sv",        "rtl/hash/shake-recipe.sv", "tb/tb_recipe.sv"]


def cases(mask: int) -> list[int]:
    rows = []
    message = bytes((i * 3 + 1) & 255 for i in range(87))
    data = [bytes(range(base, base + 32)) for base in range(0, 224, 32)]
    secret, prf, public, randomizer, root, left, right = data

    def add(n: int, shape: int, arity: int = 1, length: int = 0, domain: int = 3):
        address = b"".join(v.to_bytes(4, "big") for v in
                           [9, 0, 0xfedcba98, 0x76543210, domain, 341, 37, 0x89abcdef])
        error = (shape not in (1, 2, 3, 4, 12) or not mask & (1 << shape)
                 or n not in (16, 24, 32) or (shape == 2 and arity not in (1, 2))
                 or (shape == 12 and not 1 <= arity <= 128)
                 or (shape in (3, 4) and length > 87))
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
            else:
                nodes = [bytes((i * 29 + j * 7 + 3) & 255 for j in range(n)) for i in range(arity)]
                frame = public[:n] + address + b"".join(nodes)
            permutations = len(frame) // 136 + 1
            expected = int.from_bytes(hashlib.shake_256(frame).digest(49), "little")
        rows.append((n << 442) | (shape << 438) | (arity << 430) | (domain << 422)
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
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unroll", type=int, nargs="+", default=[1, 2, 4])
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="mhbs-single-hash-") as directory:
        build = Path(directory)
        for mask in (0x101e, 0x0006):
            vectors = cases(mask)
            vector_file = build / f"vectors_{mask:04x}.mem"
            vector_file.write_text("".join(f"{row:0112x}\n" for row in vectors))
            for unroll in args.unroll:
                exe = build / f"lane_{mask:04x}_u{unroll}.vvp"
                subprocess.run(["iverilog", "-g2012", "-s", "tb_recipe",
                                f"-Ptb_recipe.UNROLL={unroll}",
                                f"-Ptb_recipe.MASK={mask}", "-o", str(exe),
                                *SOURCES], cwd=ROOT, check=True)
                subprocess.run(["vvp", str(exe), f"+VECTORS={vector_file}", f"+COUNT={len(vectors)}"],
                               cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
