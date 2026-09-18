#!/usr/bin/env python3
"""Build deterministic multi-message vectors for the static microcode RTL."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.interpreter import MicroInterpreter  # noqa: E402
from model.microcode_assembler import load_and_assemble  # noqa: E402


def derived(label: str, length: int) -> bytes:
    output = b""
    counter = 0
    while len(output) < length:
        output += hashlib.sha256(
            f"micro-hbs-static:{label}:{counter}".encode("ascii")
        ).digest()
        counter += 1
    return output[:length]


def le_hex(value: bytes, width: int | None = None) -> str:
    if width is not None:
        value = value + bytes(width - len(value))
    return f"{int.from_bytes(value, 'little'):0{len(value)*2}x}"


def main() -> None:
    output_dir = ROOT / "build/static_microcode_vectors"
    output_dir.mkdir(parents=True, exist_ok=True)
    image = load_and_assemble(
        ROOT / "microcode/slh_dsa/slh_dsa_shake_128f_sign.json")
    lengths = (1, 8, 31, 64, 87)
    jobs: list[dict[str, bytes]] = []
    signatures: list[bytes] = []
    permutations: list[int] = []
    for index, length in enumerate(lengths):
        job = {
            "sk_seed": derived(f"{index}:sk-seed", 16),
            "sk_prf": derived(f"{index}:sk-prf", 16),
            "pub_seed": derived(f"{index}:pk-seed", 16),
            "root": derived(f"{index}:pk-root", 16),
            "message": derived(f"{index}:message", length),
        }
        execution = MicroInterpreter(image, trace_mode="none").execute(job)
        if not execution.done or execution.error is not None:
            raise RuntimeError(f"reference failed for message length {length}")
        jobs.append(job)
        signatures.append(execution.output)
        permutations.append(execution.counters["keccak_permutations"])

    def write(name: str, rows: list[str]) -> None:
        (output_dir / name).write_text("\n".join(rows) + "\n",
                                      encoding="ascii")

    write("lengths.mem", [f"{length:02x}" for length in lengths])
    for field in ("sk_seed", "sk_prf", "pub_seed", "root"):
        write(f"{field}.mem", [le_hex(job[field]) for job in jobs])
    write("message.mem", [le_hex(job["message"], 87) for job in jobs])
    write("signature.mem", [
        le_hex(signature[offset:offset + 8])
        for signature in signatures
        for offset in range(0, len(signature), 8)
    ])
    write("permutations.mem", [f"{value:08x}" for value in permutations])
    print("generated", len(jobs), "static-microcode message vectors",
          "permutations", permutations)


if __name__ == "__main__":
    main()
