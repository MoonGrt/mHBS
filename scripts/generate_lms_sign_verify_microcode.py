#!/usr/bin/env python3
"""Generate RFC 8554 LMS H10 / LM-OTS W4 Sign and Verify programs."""

from __future__ import annotations

import argparse
import json


N = 32
P = 67
HEIGHT = 10
Y_VALUES = 0
DIGITS = 67
TREE_OTS = 134
TREE_LEAF = 135
CURRENT_NODE = 136
AUTH_NODE = 137
Q_VALUE = 138
RANDOMIZER = 139
DYNAMIC_BOUND = 140
LMOTS_DIGEST = 141
AUTH_PATH = 150
Q_OUTPUT = 160
LMOTS_TYPE_OUTPUT = 161
RANDOMIZER_OUTPUT = 162
LMS_TYPE_OUTPUT = 163
TREE_ROOT = 170

LMOTS_TYPE = 3
LMS_TYPE = 6
LMOTS_SIGNATURE_BYTES = 4 + N * (P + 1)
LMS_TYPE_OFFSET = 4 + LMOTS_SIGNATURE_BYTES
AUTH_PATH_OFFSET = LMS_TYPE_OFFSET + 4


def lit(value: int) -> dict[str, object]:
    return {"kind": "literal_int", "value": value}


def reg(index: int) -> dict[str, object]:
    return {"kind": "reg", "reg": index}


def mem(address: int) -> dict[str, object]:
    return {"kind": "memory_int", "base": address}


def op(name: str, *arguments: dict[str, object]) -> dict[str, object]:
    return {"op": name, "args": list(arguments)}


def binary(name: str, left: dict[str, object], right: dict[str, object]) -> dict[str, object]:
    return {"op": name, "left": left, "right": right}


def shift(name: str, value: dict[str, object], amount: dict[str, object]) -> dict[str, object]:
    return {"op": name, "value": value, "shift": amount}


def word(expression: dict[str, object]) -> dict[str, object]:
    return {"kind": "expr", "expression": expression}


def sha_layout(
    name: str,
    hash_class: str,
    destination: dict[str, object],
    components: list[dict[str, object]],
    max_input_bytes: int,
) -> dict[str, object]:
    return {
        "name": name,
        "class": hash_class,
        "hash": "sha256",
        "output_bytes": N,
        "max_input_bytes": max_input_bytes,
        "destination": destination,
        "components": components,
    }


def signature_slice(offset: dict[str, object], length: int = N) -> dict[str, object]:
    return {
        "kind": "job_slice",
        "field": "signature",
        "offset": offset,
        "length": length,
    }


def base_document(name: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "micro_isa_version": "0.2",
        "name": name,
        "entry": "entry",
        "bounds": {
            "scratch_slots": 192,
            "max_loop_bound": 1024,
            "max_dynamic_instructions": 3000000,
        },
    }


