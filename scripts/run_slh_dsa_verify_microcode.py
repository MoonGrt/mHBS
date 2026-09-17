#!/usr/bin/env python3
"""Execute one autonomous FIPS 205 SHAKE-128f Verify microprogram Job."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.interpreter import MicroInterpreter  # noqa: E402
from model.microcode_assembler import load_and_assemble  # noqa: E402
from model.reference.slh_dsa import (  # noqa: E402
    SLH_DSA_SHAKE_128F,
    sign_internal,
    verify_internal,
)


PROGRAM = ROOT / "microcode/slh_dsa/slh_dsa_shake_128f_verify.json"
KAT = ROOT / "tests/kat/slh_dsa_shake_128f_siggen_acvp_tc137.json"


def build_verify_job(
    public_key: bytes, message: bytes, signature: bytes
) -> dict[str, Any]:
    if len(public_key) != 32 or len(signature) != 17088:
        raise ValueError("SLH-DSA-SHAKE-128f Verify input length mismatch")
    return {
        "signature": signature,
        "pub_seed": public_key[:16],
        "public_root": public_key[16:],
        "message": message,
    }


def load_kat_inputs() -> tuple[dict[str, Any], bytes, bytes, bytes]:
    vector = json.loads(KAT.read_text(encoding="utf-8"))
    secret_key = bytes.fromhex(vector["sk"])
    public_key = bytes.fromhex(vector["pk"])
    message = bytes.fromhex(vector["message"])
    signature = sign_internal(SLH_DSA_SHAKE_128F, message, secret_key)
    if hashlib.sha256(signature).hexdigest() != vector["signature_sha256"]:
        raise AssertionError("materialized ACVP signature digest mismatch")
    return vector, public_key, message, signature


def oracle_trace(
    public_key: bytes, message: bytes, signature: bytes
) -> tuple[bool, str, dict[str, int]]:
    digest = hashlib.sha256()
    counts: Counter[str] = Counter()

    def observe(kind: str, data: bytes, value: bytes) -> None:
        record = {
            "hash_class": kind,
            "hash_input_digest": hashlib.sha256(data).hexdigest(),
            "hash_output": value.hex(),
        }
        digest.update(
            json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
        )
        counts[kind] += 1

    accepted = verify_internal(
        SLH_DSA_SHAKE_128F,
        message,
        signature,
        public_key,
        observe=observe,
    )
    return accepted, digest.hexdigest(), dict(sorted(counts.items()))


def main() -> int:
    image = load_and_assemble(PROGRAM)
    _vector, public_key, message, signature = load_kat_inputs()
    result = MicroInterpreter(image, trace_mode="none").execute(
        build_verify_job(public_key, message, signature)
    )
    oracle_accepts, oracle_digest, class_counts = oracle_trace(
        public_key, message, signature
    )

    mutated = bytearray(signature)
    mutated[16] ^= 1
    mutated = bytes(mutated)
    mutated_result = MicroInterpreter(image, trace_mode="none").execute(
        build_verify_job(public_key, message, mutated)
    )
    checks = {
        "valid_root_match": result.output == public_key[16:],
        "oracle_accepts_valid_signature": oracle_accepts,
        "per_hash_trace_match": result.hash_trace_sha256 == oracle_digest,
        "one_job": result.counters["accepted_job_commands"] == 1,
        "zero_busy_host_writes": result.counters["host_control_writes_during_busy"] == 0,
        "zero_external_task_descriptors": result.counters["external_task_descriptors"] == 0,
        "zero_external_hash_descriptors": result.counters["external_hash_descriptors"] == 0,
        "mutated_job_completed": mutated_result.done and mutated_result.error is None,
        "one_bit_mutation_root_mismatch": mutated_result.output != public_key[16:],
        "oracle_rejects_one_bit_mutation": not verify_internal(
            SLH_DSA_SHAKE_128F, message, mutated, public_key
        ),
    }
    record = {
        "program": image["name"],
        "program_sha256": image["sha256"],
        "static_words": image["word_count"],
        "static_bytes": image["image_bytes"],
        "static_opcode_types": len({i.opcode for i in image["instructions"]}),
        "done": result.done,
        "error": result.error,
        "computed_root": result.output.hex(),
        "public_root": public_key[16:].hex(),
        "mutated_computed_root": mutated_result.output.hex(),
        "hash_trace_sha256": result.hash_trace_sha256,
        "oracle_hash_trace_sha256": oracle_digest,
        "hash_class_counts": class_counts,
        "counters": result.counters,
        "checks": checks,
        "status": "PASS" if result.done and all(checks.values()) else "FAIL",
    }
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0 if record["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
