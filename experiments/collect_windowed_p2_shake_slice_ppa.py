#!/usr/bin/env python3
"""Collect the microsequencer + banked-window P=2/U2 routed point."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "build" / "vivado" / "windowed_p2_u2_slice"
OUTPUT = ROOT / "manifests" / "experiments" / "windowed_p2_u2_slice_v0.1.0.json"
REJECTED = ROOT / "manifests" / "experiments" / "static_p2_u2_batch_v0.1.0.json"


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
    hierarchy_path = REPORT_DIR / "utilization_hierarchical.rpt"
    timing_path = REPORT_DIR / "timing_summary.rpt"
    identity_path = REPORT_DIR / "run_identity.txt"
    utilization = utilization_path.read_text(encoding="utf-8", errors="replace")
    hierarchy = hierarchy_path.read_text(encoding="utf-8", errors="replace")
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
        "ramb18": int(require(r"\|\s+RAMB18\s+\|\s+(\d+)\s+\|", utilization, "RAMB18")),
        "dsp": int(require(r"\| DSPs\s+\|\s+(\d+)\s+\|", utilization, "DSP")),
        "wns_ns": float(require(
            r"Design Timing Summary[\s\S]*?\n\s*[-]+\s+[-]+[\s\S]*?\n\s*([-+]?\d+\.\d+)\s+",
            timing,
            "WNS",
        )),
    }
    post_route["bram36_equivalent"] = post_route["ramb36"] + post_route["ramb18"] / 2.0
    post_route["timing_met"] = post_route["wns_ns"] >= 0.0

    rejected = json.loads(REJECTED.read_text(encoding="utf-8"))
    rejected_ppa = rejected["post_route"]
    comparison = {
        "windowed_message_capacity": int(identity["message_capacity"]),
        "rejected_wide_message_capacity": int(rejected["configuration"]["max_tasks"]),
        "lut_reduction_percent": round(
            100.0 * (1.0 - post_route["slice_lut"] / int(rejected_ppa["slice_lut"])), 3
        ),
        "ff_reduction_percent": round(
            100.0 * (1.0 - post_route["slice_register"] / int(rejected_ppa["slice_register"])), 3
        ),
    }
    sources = [
        ROOT / "rtl" / "sequencer" / "micro_hbs_program_store.sv",
        ROOT / "rtl" / "sequencer" / "micro_hbs_sequencer.sv",
        ROOT / "rtl" / "memory" / "micro_hbs_dual_message_bank64.sv",
        ROOT / "rtl" / "hash_lane" / "micro_hbs_keccak_f1600.sv",
        ROOT / "rtl" / "hash_lane" / "micro_hbs_shake256_single_block.sv",
        ROOT / "rtl" / "composer" / "micro_hbs_static_p2_window_adapter.sv",
        ROOT / "rtl" / "top" / "micro_hbs_windowed_p2_shake_slice.sv",
        ROOT / "tb" / "integration" / "tb_micro_hbs_windowed_p2_shake_slice.sv",
        ROOT / "experiments" / "synth_windowed_p2_shake_slice.tcl",
        REJECTED,
    ]
    manifest = {
        "schema_version": 1,
        "result_id": "windowed_p2_u2_slice_v0.1.0",
        "scope": identity["scope"],
        "classification": "engineering_vertical_slice_not_algorithm_replay",
        "paper_comparable": False,
        "device": identity["part"],
        "tool": identity["tool"],
        "configuration": {
            "parallel_lanes": int(identity["parallel_lanes"]),
            "unroll": int(identity["unroll"]),
            "program_words": int(identity["program_words"]),
            "pair_capacity": int(identity["pair_capacity"]),
            "message_capacity": int(identity["message_capacity"]),
            "scheduler": identity["scheduler"],
            "integrated_with_microsequencer": identity["integrated_with_microsequencer"] == "true",
        },
        "clock_constraint": {"period_ns": 10.0, "frequency_mhz": 100.0},
        "post_route": post_route,
        "hierarchical_post_route": {
            "top_glue": hierarchy_point(
                r"\(micro_hbs_windowed_p2_shake_slice\)", hierarchy, "top glue"
            ),
            "sequencer": hierarchy_point("sequencer", hierarchy, "sequencer"),
            "adapter": hierarchy_point("adapter", hierarchy, "adapter"),
            "message_banks": {
                "slice_lut": None,
                "slice_register": None,
                "ramb36": post_route["ramb36"] - 1,
                "basis": "two message-bank RAMs are absorbed into the top row; subtract the sequencer's one program-store RAMB36",
            },
        },
        "functional_checks": {
            "known_answer_hashes": 7,
            "jobs": 2,
            "hash_requests_per_job": 2,
            "even_lane_masks": [3, 3],
            "odd_lane_masks": [3, 1],
            "even_bank_reads": [36, 36],
            "odd_bank_reads": [36, 18],
            "odd_lane_active_cycles": [32, 16],
            "even_lane_active_cycles": [32, 32],
            "even_lane_idle_cycles": [52, 52],
            "odd_lane_idle_cycles": [52, 68],
            "busy_window_cycles_even": 84,
            "busy_window_cycles_odd": 84,
            "compose_cycles_per_job": 38,
            "busy_program_writes": 0,
            "busy_message_writes_rejected": 2,
            "external_bus_mutation_after_job_acceptance_safe": True,
            "invalid_lane_mask_rejected_before_bank_read_or_lane_dispatch": True,
        },
        "versus_rejected_wide_batch": comparison,
        "limitations": [
            "This is a microsequencer/banked-composer/hash-lane vertical slice, not a complete LMS, XMSS or SLH-DSA replay.",
            "The test preloads complete SHAKE messages while IDLE; the final algorithm path must compose them from raw Job data and internal nodes.",
            "The 64-bit bank adds 18 read/assembly cycles per pair and is not the required one-cycle OTS rate-wide fast path.",
            "The five-message rejected point and six-message windowed point are close but not identical capacities.",
            "The external paper baseline remains non-strict and is not used for a speedup claim.",
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
    print(json.dumps({"post_route": post_route, "comparison": comparison}, sort_keys=True))
    print(f"wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
