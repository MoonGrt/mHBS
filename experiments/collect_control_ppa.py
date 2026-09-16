#!/usr/bin/env python3
"""Collect the routed control-slice result without promoting it to a paper result."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "build" / "vivado" / "control_slice_p1"
OUTPUT = ROOT / "manifests" / "experiments" / "control_slice_p1_v0.1.0.json"


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
    bram36 = int(require(r"\|\s+RAMB36/FIFO\*\s+\|\s+(\d+)\s+\|", utilization, "RAMB36"))
    dsp = int(require(r"\| DSPs\s+\|\s+(\d+)\s+\|", utilization, "DSP"))
    wns = float(
        require(
            r"Design Timing Summary[\s\S]*?\n\s*[-]+\s+[-]+[\s\S]*?\n\s*([-+]?\d+\.\d+)\s+",
            timing,
            "WNS",
        )
    )
    period_ns = float(identity["clock_period_ns"])

    sources = [
        ROOT / "rtl" / "sequencer" / "micro_hbs_program_store.sv",
        ROOT / "rtl" / "sequencer" / "micro_hbs_sequencer.sv",
        ROOT / "rtl" / "hash_lane" / "micro_hbs_hash_latency_stub.sv",
        ROOT / "rtl" / "top" / "micro_hbs_job_latch.sv",
        ROOT / "rtl" / "top" / "micro_hbs_control_slice.sv",
        ROOT / "experiments" / "synth_control_slice.tcl",
    ]
    manifest = {
        "schema_version": 1,
        "result_id": "control_slice_p1_v0.1.0",
        "scope": identity["scope"],
        "classification": "engineering_evidence_only",
        "paper_comparable": identity["paper_comparable"] == "true",
        "contains_real_hash_lane": identity["contains_real_hash_lane"] == "true",
        "device": identity["part"],
        "tool": identity["tool"],
        "clock_constraint": {"period_ns": period_ns, "frequency_mhz": 1000.0 / period_ns},
        "post_route": {
            "slice_lut": lut,
            "slice_register": ff,
            "ramb36": bram36,
            "dsp": dsp,
            "wns_ns": wns,
            "timing_met": wns >= 0.0,
        },
        "limitations": [
            "Control slice only; no cryptographic hash datapath, composer, scratchpad, TreeHash, output, or state manager.",
            "Job payload fields without a consumer are optimized away.",
            "The latency stub is non-cryptographic and excluded from any correctness or throughput claim.",
            "Vivado 2025.2 is not the paper's Vivado 2018.3 flow.",
            "This result must not be divided into the paper-reported area or cycles to claim improvement.",
        ],
        "report_sha256": {
            "utilization.rpt": sha256(utilization_path),
            "timing_summary.rpt": sha256(timing_path),
            "run_identity.txt": sha256(identity_path),
        },
        "source_sha256": {str(path.relative_to(ROOT)): sha256(path) for path in sources},
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest["post_route"], sort_keys=True))
    print(f"wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
