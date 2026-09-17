#!/usr/bin/env python3
"""Build and schedule complete SLH-DSA-SHAKE-128f Hash DAGs."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.interpreter import MicroInterpreter  # noqa: E402
from model.microcode_assembler import load_and_assemble  # noqa: E402
from model.microcode_frequency import profile_microcode  # noqa: E402
from model.reference.slh_dsa import (  # noqa: E402
    SLH_DSA_SHAKE_128F,
    keygen_internal,
    shake_permutations,
    sign_internal,
    verify_internal,
)
from model.slh_dsa_schedule import (  # noqa: E402
    HashTaskGraph,
    ScheduleConfig,
    build_keygen_graph,
    build_sign_graph,
    build_verify_graph,
    phase_counts,
    schedule_graph,
)


SIGN_KAT = ROOT / "tests/kat/slh_dsa_shake_128f_siggen_acvp_tc137.json"
KEYGEN_KAT = ROOT / "tests/kat/slh_dsa_shake_128f_keygen_acvp_tc31.json"
SIGN_PROGRAM = ROOT / "microcode/slh_dsa/slh_dsa_shake_128f_sign.json"
KEYGEN_PROGRAM = ROOT / "microcode/slh_dsa/slh_dsa_shake_128f_keygen.json"
VERIFY_PROGRAM = ROOT / "microcode/slh_dsa/slh_dsa_shake_128f_verify.json"


def parse_kxu(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"(?:K)?([1-9][0-9]*)[xX](?:U)?([1-9][0-9]*)", value)
    if not match:
        raise argparse.ArgumentTypeError("configuration must look like 2x2 or K2xU2")
    return int(match.group(1)), int(match.group(2))


def reference_profile(callable_: Any) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    permutations = 0

    def observe(kind: str, data: bytes, value: bytes) -> None:
        nonlocal permutations
        counts[kind] += 1
        permutations += shake_permutations(len(data), len(value))

    value = callable_(observe)
    return {
        "value": value,
        "hash_class_counts": dict(sorted(counts.items())),
        "hash_calls": sum(counts.values()),
        "keccak_permutations": permutations,
    }


def graph_record(graph: HashTaskGraph, reference: dict[str, Any]) -> dict[str, Any]:
    counts = graph.hash_class_counts()
    checks = {
        "hash_class_counts_match_reference": counts == reference["hash_class_counts"],
        "hash_calls_match_reference": len(graph.tasks) == reference["hash_calls"],
        "permutations_match_reference": graph.permutation_count
        == reference["keccak_permutations"],
    }
    if graph.signature_bytes:
        graph.validate_signature_map()
        checks["signature_map_complete"] = True
    return {
        "hash_tasks": len(graph.tasks),
        "keccak_permutations": graph.permutation_count,
        "hash_class_counts": counts,
        "phase_counts": phase_counts(graph),
        "signature_bytes": graph.signature_bytes,
        "checks": checks,
    }


def schedule_detail(graph: HashTaskGraph, result: Any) -> dict[str, Any]:
    lane_classes: dict[int, Counter[str]] = defaultdict(Counter)
    phase_lanes: dict[str, Counter[str]] = defaultdict(Counter)
    rows = []
    for task in graph.tasks:
        lane = result.task_lane[task.task_id]
        lane_classes[lane][task.hash_class] += 1
        family = ":".join(task.phase.split(":")[:2])
        phase_lanes[family][str(lane)] += 1
        rows.append(
            {
                "task_id": task.task_id,
                "name": task.name,
                "phase": task.phase,
                "hash_class": task.hash_class,
                "permutations": task.permutations,
                "dependencies": list(task.dependencies),
                "lane": lane,
                "start": result.task_start[task.task_id],
                "finish": result.task_finish[task.task_id],
                "signature_offset": task.signature_offset,
                "signature_bytes": task.signature_bytes,
            }
        )
    ordered = sorted(rows, key=lambda row: (row["start"], row["lane"], row["task_id"]))
    return {
        "lane_hash_class_counts": {
            str(lane): dict(sorted(counts.items()))
            for lane, counts in sorted(lane_classes.items())
        },
        "phase_lane_task_counts": {
            phase: dict(sorted(counts.items()))
            for phase, counts in sorted(phase_lanes.items())
        },
        "timeline_head": ordered[:32],
        "timeline_tail": ordered[-32:],
        "rows": rows,
    }


def write_trace(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")))
            handle.write("\n")


def microcode_profile(program: Path, job: dict[str, bytes]) -> dict[str, Any]:
    image = load_and_assemble(program)
    result = MicroInterpreter(image, trace_mode="full").execute(job)
    if not result.done:
        raise RuntimeError(f"microprogram {program.name} failed: {result.error}")
    return profile_microcode(image, result)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--operation",
        choices=("keygen", "sign", "verify", "all"),
        default="all",
    )
    parser.add_argument(
        "--config",
        type=parse_kxu,
        action="append",
        help="KxU configuration, for example 2x2; repeat for a matrix",
    )
    parser.add_argument("--issue-width", type=int, default=1)
    parser.add_argument("--hash-overhead-cycles", type=int, default=3)
    parser.add_argument("--output-bytes-per-cycle", type=int, default=8)
    parser.add_argument(
        "--policy", choices=("fifo", "critical", "signature"), default="critical"
    )
    parser.add_argument("--json-out", type=Path)
    parser.add_argument(
        "--trace-dir",
        type=Path,
        help="write one complete gzip JSONL task-to-lane trace per operation/config",
    )
    parser.add_argument("--skip-microcode-profile", action="store_true")
    args = parser.parse_args()
    configurations = args.config or [(1, 1), (1, 2), (2, 1), (2, 2), (4, 2)]

    sign_vector = json.loads(SIGN_KAT.read_text(encoding="utf-8"))
    key_vector = json.loads(KEYGEN_KAT.read_text(encoding="utf-8"))
    secret_key = bytes.fromhex(sign_vector["sk"])
    public_key = bytes.fromhex(sign_vector["pk"])
    message = bytes.fromhex(sign_vector["message"])

    sign_reference = reference_profile(
        lambda observe: sign_internal(
            SLH_DSA_SHAKE_128F, message, secret_key, observe=observe
        )
    )
    signature = sign_reference.pop("value")
    verify_reference = reference_profile(
        lambda observe: verify_internal(
            SLH_DSA_SHAKE_128F,
            message,
            signature,
            public_key,
            observe=observe,
        )
    )
    verify_value = verify_reference.pop("value")
    key_reference = reference_profile(
        lambda observe: keygen_internal(
            SLH_DSA_SHAKE_128F,
            bytes.fromhex(key_vector["sk_seed"]),
            bytes.fromhex(key_vector["sk_prf"]),
            bytes.fromhex(key_vector["pk_seed"]),
            observe=observe,
        )
    )
    generated_secret, generated_public = key_reference.pop("value")

    correctness = {
        "nist_tc137_signature_sha256": hashlib.sha256(signature).hexdigest()
        == sign_vector["signature_sha256"],
        "nist_tc137_randomizer": signature[:16].hex() == sign_vector["signature_r"],
        "nist_tc137_verifies": verify_value is True,
        "nist_tc31_secret_key": generated_secret.hex() == key_vector["sk"],
        "nist_tc31_public_key": generated_public.hex() == key_vector["pk"],
    }

    all_graphs = {
        "keygen": (build_keygen_graph(), key_reference),
        "sign": (build_sign_graph(message, secret_key), sign_reference),
        "verify": (build_verify_graph(message, signature, public_key), verify_reference),
    }
    selected = all_graphs if args.operation == "all" else {
        args.operation: all_graphs[args.operation]
    }
    graph_records: dict[str, Any] = {}
    schedules: dict[str, Any] = {}
    for operation, (graph, reference) in selected.items():
        graph_records[operation] = graph_record(graph, reference)
        schedules[operation] = {}
        for lanes, unroll in configurations:
            config = ScheduleConfig(
                lanes=lanes,
                unroll=unroll,
                issue_width=args.issue_width,
                hash_overhead_cycles=args.hash_overhead_cycles,
                output_bytes_per_cycle=args.output_bytes_per_cycle,
                policy=args.policy,
            )
            result = schedule_graph(graph, config)
            detail = schedule_detail(graph, result)
            key = f"K{lanes}xU{unroll}"
            schedules[operation][key] = {
                **result.summary(),
                "lane_hash_class_counts": detail["lane_hash_class_counts"],
                "phase_lane_task_counts": detail["phase_lane_task_counts"],
                "timeline_head": detail["timeline_head"],
                "timeline_tail": detail["timeline_tail"],
            }
            if args.trace_dir:
                write_trace(
                    args.trace_dir / f"slh_dsa_{operation}_{key}.jsonl.gz",
                    detail["rows"],
                )

    microcode: dict[str, Any] = {}
    if not args.skip_microcode_profile:
        sign_job = {
            "sk_seed": secret_key[:16],
            "sk_prf": secret_key[16:32],
            "pub_seed": secret_key[32:48],
            "root": secret_key[48:64],
            "message": message,
        }
        key_job = {
            "sk_seed": bytes.fromhex(key_vector["sk_seed"]),
            "sk_prf": bytes.fromhex(key_vector["sk_prf"]),
            "pub_seed": bytes.fromhex(key_vector["pk_seed"]),
        }
        verify_job = {
            "signature": signature,
            "pub_seed": public_key[:16],
            "public_root": public_key[16:],
            "message": message,
        }
        microcode["slh_dsa_sign"] = microcode_profile(SIGN_PROGRAM, sign_job)
        microcode["slh_dsa_keygen"] = microcode_profile(KEYGEN_PROGRAM, key_job)
        microcode["slh_dsa_verify"] = microcode_profile(VERIFY_PROGRAM, verify_job)

    checks = list(correctness.values())
    for record in graph_records.values():
        checks.extend(record["checks"].values())
    report = {
        "schema_version": 1,
        "result_id": "slh_dsa_hash_schedule_v0.1.0",
        "model": "complete_hash_granularity_dependency_schedule",
        "parameter_set": SLH_DSA_SHAKE_128F.name,
        "classification": "algorithm_dependency_aware_theoretical_schedule",
        "paper_comparable": False,
        "timing_contract": {
            "task_atomicity": "one complete SHAKE call stays on one lane",
            "permutation_cycles": "ceil(24/U)",
            "default_hash_wrapper_overhead_cycles": args.hash_overhead_cycles,
            "issue_width": args.issue_width,
            "dependencies": "FIPS 205 data dependencies plus canonical signature producer map",
            "excluded": [
                "RTL placement and routing delay",
                "Scratchpad bank conflicts",
                "finite ready-queue capacity",
                "template-builder structural hazards",
            ],
        },
        "correctness": correctness,
        "graphs": graph_records,
        "schedules": schedules,
        "existing_microcode_frequency": microcode,
        "microcode_guidance": {
            "isa": "generic 12-op micro-ISA v0.2",
            "algorithm_specific_opcodes": False,
            "static_rom_words_max": 256,
            "instruction_width_bits": 64,
            "issue_width": 1,
            "zero_overhead_loops": True,
            "optimization_scope": [
                "compiler ordering of generic Hash and Tree instructions",
                "configurable component and layout descriptors",
                "equivalent Hash lanes with descriptor-selected lane masks",
                "generic lane-local feedback",
            ],
            "K2xU2_resources": {
                "request_fifo_entries": 4,
                "completion_tag_entries": 4,
                "lane_feedback_bytes_each": 16,
                "recommended_policy": "fifo",
                "signature_reorder_bytes_for_fifo_schedule": 96,
            },
            "tc137_analytical_context_counts_not_opcodes": {
                "keygen": {
                    "chain_contexts": 280,
                    "other_hash_requests": 15,
                    "total_crypto_descriptors": 295,
                },
                "sign": {
                    "chain_contexts": 8272,
                    "other_hash_requests": 2408,
                    "total_crypto_descriptors": 10680,
                },
                "verify": {
                    "chain_contexts": 803,
                    "other_hash_requests": 288,
                    "total_crypto_descriptors": 1091,
                },
            },
        },
        "evidence": {
            "command": (
                "python3 scripts/simulate_slh_dsa_hash_schedule.py "
                "--json-out manifests/experiments/"
                "slh_dsa_hash_schedule_v0.1.0.json "
                "--trace-dir build/schedules/slh_dsa_kxu"
            ),
            "complete_task_trace_format": "gzip JSONL, one task-to-lane assignment per line",
        },
        "source_sha256": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (
                ROOT / "model/slh_dsa_schedule.py",
                ROOT / "model/microcode_frequency.py",
                ROOT / "model/reference/slh_dsa.py",
                ROOT / "scripts/simulate_slh_dsa_hash_schedule.py",
                ROOT / "tests/test_slh_dsa_schedule.py",
                SIGN_PROGRAM,
                KEYGEN_PROGRAM,
                VERIFY_PROGRAM,
                SIGN_KAT,
                KEYGEN_KAT,
            )
        },
        "status": "PASS" if all(checks) else "FAIL",
    }
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
