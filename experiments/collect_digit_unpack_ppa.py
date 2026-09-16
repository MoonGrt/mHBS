#!/usr/bin/env python3
"""Collect the post-synthesis static digit-unpack capability result."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "build" / "vivado" / "digit_unpack"
OUTPUT = ROOT / "manifests" / "experiments" / "digit_unpack_v0.1.0.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(pattern: str, text: str, name: str) -> str:
    match = re.search(pattern, text, re.MULTILINE)
    if match is None:
        raise RuntimeError(f"could not extract {name}")
    return match.group(1)


def main() -> None:
    utilization_path = REPORT_DIR / "utilization.rpt"
    identity_path = REPORT_DIR / "run_identity.txt"
    utilization = utilization_path.read_text(encoding="utf-8", errors="replace")
    identity = dict(
        line.split("=", 1)
        for line in identity_path.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    sources = [
        ROOT / "rtl" / "composer" / "micro_hbs_digit_unpack.sv",
        ROOT / "tb" / "unit" / "tb_micro_hbs_digit_unpack.sv",
        ROOT / "experiments" / "synth_digit_unpack.tcl",
    ]
    manifest = {
        "schema_version": 1,
        "result_id": "digit_unpack_v0.1.0",
        "scope": identity["scope"],
        "classification": "engineering_capability_evidence_only",
        "paper_comparable": False,
        "device": identity["part"],
        "tool": identity["tool"],
        "configuration": {
            "input_bytes": int(identity["input_bytes"]),
            "digit_bits": int(identity["digit_bits"]),
            "count": int(identity["count"]),
        },
        "implementation_stage": identity["implementation_stage"],
        "post_synthesis": {
            "slice_lut": int(require(r"\| Slice LUTs\*?\s+\|\s+(\d+)\s+\|", utilization, "LUT")),
            "slice_register": int(require(r"\| Slice Registers\s+\|\s+(\d+)\s+\|", utilization, "FF")),
            "ramb36": int(require(r"\|\s+RAMB36/FIFO\*\s+\|\s+(\d+)\s+\|", utilization, "RAMB36")),
            "dsp": int(require(r"\| DSPs\s+\|\s+(\d+)\s+\|", utilization, "DSP")),
        },
        "functional_checks": {
            "acvp_tc137_all_33_fors_indices": True,
            "cross_byte_digit": True,
            "consumed_and_unused_bit_boundaries": True,
            "four_bit_configuration": True,
        },
        "limitations": [
            "Static wiring capability only; no registers, scheduling or hash lane are included.",
            "The result is an architecture-selection point, not a complete-design paper comparison.",
        ],
        "report_sha256": {
            "utilization.rpt": sha256(utilization_path),
            "run_identity.txt": sha256(identity_path),
        },
        "source_sha256": {str(path.relative_to(ROOT)): sha256(path) for path in sources},
    }
    OUTPUT.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest["post_synthesis"], sort_keys=True))
    print(f"wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
