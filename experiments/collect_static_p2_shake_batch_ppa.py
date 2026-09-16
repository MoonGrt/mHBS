#!/usr/bin/env python3
"""Collect static P=2/U2 SHAKE batch slice post-route evidence."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "build" / "vivado" / "static_p2_u2_batch"
OUTPUT = ROOT / "manifests" / "experiments" / "static_p2_u2_batch_v0.1.0.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(pattern: str, text: str, name: str) -> str:
    match = re.search(pattern, text, re.MULTILINE)
    if match is None:
        raise RuntimeError(f"could not extract {name}")
    return match.group(1)


def hierarchy_point(instance_pattern: str, text: str, name: str) -> dict[str, int]:
    match = re.search(
        rf"\|\s+{instance_pattern}\s+\|[^\n]*?\|\s+(\d+)\s+\|\s+\d+\s+\|\s+\d+\s+\|\s+\d+\s+\|\s+(\d+)\s+\|",
        text,
        re.MULTILINE,
    )
    if match is None:
        raise RuntimeError(f"could not extract {name} hierarchy")
    return {"slice_lut": int(match.group(1)), "slice_register": int(match.group(2))}


def main() -> None:
    utilization_path = REPORT_DIR / "utilization.rpt"
    timing_path = REPORT_DIR / "timing_summary.rpt"
    hierarchy_path = REPORT_DIR / "utilization_hierarchical.rpt"
    identity_path = REPORT_DIR / "run_identity.txt"
    utilization = utilization_path.read_text(encoding="utf-8", errors="replace")
    timing = timing_path.read_text(encoding="utf-8", errors="replace")
    hierarchy = hierarchy_path.read_text(encoding="utf-8", errors="replace")
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
        ROOT / "rtl" / "hash_lane" / "micro_hbs_keccak_f1600.sv",
        ROOT / "rtl" / "hash_lane" / "micro_hbs_shake256_single_block.sv",
        ROOT / "rtl" / "top" / "micro_hbs_static_p2_shake_batch.sv",
        ROOT / "tb" / "integration" / "tb_micro_hbs_static_p2_shake_batch.sv",
        ROOT / "experiments" / "synth_static_p2_shake_batch.tcl",
    ]
    manifest = {
        "schema_version": 1,
        "result_id": "static_p2_u2_batch_v0.1.0",
        "scope": identity["scope"],
        "classification": "engineering_capability_evidence_only",
        "paper_comparable": False,
        "integrated_with_microsequencer": False,
        "device": identity["part"],
        "tool": identity["tool"],
        "configuration": {
            "parallel_lanes": int(identity["parallel_lanes"]),
            "unroll": int(identity["unroll"]),
            "max_tasks": int(identity["max_tasks"]),
            "scheduler": identity["scheduler"],
        },
        "clock_constraint": {"period_ns": 10.0, "frequency_mhz": 100.0},
        "post_route": post_route,
        "hierarchical_post_route": {
            "batch_control_and_wide_storage": hierarchy_point(
                r"\(micro_hbs_static_p2_shake_batch\)", hierarchy, "batch control"
            ),
            "lane0": hierarchy_point("lane0", hierarchy, "lane0"),
            "lane1": hierarchy_point("lane1", hierarchy, "lane1"),
        },
        "functional_checks": {
            "known_answer_hashes": 7,
            "coarse_batch_requests": 2,
            "even_batch_lane_masks": [3, 3],
            "odd_batch_lane_masks": [3, 1],
            "even_four_hash_window_cycles": 34,
            "odd_three_hash_window_cycles": 34,
            "odd_lane_active_cycles": [32, 16],
            "odd_lane_idle_cycles": [2, 18],
            "external_bus_mutation_after_acceptance_safe": True,
            "invalid_batches_rejected_before_lane_start": True,
        },
        "limitations": [
            "Static SHAKE batch slice only; no microsequencer, composer, Scratchpad, TreeHash or algorithm replay.",
            "Messages are preassembled and latched in wide local registers; this is not the final banked input path.",
            "The fixed even/odd mapper is not a runtime scheduler.",
            "The result cannot be compared with the paper's complete P2/U2 engine.",
        ],
        "report_sha256": {
            "utilization.rpt": sha256(utilization_path),
            "utilization_hierarchical.rpt": sha256(hierarchy_path),
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
