#!/usr/bin/env python3
"""Collect paired U1/U2 Keccak-f OOC results and compute only local ratios."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "manifests" / "experiments" / "keccak_u1_u2_v0.1.0.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(pattern: str, text: str, name: str) -> str:
    match = re.search(pattern, text, re.MULTILINE)
    if match is None:
        raise RuntimeError(f"could not extract {name}")
    return match.group(1)


def collect(unroll: int) -> dict[str, object]:
    report_dir = ROOT / "build" / "vivado" / f"keccak_u{unroll}"
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
    result: dict[str, object] = {
        "unroll": unroll,
        "permutation_active_cycles": 24 // unroll,
        "slice_lut": int(require(r"\| Slice LUTs\s+\|\s+(\d+)\s+\|", utilization, "LUT")),
        "slice_register": int(
            require(r"\| Slice Registers\s+\|\s+(\d+)\s+\|", utilization, "FF")
        ),
        "ramb36": int(
            require(r"\|\s+RAMB36/FIFO\*\s+\|\s+(\d+)\s+\|", utilization, "RAMB36")
        ) if "RAMB36/FIFO" in utilization else 0,
        "dsp": int(require(r"\| DSPs\s+\|\s+(\d+)\s+\|", utilization, "DSP")),
        "wns_ns": float(
            require(
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
    if identity["unroll"] != str(unroll):
        raise RuntimeError("run identity does not match directory")
    return result


def main() -> None:
    u1 = collect(1)
    u2 = collect(2)
    lut_ratio = float(u2["slice_lut"]) / float(u1["slice_lut"])
    lut_cycle_ratio = (
        float(u2["slice_lut"]) * float(u2["permutation_active_cycles"])
        / (float(u1["slice_lut"]) * float(u1["permutation_active_cycles"]))
    )
    eq_u1 = float(u1["slice_lut"]) / 4 + float(u1["slice_register"]) / 8
    eq_u2 = float(u2["slice_lut"]) / 4 + float(u2["slice_register"]) / 8
    manifest = {
        "schema_version": 1,
        "result_id": "keccak_u1_u2_v0.1.0",
        "classification": "paired_out_of_context_hash_primitive_ablation",
        "paper_comparable": False,
        "device": "xc7a200tffg1156-2",
        "tool": "Vivado 2025.2",
        "clock_constraint_mhz": 100.0,
        "points": {"U1": u1, "U2": u2},
        "paired_ratios_u2_over_u1": {
            "lut": round(lut_ratio, 6),
            "permutation_cycles": 0.5,
            "lut_cycle_product": round(lut_cycle_ratio, 6),
            "equivalent_slice_cycle_product": round((eq_u2 * 12) / (eq_u1 * 24), 6),
        },
        "limitations": [
            "Out-of-context wide state ports have no top-level partition pin locations.",
            "Clock source location is absent, so WNS is not full-design timing signoff.",
            "The result excludes SHAKE absorb control, HIL/composer, sequencer, memory, output and state manager.",
            "Only the paired U1/U2 area and fixed-frequency cycle ratios are admissible.",
            "The tool version differs from the paper's Vivado 2018.3 flow.",
        ],
        "source_sha256": {
            "rtl/hash_lane/micro_hbs_keccak_f1600.sv": sha256(
                ROOT / "rtl" / "hash_lane" / "micro_hbs_keccak_f1600.sv"
            ),
            "experiments/synth_keccak_lane.tcl": sha256(
                ROOT / "experiments" / "synth_keccak_lane.tcl"
            ),
        },
    }
    OUTPUT.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest["paired_ratios_u2_over_u1"], sort_keys=True))
    print(f"wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
