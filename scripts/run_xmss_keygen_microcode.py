#!/usr/bin/env python3
"""Execute one autonomous XMSS-SHAKE256 H10 Keygen microprogram Job."""

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
from model.reference.xmss import xmss_seed_keypair  # noqa: E402


PROGRAM = ROOT / "microcode" / "xmss" / "xmss_shake256_h10_w4_keygen.json"
KAT = ROOT / "tests" / "kat" / "xmss_shake256_10_256_idx5.json"


def main() -> int:
    image = load_and_assemble(PROGRAM)
    vector = json.loads(KAT.read_text(encoding="utf-8"))
    seed = bytes.fromhex(vector["seed"])
    job = {"sk_seed": seed[:32], "pub_seed": seed[64:]}
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

    oracle_public_key, _ = xmss_seed_keypair(seed, observe=observe)
    expected_root = bytes.fromhex(vector["public_key"])[:32]
    checks = {
        "rfc_reference_root_match": result.output == expected_root,
        "live_oracle_root_match": result.output == oracle_public_key[:32],
        "per_hash_trace_match": result.hash_trace_sha256 == oracle_digest.hexdigest(),
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
        "root": result.output.hex(),
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
