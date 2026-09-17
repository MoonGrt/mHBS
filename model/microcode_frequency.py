"""Static and dynamic frequency analysis for an assembled microprogram."""

from __future__ import annotations

from collections import Counter, defaultdict
import math
from typing import Any

from model.interpreter import ExecutionResult


def profile_microcode(
    image: dict[str, Any], result: ExecutionResult, *, unroll: int = 2
) -> dict[str, Any]:
    """Summarize instruction, PC, layout, and signature-output frequency.

    ``result`` must have been produced with ``trace_mode="full"``.  Paired
    HASH events count as one instruction issue and two logical Hashes.
    TREE_PUSH reductions are included as internal parent Hash calls.
    """
    if len(result.trace) != result.counters["dynamic_instructions"]:
        raise ValueError("microcode frequency profiling requires trace_mode='full'")
    if unroll <= 0 or unroll > 24:
        raise ValueError("unroll must be in 1..24")

    static = Counter(inst.opcode.name for inst in image["instructions"])
    dynamic = Counter(str(event["opcode"]) for event in result.trace)
    pcs = Counter(int(event["pc"]) for event in result.trace)
    layouts: dict[int, Counter[str]] = defaultdict(Counter)
    hash_classes: Counter[str] = Counter()
    tree_parent_hashes = 0
    emit_bytes = 0
    rounds_cycles = math.ceil(24 / unroll)
    fixed_hash_cycles = 0
    fixed_lane_permutations = [0, 0]
    pair_instructions = 0
    for event in result.trace:
        opcode = event["opcode"]
        if opcode == "HASH":
            layout_id = int(event["layout_id"])
            logical_hashes = len(event.get("hash_lanes", ())) or 1
            layouts[layout_id]["instruction_issues"] += 1
            layouts[layout_id]["logical_hashes"] += logical_hashes
            hash_classes[str(event.get("hash_class", "unspecified"))] += logical_hashes
            lane_permutations = [0, 0]
            lane_hashes = [0, 0]
            for lane_event in event.get("hash_lanes", (event,)):
                permutations = int(lane_event["hash_input_length"]) // 136 + 1
                lane = int(lane_event.get("lane", 0))
                fixed_lane_permutations[lane] += permutations
                lane_permutations[lane] += permutations
                lane_hashes[lane] += 1
            fixed_hash_cycles += max(lane_permutations) * rounds_cycles
            pair_instructions += min(lane_hashes)
        elif opcode == "TREE_PUSH":
            reductions = int(event.get("tree_reductions", 0))
            tree_parent_hashes += reductions
            if reductions:
                layouts[int(event["layout_id"])]["tree_parent_hashes"] += reductions
                hash_classes["h"] += reductions
                # The present RTL sends blocking TreeHash parents to lane 1.
                fixed_lane_permutations[1] += reductions
                fixed_hash_cycles += reductions * rounds_cycles
        elif opcode == "OUTPUT":
            emit_bytes += int(event.get("emit_bytes", 0))

    top_pcs = [
        {"pc": pc, "opcode": image["instructions"][pc].opcode.name, "executions": count}
        for pc, count in sorted(pcs.items(), key=lambda item: (-item[1], item[0]))
    ]
    return {
        "program": image.get("name", "unnamed"),
        "program_sha256": image.get("sha256"),
        "static_words": image["word_count"],
        "static_bytes": image["image_bytes"],
        "static_opcode_counts": dict(sorted(static.items())),
        "dynamic_instructions": result.counters["dynamic_instructions"],
        "dynamic_opcode_counts": dict(sorted(dynamic.items())),
        "top_dynamic_pcs": top_pcs,
        "layout_frequency": {
            str(layout_id): dict(sorted(counts.items()))
            for layout_id, counts in sorted(layouts.items())
        },
        "hash_class_counts": dict(sorted(hash_classes.items())),
        "tree_parent_hashes": tree_parent_hashes,
        "hash_calls": result.counters["hash_calls"],
        "keccak_permutations": result.counters["keccak_permutations"],
        "emit_bytes": emit_bytes,
        "fixed_hash_granularity_schedule": {
            "unroll": unroll,
            "round_cycles_per_permutation": rounds_cycles,
            "pair_instructions": pair_instructions,
            "hash_cycles": fixed_hash_cycles,
            "lane_permutations": fixed_lane_permutations,
            "lane_active_cycles": [
                value * rounds_cycles for value in fixed_lane_permutations
            ],
            "lane_utilization": (
                sum(fixed_lane_permutations) * rounds_cycles
                / (2 * fixed_hash_cycles)
                if fixed_hash_cycles
                else 0.0
            ),
        },
    }
