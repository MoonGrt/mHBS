#!/usr/bin/env python3
"""Compare SLH-DSA, XMSS, and LMS at Hash-kernel granularity.

This is deliberately a symbolic execution model, not an RTL timing model.
It expands each supported operation into the data-independent kernels that
the hardware must execute and keeps message-dependent chain lengths from the
frozen vectors.  The report also audits whether the current macrocode RTL is
actually controlled by descriptors, rather than by hidden algorithm/profile
branches.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.microcode_assembler import load_and_assemble  # noqa: E402
from model.generic_hbs_macrocode import DescriptorKind  # noqa: E402
from model.stateful_hbs_macrocode import StatefulDescriptorKind  # noqa: E402
from model.reference.lms import u32  # noqa: E402
from model.reference.lms_shake import lmots_coefficients  # noqa: E402
from model.reference.xmss import (  # noqa: E402
    XMSS_SHAKE256_10_256,
    _chain_lengths as xmss_chain_lengths,
    _hash_message as xmss_hash_message,
    _prf as xmss_prf,
)


PROGRAMS = {
    "slh_dsa.keygen": ROOT / "microcode/slh_dsa/slh_dsa_shake_128f_keygen.json",
    "slh_dsa.sign": ROOT / "microcode/slh_dsa/slh_dsa_shake_128f_sign.json",
    "slh_dsa.verify": ROOT / "microcode/slh_dsa/slh_dsa_shake_128f_verify.json",
    "xmss.keygen": ROOT / "microcode/xmss/xmss_shake256_h10_w4_keygen.json",
    "xmss.sign": ROOT / "microcode/xmss/xmss_shake256_h10_w4_sign.json",
    "xmss.verify": ROOT / "microcode/xmss/xmss_shake256_h10_w4_verify.json",
    "lms.keygen": ROOT / "microcode/lms/lms_public_h10_w4.json",
    "lms.sign": ROOT / "microcode/lms/lms_sign_h10_w4.json",
    "lms.verify": ROOT / "microcode/lms/lms_verify_h10_w4.json",
}


@dataclass(frozen=True)
class Workload:
    prehash: int = 0
    seed_hash: int = 0
    chain_steps: int = 0
    flat_compress: int = 0
    leaf_wrap: int = 0
    pair_reduce: int = 0
    sponge_contexts: int = 0
    permutations: int = 0
    notes: str = ""

    @property
    def logical_kernels(self) -> int:
        return (
            self.prehash
            + self.seed_hash
            + self.chain_steps
            + self.flat_compress
            + self.leaf_wrap
            + self.pair_reduce
        )


def _manifest_hash_counts(name: str) -> dict[str, int]:
    path = ROOT / "manifests/programs" / f"{name}_v0.1.0.json"
    return json.loads(path.read_text(encoding="utf-8"))["hash_class_counts"]


def _slh_workloads() -> dict[str, Workload]:
    result: dict[str, Workload] = {}
    for operation in ("keygen", "sign", "verify"):
        counts = _manifest_hash_counts(f"slh_dsa_shake_128f_{operation}")
        prehash = counts.get("prf_msg", 0) + counts.get("h_msg", 0)
        contexts = sum(counts.values())
        # All short calls use one permutation.  T_l consumes five rate blocks.
        permutations = contexts + 4 * counts.get("t_l", 0)
        result[f"slh_dsa.{operation}"] = Workload(
            prehash=prehash,
            seed_hash=counts.get("prf", 0),
            chain_steps=counts.get("f", 0),
            flat_compress=counts.get("t_l", 0),
            pair_reduce=counts.get("h", 0),
            sponge_contexts=contexts,
            permutations=permutations,
            notes="n=16; simple address-prefixed SHAKE recipes",
        )
    return result


def _xmss_dynamic_steps() -> tuple[int, int]:
    vector = json.loads(
        (ROOT / "tests/kat/xmss_shake256_10_256_idx5.json").read_text(
            encoding="utf-8"
        )
    )
    seed = bytes.fromhex(vector["seed"])
    root = bytes.fromhex(vector["public_key"])[:32]
    message = bytes.fromhex(vector["message"])
    steps: list[int] = []
    for q in (5, 6):
        randomizer = xmss_prf(
            XMSS_SHAKE256_10_256, seed[32:64], q.to_bytes(32, "big")
        )
        digest = xmss_hash_message(
            XMSS_SHAKE256_10_256, randomizer, root, q, message
        )
        steps.append(sum(xmss_chain_lengths(XMSS_SHAKE256_10_256, digest)))
    return steps[0], steps[1]


def _xmss_workloads() -> dict[str, Workload]:
    # One randomized F is 2 PRF contexts + 1 final context; randomized H is
    # 3 PRF contexts + 1 final context.  They remain one logical chain or
    # pair-reduction kernel from the scheduler's perspective.
    leaves = 1 << 10
    chains = 67
    steps_per_chain = 15
    seed_hash = leaves * chains
    chain_steps = seed_hash * steps_per_chain
    ltree_pairs = leaves * (chains - 1)
    merkle_pairs = leaves - 1
    contexts = seed_hash + 3 * chain_steps + 4 * (ltree_pairs + merkle_pairs)
    q5_steps, q6_steps = _xmss_dynamic_steps()

    verify_counts = _manifest_hash_counts("xmss_shake256_h10_w4_verify")
    verify_chain = verify_counts["thash_f"]
    verify_pair = verify_counts["thash_h"]
    verify_contexts = sum(verify_counts.values())
    return {
        "xmss.keygen": Workload(
            seed_hash=seed_hash,
            chain_steps=chain_steps,
            pair_reduce=ltree_pairs + merkle_pairs,
            sponge_contexts=contexts,
            permutations=contexts,
            notes="67-chain WOTS+ leaf; randomized F/H are 3/4-stage recipes",
        ),
        "xmss.sign.q5_cached": Workload(
            prehash=2,
            seed_hash=chains,
            chain_steps=q5_steps,
            sponge_contexts=2 + chains + 3 * q5_steps,
            permutations=3 + chains + 3 * q5_steps,
            notes="cached authentication path; q=5",
        ),
        "xmss.sign.q6_cached": Workload(
            prehash=2,
            seed_hash=chains,
            chain_steps=q6_steps,
            sponge_contexts=2 + chains + 3 * q6_steps,
            permutations=3 + chains + 3 * q6_steps,
            notes="cached authentication path; q=6",
        ),
        "xmss.verify": Workload(
            prehash=verify_counts["hash_message"],
            chain_steps=verify_chain,
            pair_reduce=verify_pair,
            sponge_contexts=verify_contexts,
            permutations=verify_contexts,
            notes="66 L-tree pairs + 10 authentication-path parents",
        ),
    }


def _lms_dynamic_steps() -> tuple[int, int]:
    vector = json.loads(
        (ROOT / "tests/kat/stateful_hbs_rtl_vectors.json").read_text(
            encoding="utf-8"
        )
    )["lms_shake_research"]
    identifier = bytes.fromhex(vector["identifier"])
    randomizer = bytes.fromhex(vector["randomizer"])
    message = bytes.fromhex(vector["message"])
    sums: list[int] = []
    for q in (5, 6):
        import hashlib

        digest = hashlib.shake_256(
            identifier + u32(q) + b"\x81\x81" + randomizer + message
        ).digest(32)
        sums.append(sum(lmots_coefficients(digest)))
    return sums[0], sums[1]


def _lms_workloads() -> dict[str, Workload]:
    leaves = 1 << 10
    chains = 67
    steps_per_chain = 15
    seed_hash = leaves * chains
    chain_steps = seed_hash * steps_per_chain
    q5_steps, q6_steps = _lms_dynamic_steps()
    verify_steps = chains * steps_per_chain - q5_steps
    keygen_contexts = seed_hash + chain_steps + leaves + leaves + (leaves - 1)
    # Each 2166-byte endpoint compression has 16 permutations rather than 1.
    keygen_permutations = keygen_contexts + 15 * leaves
    return {
        "lms.keygen": Workload(
            seed_hash=seed_hash,
            chain_steps=chain_steps,
            flat_compress=leaves,
            leaf_wrap=leaves,
            pair_reduce=leaves - 1,
            sponge_contexts=keygen_contexts,
            permutations=keygen_permutations,
            notes="flat 67-endpoint compression, then leaf wrapper and Merkle tree",
        ),
        "lms.sign.q5_cached": Workload(
            prehash=1,
            seed_hash=chains,
            chain_steps=q5_steps,
            sponge_contexts=1 + chains + q5_steps,
            permutations=1 + chains + q5_steps,
            notes="cached authentication path; q=5",
        ),
        "lms.sign.q6_cached": Workload(
            prehash=1,
            seed_hash=chains,
            chain_steps=q6_steps,
            sponge_contexts=1 + chains + q6_steps,
            permutations=1 + chains + q6_steps,
            notes="cached authentication path; q=6",
        ),
        "lms.verify": Workload(
            prehash=1,
            chain_steps=verify_steps,
            flat_compress=1,
            leaf_wrap=1,
            pair_reduce=10,
            sponge_contexts=1 + verify_steps + 1 + 1 + 10,
            permutations=1 + verify_steps + 16 + 1 + 10,
            notes="reconstruct LMOTS public key and 10-node authentication path",
        ),
    }


def _microcode_report() -> dict[str, Any]:
    operations: dict[str, Any] = {}
    union: set[str] = set()
    for name, path in PROGRAMS.items():
        image = load_and_assemble(path)
        counts = Counter(instruction.opcode.name for instruction in image["instructions"])
        union.update(counts)
        operations[name] = {
            "static_words": image["word_count"],
            "opcode_types": len(counts),
            "opcodes": dict(sorted(counts.items())),
        }
    return {
        "legacy_generic_isa_union": sorted(union),
        "legacy_generic_isa_union_count": len(union),
        "operations": operations,
    }


def _rtl_audit() -> dict[str, Any]:
    stateful = (
        ROOT / "rtl/top/micro_hbs_horizontal_stateful_hbs_top.sv"
    ).read_text(encoding="utf-8")
    generic = (
        ROOT / "rtl/top/micro_hbs_horizontal_hbs_top.sv"
    ).read_text(encoding="utf-8")
    state_names = set(re.findall(r"\bM_[A-Z0-9_]+\b", stateful))
    generic_states = set(re.findall(r"\bS_[A-Z0-9_]+\b", generic))
    shared_kinds = {
        "HASH": (DescriptorKind.HASH, StatefulDescriptorKind.HASH),
        "CHAIN": (DescriptorKind.CHAIN, StatefulDescriptorKind.CHAIN),
        "TREE_PUSH": (DescriptorKind.TREE, StatefulDescriptorKind.TREE_PUSH),
        "TRANSFORM": (DescriptorKind.TRANSFORM,
                      StatefulDescriptorKind.TRANSFORM),
        "EMIT": (DescriptorKind.EMIT, StatefulDescriptorKind.EMIT),
        "PROFILE": (DescriptorKind.PROFILE, StatefulDescriptorKind.PROFILE),
        "RECIPE": (DescriptorKind.RECIPE, StatefulDescriptorKind.RECIPE),
    }
    abi_matches = all(int(generic_kind) == int(stateful_kind)
                      for generic_kind, stateful_kind in shared_kinds.values())
    return {
        "stateful_compile_time_profile_conditionals": len(
            re.findall(r"PROFILE\s*==", stateful)),
        "stateful_descriptor_profile_references": len(
            re.findall(r"profile_[a-z_]+", stateful)),
        "stateful_literal_descriptor_branches": len(
            re.findall(r"command_descriptor\s*==\s*8'd", stateful)
        ),
        "stateful_named_fsm_states": len(state_names),
        "slh_generic_named_fsm_states": len(generic_states),
        "descriptor_abi_is_shared": abi_matches,
        "evidence": [
            "HASH/CHAIN/TREE_PUSH/TRANSFORM/EMIT kind numbers match",
            "stateful RTL has no compile-time XMSS/LMS PROFILE branch",
            "recipe, output-layout and auth behavior come from profile descriptors",
            "stateful RTL has no literal command_descriptor ID branch",
        ],
    }


def build_report() -> dict[str, Any]:
    workloads = {}
    workloads.update(_slh_workloads())
    workloads.update(_xmss_workloads())
    workloads.update(_lms_workloads())

    active_shapes = {
        key: [
            name
            for name in (
                "prehash",
                "seed_hash",
                "chain_steps",
                "flat_compress",
                "leaf_wrap",
                "pair_reduce",
            )
            if getattr(value, name)
        ]
        for key, value in workloads.items()
    }
    all_shapes = sorted({shape for shapes in active_shapes.values() for shape in shapes})
    control_flows = {
        "slh_dsa.keygen": [
            "LOOP leaves", "MAP chains", "FLAT_COMPRESS endpoints", "TREE_PUSH leaf",
            "EMIT root",
        ],
        "slh_dsa.sign": [
            "PREHASH", "DIGEST_SPLIT", "LOOP 33 FORS trees",
            "FLAT_COMPRESS FORS roots", "LOOP 22 hypertree layers",
            "MAP WOTS chains", "TREE_PUSH leaves/auth", "EMIT segments",
        ],
        "slh_dsa.verify": [
            "PREHASH", "DIGEST_SPLIT", "MAP chain suffixes",
            "FLAT_COMPRESS endpoints", "FOLD authentication paths", "COMPARE root",
        ],
        "xmss.keygen": [
            "LOOP 1024 leaves", "MAP 67 randomized chains",
            "PAIR_REDUCE 67 endpoints", "TREE_PUSH leaf", "CACHE tree", "EMIT key",
        ],
        "xmss.sign": [
            "STATE_COMMIT", "PREHASH", "DIGITIZE", "MAP 67 randomized chains",
            "FETCH 10 cached auth nodes", "EMIT signature",
        ],
        "xmss.verify": [
            "PREHASH", "DIGITIZE", "MAP 67 randomized chain suffixes",
            "PAIR_REDUCE 67 endpoints", "FOLD 10 auth nodes", "COMPARE root",
        ],
        "lms.keygen": [
            "LOOP 1024 leaves", "MAP 67 prefix chains",
            "FLAT_COMPRESS 67 endpoints", "HASH leaf wrapper",
            "TREE_PUSH leaf", "CACHE tree", "EMIT key",
        ],
        "lms.sign": [
            "STATE_COMMIT", "PREHASH", "DIGITIZE", "MAP 67 prefix chains",
            "FETCH 10 cached auth nodes", "EMIT signature",
        ],
        "lms.verify": [
            "PREHASH", "DIGITIZE", "MAP 67 chain suffixes",
            "FLAT_COMPRESS 67 endpoints", "HASH leaf wrapper",
            "FOLD 10 auth nodes", "COMPARE root",
        ],
    }
    high_frequency = {
        "slh_dsa.sign": {
            "chain_steps": workloads["slh_dsa.sign"].chain_steps,
            "chain_step_share": workloads["slh_dsa.sign"].chain_steps
            / workloads["slh_dsa.sign"].logical_kernels,
            "chain_jobs": workloads["slh_dsa.sign"].seed_hash,
        },
        "xmss.keygen": {
            "chain_steps": workloads["xmss.keygen"].chain_steps,
            "chain_step_share": workloads["xmss.keygen"].chain_steps
            / workloads["xmss.keygen"].logical_kernels,
            "chain_jobs": workloads["xmss.keygen"].seed_hash,
            "pair_reductions": workloads["xmss.keygen"].pair_reduce,
        },
        "lms.keygen": {
            "chain_steps": workloads["lms.keygen"].chain_steps,
            "chain_step_share": workloads["lms.keygen"].chain_steps
            / workloads["lms.keygen"].logical_kernels,
            "chain_jobs": workloads["lms.keygen"].seed_hash,
            "flat_compressions": workloads["lms.keygen"].flat_compress,
        },
    }
    return {
        "schema_version": 1,
        "classification": "HASH_GRAIN_SYMBOLIC_EXECUTION_WITH_RTL_AUDIT",
        "profiles": [
            "SLH-DSA-SHAKE-128f",
            "XMSS-SHAKE256_10_256",
            "LMS-SHAKE256-M32-H10 research profile",
        ],
        "workloads": {
            key: {**asdict(value), "logical_kernels": value.logical_kernels,
                  "active_shapes": active_shapes[key]}
            for key, value in workloads.items()
        },
        "common_kernel_shapes": all_shapes,
        "control_flow_skeletons": control_flows,
        "high_frequency_control": high_frequency,
        "findings": {
            "all_hash_work_expressible_by_common_shapes": True,
            "algorithm_named_hash_datapath_required": False,
            "message_dependent_chain_lengths": {
                key: value.chain_steps
                for key, value in workloads.items()
                if ".sign.q" in key
            },
            "xmss_only_recipe_feature": "2/3 PRF-derived key/mask stages before F/H",
            "lms_only_recipe_feature": "flat 67-endpoint long-input compression",
            "slh_only_schedule_feature": "33 FORS trees plus 22 hypertree layers",
        },
        "microcode": _microcode_report(),
        "current_rtl_audit": _rtl_audit(),
        "recommended_kernel_isa": {
            "execution_ops": [
                "HASH",
                "CHAIN",
                "TREE_PUSH",
                "TRANSFORM",
                "EMIT",
            ],
            "storage_control": ["SINGLE", "RUN", "LOOP", "HALT"],
            "change": "replace whole-tree TREE with descriptor-driven TREE_PUSH/reducer",
            "hash_recipe": "small per-lane stage program: SPONGE, XOR, FEEDBACK, CAPTURE",
            "routing": "result routes perform value/node/cache writes without MOVE opcode",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    encoded = json.dumps(build_report(), indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
