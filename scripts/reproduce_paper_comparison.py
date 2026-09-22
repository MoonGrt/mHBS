#!/usr/bin/env python3
"""Recalculate the paper comparison from archived PDF tables and U2 evidence.

This checks the report's headline numbers without rerunning a long Vivado route.
The separate Makefile targets regenerate the RTL cycles and routed netlists.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
READER = REPO / "references/papers/Unified_HBS_Architecture_2026_Reader"
ARCHIVE = ROOT / "manifests/experiments"
REPORT = ROOT / "docs/Unified_HBS_Paper_Comparison.md"
FAMILIES = {
    "slh": ("SPHINCS+", "n=128", 0),
    "xmss": ("XMSS", "h=10;w=4", 1),
    "lms": ("LMS", "h=10;w=4", 2),
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def same(actual: float, expected: float, label: str) -> None:
    require(math.isclose(float(actual), float(expected), rel_tol=1e-11, abs_tol=1e-9),
            f"{label}: {actual} != {expected}")


def utilization(report: str, label: str) -> int:
    match = re.search(r"^\|\s*" + re.escape(label) + r"\s*\|\s*([\d,]+)\s*\|", report, re.M)
    require(match is not None, f"missing utilization row: {label}")
    return int(match.group(1).replace(",", ""))


def main() -> None:
    final = json.loads((ARCHIVE / "unified_hbs_final.json").read_text())
    comparison = json.loads((ARCHIVE / "unified_hbs_paper_comparison.json").read_text())
    tables = json.loads((READER / "data/paper_tables.json").read_text())["tables"]
    pdf = REPO / "references/papers/Unified_Stateful_Stateless_HBS_Architecture_2026.pdf"
    require(hashlib.sha256(pdf.read_bytes()).hexdigest() == comparison["paper_sha256"],
            "paper PDF digest changed")
    require(hashlib.sha256((ARCHIVE / "unified_hbs_final.json").read_bytes()).hexdigest()
            == comparison["current_source_sha256"], "final manifest digest changed")
    with (ARCHIVE / "unified_hbs_paper_comparison.csv").open(newline="") as stream:
        csv_rows = list(csv.DictReader(stream))
    report = REPORT.read_text()
    require(len(csv_rows) == len(comparison["rows"]) == 3, "comparison must have three rows")

    for family, (scheme, parameter, profile_id) in FAMILIES.items():
        row = next(r for r in comparison["rows"] if r["family"] == family)
        table5 = next(r for r in tables["table5"]["rows"]
                      if r[0] == scheme and r[1].replace("omega=", "w=") == parameter)
        table7 = next(r for r in tables["table7"]["rows"]
                      if r[0] == scheme and r[1] == "This work" and r[2] == parameter)
        archived = ARCHIVE / "unified_hbs_v3" / f"{family}_u2"
        raw_util = (archived / "utilization.rpt").read_text()
        raw_clock = json.loads((archived / "final_clock.json").read_text())
        raw_ppa = json.loads((archived / "ppa.json").read_text())
        raw_input = json.loads((archived / "inputs.json").read_text())
        timing = (archived / "timing_summary.rpt").read_text()
        status = (archived / "route_status.rpt").read_text()
        normal = (ARCHIVE / "unified_hbs_v3" / f"{family}_u2_normal.log").read_text()
        match = re.search(r"UNIFIED_PASS profile=(\d+) keygen_cycles=(\d+) sign_cycles=(\d+)", normal)
        require(match is not None and int(match[1]) == profile_id, f"{family}: missing cycle record")
        kg_cycles, sign_cycles = int(match[2]), int(match[3])

        for path, digest in raw_input["source_sha256"].items():
            source = ROOT / path
            if path == "experiments/route_unified_hbs.tcl":
                # Captured at synthesis; the final route flow has its own digest.
                route_input = json.loads((archived / "route_inputs.json").read_text())
                require(hashlib.sha256(source.read_bytes()).hexdigest() == route_input["script_sha256"],
                        f"{family}: final route flow changed")
                continue
            require(source.exists() and hashlib.sha256(source.read_bytes()).hexdigest() == digest,
                    f"{family}: source changed or removed: {path}")
        require(raw_ppa["source_set_sha256"] == raw_input["source_set_sha256"],
                f"{family}: source set mismatch")
        require(raw_ppa["final_pass"] and final["profiles"][family]["final_pass"],
                f"{family}: routed acceptance did not pass")
        require((archived / "route_status.rpt").exists() and (archived / "check_timing.rpt").exists(),
                f"{family}: missing route/timing evidence")
        clock_line = re.search(r"^clk\s+\{[^}]+\}\s+([\d.]+)", timing, re.M)
        require(clock_line is not None, f"{family}: missing routed clock")
        same(clock_line[1], raw_clock["period_ns"], f"{family}.clock_period")
        timing_row = re.search(r"WNS\(ns\).*?\n\s*[- ]+\n([^\n]+)", timing, re.S)
        require(timing_row is not None, f"{family}: missing timing summary")
        timing_fields = timing_row[1].split()
        for key, position in (("wns_ns", 0), ("tns_ns", 1),
                              ("whs_ns", 4), ("ths_ns", 5),
                              ("wpws_ns", 8), ("tpws_ns", 9)):
            same(timing_fields[position], raw_ppa[key], f"{family}.timing.{key}")
        route_counts = raw_ppa["route_counts"]
        for label, key in (("routable nets", "routable nets"),
                           ("fully routed nets", "fully routed nets"),
                           ("nets with routing errors", "nets with routing errors")):
            count = re.search(re.escape(label) + r"[^\d\n]*?(\d+)", status, re.I)
            require(count is not None and int(count[1]) == route_counts[key],
                    f"{family}: {label} differs from route status")

        lut = utilization(raw_util, "Slice LUTs")
        ff = utilization(raw_util, "Slice Registers")
        bram = utilization(raw_util, "Block RAM Tile")
        dsp = utilization(raw_util, "DSPs")
        lutram = utilization(raw_util, "LUT as Memory")
        area = lut / 4 + ff / 8 + bram * 232.4 + dsp * 102.4
        p_lut, p_ff, p_bram, p_dsp, frequency = table7[3:8]
        p_area = p_lut / 4 + p_ff / 8 + p_bram * 232.4 + p_dsp * 102.4
        period = raw_clock["period_ns"]
        kg_ms = kg_cycles * period / 1e6
        sign_ms = sign_cycles * period / 1e6
        p_kg_ms, p_sign_ms = table5[3], table5[5]
        p_kg_atp, p_sign_atp = p_area * p_kg_ms, p_area * p_sign_ms
        kg_atp, sign_atp = area * kg_ms, area * sign_ms

        checks = {
            "paper_lut": p_lut, "paper_ff": p_ff, "paper_bram36": p_bram,
            "paper_dsp": p_dsp, "paper_eq_slice": p_area,
            "paper_frequency_mhz": frequency, "paper_keygen_cycles": table5[2],
            "paper_sign_cycles": table5[4], "paper_keygen_ms": p_kg_ms,
            "paper_sign_ms": p_sign_ms, "current_lut": lut, "current_ff": ff,
            "current_bram36": bram, "current_dsp": dsp, "current_lutram": lutram,
            "current_eq_slice": area, "current_frequency_mhz": 1000 / period,
            "current_keygen_cycles": kg_cycles, "current_sign_cycles": sign_cycles,
            "current_keygen_ms": kg_ms, "current_sign_ms": sign_ms,
            "current_unroll": raw_input["unroll"], "current_lanes": raw_input["lanes"],
            "paper_keygen_atp": p_kg_atp, "current_keygen_atp": kg_atp,
            "keygen_cycles_ratio": kg_cycles / table5[2],
            "keygen_ms_ratio": kg_ms / p_kg_ms,
            "keygen_atp_ratio": kg_atp / p_kg_atp,
            "paper_keygen_ms_from_108mhz": table5[2] / (frequency * 1000),
            "current_keygen_ms_at_108mhz": kg_cycles / (frequency * 1000),
            "paper_keygen_atp_from_108mhz": p_area * table5[2] / (frequency * 1000),
            "paper_sign_atp": p_sign_atp, "current_sign_atp": sign_atp,
            "sign_cycles_ratio": sign_cycles / table5[4],
            "sign_ms_ratio": sign_ms / p_sign_ms,
            "sign_atp_ratio": sign_atp / p_sign_atp,
            "paper_sign_ms_from_108mhz": table5[4] / (frequency * 1000),
            "current_sign_ms_at_108mhz": sign_cycles / (frequency * 1000),
            "paper_sign_atp_from_108mhz": p_area * table5[4] / (frequency * 1000),
            "area_ratio": area / p_area,
            "paper_kg_sign_sum_ms": p_kg_ms + p_sign_ms,
            "current_kg_sign_lifecycle_ms": (kg_cycles + sign_cycles + 4) * period / 1e6,
            "paper_kg_sign_sum_atp": p_area * (p_kg_ms + p_sign_ms),
            "current_kg_sign_lifecycle_atp": area * (kg_cycles + sign_cycles + 4) * period / 1e6,
        }
        checks["lifecycle_atp_ratio"] = checks["current_kg_sign_lifecycle_atp"] / checks["paper_kg_sign_sum_atp"]
        for key, value in checks.items():
            same(row[key], value, f"{family}.{key}")
        require(abs(row["sign_target"] - p_sign_atp) <= 0.0005,
                f"{family}: three-decimal paper target differs")
        require(row["sign_target_pass"] and sign_atp < row["sign_target"],
                f"{family}: sign ATP target failed")
        for key in ("lut", "ff", "equivalent_slice", "keygen_cycles", "sign_cycles", "period_ns", "sign_atp"):
            expected = {"lut": lut, "ff": ff, "equivalent_slice": area,
                        "keygen_cycles": kg_cycles, "sign_cycles": sign_cycles,
                        "period_ns": period, "sign_atp": sign_atp}[key]
            same(raw_ppa[key], expected, f"{family}.ppa.{key}")
            same(final["profiles"][family][key], expected, f"{family}.final.{key}")
        csv_row = next(r for r in csv_rows if r["family"] == family)
        for key, value in row.items():
            if isinstance(value, bool):
                require(csv_row[key] == str(value), f"{family}.csv.{key}")
            elif isinstance(value, (int, float)):
                same(csv_row[key], value, f"{family}.csv.{key}")
            else:
                require(csv_row[key] == value, f"{family}.csv.{key}")
        for value in (f"{sign_atp:,.3f}", f"{area:,.3f}", f"{sign_ms:.6f}",
                      f"{kg_cycles:,}", f"{sign_cycles:,}"):
            require(value in report, f"{family}: report missing {value}")
        print(f"{family:4} area={area:9.3f} sign_cycles={sign_cycles:9,} "
              f"sign_ms={sign_ms:.6f} ATP={sign_atp:,.3f} "
              f"paper_ATP={p_sign_atp:,.3f} PASS")

    for family in FAMILIES:
        incomplete = ARCHIVE / "unified_hbs_v3" / f"{family}_u4_incomplete"
        require((incomplete / "status.json").exists() and
                (incomplete / "post_synth_ppa.json").exists() and
                (incomplete / "partial_route.log").exists(),
                f"{family}: requested U4 archive missing")
    print("Paper comparison, source digests, U2 evidence and retained U4 archives: PASS")


if __name__ == "__main__":
    main()