def build_sign_document() -> dict[str, object]:
    layouts = {
        "0": sha_layout(
            "lmots_message_digest",
            "lmots_message",
            {"base": LMOTS_DIGEST},
            [
                {"kind": "job_bytes", "field": "identifier", "length": 16},
                {"kind": "job_int", "field": "q", "bytes": 4},
                {"kind": "literal", "hex": "8181"},
                {"kind": "job_bytes", "field": "randomizer", "length": N},
                {"kind": "job_bytes", "field": "message"},
            ],
            4096,
        ),
        "1": sha_layout(
            "lmots_signature_private_element",
            "lmots_prf",
            {"base": Y_VALUES, "index_reg": 0},
            [
                {"kind": "job_bytes", "field": "identifier", "length": 16},
                {"kind": "job_int", "field": "q", "bytes": 4},
                {"kind": "reg", "reg": 0, "bytes": 2},
                {"kind": "literal", "hex": "ff"},
                {"kind": "job_bytes", "field": "seed", "length": N},
            ],
            55,
        ),
        "2": sha_layout(
            "lmots_signature_chain_step",
            "ots_chain",
            {"base": Y_VALUES, "index_reg": 0},
            [
                {"kind": "job_bytes", "field": "identifier", "length": 16},
                {"kind": "job_int", "field": "q", "bytes": 4},
                {"kind": "reg", "reg": 0, "bytes": 2},
                {"kind": "reg", "reg": 2, "bytes": 1},
                {"kind": "memory", "base": Y_VALUES, "index_reg": 0},
            ],
            55,
        ),
        "3": sha_layout(
            "tree_lmots_private_element",
            "lmots_prf",
            {"base": Y_VALUES, "index_reg": 0},
            [
                {"kind": "job_bytes", "field": "identifier", "length": 16},
                {"kind": "reg", "reg": 3, "bytes": 4},
                {"kind": "reg", "reg": 0, "bytes": 2},
                {"kind": "literal", "hex": "ff"},
                {"kind": "job_bytes", "field": "seed", "length": N},
            ],
            55,
        ),
        "4": sha_layout(
            "tree_lmots_chain_step",
            "ots_chain",
            {"base": Y_VALUES, "index_reg": 0},
            [
                {"kind": "job_bytes", "field": "identifier", "length": 16},
                {"kind": "reg", "reg": 3, "bytes": 4},
                {"kind": "reg", "reg": 0, "bytes": 2},
                {"kind": "reg", "reg": 1, "bytes": 1},
                {"kind": "memory", "base": Y_VALUES, "index_reg": 0},
            ],
            55,
        ),
        "5": sha_layout(
            "tree_lmots_public_compress",
            "ots_compress",
            {"base": TREE_OTS},
            [
                {"kind": "job_bytes", "field": "identifier", "length": 16},
                {"kind": "reg", "reg": 3, "bytes": 4},
                {"kind": "literal", "hex": "8080"},
                {"kind": "memory_range", "base": Y_VALUES, "count": P},
            ],
            2166,
        ),
        "6": sha_layout(
            "lms_leaf",
            "merkle_leaf",
            {"base": TREE_LEAF},
            [
                {"kind": "job_bytes", "field": "identifier", "length": 16},
                {"kind": "reg", "reg": 3, "add": 1 << HEIGHT, "bytes": 4},
                {"kind": "literal", "hex": "8282"},
                {"kind": "memory", "base": TREE_OTS},
            ],
            54,
        ),
        "7": {
            "name": "lms_tree_reduce_with_authentication",
            "class": "merkle_internal",
            "hash": "sha256",
            "output_bytes": N,
            "max_input_bytes": 86,
            "tree_height": HEIGHT,
            "storage_mode": "TREEHASH_MIN",
            "subtree_height": 4,
            "root_destination": TREE_ROOT,
            "target_leaf_field": "q",
            "auth_destination": AUTH_PATH,
            "components": [
                {"kind": "job_bytes", "field": "identifier", "length": 16},
                {"kind": "tree_index", "bytes": 4},
                {"kind": "literal", "hex": "8383"},
                {"kind": "tree_left"},
                {"kind": "tree_right"},
            ],
        },
    }
    loads = {
        "0": {
            "name": "signature_q",
            "source": {"kind": "job_int", "field": "q", "bytes": 4},
            "destination": {"base": Q_OUTPUT},
        },
        "1": {
            "name": "lmots_typecode",
            "source": {"kind": "literal", "hex": "00000003"},
            "destination": {"base": LMOTS_TYPE_OUTPUT},
        },
        "2": {
            "name": "signature_randomizer",
            "source": {"kind": "job_bytes", "field": "randomizer", "length": N},
            "destination": {"base": RANDOMIZER_OUTPUT},
        },
        "3": {
            "name": "lmots_coefficients",
            "source": {"kind": "memory", "base": LMOTS_DIGEST},
            "transform": "base_w_checksum",
            "log_w": 4,
            "len1": 64,
            "len2": 3,
            "destination": {"base": DIGITS},
        },
        "4": {
            "name": "lmots_coefficient_register",
            "source": {"kind": "memory", "base": DIGITS, "index_reg": 0},
            "destination_reg": 7,
            "endian": "big",
        },
        "5": {
            "name": "lmots_sign_chain_bound",
            "source": {"kind": "reg", "reg": 7, "bytes": 1},
            "destination": {"base": DYNAMIC_BOUND},
        },
        "6": {
            "name": "lms_typecode",
            "source": {"kind": "literal", "hex": "00000006"},
            "destination": {"base": LMS_TYPE_OUTPUT},
        },
    }
    program = [
        {"label": "entry"},
        {"op": "DATA_LOAD", "imm": 0},
        {"op": "DATA_LOAD", "imm": 1},
        {"op": "DATA_LOAD", "imm": 2},
        {"op": "OUTPUT", "rd": Q_OUTPUT},
        {"op": "OUTPUT", "rd": LMOTS_TYPE_OUTPUT},
        {"op": "OUTPUT", "rd": RANDOMIZER_OUTPUT},
        {"op": "HASH", "imm": 0},
        {"op": "DATA_LOAD", "imm": 3},
        {"op": "SET_REG", "rd": 6, "imm": DYNAMIC_BOUND},
        {"op": "LOOP_BEGIN", "rs": 0, "imm": P},
        {"op": "HASH", "imm": 1},
        {"op": "DATA_LOAD", "imm": 4},
        {"op": "DATA_LOAD", "imm": 5},
        {
            "op": "LOOP_BEGIN",
            "flags": 1,
            "rd": 6,
            "rs": 2,
            "target": "after_signature_chain",
        },
        {"op": "HASH", "imm": 2},
        {"op": "LOOP_END"},
        {"label": "after_signature_chain"},
        {"op": "OUTPUT", "flags": 1, "rd": Y_VALUES, "rs": 0},
        {"op": "LOOP_END"},
        {"op": "DATA_LOAD", "imm": 6},
        {"op": "OUTPUT", "rd": LMS_TYPE_OUTPUT},
        {"op": "LOOP_BEGIN", "rs": 3, "imm": 1 << HEIGHT},
        {"op": "LOOP_BEGIN", "rs": 0, "imm": P},
        {"op": "HASH", "imm": 3},
        {"op": "LOOP_BEGIN", "rs": 1, "imm": 15},
        {"op": "HASH", "imm": 4},
        {"op": "LOOP_END"},
        {"op": "LOOP_END"},
        {"op": "HASH", "imm": 5},
        {"op": "HASH", "imm": 6},
        {"op": "TREE_PUSH", "rd": TREE_LEAF, "imm": 7},
        {"op": "LOOP_END"},
        {"op": "LOOP_BEGIN", "rs": 0, "imm": HEIGHT},
        {"op": "OUTPUT", "flags": 1, "rd": AUTH_PATH, "rs": 0},
        {"op": "LOOP_END"},
        {"op": "HALT"},
    ]
    document = base_document("rfc8554-lms-sha256-m32-h10-w4-sign")
    document.update({"layouts": layouts, "loads": loads, "program": program})
    return document


