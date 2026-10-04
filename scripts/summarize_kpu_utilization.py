#!/usr/bin/env python3
"""Recompute utilization summaries from archived, source-bound stage traces."""
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "manifests/analysis/k2p4u2_utilization_20261008"
MATRIX = ROOT / "manifests/experiments/kpu_cycle_synth_20261008_v1"
NAMES = [
    "FORS batches", "WOTS full batches", "WOTS tail batches",
    "Shortened WOTS full batches", "Shortened WOTS tail batches",
    "Ordinary parent requests", "Ordinary list requests",
    "Message requests", "Controller",
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(point):
    path = OUT / point / "results.json"
    data = json.loads(path.read_text())
    area = json.loads((MATRIX / point / "synthesis.json").read_text())["area"]
    assert data["passed"]
    for filename, digest in data["rtl_sha256"].items():
        assert sha(ROOT / filename) == digest, filename
    assert sha(OUT / point / "simulation.log") == data["log_sha256"]
    assert sha(OUT / point / "probe.svh") == data["probe_sha256"]
    assert sha(OUT / point / "actual.mem") == data["reference"]["output_sha256"]
    trace = data["profile"]
    cycles, work = (trace["total"][0][key] for key in ("cycles", "work"))
    slots = data["lanes"] * data["pipeline"]
    unroll = data["unroll"]
    assert cycles == data["reference"]["sign_cycles"]
    assert work * unroll == data["reference"]["permutations"] * 24
    assert sum(r["cycles"] for r in trace["occupancy"]) == cycles
    assert sum(r["cycles"] * r["active"] for r in trace["occupancy"]) == work
    assert sum(r["work"] for r in trace["stage"]) == work
    assert sum(r["cycles"] for r in trace["class"]) == cycles
    assert sum(r["work"] for r in trace["class"]) == work
    assert sum(r["permutations"] for r in trace["lane"]) == data["reference"]["permutations"]
    gap = cycles - work / slots
    classes = []
    for row in trace["class"]:
        lost = row["cycles"] - row["work"] / slots
        classes.append(dict(
            point=point, kind=row["kind"], category=NAMES[row["kind"]],
            cycles=row["cycles"], work_stage_cycles=row["work"] ,
            zero_work_cycles=row["zero"],
            time_share_percent=100 * row["cycles"] / cycles,
            utilization_percent=100 * row["work"] / (slots * row["cycles"]),
            unused_capacity_equivalent_cycles=lost,
            share_of_unused_capacity_percent=100 * lost / gap,
        ))
    assert sum(r["unused_capacity_equivalent_cycles"] for r in classes) == gap
    mhz = 150 if unroll == 1 else 110
    return dict(
        point=point, cycles=cycles, work_stage_cycles=work,
        useful_rounds=work * unroll, round_capacity=cycles * slots * unroll,
        utilization_percent=100 * work / (cycles * slots),
        work_lower_bound_cycles=work / slots,
        unused_capacity_equivalent_cycles=gap,
        all_idle_cycles=trace["occupancy"][0]["cycles"],
        equivalent_slice=area["equivalent_slice"], assumed_mhz=mhz,
        estimated_time_ms=cycles / (1000 * mhz),
        estimated_atp=area["equivalent_slice"] * cycles / (1000 * mhz),
        classes=classes, source_results_sha256=sha(path),
    )


def main():
    points = [summarize(p) for p in ("K2P4U2", "K2P4U1", "K2P3U2")]
    base = points[0]
    sensitivity = []
    for label, saved in (("One cycle per parent", 2230),
                         ("WOTS PIPE_LOAD plus CHAIN_STORE budget", 6336),
                         ("Eight feed cycles per list block budget", 7040)):
        cycles = base["cycles"] - saved
        sensitivity.append(dict(
            scenario=label, hypothetical_saved_cycles=saved, cycles=cycles,
            utilization_percent=100 * base["work_lower_bound_cycles"] / cycles,
            estimated_atp=base["equivalent_slice"] * cycles / 110000,
        ))
    summary = dict(
        schema_version=1, points=points, hypothetical_sensitivity=sensitivity,
        sensitivity_caveat="Not implemented or measured savings; constant area/frequency assumed; do not add overlapping budgets.",
        definitions=dict(work="Productive pipeline stage-cycles; each performs U rounds.",
                         unused_capacity="cycles - work/(K*P); not a claim of recoverable wall time."),
    )
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    rows = [row for p in points for row in p["classes"]]
    with (OUT / "categories.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    evidence = {str(p.relative_to(ROOT)): sha(p) for p in sorted(OUT.rglob("*"))
                if p.is_file() and p.name != "evidence_sha256.json"}
    for name in ("profile_kpu_utilization.py", "summarize_kpu_utilization.py"):
        evidence[f"scripts/{name}"] = sha(ROOT / "scripts" / name)
    (OUT / "evidence_sha256.json").write_text(json.dumps(evidence, indent=2) + "\n")
    for p in points:
        print(f'{p["point"]}: {p["cycles"]:,} cycles, {p["utilization_percent"]:.6f}% utilization, checks PASS')


if __name__ == "__main__":
    main()
