#!/usr/bin/env python3
"""Collect the raw-Job randomized-F P=2/U2 routed engineering point."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "build" / "vivado" / "randomized_f_p2_u2_raw"
OUTPUT = ROOT / "manifests" / "experiments" / "randomized_f_p2_u2_raw_v0.1.0.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(pattern: str, text: str, name: str) -> str:
    match = re.search(pattern, text, re.MULTILINE)
    if match is None:
        raise RuntimeError(f"could not extract {name}")
    return match.group(1)


def main() -> None:
    utilization_path = REPORT_DIR / "utilization.rpt"
    hierarchy_path = REPORT_DIR / "utilization_hierarchical.rpt"
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
    sources = [
        ROOT / "rtl" / "sequencer" / "micro_hbs_program_store.sv",
        ROOT / "rtl" / "sequencer" / "micro_hbs_sequencer.sv",
        ROOT / "rtl" / "hash_lane" / "micro_hbs_keccak_f1600.sv",
        ROOT / "rtl" / "hash_lane" / "micro_hbs_shake256_single_block.sv",
        ROOT / "rtl" / "composer" / "micro_hbs_randomized_hash.sv",
        ROOT / "rtl" / "top" / "micro_hbs_randomized_f_p2_slice.sv",
        ROOT / "tb" / "integration" / "tb_micro_hbs_randomized_f_p2_slice.sv",
        ROOT / "experiments" / "synth_randomized_f_p2_slice.tcl",
    ]
    manifest = {
        "schema_version": 1,
        "result_id": "randomized_f_p2_u2_raw_v0.1.0",
        "scope": identity["scope"],
        "classification": "engineering_vertical_slice_not_algorithm_replay",
        "paper_comparable": False,
        "complete_algorithm": False,
        "device": identity["part"],
        "tool": identity["tool"],
        "configuration": {
            "parallel_lanes": int(identity["parallel_lanes"]),
            "unroll": int(identity["unroll"]),
            "program_words": int(identity["program_words"]),
            "input_semantics": identity["input_semantics"],
            "scheduler": identity["scheduler"],
            "preassembled_hash_messages": identity["preassembled_hash_messages"] == "true",
            "host_writes_while_busy": identity["host_writes_while_busy"] == "true",
        },
        "clock_constraint": {"period_ns": 10.0, "frequency_mhz": 100.0},
        "post_route": post_route,
        "functional_checks": {
            "jobs": 2,
            "chain_steps_per_job": 3,
            "p2_lane_masks": [3, 3, 3],
            "tail_lane_masks": [1, 1, 1],
            "p2_internal_shake_calls": [9, 9],
            "tail_internal_shake_calls": [9, 0],
            "p2_lane_active_cycles": [150, 150],
            "tail_lane_active_cycles": [150, 0],
            "tail_lane_idle_cycles": [26, 176],
            "busy_program_writes": 0,
            "raw_input_bus_mutation_after_job_acceptance_safe": True,
            "invalid_bound_and_lane_mask_fail_closed": True,
            "ordered_intermediate_and_final_nodes_match_oracle": True,
            "lane_chain_addresses": [2, 3],
            "lane1_adjacent_chain_address_derived_in_hardware": True,
        },
        "limitations": [
            "This is the RFC 8391 WOTS+ randomized-F chain hotspot, not a complete OTS, Keygen or Sign replay.",
            "The slice derives only an adjacent chain pair from one address template; arbitrary microcode-derived chain-pair addressing remains to be integrated.",
            "The public bound is limited to the RFC 8391 w=16 range 1..15.",
            "The external paper baseline remains non-strict and is not used for a speedup claim.",
            "Wide out-of-context ports lack top-level package-pin placement.",
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