def build_verify_document() -> dict[str, object]:
    parent_index = shift("shr", reg(5), lit(1))
    parent_order = op("and", reg(5), lit(1))
    layouts = {
        "0": sha_layout(
            "lmots_message_digest",
            "lmots_message",
            {"base": LMOTS_DIGEST},
            [
                {"kind": "job_bytes", "field": "identifier", "length": 16},
                {"kind": "memory", "base": Q_VALUE},
                {"kind": "literal", "hex": "8181"},
                {"kind": "memory", "base": RANDOMIZER},
                {"kind": "job_bytes", "field": "message"},
            ],
            4096,
        ),
        "1": sha_layout(
            "lmots_verify_chain_step",
            "ots_chain",
            {"base": Y_VALUES, "index_reg": 0},
            [
                {"kind": "job_bytes", "field": "identifier", "length": 16},
                {"kind": "memory", "base": Q_VALUE},
                {"kind": "reg", "reg": 0, "bytes": 2},
                {
                    "kind": "word_array",
                    "word_bytes": 1,
                    "words": [word(op("add", reg(7), reg(2)))],
                },
                {"kind": "memory", "base": Y_VALUES, "index_reg": 0},
            ],
            55,
        ),
        "2": sha_layout(
            "lmots_public_compress",
            "ots_compress",
            {"base": TREE_OTS},
            [
                {"kind": "job_bytes", "field": "identifier", "length": 16},
                {"kind": "memory", "base": Q_VALUE},
                {"kind": "literal", "hex": "8080"},
                {"kind": "memory_range", "base": Y_VALUES, "count": P},
            ],
            2166,
        ),
        "3": sha_layout(
            "lms_leaf_candidate",
            "merkle_leaf",
            {"base": CURRENT_NODE},
            [
                {"kind": "job_bytes", "field": "identifier", "length": 16},
                {
                    "kind": "word_array",
                    "words": [word(op("add", mem(Q_VALUE), lit(1 << HEIGHT)))],
                },
                {"kind": "literal", "hex": "8282"},
                {"kind": "memory", "base": TREE_OTS},
            ],
            54,
        ),
        "4": sha_layout(
            "lms_auth_path",
            "merkle_internal",
            {"base": CURRENT_NODE},
            [
                {"kind": "job_bytes", "field": "identifier", "length": 16},
                {"kind": "word_array", "words": [word(parent_index)]},
                {"kind": "literal", "hex": "8383"},
                {
                    "kind": "ordered_pair",
                    "condition": parent_order,
                    "when_zero": [
                        {"kind": "memory", "base": CURRENT_NODE},
                        {"kind": "memory", "base": AUTH_NODE},
                    ],
                    "when_nonzero": [
                        {"kind": "memory", "base": AUTH_NODE},
                        {"kind": "memory", "base": CURRENT_NODE},
                    ],
                },
            ],
            86,
        ),
    }
    y_offset = op("add", lit(40), op("mul", reg(0), lit(N)))
    auth_offset = op(
        "add", lit(AUTH_PATH_OFFSET), op("mul", reg(2), lit(N))
    )
    loads = {
        "0": {
            "name": "signature_q",
            "source": signature_slice(lit(0), 4),
            "destination": {"base": Q_VALUE},
        },
        "1": {
            "name": "q_node_index_register",
            "source": {"kind": "memory", "base": Q_VALUE},
            "destination_reg": 5,
            "endian": "big",
        },
        "2": {
            "name": "signature_randomizer",
            "source": signature_slice(lit(8)),
            "destination": {"base": RANDOMIZER},
        },
        "3": {
            "name": "lmots_coefficients",
            "source": {"kind": "memory", "base": LMOTS_DIGEST},
            "transform": "base_w_checksum",
            "log_w": 4,
            "len1": 64,
            "len2": 3,
            "destination": {"base": DIGITS},
        },
        "4": {
            "name": "lmots_y_from_signature",
            "source": signature_slice(y_offset),
            "destination": {"base": Y_VALUES, "index_reg": 0},
        },
        "5": {
            "name": "lmots_coefficient_register",
            "source": {"kind": "memory", "base": DIGITS, "index_reg": 0},
            "destination_reg": 7,
            "endian": "big",
        },
        "6": {
            "name": "lmots_verify_chain_bound",
            "transform": "integer_expression",
            "expression": binary("sub", lit(15), reg(7)),
            "bytes": 1,
            "destination": {"base": DYNAMIC_BOUND},
        },
        "7": {
            "name": "lms_auth_from_signature",
            "source": signature_slice(auth_offset),
            "destination": {"base": AUTH_NODE},
        },
        "8": {
            "name": "next_lms_node_index",
            "transform": "integer_expression",
            "expression": parent_index,
            "destination_reg": 5,
        },
    }
    program = [
        {"label": "entry"},
        {"op": "DATA_LOAD", "imm": 0},
        {"op": "DATA_LOAD", "imm": 1},
        {"op": "DATA_LOAD", "imm": 2},
        {"op": "HASH", "imm": 0},
        {"op": "DATA_LOAD", "imm": 3},
        {"op": "SET_REG", "rd": 6, "imm": DYNAMIC_BOUND},
        {"op": "LOOP_BEGIN", "rs": 0, "imm": P},
        {"op": "DATA_LOAD", "imm": 4},
        {"op": "DATA_LOAD", "imm": 5},
        {"op": "DATA_LOAD", "imm": 6},
        {
            "op": "LOOP_BEGIN",
            "flags": 1,
            "rd": 6,
            "rs": 2,
            "target": "after_verify_chain",
        },
        {"op": "HASH", "imm": 1},
        {"op": "LOOP_END"},
        {"label": "after_verify_chain"},
        {"op": "LOOP_END"},
        {"op": "HASH", "imm": 2},
        {"op": "HASH", "imm": 3},
        {"op": "ADD_IMM", "rd": 5, "rs": 5, "imm": 1 << HEIGHT},
        {"op": "LOOP_BEGIN", "rs": 2, "imm": HEIGHT},
        {"op": "DATA_LOAD", "imm": 7},
        {"op": "HASH", "imm": 4},
        {"op": "DATA_LOAD", "imm": 8},
        {"op": "LOOP_END"},
        {"op": "OUTPUT", "rd": CURRENT_NODE},
        {"op": "HALT"},
    ]
    document = base_document("rfc8554-lms-sha256-m32-h10-w4-verify")
    document.update({"layouts": layouts, "loads": loads, "program": program})
    return document


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("sign", "verify"))
    args = parser.parse_args()
    document = build_sign_document() if args.operation == "sign" else build_verify_document()
    print(json.dumps(document, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
