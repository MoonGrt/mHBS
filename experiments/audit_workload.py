#!/usr/bin/env python3
"""Validate the frozen B0 table and emit a conservative comparability audit."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "manifests/experiments/workload_audit_v0.1.0.json"


def audit(data: dict) -> dict:
    base = data["baseline"]
    p = int(base["parallelism"])
    cycles_per_perm = int(base["cycles_per_lane_permutation"])
    if p <= 0 or cycles_per_perm <= 0:
        raise ValueError("parallelism and cycles_per_lane_permutation must be positive")

    rows = []
    for point in data["points"]:
        cycles = int(point["cycles"])
        if cycles <= 0:
            raise ValueError(f"non-positive cycle count: {point}")
        capacity = cycles * p // cycles_per_perm
        strict = point["semantic_alignment"] == "strict"
        rows.append(
            {
                **point,
                "max_saturated_permutations": capacity,
                "comparison_class": "STRICT" if strict else "NON_STRICT",
                "speedup_allowed": strict,
            }
        )
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    return {
        "schema_version": 1,
        "input_sha256": hashlib.sha256(canonical).hexdigest(),
        "interpretation": (
            "max_saturated_permutations is a capacity upper bound under perfect "
            "two-lane occupancy, not the algorithm's measured permutation count"
        ),
        "strict_points": sum(row["speedup_allowed"] for row in rows),
        "non_strict_points": sum(not row["speedup_allowed"] for row in rows),
        "rows": rows,
    }


def markdown(report: dict) -> str:
    out = [
        "# B0 工作量与可比性自动审计",
        "",
        f"输入摘要：`{report['input_sha256']}`",
        "",
        "> `max saturated permutations` 只表示 P=2/U=2、无气泡时由报告 cycles 可容纳的 Keccak permutation 上限；它不是论文实际 Hash 计数。",
        "",
        "| Family | Profile | Op | Cycles | Max saturated permutations | Class |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in report["rows"]:
        out.append(
            f"| {row['family']} | {row['profile']} | {row['operation']} | "
            f"{row['cycles']:,} | {row['max_saturated_permutations']:,} | "
            f"{row['comparison_class']} ({row['semantic_alignment']}) |"
        )
    out.extend(
        [
            "",
            f"严格点：{report['strict_points']}；非严格点：{report['non_strict_points']}。",
            "",
            "当前没有 B0 点获准计算相对 FIPS/RFC 实现的 speedup。后续必须以逐 Hash trace 和实际 permutation 计数解除该限制。",
            "",
        ]
    )
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--md-out", type=Path)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    report = audit(data)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.md_out:
        args.md_out.parent.mkdir(parents=True, exist_ok=True)
        args.md_out.write_text(markdown(report), encoding="utf-8")
    if not args.json_out and not args.md_out:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
