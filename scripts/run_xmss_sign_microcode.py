#!/usr/bin/env python3
"""Execute one autonomous XMSS-SHAKE256 H10 Sign microprogram Job."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.interpreter import MicroInterpreter  # noqa: E402
from model.microcode_assembler import load_and_assemble  # noqa: E402
from model.reference.xmss import xmss_sign, xmss_verify  # noqa: E402


PROGRAM = ROOT / "microcode" / "xmss" / "xmss_shake256_h10_w4_sign.json"
KAT = ROOT / "tests" / "kat" / "xmss_shake256_10_256_idx5.json"


def main() -> int:
    image = load_and_assemble(PROGRAM)
    vector = json.loads(KAT.read_text(encoding="utf-8"))
    seed = bytes.fromhex(vector["seed"])
    root = bytes.fromhex(vector["public_key"])[:32]
    message = bytes.fromhex(vector["message"])
    index = int(vector["signing_index"])
    job = {
        "index": index,
        "sk_seed": seed[:32],
        "sk_prf": seed[32:64],
        "pub_seed": seed[64:],
        "root": root,
        "message": message,
    }
    result = MicroInterpreter(image, trace_mode="none").execute(job)

    oracle_digest = hashlib.sha256()
    class_counts: dict[str, int] = {}

    def observe(kind: str, data: bytes, value: bytes) -> None:
        record = {
            "hash_class": kind,
            "hash_input_digest": hashlib.sha256(data).hexdigest(),
            "hash_output": value.hex(),
        }
        oracle_digest.update(
            json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
        )
        class_counts[kind] = class_counts.get(kind, 0) + 1

    secret_key = (
        index.to_bytes(4, "big") + seed[:32] + seed[32:64] + root + seed[64:]
    )
    oracle_signature, _ = xmss_sign(secret_key, message, observe=observe)
    signature_digest = hashlib.sha256(result.output).hexdigest()
    checks = {
        "complete_signature_match": result.output == oracle_signature,
        "official_reference_digest_match": signature_digest == vector["signature_sha256"],
        "per_hash_trace_match": result.hash_trace_sha256 == oracle_digest.hexdigest(),
        "signature_verifies": xmss_verify(bytes.fromhex(vector["public_key"]), message, result.output),
        "one_job": result.counters["accepted_job_commands"] == 1,
        "zero_busy_host_writes": result.counters["host_control_writes_during_busy"] == 0,
        "zero_external_task_descriptors": result.counters["external_task_descriptors"] == 0,
        "zero_external_hash_descriptors": result.counters["external_hash_descriptors"] == 0,
    }
    record = {
        "program": image["name"],
        "program_sha256": image["sha256"],
        "static_words": image["word_count"],
        "static_bytes": image["image_bytes"],
        "done": result.done,
        "error": result.error,
        "signature_bytes": len(result.output),
        "signature_sha256": signature_digest,
        "hash_trace_sha256": result.hash_trace_sha256,
        "oracle_hash_trace_sha256": oracle_digest.hexdigest(),
        "hash_class_counts": class_counts,
        "counters": result.counters,
        "checks": checks,
        "status": "PASS" if result.done and all(checks.values()) else "FAIL",
    }
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0 if record["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
