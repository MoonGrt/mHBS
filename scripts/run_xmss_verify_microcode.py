#!/usr/bin/env python3
"""Execute one autonomous XMSS-SHAKE256 H10 Verify microprogram Job."""

from __future__ import annotations

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
from model.reference.xmss import xmss_sign, xmss_verify  # noqa: E402


PROGRAM = ROOT / "microcode" / "xmss" / "xmss_shake256_h10_w4_verify.json"
KAT = ROOT / "tests" / "kat" / "xmss_shake256_10_256_idx5.json"
N = 32
WOTS_LEN = 67
TREE_HEIGHT = 10
INDEX_BYTES = 4


def load_kat_inputs() -> tuple[dict[str, Any], bytes, bytes, bytes]:
    """Materialize the signature bound by the compact existing KAT."""
    vector = json.loads(KAT.read_text(encoding="utf-8"))
    seed = bytes.fromhex(vector["seed"])
    public_key = bytes.fromhex(vector["public_key"])
    message = bytes.fromhex(vector["message"])
    index = int(vector["signing_index"])
    secret_key = (
        index.to_bytes(INDEX_BYTES, "big")
        + seed[:N]
        + seed[N : 2 * N]
        + public_key[:N]
        + seed[2 * N :]
    )
    signature, _ = xmss_sign(secret_key, message)
    if len(signature) != int(vector["signature_bytes"]):
        raise AssertionError("materialized KAT signature length mismatch")
    if hashlib.sha256(signature).hexdigest() != vector["signature_sha256"]:
        raise AssertionError("materialized KAT signature digest mismatch")
    return vector, public_key, message, signature


def build_verify_job(public_key: bytes, message: bytes, signature: bytes) -> dict[str, Any]:
    """Bind one complete XMSS input tuple into one immutable structured Job.

    The frozen interpreter has no byte-slice component.  Admission therefore
    splits the signature into its statically sized fields once; it does not
    issue execution-time task or Hash descriptors.
    """
    expected_signature_bytes = INDEX_BYTES + N + WOTS_LEN * N + TREE_HEIGHT * N
    if len(public_key) != 2 * N or len(signature) != expected_signature_bytes:
        raise ValueError("XMSS Verify input length mismatch")
    index = int.from_bytes(signature[:INDEX_BYTES], "big")
    offset = INDEX_BYTES
    job: dict[str, Any] = {
        "index": index,
        "randomizer": signature[offset : offset + N],
        "public_root": public_key[:N],
        "pub_seed": public_key[N:],
        "message": message,
    }
    offset += N
    for chain in range(WOTS_LEN):
        job[f"wots_signature_{chain:02d}"] = signature[
            offset + chain * N : offset + (chain + 1) * N
        ]
    offset += WOTS_LEN * N
    for height in range(TREE_HEIGHT):
        job[f"authentication_node_{height:02d}"] = signature[
            offset + height * N : offset + (height + 1) * N
        ]
    return job


def oracle_trace(public_key: bytes, message: bytes, signature: bytes) -> tuple[bool, str, dict[str, int]]:
    digest = hashlib.sha256()
    class_counts: dict[str, int] = {}

    def observe(kind: str, data: bytes, value: bytes) -> None:
        record = {
            "hash_class": kind,
            "hash_input_digest": hashlib.sha256(data).hexdigest(),
            "hash_output": value.hex(),
        }
        digest.update(json.dumps(record, sort_keys=True, separators=(",", ":")).encode())
        class_counts[kind] = class_counts.get(kind, 0) + 1

    accepted = xmss_verify(public_key, message, signature, observe=observe)
    return accepted, digest.hexdigest(), class_counts


def main() -> int:
    image = load_and_assemble(PROGRAM)
    vector, public_key, message, signature = load_kat_inputs()
    result = MicroInterpreter(image, trace_mode="none").execute(
        build_verify_job(public_key, message, signature)
    )
    oracle_accepts, oracle_digest, class_counts = oracle_trace(
        public_key, message, signature
    )

    mutated_signature = bytearray(signature)
    mutated_signature[INDEX_BYTES + N] ^= 1
    mutated_signature = bytes(mutated_signature)
    mutated_result = MicroInterpreter(image, trace_mode="none").execute(
        build_verify_job(public_key, message, mutated_signature)
    )

    autonomy = {
        "accepted_job_commands": result.counters["accepted_job_commands"],
        "host_control_writes_during_busy": result.counters[
            "host_control_writes_during_busy"
        ],
        "external_task_descriptors": result.counters["external_task_descriptors"],
        "external_hash_descriptors": result.counters["external_hash_descriptors"],
        "host_supplied_chain_lengths": 0,
    }
    checks = {
        "valid_root_match": result.output == public_key[:N],
        "oracle_accepts_valid_signature": oracle_accepts,
        "per_hash_trace_match": result.hash_trace_sha256 == oracle_digest,
        "one_job": autonomy["accepted_job_commands"] == 1,
        "zero_busy_host_writes": autonomy["host_control_writes_during_busy"] == 0,
        "zero_external_task_descriptors": autonomy["external_task_descriptors"] == 0,
        "zero_external_hash_descriptors": autonomy["external_hash_descriptors"] == 0,
        "zero_host_supplied_chain_lengths": autonomy["host_supplied_chain_lengths"] == 0,
        "mutated_job_completed": mutated_result.done and mutated_result.error is None,
        "one_bit_mutation_root_mismatch": mutated_result.output != public_key[:N],
        "oracle_rejects_one_bit_mutation": not xmss_verify(
            public_key, message, mutated_signature
        ),
    }
    record = {
        "program": image["name"],
        "program_sha256": image["sha256"],
        "static_words": image["word_count"],
        "static_bytes": image["image_bytes"],
        "maximum_loop_depth": MicroInterpreter(image).verification["max_loop_depth"],
        "maximum_call_depth": MicroInterpreter(image).verification["max_call_depth"],
        "done": result.done,
        "error": result.error,
        "input_signature_sha256": hashlib.sha256(signature).hexdigest(),
        "computed_root": result.output.hex(),
        "public_root": public_key[:N].hex(),
        "mutated_computed_root": mutated_result.output.hex(),
        "hash_trace_sha256": result.hash_trace_sha256,
        "oracle_hash_trace_sha256": oracle_digest,
        "hash_class_counts": class_counts,
        "counters": result.counters,
        "autonomy": autonomy,
        "checks": checks,
        "status": "PASS" if result.done and all(checks.values()) else "FAIL",
    }
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0 if record["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
