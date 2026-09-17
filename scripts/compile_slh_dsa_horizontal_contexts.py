#!/usr/bin/env python3
"""Compile tc137 generic microcode execution into horizontal contexts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.horizontal_context_schedule import (  # noqa: E402
    compile_context_program,
    extract_hash_contexts,
    schedule_contexts,
)
from model.interpreter import MicroInterpreter  # noqa: E402
from model.horizontal_token_microcode import (  # noqa: E402
    compress_horizontal_program,
)
from model.microcode_assembler import load_and_assemble  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json-out", type=Path,
        default=ROOT / "build/slh_dsa_horizontal_context_v0.json",
    )
    parser.add_argument(
        "--token-mem-out", type=Path,
        default=ROOT / "build/slh_dsa_horizontal_tokens_v0.mem",
    )
    parser.add_argument(
        "--template-mem-out", type=Path,
        default=ROOT / "build/slh_dsa_horizontal_templates_v0.mem",
    )
    parser.add_argument(
        "--expanded-mem-out", type=Path,
        default=ROOT / "build/slh_dsa_horizontal_expanded_v0.mem",
    )
    args = parser.parse_args()
    vector = json.loads((
        ROOT / "tests/kat/slh_dsa_shake_128f_siggen_acvp_tc137.json"
    ).read_text(encoding="utf-8"))
    secret_key = bytes.fromhex(vector["sk"])
    job = {
        "sk_seed": secret_key[:16],
        "sk_prf": secret_key[16:32],
        "pub_seed": secret_key[32:48],
        "root": secret_key[48:64],
        "message": bytes.fromhex(vector["message"]),
    }
    image = load_and_assemble(
        ROOT / "microcode/slh_dsa/slh_dsa_shake_128f_sign.json"
    )
    execution = MicroInterpreter(image, trace_mode="full").execute(job)
    contexts = extract_hash_contexts(execution)
    active_schedule = schedule_contexts(contexts, boundary_cycles=0)
    words, active_metrics = compile_context_program(active_schedule)
    templates, tokens, token_metrics = compress_horizontal_program(words)
    direct_schedule = schedule_contexts(contexts, boundary_cycles=1)
    _, direct_metrics = compile_context_program(direct_schedule)
    signature_digest = hashlib.sha256(execution.output).hexdigest()
    token_image = "".join(f"{token.encode():016x}\n" for token in tokens)
    template_image = "".join(f"{template:032x}\n" for template in templates)
    expanded_image = "".join(f"{word.encode():032x}\n" for word in words)
    result = {
        "schema_version": "0.1.0",
        "classification": "HORIZONTAL_CONTEXT_RTL_CONTROL_MODEL",
        "correctness": {
            "microcode_completed": execution.done and execution.error is None,
            "signature_sha256_match": signature_digest
                == vector["signature_sha256"],
            "hash_calls_preserved": sum(len(context.hash_ids)
                for context in contexts) == execution.counters["hash_calls"],
            "permutations_preserved": execution.counters[
                "keccak_permutations"
            ] == 105641,
        },
        "architecture": {
            "word_bits": 128,
            "equal_hash_lanes": 2,
            "dynamic_ready_window_entries": 0,
            "event_scoreboard_bits": 8,
            "context_sources": ["generic HASH", "generic TREE_PUSH"],
            "algorithm_specific_opcodes": [],
        },
        "active_cycle_schedule": active_metrics,
        "direct_lane_boundary_schedule": direct_metrics,
        "static_program": {
            "encoded_words": len(words),
            "first_words_hex": [f"{word.encode():032x}" for word in words[:8]],
        },
        "compressed_program": {
            **token_metrics,
            "token_bits": 64,
            "template_bits": 128,
            "first_tokens_hex": [f"{token.encode():016x}"
                                 for token in tokens[:8]],
            "template_words_hex": [f"{template:032x}"
                                   for template in templates],
            "token_image_sha256": hashlib.sha256(
                token_image.encode("ascii")
            ).hexdigest(),
            "template_image_sha256": hashlib.sha256(
                template_image.encode("ascii")
            ).hexdigest(),
            "expanded_image_sha256": hashlib.sha256(
                expanded_image.encode("ascii")
            ).hexdigest(),
        },
        "limitations": [
            "context materializer and Scratchpad writeback are not yet connected",
            "schedule is profile-guided by tc137; other messages require validation",
            "reported cycles are hash-service schedules, not complete RTL cycles",
        ],
    }
    if not all(result["correctness"].values()):
        raise SystemExit("horizontal context correctness gate failed")
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.token_mem_out.parent.mkdir(parents=True, exist_ok=True)
    args.template_mem_out.parent.mkdir(parents=True, exist_ok=True)
    args.expanded_mem_out.parent.mkdir(parents=True, exist_ok=True)
    args.token_mem_out.write_text(token_image, encoding="ascii")
    args.template_mem_out.write_text(template_image, encoding="ascii")
    args.expanded_mem_out.write_text(expanded_image, encoding="ascii")
    args.json_out.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
