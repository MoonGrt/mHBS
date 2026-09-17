#!/usr/bin/env python3
"""Execute and cross-check LMS H10 / LM-OTS W4 Sign and Verify programs."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.interpreter import MicroInterpreter  # noqa: E402
from model.microcode_assembler import load_and_assemble  # noqa: E402
from model.reference.lms import (  # noqa: E402
    RFC8554_TEST2,
    lms_public_key_encoding,
    lms_sign,
    lms_verify,
)


SIGN_PROGRAM = ROOT / "microcode/lms/lms_sign_h10_w4.json"
VERIFY_PROGRAM = ROOT / "microcode/lms/lms_verify_h10_w4.json"
MESSAGE = b"LMS microcode coverage"
LEAF_INDEX = 5
RANDOMIZER = bytes(range(32))


def trace_observer() -> tuple[hashlib._Hash, Counter[str], object]:
    digest = hashlib.sha256()
    counts: Counter[str] = Counter()

    def observe(kind: str, data: bytes, value: bytes) -> None:
        digest.update(
            json.dumps(
                {
                    "hash_class": kind,
                    "hash_input_digest": hashlib.sha256(data).hexdigest(),
                    "hash_output": value.hex(),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        )
        counts[kind] += 1

    return digest, counts, observe


def main() -> int:
    identifier = RFC8554_TEST2["identifier"]
    seed = RFC8554_TEST2["seed"]
    root = RFC8554_TEST2["expected_root"]
    public_key = lms_public_key_encoding(identifier, root)

    sign_digest, sign_counts, sign_observe = trace_observer()
    expected_signature, next_q = lms_sign(
        MESSAGE,
        identifier,
        seed,
        LEAF_INDEX,
        RANDOMIZER,
        observe=sign_observe,
    )
    sign_image = load_and_assemble(SIGN_PROGRAM)
    sign_result = MicroInterpreter(sign_image, trace_mode="none").execute(
        {
            "identifier": identifier,
            "seed": seed,
            "q": LEAF_INDEX,
            "randomizer": RANDOMIZER,
            "message": MESSAGE,
        }
    )

    verify_digest, verify_counts, verify_observe = trace_observer()
    oracle_accepts = lms_verify(
        public_key,
        MESSAGE,
        expected_signature,
        observe=verify_observe,
    )
    verify_image = load_and_assemble(VERIFY_PROGRAM)
    verify_result = MicroInterpreter(verify_image, trace_mode="none").execute(
        {
            "identifier": identifier,
            "signature": expected_signature,
            "message": MESSAGE,
        }
    )
    mutated = bytearray(expected_signature)
    mutated[40] ^= 1
    mutated = bytes(mutated)
    mutated_result = MicroInterpreter(verify_image, trace_mode="none").execute(
        {"identifier": identifier, "signature": mutated, "message": MESSAGE}
    )

    checks = {
        "sign_complete_signature_match": sign_result.output == expected_signature,
        "sign_per_hash_trace_match": sign_result.hash_trace_sha256 == sign_digest.hexdigest(),
        "state_advances_to_q_plus_one": next_q == LEAF_INDEX + 1,
        "oracle_accepts_valid_signature": oracle_accepts,
        "verify_root_match": verify_result.output == root,
        "verify_per_hash_trace_match": verify_result.hash_trace_sha256 == verify_digest.hexdigest(),
        "one_bit_mutation_root_mismatch": mutated_result.output != root,
        "oracle_rejects_one_bit_mutation": not lms_verify(public_key, MESSAGE, mutated),
    }
    report = {
        "profile": "LMS_SHA256_M32_H10/LMOTS_SHA256_N32_W4",
        "signature_bytes": len(expected_signature),
        "sign": {
            "static_words": sign_image["word_count"],
            "static_opcode_types": len({i.opcode for i in sign_image["instructions"]}),
            "hash_class_counts": dict(sorted(sign_counts.items())),
            "hash_trace_sha256": sign_result.hash_trace_sha256,
            "counters": sign_result.counters,
        },
        "verify": {
            "static_words": verify_image["word_count"],
            "static_opcode_types": len({i.opcode for i in verify_image["instructions"]}),
            "hash_class_counts": dict(sorted(verify_counts.items())),
            "hash_trace_sha256": verify_result.hash_trace_sha256,
            "counters": verify_result.counters,
        },
        "checks": checks,
        "status": "PASS" if all(checks.values()) else "FAIL",
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
