#!/usr/bin/env python3
"""Execute one complete RFC 8554 LMS H10 public-key Job."""

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
from model.reference.lms import RFC8554_TEST2, lms_public_key  # noqa: E402


def main() -> int:
    image = load_and_assemble(ROOT / "microcode/lms/lms_public_h10_w4.json")
    vector = RFC8554_TEST2
    job = {"identifier": vector["identifier"], "seed": vector["seed"]}
    result = MicroInterpreter(image, trace_mode="none").execute(job)
    oracle_digest = hashlib.sha256()
    class_counts: dict[str, int] = {}

    def observe(kind: str, data: bytes, value: bytes) -> None:
        record = {
            "hash_class": kind,
            "hash_input_digest": hashlib.sha256(data).hexdigest(),
            "hash_output": value.hex(),
        }
        oracle_digest.update(json.dumps(record, sort_keys=True, separators=(",", ":")).encode())
        class_counts[kind] = class_counts.get(kind, 0) + 1

    oracle_root = lms_public_key(job["identifier"], job["seed"], 10, observe=observe)
    record = {
        "program": image["name"],
        "program_sha256": image["sha256"],
        "static_words": image["word_count"],
        "static_bytes": image["image_bytes"],
        "done": result.done,
        "error": result.error,
        "root": result.output.hex(),
        "rfc8554_appendix_f_root": vector["expected_root"].hex(),
        "kat_match": result.output == vector["expected_root"],
        "hash_trace_sha256": result.hash_trace_sha256,
        "oracle_hash_trace_sha256": oracle_digest.hexdigest(),
        "per_hash_trace_match": result.hash_trace_sha256 == oracle_digest.hexdigest(),
        "oracle_root_match": result.output == oracle_root,
        "hash_class_counts": class_counts,
        "counters": result.counters,
    }
    print(json.dumps(record, indent=2))
    return 0 if record["done"] and record["kat_match"] and record["per_hash_trace_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
