#!/usr/bin/env python3
"""Measure complete SLH-DSA traces with RTL-calibrated cycle contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.cycle_model import ShakeTraceMeter, build_current_u2_report  # noqa: E402
from model.interpreter import MicroInterpreter  # noqa: E402
from model.microcode_assembler import load_and_assemble  # noqa: E402
from model.reference.slh_dsa import (  # noqa: E402
    SLH_DSA_SHAKE_128F,
    keygen_internal,
    sign_internal,
)


KEYGEN_PROGRAM = ROOT / "microcode/slh_dsa/slh_dsa_shake_128f_keygen.json"
SIGN_PROGRAM = ROOT / "microcode/slh_dsa/slh_dsa_shake_128f_sign.json"
KEYGEN_KAT = ROOT / "tests/kat/slh_dsa_shake_128f_keygen_acvp_tc31.json"
SIGN_KAT = ROOT / "tests/kat/slh_dsa_shake_128f_siggen_acvp_tc137.json"


def _digest_observer(meter: ShakeTraceMeter):
    digest = hashlib.sha256()

    def observe(kind: str, data: bytes, value: bytes) -> None:
        meter.observe(kind, data, value)
        record = {
            "hash_class": kind,
            "hash_input_digest": hashlib.sha256(data).hexdigest(),
            "hash_output": value.hex(),
        }
        digest.update(
            json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
        )

    return observe, digest


def measure_keygen() -> dict[str, object]:
    vector = json.loads(KEYGEN_KAT.read_text(encoding="utf-8"))
    image = load_and_assemble(KEYGEN_PROGRAM)
    job = {
        "sk_seed": bytes.fromhex(vector["sk_seed"]),
        "pub_seed": bytes.fromhex(vector["pk_seed"]),
    }
    execution = MicroInterpreter(image, trace_mode="none").execute(job)
    meter = ShakeTraceMeter()
    observe, digest = _digest_observer(meter)
    _secret_key, public_key = keygen_internal(
        SLH_DSA_SHAKE_128F,
        bytes.fromhex(vector["sk_seed"]),
        bytes.fromhex(vector["sk_prf"]),
        bytes.fromhex(vector["pk_seed"]),
        observe,
    )
    if not execution.done or execution.output != public_key[16:]:
        raise RuntimeError("Keygen microcode/oracle result mismatch")
    if execution.hash_trace_sha256 != digest.hexdigest():
        raise RuntimeError("Keygen ordered Hash trace mismatch")
    report = build_current_u2_report(
        operation="SLH-DSA-SHAKE-128f Keygen",
        dynamic_instructions=execution.counters["dynamic_instructions"],
        operation_output_bytes=len(execution.output),
        meter=meter,
    )
    report["program_sha256"] = image["sha256"]
    report["ordered_hash_trace_sha256"] = digest.hexdigest()
    return report


def measure_sign() -> dict[str, object]:
    vector = json.loads(SIGN_KAT.read_text(encoding="utf-8"))
    image = load_and_assemble(SIGN_PROGRAM)
    secret_key = bytes.fromhex(vector["sk"])
    message = bytes.fromhex(vector["message"])
    job = {
        "sk_seed": secret_key[:16],
        "sk_prf": secret_key[16:32],
        "pub_seed": secret_key[32:48],
        "root": secret_key[48:64],
        "message": message,
    }
    execution = MicroInterpreter(image, trace_mode="none").execute(job)
    meter = ShakeTraceMeter()
    observe, digest = _digest_observer(meter)
    signature = sign_internal(
        SLH_DSA_SHAKE_128F, message, secret_key, observe=observe
    )
    if not execution.done or execution.output != signature:
        raise RuntimeError("Sign microcode/oracle result mismatch")
    if execution.hash_trace_sha256 != digest.hexdigest():
        raise RuntimeError("Sign ordered Hash trace mismatch")
    report = build_current_u2_report(
        operation="SLH-DSA-SHAKE-128f Sign",
        dynamic_instructions=execution.counters["dynamic_instructions"],
        operation_output_bytes=len(execution.output),
        meter=meter,
    )
    report["program_sha256"] = image["sha256"]
    report["ordered_hash_trace_sha256"] = digest.hexdigest()
    report["signature_sha256"] = hashlib.sha256(signature).hexdigest()
    return report


def main() -> int:
    report = {
        "schema_version": 1,
        "profile": "SLH-DSA-SHAKE-128f",
        "keygen": measure_keygen(),
        "sign": measure_sign(),
        "status": "PASS",
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
