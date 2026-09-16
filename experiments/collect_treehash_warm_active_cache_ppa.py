#!/usr/bin/env python3
"""Collect the routed h10/w4 warm active-subtree cache checkpoint."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "build" / "vivado" / "treehash_warm_active_cache_h10w4"
OUTPUT = (
    ROOT
    / "manifests"
    / "experiments"
    / "treehash_warm_active_cache_h10w4_v0.1.0.json"
)


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
    logic_lut = int(
        require(r"\|\s+LUT as Logic\s+\|\s+(\d+)\s+\|", utilization, "logic LUT")
    )
    distributed_ram_lut = int(
        require(
            r"\|\s+LUT as Distributed RAM\s+\|\s+(\d+)\s+\|",
            utilization,
            "distributed-RAM LUT",
        )
    )
    ff = int(
        require(r"\| Slice Registers\s+\|\s+(\d+)\s+\|", utilization, "FF")
    )
    ramb36 = int(
        require(r"\|\s+RAMB36/FIFO\*\s+\|\s+(\d+)\s+\|", utilization, "RAMB36")
    )
    ramb18 = int(require(r"\|\s+RAMB18\s+\|\s+(\d+)\s+\|", utilization, "RAMB18"))
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
        ROOT / "rtl" / "treehash" / "micro_hbs_treehash_warm_active_cache.sv",
        ROOT / "rtl" / "treehash" / "micro_hbs_treehash_auth_provider.sv",
        ROOT / "tb" / "integration" / "tb_micro_hbs_treehash_warm_active_cache.sv",
        ROOT / "tb" / "integration" / "tb_micro_hbs_treehash_warm_auth_integration.sv",
        ROOT / "experiments" / "synth_treehash_warm_active_cache.tcl",
        ROOT / "experiments" / "collect_treehash_warm_active_cache_ppa.py",
    ]

    manifest = {
        "schema_version": 1,
        "result_id": "treehash_warm_active_cache_h10w4_v0.1.0",
        "scope": identity["scope"],
        "classification": "out_of_context_cache_storage_ppa",
        "paper_comparable": identity["paper_comparable"] == "true",
        "integrated": identity["integrated"] == "true",
        "complete_algorithm": identity["complete_algorithm"] == "true",
        "device": identity["part"],
        "tool": identity["tool"],
        "configuration": {
            "tree_height": int(identity["tree_height"]),
            "window_height": int(identity["window_height"]),
            "node_width_bits": int(identity["node_width_bits"]),
            "upper_capacity_nodes": int(identity["upper_capacity_nodes"]),
            "active_lower_capacity_nodes": int(identity["lower_capacity_nodes"]),
            "total_capacity_nodes": int(identity["total_capacity_nodes"]),
            "logical_capacity_bytes": int(identity["logical_capacity_bytes"]),
            "activation_control": identity["activation_control"],
            "upper_retention_rule": "height >= 4, global",
            "lower_retention_rule": "height < 4, active aligned 16-leaf window",
        },
        "clock_constraint": {
            "period_ns": period_ns,
            "frequency_mhz": 1000.0 / period_ns,
        },
        "post_route": {
            "slice_lut": lut,
            "logic_lut": logic_lut,
            "distributed_ram_lut": distributed_ram_lut,
            "slice_register": ff,
            "ramb36": ramb36,
            "ramb18": ramb18,
            "ramb36_equivalent": ramb36 + ramb18 / 2.0,
            "dsp": dsp,
            "wns_ns": wns,
            "timing_met": wns >= 0.0,
        },
        "functional_result": {
            "testbench": "tb/integration/tb_micro_hbs_treehash_warm_active_cache.sv",
            "target_leaf": 5,
            "activation_examples": {"target_5_base": 0, "target_21_base": 16},
            "initial_auth_sibling_hits": 10,
            "post_switch_lower_misses": 4,
            "post_switch_upper_hits": 6,
            "activation_target_fail_closed": True,
            "busy_activation_fail_closed": True,
            "lookup_active_activation_fail_closed": True,
            "identity_bounds_fail_closed": True,
            "oracle_match": True,
            "provider_composition": {
                "external_commands_per_auth_path": 1,
                "target_5_cache_hits": 10,
                "target_21_cache_hits": 10,
                "recompute_requests": 0,
                "auth_backpressure_cycles": 2,
                "per_level_software_lookup_inputs": 0,
            },
        },
        "limitations": [
            "This is an out-of-context cache storage/control point, not a complete XMSS or SLH-DSA Sign implementation.",
            "The authentication-path provider is functionally composed in simulation but excluded from this cache-only PPA report.",
            "Window refill and authentication-node recomputation latency are not included in this PPA point.",
            "The 256-bit single-cycle node port can overprovision FPGA block-RAM width relative to logical stored bits.",
            "Wide out-of-context data ports omit integration routing and top-level package-pin placement.",
            "Vivado 2025.2 differs from the comparison paper's Vivado 2018.3 flow.",
        ],
        "report_sha256": {
            "utilization.rpt": sha256(utilization_path),
            "timing_summary.rpt": sha256(timing_path),
            "run_identity.txt": sha256(identity_path),
        },
        "source_sha256": {
            str(path.relative_to(ROOT)): sha256(path) for path in sources
        },
    }
    OUTPUT.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest["post_route"], sort_keys=True))
    print(f"wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
