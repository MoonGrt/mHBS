#!/usr/bin/env python3
"""Optimize SLH-DSA Hash scheduling from the executed generic microcode trace."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.interpreter import MicroInterpreter  # noqa: E402
from model.microcode_assembler import load_and_assemble  # noqa: E402
from model.microcode_frequency import profile_microcode  # noqa: E402
from model.microcode_hash_schedule import (  # noqa: E402
    extract_hash_tasks,
    schedule_hash_tasks,
)
from model.reference.slh_dsa import SLH_DSA_SHAKE_128F, sign_internal  # noqa: E402


SIGN_KAT = ROOT / "tests/kat/slh_dsa_shake_128f_siggen_acvp_tc137.json"
KEYGEN_KAT = ROOT / "tests/kat/slh_dsa_shake_128f_keygen_acvp_tc31.json"
PROGRAMS = {
    "keygen": ROOT / "microcode/slh_dsa/slh_dsa_shake_128f_keygen.json",
    "sign": ROOT / "microcode/slh_dsa/slh_dsa_shake_128f_sign.json",
    "verify": ROOT / "microcode/slh_dsa/slh_dsa_shake_128f_verify.json",
}


def _reduction(before: int, after: int) -> float:
    return (before - after) / before if before else 0.0


def build_report() -> dict[str, Any]:
    sign_vector = json.loads(SIGN_KAT.read_text(encoding="utf-8"))
    key_vector = json.loads(KEYGEN_KAT.read_text(encoding="utf-8"))
    secret_key = bytes.fromhex(sign_vector["sk"])
    public_key = bytes.fromhex(sign_vector["pk"])
    message = bytes.fromhex(sign_vector["message"])
    signature = sign_internal(SLH_DSA_SHAKE_128F, message, secret_key)
    jobs = {
        "keygen": {
            "sk_seed": bytes.fromhex(key_vector["sk_seed"]),
            "sk_prf": bytes.fromhex(key_vector["sk_prf"]),
            "pub_seed": bytes.fromhex(key_vector["pk_seed"]),
        },
        "sign": {
            "sk_seed": secret_key[:16],
            "sk_prf": secret_key[16:32],
            "pub_seed": secret_key[32:48],
            "root": secret_key[48:64],
            "message": message,
        },
        "verify": {
            "signature": signature,
            "pub_seed": public_key[:16],
            "public_root": public_key[16:],
            "message": message,
        },
    }
    expected_outputs = {
        "keygen": bytes.fromhex(key_vector["pk"])[16:],
        "sign": signature,
        "verify": public_key[16:],
    }

    operations: dict[str, Any] = {}
    output_checks: dict[str, bool] = {}
    for operation, program_path in PROGRAMS.items():
        image = load_and_assemble(program_path)
        execution = MicroInterpreter(image, trace_mode="full").execute(jobs[operation])
        if not execution.done:
            raise RuntimeError(f"{operation} microcode failed: {execution.error}")
        tasks = extract_hash_tasks(execution)
        profile = profile_microcode(image, execution)
        fixed = profile["fixed_hash_granularity_schedule"]
        schedules: dict[str, Any] = {}
        configurations = (
            ("program_order_w1", "program_order", 1),
            ("fifo_w4", "window_fifo", 4),
            ("fifo_w16", "window_fifo", 16),
            ("critical_w4", "window_critical", 4),
            ("critical_w16", "window_critical", 16),
            ("critical_w64", "window_critical", 64),
            ("critical_w256", "window_critical", 256),
        )
        for name, policy, window in configurations:
            for overhead in (0, 3):
                schedules[f"{name}_wrapper{overhead}"] = schedule_hash_tasks(
                    tasks,
                    policy=policy,
                    window_entries=window,
                    lanes=2,
                    unroll=2,
                    issue_width=1,
                    request_fifo_depth=4,
                    hash_overhead_cycles=overhead,
                ).summary()
        selected = schedules["fifo_w16_wrapper0"]
        output_checks[operation] = execution.output == expected_outputs[operation]
        operations[operation] = {
            "microcode": {
                "static_words": profile["static_words"],
                "opcode_types": len(profile["static_opcode_counts"]),
                "opcode_names": sorted(profile["static_opcode_counts"]),
                "dynamic_instructions": profile["dynamic_instructions"],
                "hash_calls": len(tasks),
                "interpreter_hash_calls": execution.counters["hash_calls"],
                "keccak_permutations": sum(
                    task.permutations for task in tasks
                ),
                "interpreter_keccak_permutations": execution.counters[
                    "keccak_permutations"
                ],
            },
            "trace_dependencies": {
                "tasks_with_dependencies": sum(
                    bool(task.dependencies) for task in tasks
                ),
                "maximum_dependencies_per_task": max(
                    (len(task.dependencies) for task in tasks), default=0
                ),
                "all_dependencies_point_backward": all(
                    dependency < task.task_id
                    for task in tasks
                    for dependency in task.dependencies
                ),
            },
            "current_fixed_mapping": fixed,
            "schedules": schedules,
            "selected_generic_window": {
                "entries": 16,
                "policy": "FIFO among ready requests",
                "hash_cycles": selected["hash_cycles"],
                "lane_utilization": selected["lane_utilization"],
                "cycle_reduction_vs_current_fixed_mapping": _reduction(
                    fixed["hash_cycles"], selected["hash_cycles"]
                ),
            },
        }

    checks = {
        "all_microcode_outputs_match": all(output_checks.values()),
        "operation_output_checks": output_checks,
        "all_trace_dependencies_point_backward": all(
            record["trace_dependencies"]["all_dependencies_point_backward"]
            for record in operations.values()
        ),
        "all_hash_counts_preserved": all(
            record["microcode"]["hash_calls"]
            == record["microcode"]["interpreter_hash_calls"]
            and record["microcode"]["keccak_permutations"]
            == record["microcode"]["interpreter_keccak_permutations"]
            for record in operations.values()
        ),
        "all_schedules_preserve_active_work": all(
            schedule["active_lane_cycles"]
            == (
                record["microcode"]["keccak_permutations"] * 12
                + record["microcode"]["hash_calls"]
                * schedule["configuration"]["hash_overhead_cycles"]
            )
            for record in operations.values()
            for schedule in record["schedules"].values()
        ),
        "no_algorithm_specific_macro_opcodes": all(
            not {
                "JOB_CONFIG",
                "SIG_CONFIG",
                "TREE_CONFIG",
                "CHAIN_ISSUE",
                "HASH_ISSUE",
                "OUTPUT_CONFIG",
            }.intersection(record["microcode"]["opcode_names"])
            for record in operations.values()
        ),
    }
    sources = (
        ROOT / "model/interpreter.py",
        ROOT / "model/microcode_hash_schedule.py",
        ROOT / "scripts/simulate_microcode_hash_schedule.py",
        ROOT / "tests/test_microcode_hash_schedule.py",
        *PROGRAMS.values(),
        SIGN_KAT,
        KEYGEN_KAT,
    )
    return {
        "schema_version": 1,
        "result_id": "slh_dsa_microcode_hash_schedule_v0.1.0",
        "classification": "MICROCODE_TRACE_MODEL_ONLY_NO_RTL_CHANGE",
        "parameter_set": SLH_DSA_SHAKE_128F.name,
        "architecture_contract": {
            "isa": "generic 12-op micro-ISA v0.2",
            "static_microcode_unchanged": True,
            "algorithm_specific_macro_opcodes": [],
            "hash_request_sources": ["HASH", "TREE_PUSH"],
            "dependency_source": "executed generic microcode provenance trace",
            "equivalent_hash_lanes": 2,
            "selected_issue_window_entries": 16,
            "selected_issue_policy": "FIFO among ready requests",
            "physical_request_fifo_entries": 4,
        },
        "timing_scope": {
            "included": [
                "every Hash emitted by the executed microcode",
                "Scratchpad/register/control provenance dependencies",
                "TREE_PUSH internal parent Hash dependencies",
                "bounded generic issue window and request FIFO",
            ],
            "excluded": [
                "non-Hash instruction execution cycles",
                "RTL Scratchpad port conflicts",
                "composer and signature-output cycles",
                "placement, routing, and clock timing",
            ],
        },
        "operations": operations,
        "checks": checks,
        "source_sha256": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sources
        },
        "status": "PASS" if all(
            value if isinstance(value, bool) else all(value.values())
            for value in checks.values()
        ) else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    report = build_report()
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
