#!/usr/bin/env python3
"""Collect the routed 32-bit layout-expression capability result."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "build" / "vivado" / "layout_expr32"
OUTPUT = ROOT / "manifests" / "experiments" / "layout_expr32_v0.1.0.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(pattern: str, text: str, name: str) -> str:
    match = re.search(pattern, text, re.MULTILINE)
    if match is None:
        raise RuntimeError(f"could not extract {name}")
    return match.group(1)


def main() -> None:
    utilization_path = REPORT_DIR / "utilization.rpt"
    timing_path = REPORT_DIR / "timing_summary.rpt"
    identity_path = REPORT_DIR / "run_identity.txt"
    utilization = utilization_path.read_text(encoding="utf-8", errors="replace")
    timing = timing_path.read_text(encoding="utf-8", errors="replace")
    identity = dict(
        line.split("=", 1)
        for line in identity_path.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    post_route = {
        "slice_lut": int(require(r"\| Slice LUTs\s+\|\s+(\d+)\s+\|", utilization, "LUT")),
        "slice_register": int(require(r"\| Slice Registers\s+\|\s+(\d+)\s+\|", utilization, "FF")),
        "ramb36": int(require(r"\|\s+RAMB36/FIFO\*\s+\|\s+(\d+)\s+\|", utilization, "RAMB36")),
        "dsp": int(require(r"\| DSPs\s+\|\s+(\d+)\s+\|", utilization, "DSP")),
        "wns_ns": float(require(
            r"Design Timing Summary[\s\S]*?\n\s*[-]+\s+[-]+[\s\S]*?\n\s*([-+]?\d+\.\d+)\s+",
            timing,
            "WNS",
        )),
    }
    post_route["timing_met"] = post_route["wns_ns"] >= 0.0
    sources = [
        ROOT / "rtl" / "composer" / "micro_hbs_layout_expr.sv",
        ROOT / "rtl" / "composer" / "micro_hbs_ordered_pair.sv",
        ROOT / "tb" / "unit" / "tb_micro_hbs_layout_expr.sv",
        ROOT / "experiments" / "synth_layout_expr32.tcl",
    ]
    manifest = {
        "schema_version": 1,
        "result_id": "layout_expr32_v0.1.0",
        "scope": identity["scope"],
        "classification": "engineering_capability_evidence_only",
        "paper_comparable": False,
        "integrated_with_hash_lane": False,
        "device": identity["part"],
        "tool": identity["tool"],
        "configuration": {
            "value_width": 32,
            "token_words": 32,
            "stack_depth": 8,
        },
        "clock_constraint": {"period_ns": 10.0, "frequency_mhz": 100.0},
        "post_route": post_route,
        "functional_checks": {
            "fors_subtree_address": True,
            "ordered_pair_both_directions": True,
            "busy_configuration_rejected": True,
            "illegal_and_unconfigured_token_rejected": True,
            "shift_range_and_add_overflow_rejected": True,
        },
        "comparison_to_w288": {
            "purpose": "architecture selection, not paper comparison",
            "wide_result_manifest": "manifests/experiments/layout_expr_v0.1.0.json",
        },
        "limitations": [
            "Standalone 32-bit address/index expression engine only.",
            "Digest digit extraction, 96-bit tree-address update, ordered-pair mux, Scratchpad and hash lane are excluded.",
            "Vivado 2025.2 is not the paper's Vivado 2018.3 flow.",
        ],
        "report_sha256": {
            "utilization.rpt": sha256(utilization_path),
            "timing_summary.rpt": sha256(timing_path),
            "run_identity.txt": sha256(identity_path),
        },
        "source_sha256": {str(path.relative_to(ROOT)): sha256(path) for path in sources},
    }
    OUTPUT.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(post_route, sort_keys=True))
    print(f"wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
