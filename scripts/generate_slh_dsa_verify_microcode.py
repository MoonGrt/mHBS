#!/usr/bin/env python3
"""Generate the loop-compressed FIPS 205 SHAKE-128f Verify program."""

from __future__ import annotations

import json


FORS_ROOTS = 0
WOTS_VALUES = 0
WOTS_DIGITS = 35
CURRENT_ROOT = 70
DIGEST = 71
TREE_ADDRESS = 72
LEAF_INDEX = 73
AUTH_NODE = 74
DYNAMIC_BOUND = 75
RANDOMIZER = 76
SIGNATURE_VALUE = 77

N = 16
FORS_SIGNATURE_OFFSET = N
FORS_TREE_SIGNATURE_BYTES = 7 * N
HYPERTREE_SIGNATURE_OFFSET = N + 33 * FORS_TREE_SIGNATURE_BYTES
XMSS_SIGNATURE_BYTES = (35 + 3) * N


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


def job_slice(offset: dict[str, object], length: int = N) -> dict[str, object]:
    return {
        "kind": "job_slice",
        "field": "signature",
        "offset": offset,
        "length": length,
    }


def adrs_components(
    address_type: int,
    key_pair: dict[str, object],
    word6: dict[str, object],
    word7: dict[str, object],
) -> list[dict[str, object]]:
    return [
        {"kind": "job_bytes", "field": "pub_seed", "length": N},
        {"kind": "word_array", "words": [word(reg(4))]},
        {"kind": "memory", "base": TREE_ADDRESS},
        {
            "kind": "word_array",
            "words": [address_type, word(key_pair), word(word6), word(word7)],
        },
    ]


def shake_layout(
    name: str,
    hash_class: str,
    destination: dict[str, object],
    components: list[dict[str, object]],
    max_input_bytes: int,
    output_bytes: int = N,
) -> dict[str, object]:
    return {
        "name": name,
        "class": hash_class,
        "hash": "shake256",
        "output_bytes": output_bytes,
        "max_input_bytes": max_input_bytes,
        "destination": destination,
        "components": components,
    }


