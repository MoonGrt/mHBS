#!/usr/bin/env python3
"""Report static ISA usage for all supported algorithm operations."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.microcode_assembler import load_and_assemble  # noqa: E402
from model.microcode_assembler.isa import Opcode  # noqa: E402


PROGRAMS = {
    "lms.keygen": ROOT / "microcode/lms/lms_public_h10_w4.json",
    "lms.sign": ROOT / "microcode/lms/lms_sign_h10_w4.json",
    "lms.verify": ROOT / "microcode/lms/lms_verify_h10_w4.json",
    "xmss.keygen": ROOT / "microcode/xmss/xmss_shake256_h10_w4_keygen.json",
    "xmss.sign": ROOT / "microcode/xmss/xmss_shake256_h10_w4_sign.json",
    "xmss.verify": ROOT / "microcode/xmss/xmss_shake256_h10_w4_verify.json",
    "slh_dsa.keygen": ROOT / "microcode/slh_dsa/slh_dsa_shake_128f_keygen.json",
    "slh_dsa.sign": ROOT / "microcode/slh_dsa/slh_dsa_shake_128f_sign.json",
    "slh_dsa.verify": ROOT / "microcode/slh_dsa/slh_dsa_shake_128f_verify.json",
}


DESCRIPTIONS = {
    "SET_REG": "write an immediate value to a register",
    "ADD_IMM": "add an immediate value to a register",
    "HASH": "execute a statically described Hash layout",
    "LOOP_BEGIN": "enter a static or scratch-bounded loop",
    "LOOP_END": "advance or exit the active loop",
    "CALL": "call a microcode subroutine",
    "RETURN": "return from a microcode subroutine",
    "DATA_LOAD": "execute a static data-load or transform descriptor",
    "DATA_MOVE": "copy a scratch value using a static move descriptor",
    "TREE_PUSH": "push a leaf and perform ready TreeHash reductions",
    "OUTPUT": "append one scratch value to the result stream",
    "HALT": "complete the Job successfully",
}


def build_report() -> dict[str, Any]:
    programs: dict[str, Any] = {}
    matrix = {opcode.name: {} for opcode in Opcode}
    for operation, path in PROGRAMS.items():
        image = load_and_assemble(path)
        counts = Counter(inst.opcode.name for inst in image["instructions"])
        programs[operation] = {
            "source": str(path.relative_to(ROOT)),
            "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "program_sha256": image["sha256"],
            "static_words": image["word_count"],
            "opcode_type_count": len(counts),
            "opcode_counts": dict(sorted(counts.items())),
        }
        for opcode in Opcode:
            matrix[opcode.name][operation] = counts.get(opcode.name, 0)
    return {
        "schema_version": 1,
        "result_id": "microcode_isa_usage_v0.2.0",
        "isa_opcode_count": len(Opcode),
        "isa": [
            {
                "name": opcode.name,
                "encoding": int(opcode),
                "description": DESCRIPTIONS[opcode.name],
            }
            for opcode in Opcode
        ],
        "programs": programs,
        "static_usage_matrix": matrix,
        "status": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    encoded = json.dumps(build_report(), indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
