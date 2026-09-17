#!/usr/bin/env python3
"""Compile an SLH-DSA hash trace into the horizontal control baseline."""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.horizontal_microcode import compile_barrier_program  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--trace",
        default="build/schedules/slh_dsa_kxu/slh_dsa_sign_K2xU2.jsonl.gz",
        type=Path,
    )
    parser.add_argument(
        "--json-out",
        default="build/slh_dsa_horizontal_control_v0.json",
        type=Path,
    )
    parser.add_argument("--hex-out", type=Path)
    args = parser.parse_args()

    with gzip.open(args.trace, "rt", encoding="utf-8") as handle:
        tasks = [json.loads(line) for line in handle if line.strip()]
    words, metrics = compile_barrier_program(tasks)
    result = {
        "schema_version": "0.1.0",
        "classification": "CONTROL_SCHEDULE_PROJECTION_NOT_FULL_RTL",
        "architecture": {
            "word_bits": 128,
            "lane_command_bits": 48,
            "equal_hash_lanes": 2,
            "keccak_unroll": 2,
            "event_scoreboard_bits": 8,
            "dynamic_ready_window_entries": 0,
            "policy": "offline order; adjacent-independent pairing; pair barrier",
        },
        "metrics": metrics,
        "limitations": [
            "context materializer and scratch writeback are not in this projection",
            "the baseline program is fully unrolled and requires affine-loop folding",
            "cycle values are direct-lane projections, not complete RTL measurements",
        ],
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if args.hex_out is not None:
        args.hex_out.parent.mkdir(parents=True, exist_ok=True)
        args.hex_out.write_text(
            "".join(f"{word.encode():032x}\n" for word in words),
            encoding="ascii",
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