def build_document() -> dict[str, object]:
    zero = lit(0)
    digest_int = mem(DIGEST)
    selected_global = op("add", op("mul", reg(0), lit(64)), reg(1))
    selected_parent = shift("shr", selected_global, op("add", reg(2), lit(1)))
    selected_bit = op("and", shift("shr", reg(1), reg(2)), lit(1))
    leaf_parent = shift("shr", reg(5), op("add", reg(2), lit(1)))
    leaf_bit = op("and", shift("shr", reg(5), reg(2)), lit(1))

    layouts = {
        "0": shake_layout(
            "message_digest",
            "h_msg",
            {"base": DIGEST},
            [
                {"kind": "memory", "base": RANDOMIZER},
                {"kind": "job_bytes", "field": "pub_seed", "length": N},
                {"kind": "job_bytes", "field": "public_root", "length": N},
                {"kind": "job_bytes", "field": "message"},
            ],
            1056,
            output_bytes=34,
        ),
        "1": shake_layout(
            "fors_selected_leaf",
            "f",
            {"base": CURRENT_ROOT},
            adrs_components(3, reg(5), zero, selected_global)
            + [{"kind": "memory", "base": SIGNATURE_VALUE}],
            64,
        ),
        "2": shake_layout(
            "fors_auth_path",
            "h",
            {"base": CURRENT_ROOT},
            adrs_components(3, reg(5), op("add", reg(2), lit(1)), selected_parent)
            + [
                {
                    "kind": "ordered_pair",
                    "condition": selected_bit,
                    "when_zero": [
                        {"kind": "memory", "base": CURRENT_ROOT},
                        {"kind": "memory", "base": AUTH_NODE},
                    ],
                    "when_nonzero": [
                        {"kind": "memory", "base": AUTH_NODE},
                        {"kind": "memory", "base": CURRENT_ROOT},
                    ],
                }
            ],
            80,
        ),
        "3": shake_layout(
            "fors_roots_compress",
            "t_l",
            {"base": CURRENT_ROOT},
            adrs_components(4, reg(5), zero, zero)
            + [{"kind": "memory_range", "base": FORS_ROOTS, "count": 33}],
            576,
        ),
        "4": shake_layout(
            "wots_signature_recovery_f",
            "f",
            {"base": WOTS_VALUES, "index_reg": 1},
            adrs_components(0, reg(5), reg(1), op("add", reg(7), reg(2)))
            + [{"kind": "memory", "base": WOTS_VALUES, "index_reg": 1}],
            64,
        ),
        "5": shake_layout(
            "wots_public_key_compress",
            "t_l",
            {"base": CURRENT_ROOT},
            adrs_components(1, reg(5), zero, zero)
            + [{"kind": "memory_range", "base": WOTS_VALUES, "count": 35}],
            608,
        ),
        "6": shake_layout(
            "xmss_auth_path",
            "h",
            {"base": CURRENT_ROOT},
            adrs_components(2, zero, op("add", reg(2), lit(1)), leaf_parent)
            + [
                {
                    "kind": "ordered_pair",
                    "condition": leaf_bit,
                    "when_zero": [
                        {"kind": "memory", "base": CURRENT_ROOT},
                        {"kind": "memory", "base": AUTH_NODE},
                    ],
                    "when_nonzero": [
                        {"kind": "memory", "base": AUTH_NODE},
                        {"kind": "memory", "base": CURRENT_ROOT},
                    ],
                }
            ],
            80,
        ),
    }

    fors_shift = binary(
        "sub", lit(272), op("mul", lit(6), op("add", reg(0), lit(1)))
    )
    fors_secret_offset = op(
        "add",
        lit(FORS_SIGNATURE_OFFSET),
        op("mul", reg(0), lit(FORS_TREE_SIGNATURE_BYTES)),
    )
    fors_auth_offset = op(
        "add",
        fors_secret_offset,
        op("mul", op("add", reg(2), lit(1)), lit(N)),
    )
    xmss_layer_offset = op(
        "add",
        lit(HYPERTREE_SIGNATURE_OFFSET),
        op("mul", reg(4), lit(XMSS_SIGNATURE_BYTES)),
    )
    wots_signature_offset = op(
        "add", xmss_layer_offset, op("mul", reg(1), lit(N))
    )
    xmss_auth_offset = op(
        "add",
        xmss_layer_offset,
        op("mul", op("add", reg(2), lit(35)), lit(N)),
    )

    loads = {
        "0": {
            "name": "signature_randomizer",
            "source": job_slice(lit(0)),
            "destination": {"base": RANDOMIZER},
        },
        "1": {
            "name": "digest_tree_address",
            "transform": "integer_expression",
            "expression": op("and", shift("shr", digest_int, lit(8)), lit((1 << 63) - 1)),
            "bytes": 12,
            "destination": {"base": TREE_ADDRESS},
        },
        "2": {
            "name": "digest_leaf_index",
            "transform": "integer_expression",
            "expression": op("and", digest_int, lit(7)),
            "bytes": 1,
            "destination": {"base": LEAF_INDEX},
        },
        "3": {
            "name": "leaf_index_register",
            "source": {"kind": "memory", "base": LEAF_INDEX},
            "destination_reg": 5,
            "endian": "big",
        },
        "4": {
            "name": "fors_selected_index",
            "transform": "integer_expression",
            "expression": op("and", shift("shr", digest_int, fors_shift), lit(63)),
            "destination_reg": 1,
        },
        "5": {
            "name": "fors_secret_from_signature",
            "source": job_slice(fors_secret_offset),
            "destination": {"base": SIGNATURE_VALUE},
        },
        "6": {
            "name": "fors_auth_from_signature",
            "source": job_slice(fors_auth_offset),
            "destination": {"base": AUTH_NODE},
        },
        "7": {
            "name": "wots_chain_lengths",
            "source": {"kind": "memory", "base": CURRENT_ROOT},
            "transform": "base_w_checksum",
            "log_w": 4,
            "len1": 32,
            "len2": 3,
            "destination": {"base": WOTS_DIGITS},
        },
        "8": {
            "name": "wots_value_from_signature",
            "source": job_slice(wots_signature_offset),
            "destination": {"base": WOTS_VALUES, "index_reg": 1},
        },
        "9": {
            "name": "wots_digit_register",
            "source": {"kind": "memory", "base": WOTS_DIGITS, "index_reg": 1},
            "destination_reg": 7,
            "endian": "big",
        },
        "10": {
            "name": "wots_recovery_bound",
            "transform": "integer_expression",
            "expression": binary("sub", lit(15), reg(7)),
            "bytes": 1,
            "destination": {"base": DYNAMIC_BOUND},
        },
        "11": {
            "name": "xmss_auth_from_signature",
            "source": job_slice(xmss_auth_offset),
            "destination": {"base": AUTH_NODE},
        },
        "12": {
            "name": "next_xmss_leaf",
            "transform": "integer_expression",
            "expression": op("and", mem(TREE_ADDRESS), lit(7)),
            "bytes": 1,
            "destination": {"base": LEAF_INDEX},
        },
        "13": {
            "name": "next_xmss_tree",
            "transform": "integer_expression",
            "expression": shift("shr", mem(TREE_ADDRESS), lit(3)),
            "bytes": 12,
            "destination": {"base": TREE_ADDRESS},
        },
    }
    moves = {
        "0": {
            "name": "save_fors_root",
            "source": {"base": CURRENT_ROOT},
            "destination": {"base": FORS_ROOTS, "index_reg": 0},
        }
    }

    program = [
        {"label": "entry"},
        {"op": "DATA_LOAD", "imm": 0},
        {"op": "HASH", "imm": 0},
        {"op": "DATA_LOAD", "imm": 1},
        {"op": "DATA_LOAD", "imm": 2},
        {"op": "DATA_LOAD", "imm": 3},
        {"op": "LOOP_BEGIN", "rs": 0, "imm": 33},
        {"op": "DATA_LOAD", "imm": 4},
        {"op": "DATA_LOAD", "imm": 5},
        {"op": "HASH", "imm": 1},
        {"op": "LOOP_BEGIN", "rs": 2, "imm": 6},
        {"op": "DATA_LOAD", "imm": 6},
        {"op": "HASH", "imm": 2},
        {"op": "LOOP_END"},
        {"op": "DATA_MOVE", "imm": 0},
        {"op": "LOOP_END"},
        {"op": "HASH", "imm": 3},
        {"op": "LOOP_BEGIN", "rs": 4, "imm": 22},
        {"op": "DATA_LOAD", "imm": 3},
        {"op": "DATA_LOAD", "imm": 7},
        {"op": "LOOP_BEGIN", "rs": 1, "imm": 35},
        {"op": "DATA_LOAD", "imm": 8},
        {"op": "DATA_LOAD", "imm": 9},
        {"op": "DATA_LOAD", "imm": 10},
        {"op": "SET_REG", "rd": 6, "imm": DYNAMIC_BOUND},
        {
            "op": "LOOP_BEGIN",
            "flags": 1,
            "rd": 6,
            "rs": 2,
            "target": "after_wots_recovery_chain",
        },
        {"op": "HASH", "imm": 4},
        {"op": "LOOP_END"},
        {"label": "after_wots_recovery_chain"},
        {"op": "LOOP_END"},
        {"op": "HASH", "imm": 5},
        {"op": "LOOP_BEGIN", "rs": 2, "imm": 3},
        {"op": "DATA_LOAD", "imm": 11},
        {"op": "HASH", "imm": 6},
        {"op": "LOOP_END"},
        {"op": "DATA_LOAD", "imm": 12},
        {"op": "DATA_LOAD", "imm": 13},
        {"op": "LOOP_END"},
        {"op": "OUTPUT", "rd": CURRENT_ROOT},
        {"op": "HALT"},
    ]
    return {
        "schema_version": 1,
        "micro_isa_version": "0.2",
        "name": "fips205-slh-dsa-shake-128f-verify",
        "entry": "entry",
        "bounds": {
            "scratch_slots": 128,
            "max_loop_bound": 35,
            "max_dynamic_instructions": 50000,
        },
        "layouts": layouts,
        "loads": loads,
        "moves": moves,
        "program": program,
    }


def main() -> int:
    print(json.dumps(build_document(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
