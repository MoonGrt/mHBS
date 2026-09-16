#!/usr/bin/env python3
"""Collect the routed randomized-F vertical-slice engineering checkpoint."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "build" / "vivado" / "randomized_chain_p1u2"
OUTPUT = ROOT / "manifests" / "experiments" / "randomized_chain_p1u2_v0.1.0.json"


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
    lut = int(require(r"\| Slice LUTs\s+\|\s+(\d+)\s+\|", utilization, "LUT"))
    ff = int(require(r"\| Slice Registers\s+\|\s+(\d+)\s+\|", utilization, "FF"))
    bram36 = int(
        require(r"\|\s+RAMB36/FIFO\*\s+\|\s+(\d+)\s+\|", utilization, "RAMB36")
    )
    dsp = int(require(r"\| DSPs\s+\|\s+(\d+)\s+\|", utilization, "DSP"))
    wns = float(
        require(
            r"Design Timing Summary[\s\S]*?\n\s*[-]+\s+[-]+[\s\S]*?\n\s*([-+]?\d+\.\d+)\s+",
            timing,
            "WNS",
        )
    )
    sources = [
        ROOT / "rtl" / "sequencer" / "micro_hbs_program_store.sv",
        ROOT / "rtl" / "sequencer" / "micro_hbs_sequencer.sv",
        ROOT / "rtl" / "memory" / "micro_hbs_scratchpad64.sv",
        ROOT / "rtl" / "hash_lane" / "micro_hbs_keccak_f1600.sv",
        ROOT / "rtl" / "hash_lane" / "micro_hbs_shake256_single_block.sv",
        ROOT / "rtl" / "composer" / "micro_hbs_randomized_hash.sv",
        ROOT / "rtl" / "composer" / "micro_hbs_randomized_f_scratch_adapter.sv",
        ROOT / "rtl" / "top" / "micro_hbs_randomized_chain_slice.sv",
        ROOT / "experiments" / "synth_randomized_chain_slice.tcl",
    ]
    period_ns = float(identity["clock_period_ns"])
    manifest = {
        "schema_version": 1,
        "result_id": "randomized_chain_p1u2_v0.1.0",
        "scope": identity["scope"],
        "classification": "engineering_vertical_slice_ppa",
        "paper_comparable": identity["paper_comparable"] == "true",
        "complete_algorithm": identity["complete_algorithm"] == "true",
        "contains_real_hash_lane": identity["contains_real_hash_lane"] == "true",
        "device": identity["part"],
        "tool": identity["tool"],
        "configuration": {
            "lanes": int(identity["lanes"]),
            "unroll": int(identity["unroll"]),
            "program_words": int(identity["program_words"]),
            "scratch_words_64bit": int(identity["scratch_words"]),
        },
        "clock_constraint": {
            "period_ns": period_ns,
            "frequency_mhz": 1000.0 / period_ns,
        },
        "post_route": {
            "slice_lut": lut,
            "slice_register": ff,
            "ramb36": bram36,
            "dsp": dsp,
            "wns_ns": wns,
            "timing_met": wns >= 0.0,
        },
        "functional_result": {
            "manifest": "manifests/experiments/randomized_chain_slice_v0.1.0.json",
            "cycles": 260,
            "internal_shake_calls": 9,
            "oracle_match": True,
        },
        "limitations": [
            "The slice implements randomized-F chaining, not a complete HBS Keygen or Sign operation.",
            "The Scratchpad adapter is single-port and serialized rather than banked/OTS-wide.",
            "Wide out-of-context ports lack top-level package-pin placement.",
            "Vivado 2025.2 differs from the paper's Vivado 2018.3 flow.",
            "This checkpoint cannot be divided into the paper-reported area or cycles to claim improvement.",
        ],
        "report_sha256": {
            "utilization.rpt": sha256(utilization_path),
            "timing_summary.rpt": sha256(timing_path),
            "run_identity.txt": sha256(identity_path),
        },
        "source_sha256": {str(path.relative_to(ROOT)): sha256(path) for path in sources},
    }
    OUTPUT.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest["post_route"], sort_keys=True))
    print(f"wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
