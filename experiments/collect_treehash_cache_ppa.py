#!/usr/bin/env python3
"""Collect paired h=10 FULL/SUBTREE cache-store OOC results."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "manifests" / "experiments" / "treehash_cache_store_v0.1.0.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(pattern: str, text: str, label: str) -> str:
    match = re.search(pattern, text, re.MULTILINE)
    if match is None:
        raise RuntimeError(f"cannot extract {label}")
    return match.group(1)


def point(label: str) -> dict[str, object]:
    report_dir = ROOT / "build" / "vivado" / f"treehash_cache_{label}"
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
    tree_height = int(identity["tree_height"])
    subtree_height = int(identity["subtree_height"])
    capacity = (
        (1 << (tree_height + 1)) - 1
        if int(identity["cache_mode"]) == 2
        else (1 << (tree_height - subtree_height + 1)) - 1
    )
    return {
        "cache_mode": int(identity["cache_mode"]),
        "tree_height": tree_height,
        "subtree_height": subtree_height,
        "capacity_nodes": capacity,
        "logical_bytes": capacity * 32,
        "slice_lut": int(extract(r"\| Slice LUTs\s+\|\s+(\d+)\s+\|", utilization, "LUT")),
        "slice_register": int(extract(r"\| Slice Registers\s+\|\s+(\d+)\s+\|", utilization, "FF")),
        "ramb36": int(extract(r"\|\s+RAMB36/FIFO\*\s+\|\s+(\d+)\s+\|", utilization, "RAMB36")),
        "dsp": int(extract(r"\| DSPs\s+\|\s+(\d+)\s+\|", utilization, "DSP")),
        "wns_ns": float(extract(
            r"Design Timing Summary[\s\S]*?\n\s*[-]+\s+[-]+[\s\S]*?\n\s*([-+]?\d+\.\d+)\s+",
            timing,
            "WNS",
        )),
        "report_sha256": {
            "utilization.rpt": sha256(utilization_path),
            "timing_summary.rpt": sha256(timing_path),
            "run_identity.txt": sha256(identity_path),
        },
    }


def main() -> None:
    full = point("full_h10")
    subtree = point("subtree_h4_h10")
    comparison = {
        "logical_bytes_reduction_percent": round(
            100.0 * (1.0 - subtree["logical_bytes"] / full["logical_bytes"]), 3
        ),
        "ramb36_reduction_percent": round(
            100.0 * (1.0 - subtree["ramb36"] / full["ramb36"]), 3
        ),
        "slice_lut_reduction_percent": round(
            100.0 * (1.0 - subtree["slice_lut"] / full["slice_lut"]), 3
        ),
        "slice_register_reduction_percent": round(
            100.0 * (1.0 - subtree["slice_register"] / full["slice_register"]), 3
        ),
    }
    manifest = {
        "schema_version": 1,
        "result_id": "treehash_cache_store_v0.1.0",
        "classification": "paired_out_of_context_cache_store_capability",
        "paper_comparable": False,
        "integrated": False,
        "device": "xc7a200tffg1156-2",
        "tool": "Vivado 2025.2",
        "clock_constraint_mhz": 100.0,
        "points": {"FULL_CACHE": full, "SUBTREE_CACHE_H4": subtree},
        "subtree_vs_full": comparison,
        "limitations": [
            "Cache store only; TreeHash, hash lanes, composer and signing replay are excluded.",
            "The 256-bit physical port may waste BRAM width/depth relative to a 64-bit banked implementation.",
            "Passive cache fill is verified, but cache-assisted signing latency is not measured.",
            "This is not directly comparable with the paper's full DataRAM or complete engine.",
        ],
        "source_sha256": {
            "rtl/treehash/micro_hbs_treehash_cache_store.sv": sha256(
                ROOT / "rtl" / "treehash" / "micro_hbs_treehash_cache_store.sv"
            ),
            "tb/integration/tb_micro_hbs_treehash_cache_modes.sv": sha256(
                ROOT / "tb" / "integration" / "tb_micro_hbs_treehash_cache_modes.sv"
            ),
            "experiments/synth_treehash_cache_store.tcl": sha256(
                ROOT / "experiments" / "synth_treehash_cache_store.tcl"
            ),
        },
    }
    OUTPUT.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(comparison, sort_keys=True))
    print(f"wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
