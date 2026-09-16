#!/usr/bin/env python3
"""Collect paired full/minimum scratchpad storage-proxy results."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "manifests" / "experiments" / "scratchpad_full_min_v0.1.0.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(pattern: str, text: str, label: str) -> str:
    match = re.search(pattern, text, re.MULTILINE)
    if match is None:
        raise RuntimeError(f"cannot extract {label}")
    return match.group(1)


def point(label: str) -> dict[str, object]:
    report_dir = ROOT / "build" / "vivado" / f"scratchpad_{label}"
    utilization_path = report_dir / "utilization.rpt"
    timing_path = report_dir / "timing_summary.rpt"
    identity_path = report_dir / "run_identity.txt"
    utilization = utilization_path.read_text(encoding="utf-8", errors="replace")
    timing = timing_path.read_text(encoding="utf-8", errors="replace")
    identity = dict(
        line.split("=", 1)
        for line in identity_path.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    return {
        "words64": int(identity["words64"]),
        "logical_bytes": int(identity["logical_bytes"]),
        "scrub_cycles": int(identity["words64"]),
        "slice_lut": int(extract(r"\| Slice LUTs\s+\|\s+(\d+)\s+\|", utilization, "LUT")),
        "slice_register": int(
            extract(r"\| Slice Registers\s+\|\s+(\d+)\s+\|", utilization, "FF")
        ),
        "ramb36": int(
            extract(r"\|\s+RAMB36/FIFO\*\s+\|\s+(\d+)\s+\|", utilization, "RAMB36")
        ),
        "dsp": int(extract(r"\| DSPs\s+\|\s+(\d+)\s+\|", utilization, "DSP")),
        "wns_ns": float(
            extract(
                r"Design Timing Summary[\s\S]*?\n\s*[-]+\s+[-]+[\s\S]*?\n\s*([-+]?\d+\.\d+)\s+",
                timing,
                "WNS",
            )
        ),
        "report_sha256": {
            "utilization.rpt": sha256(utilization_path),
            "timing_summary.rpt": sha256(timing_path),
            "run_identity.txt": sha256(identity_path),
        },
    }


def main() -> None:
    full = point("full")
    minimum = point("min")
    manifest = {
        "schema_version": 1,
        "result_id": "scratchpad_full_min_v0.1.0",
        "classification": "paired_out_of_context_storage_proxy",
        "paper_comparable": False,
        "integrated": False,
        "device": "xc7a200tffg1156-2",
        "tool": "Vivado 2025.2",
        "clock_constraint_mhz": 100.0,
        "points": {"FULL_CACHE_PROXY": full, "TREEHASH_MIN_BUDGET_PROXY": minimum},
        "min_over_full": {
            "logical_bytes": round(
                float(minimum["logical_bytes"]) / float(full["logical_bytes"]), 6
            ),
            "physical_ramb36": round(float(minimum["ramb36"]) / float(full["ramb36"]), 6),
            "physical_ramb36_reduction_percent": 93.75,
            "scrub_cycles": round(
                float(minimum["scrub_cycles"]) / float(full["scrub_cycles"]), 6
            ),
        },
        "limitations": [
            "Storage macros are not yet connected to the complete HBS engine.",
            "The minimum budget reserves 21 256-bit nodes (stack/work/auth accounting); the current RTL streams authentication nodes.",
            "Signing recomputation and cache traffic are not measured, so this is not a BRAM-latency Pareto point.",
            "The full proxy uses a 64-bit physical port and maps to 16 RAMB36, not the paper's 256-bit 14.5-BRAM DataRAM.",
            "Vivado 2025.2 differs from the paper's Vivado 2018.3 flow.",
        ],
        "source_sha256": {
            "rtl/memory/micro_hbs_scratchpad64.sv": sha256(
                ROOT / "rtl" / "memory" / "micro_hbs_scratchpad64.sv"
            ),
            "experiments/synth_scratchpad.tcl": sha256(
                ROOT / "experiments" / "synth_scratchpad.tcl"
            ),
        },
    }
    OUTPUT.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest["min_over_full"], sort_keys=True))
    print(f"wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
