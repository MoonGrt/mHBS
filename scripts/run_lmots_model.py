#!/usr/bin/env python3
"""Run the first autonomous μHBS job and print its evidence record."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.interpreter import MicroInterpreter  # noqa: E402
from model.microcode_assembler import load_and_assemble  # noqa: E402
from model.reference.lms import RFC8554_TEST2, lmots_public_key  # noqa: E402


def main() -> int:
    image = load_and_assemble(ROOT / "microcode/lms/lmots_public_w4.json")
    job = {
        "identifier": RFC8554_TEST2["identifier"],
        "q": 5,
        "seed": RFC8554_TEST2["seed"],
    }
    result = MicroInterpreter(image).execute(job)
    expected = lmots_public_key(job["identifier"], job["q"], job["seed"])
    record = {
        "program": image["name"],
        "program_sha256": image["sha256"],
        "static_words": image["word_count"],
        "static_bytes": image["image_bytes"],
        "done": result.done,
        "error": result.error,
        "output": result.output.hex(),
        "oracle_output": expected.hex(),
        "oracle_match": result.output == expected,
        "counters": result.counters,
    }
    print(json.dumps(record, indent=2))
    return 0 if result.done and result.output == expected else 1


if __name__ == "__main__":
    raise SystemExit(main())
