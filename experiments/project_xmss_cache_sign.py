#!/usr/bin/env python3
"""Project XMSS h10/w4 Hash floors for the implemented cache policies."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model.treehash import storage_latency_projection


OUTPUT = ROOT / "manifests" / "experiments" / "xmss_cache_sign_projection_v0.1.0.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ideal_p2_u2_cycles(permutations: int) -> int:
    return ((permutations + 1) // 2) * 12


def main() -> None:
    keygen_path = ROOT / "manifests" / "programs" / "xmss_shake256_h10_w4_keygen_v0.1.0.json"
    sign_path = ROOT / "manifests" / "programs" / "xmss_shake256_h10_w4_sign_v0.1.0.json"
    audit_path = ROOT / "manifests" / "experiments" / "workload_audit_v0.1.0.json"
    keygen = json.loads(keygen_path.read_text(encoding="utf-8"))
    sign = json.loads(sign_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))

    tree_height = int(keygen["paper_parameter_notation"]["h"])
    leaves = 1 << tree_height
    randomized_h_calls = 4
    internal_tree_calls = (leaves - 1) * randomized_h_calls
    leaf_calls = (int(keygen["shake256_calls"]) - internal_tree_calls) // leaves
    if leaf_calls * leaves + internal_tree_calls != int(keygen["shake256_calls"]):
        raise RuntimeError("XMSS Keygen workload does not decompose into equal leaves")

    core_calls = int(sign["shake256_calls"]) - int(keygen["shake256_calls"])
    core_permutations = int(sign["keccak_permutations"]) - int(keygen["keccak_permutations"])
    rows = {
        row["mode"]: row for row in storage_latency_projection(tree_height, 32, 4)
    }
    subtree = rows["SUBTREE_CACHE"]
    cold_extra_calls = (
        int(subtree["auth_recompute_leaves"]) * leaf_calls
        + int(subtree["auth_recompute_parents"]) * randomized_h_calls
    )
    paper_cycles = next(
        int(point["cycles"])
        for point in audit["points"]
        if point["id"] == "xmss_h10_w4" and point["operation"] == "sign"
    )

    points = {
        "FULL_CACHE_OR_WARM_ACTIVE_SUBTREE": {
            "shake256_calls": core_calls,
            "keccak_permutations": core_permutations,
            "ideal_p2_u2_cycles": ideal_p2_u2_cycles(core_permutations),
            "auth_cache_hits": tree_height,
            "auth_recompute_nodes": 0,
        },
        "SUBTREE_UPPER_ONLY_COLD": {
            "shake256_calls": core_calls + cold_extra_calls,
            "keccak_permutations": core_permutations + cold_extra_calls,
            "ideal_p2_u2_cycles": ideal_p2_u2_cycles(core_permutations + cold_extra_calls),
            "auth_cache_hits": int(subtree["auth_cache_hits"]),
            "auth_cache_misses": int(subtree["auth_cache_misses"]),
            "auth_recompute_leaves": int(subtree["auth_recompute_leaves"]),
            "auth_recompute_parents": int(subtree["auth_recompute_parents"]),
            "auth_recompute_nodes": int(subtree["auth_recompute_node_upper_bound"]),
        },
        "TREEHASH_MIN": {
            "shake256_calls": int(sign["shake256_calls"]),
            "keccak_permutations": int(sign["keccak_permutations"]),
            "ideal_p2_u2_cycles": ideal_p2_u2_cycles(int(sign["keccak_permutations"])),
            "auth_recompute_nodes": int(rows["TREEHASH_MIN"]["auth_recompute_node_upper_bound"]),
        },
    }
    for point in points.values():
        point["ideal_floor_over_non_strict_paper_cycles"] = round(
            int(point["ideal_p2_u2_cycles"]) / paper_cycles, 6
        )

    manifest = {
        "schema_version": 1,
        "result_id": "xmss_cache_sign_projection_v0.1.0",
        "classification": "model_projection_not_rtl_cycles",
        "paper_comparable": False,
        "profile": keygen["profile"],
        "assumptions": {
            "parallel_lanes": 2,
            "keccak_round_unroll": 2,
            "cycles_per_permutation": 12,
            "perfect_lane_balance": True,
            "composer_memory_control_output_cycles": 0,
            "randomized_h_shake_calls": randomized_h_calls,
            "wots_leaf_shake_calls": leaf_calls,
            "sign_core_shake_calls": core_calls,
            "sign_core_keccak_permutations": core_permutations,
        },
        "storage_projection": rows,
        "points": points,
        "non_strict_paper_reference": {
            "reported_mean_cycles": paper_cycles,
            "semantic_alignment": "structural_match_trace_unproven",
            "use": "diagnostic ratio only; not a speedup claim",
        },
        "decision": [
            "The implemented upper-only SUBTREE cache is a cold-cache storage point, not a fast-signing point.",
            "A warm active low subtree must be added to make all authentication nodes cache hits within a subtree window.",
            "All cycle values are permutation-only lower bounds and exclude the complete RTL datapath.",
        ],
        "source_sha256": {
            "model/treehash.py": sha256(ROOT / "model" / "treehash.py"),
            str(keygen_path.relative_to(ROOT)): sha256(keygen_path),
            str(sign_path.relative_to(ROOT)): sha256(sign_path),
            str(audit_path.relative_to(ROOT)): sha256(audit_path),
        },
    }
    OUTPUT.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(points, sort_keys=True))
    print(f"wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
