#!/usr/bin/env python3
"""Convert the complete SLH-DSA RTL PROFILE/PASS log into stable JSON."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


KEY_VALUE = re.compile(r"([A-Za-z0-9_]+)=([0-9]+(?:[+/][0-9]+)*)")


def _value(raw: str) -> int | list[int]:
    if "+" in raw:
        return [int(item) for item in raw.split("+")]
    if "/" in raw:
        return [int(item) for item in raw.split("/")]
    return int(raw)


def _fields(line: str) -> dict[str, int | list[int]]:
    return {name: _value(value) for name, value in KEY_VALUE.findall(line)}


def parse_profile(text: str) -> dict[str, object]:
    profiles: dict[str, dict[str, int | list[int]]] = {}
    result: dict[str, int | list[int]] | None = None

    for line in text.splitlines():
        if line.startswith("PROFILE "):
            section = line.split(None, 2)[1]
            profiles[section] = _fields(line)
        elif line.startswith("PASS no-DMA complete SLH-DSA Sign "):
            result = _fields(line)

    if result is None:
        raise ValueError("complete SLH-DSA PASS line is missing")
    composer = profiles.get("composer")
    sequencer = profiles.get("sequencer")
    if composer is None or sequencer is None:
        raise ValueError("sequencer/composer PROFILE line is missing")

    total_cycles = result["cycles"]
    if not isinstance(total_cycles, int):
        raise ValueError("cycles must be a scalar")

    partition = {
        "emit": int(composer.get("emit_word", composer.get("emit_byte", 0))),
        "component_control": sum(
            int(composer.get(name, 0))
            for name in (
                "comp_req", "comp_wait", "comp_product", "comp_validate",
                "prefetch_wait",
            )
        ),
        "scratch_source_read": sum(
            int(composer[name])
            for name in ("src_a_req", "src_a_wait", "src_b_req", "src_b_wait")
        ),
        "shake_block_send_and_digest_wait": int(composer["block_send"])
        + int(composer["digest_wait"]),
        "layout_lookup_product_validate_start": sum(
            int(composer[name])
            for name in ("layout_wait", "layout_product", "layout_validate", "hash_start")
        ),
        "digest_writeback": int(composer["write_req"]),
        "idle_and_other_engines": int(composer["idle"]),
    }
    partition_sum = sum(partition.values())
    if partition_sum != total_cycles:
        raise ValueError(
            f"composer partition {partition_sum} does not equal total {total_cycles}"
        )

    return {
        "schema_version": 1,
        "result": result,
        "profiles": profiles,
        "derived": {
            "composer_partition": partition,
            "composer_partition_percent": {
                name: round(100.0 * cycles / total_cycles, 6)
                for name, cycles in partition.items()
            },
            "sequencer_fetch_and_run": int(sequencer["fetch"])
            + int(sequencer["run"]),
            "partition_sum": partition_sum,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("log", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    args = parser.parse_args()
    parsed = parse_profile(args.log.read_text(encoding="utf-8"))
    encoded = json.dumps(parsed, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(encoded, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")


if __name__ == "__main__":
    main()
