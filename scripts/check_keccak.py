#!/usr/bin/env python3
"""Check both RTL mappings against an independent lane-array Keccak round."""
import os
from pathlib import Path
import random
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MASK = (1 << 64) - 1
RHO = (0, 1, 62, 28, 27, 36, 44, 6, 55, 20, 3, 10, 43, 25, 39,
       41, 45, 15, 21, 8, 18, 2, 61, 56, 14)
RC = (0x1, 0x8082, 0x800000000000808A, 0x8000000080008000,
      0x808B, 0x80000001, 0x8000000080008081, 0x8000000000008009,
      0x8A, 0x88, 0x80008009, 0x8000000A, 0x8000808B,
      0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
      0x8000000000008002, 0x8000000000000080, 0x800A,
      0x800000008000000A, 0x8000000080008081, 0x8000000000008080,
      0x80000001, 0x8000000080008008)


def rotate(v, shift):
    return ((v << shift) | (v >> ((64 - shift) % 64))) & MASK


def round_reference(state, index):
    lanes = [(state >> (64 * i)) & MASK for i in range(25)]
    parity = [lanes[x] ^ lanes[x+5] ^ lanes[x+10] ^ lanes[x+15]
              ^ lanes[x+20] for x in range(5)]
    delta = [parity[(x-1) % 5] ^ rotate(parity[(x+1) % 5], 1)
             for x in range(5)]
    permuted = [0] * 25
    for y in range(5):
        for x in range(5):
            i = x + 5*y
            permuted[y + 5*((2*x + 3*y) % 5)] = rotate(lanes[i] ^ delta[x], RHO[i])
    output = []
    for y in range(5):
        for x in range(5):
            output.append(permuted[x+5*y]
                          ^ ((~permuted[(x+1) % 5+5*y]) & permuted[(x+2) % 5+5*y]))
    output[0] ^= RC[index]
    return sum(v << (64*i) for i, v in enumerate(output))


def main():
    work = ROOT / "build" / "keccak_check"
    work.mkdir(parents=True, exist_ok=True)
    init = 0x6666966996696666
    for inputs in range(64):
        b = [(inputs >> i) & 1 for i in range(6)]
        expected = (b[0] ^ b[1]) ^ ((1 ^ (b[2] ^ b[3])) & (b[4] ^ b[5]))
        assert ((init >> inputs) & 1) == expected
    rng = random.Random(20261013)
    states = [0, (1 << 1600)-1] + [rng.getrandbits(1600) for _ in range(32)]
    vectors = [((r << 3200) | (s << 1600) | round_reference(s, r))
               for r in range(24) for s in states]
    vector_file = work / "rounds.mem"
    vector_file.write_text("".join(f"{v:0802x}\n" for v in vectors))
    for mapping in ("generic", "lut6"):
        obj = work / mapping
        command = [os.environ.get("VERILATOR", "verilator"), "--binary", "--timing",
                   "-O3", "-j", "2", "-Wno-fatal", "--top-module", "tb_keccak",
                   "--Mdir", str(obj)]
        if mapping == "lut6":
            command.append("+define+MHBS_XILINX_LUT6")
        command += ["rtl/hash/keccak.sv", "tb/tb_keccak.sv"]
        with (work / f"{mapping}_compile.log").open("w") as log:
            subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        result = subprocess.run([str(obj / "Vtb_keccak"), f"+VECTOR={vector_file}",
                                 f"+COUNT={len(vectors)}"], cwd=ROOT, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)
        (work / f"{mapping}.log").write_text(result.stdout)
        print(f"{mapping}: {result.stdout.splitlines()[0]}")
    print("LUT6 truth table: 64/64 inputs passed")


if __name__ == "__main__":
    main()
