#!/usr/bin/env python3
"""Execute one autonomous FIPS 205 SHAKE-128f Keygen microprogram Job."""

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
from model.reference.slh_dsa import SLH_DSA_SHAKE_128F, keygen_internal  # noqa: E402


PROGRAM = ROOT / "microcode" / "slh_dsa" / "slh_dsa_shake_128f_keygen.json"
KAT = ROOT / "tests" / "kat" / "slh_dsa_shake_128f_keygen_acvp_tc31.json"


def main() -> int:
    image = load_and_assemble(PROGRAM)
    vector = json.loads(KAT.read_text(encoding="utf-8"))
    job = {
        "sk_seed": bytes.fromhex(vector["sk_seed"]),
        "pub_seed": bytes.fromhex(vector["pk_seed"]),
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

    _secret_key, oracle_public_key = keygen_internal(
        SLH_DSA_SHAKE_128F,
        bytes.fromhex(vector["sk_seed"]),
        bytes.fromhex(vector["sk_prf"]),
        bytes.fromhex(vector["pk_seed"]),
        observe,
    )
    expected_root = bytes.fromhex(vector["pk"])[16:]
    checks = {
        "nist_acvp_root_match": result.output == expected_root,
        "live_oracle_root_match": result.output == oracle_public_key[16:],
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
