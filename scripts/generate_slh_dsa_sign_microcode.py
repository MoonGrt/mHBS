#!/usr/bin/env python3
"""Generate the loop-compressed FIPS 205 SHAKE-128f Sign program source."""

from __future__ import annotations

import json


FORS_SIGNATURE = 0
# FORS roots overwrite already-consumed signature slots 0..32.  The WOTS
# workspace reuses the same region after FORS compression, keeping every
# instruction-visible address inside the ISA's 8-bit rd field.
FORS_ROOTS = 0
WOTS_VALUES = 0
WOTS_DIGITS = 35
XMSS_AUTH = 70
DIGEST = 231
TREE_ADDRESS = 232
LEAF_INDEX = 233
CURRENT_ROOT = 234
RANDOMIZER = 236
# These temporaries must not alias the live 231-slot FORS signature.
WORK = 237
TREE_ROOT = 238
DYNAMIC_BOUND = 239


def lit(value: int) -> dict[str, object]:
    return {"kind": "literal_int", "value": value}


def reg(index: int) -> dict[str, object]:
    return {"kind": "reg", "reg": index}


def mem(address: int) -> dict[str, object]:
    return {"kind": "memory_int", "base": address}


def ctx(name: str) -> dict[str, object]:
    return {"kind": "context", "name": name}


def op(name: str, *arguments: dict[str, object]) -> dict[str, object]:
    return {"op": name, "args": list(arguments)}


def binary(name: str, left: dict[str, object], right: dict[str, object]) -> dict[str, object]:
    return {"op": name, "left": left, "right": right}


def shift(name: str, value: dict[str, object], amount: dict[str, object]) -> dict[str, object]:
    return {"op": name, "value": value, "shift": amount}


def word(expression: dict[str, object]) -> dict[str, object]:
    return {"kind": "expr", "expression": expression}


def adrs_components(
    address_type: int,
    key_pair: dict[str, object],
    word6: dict[str, object],
    word7: dict[str, object],
) -> list[dict[str, object]]:
    return [
        {"kind": "job_bytes", "field": "pub_seed", "length": 16},
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
    output_bytes: int = 16,
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


def tree_layout(name: str, height: int, address_type: int, key_pair: dict[str, object]) -> dict[str, object]:
    parent_index = shift(
        "shr",
        op("add", reg(3), ctx("tree_start_leaf")),
        ctx("tree_parent_height"),
    )
    return {
        "name": name,
        "tree_height": height,
        "storage_mode": "TREEHASH_MIN",
        "subtree_height": height,
        "root_destination": TREE_ROOT,
        "restart_on_complete": True,
        "class": "h",
        "hash": "shake256",
        "output_bytes": 16,
        "max_input_bytes": 80,
        "components": adrs_components(
            address_type,
            key_pair,
            ctx("tree_parent_height"),
            parent_index,
        )
        + [{"kind": "tree_left"}, {"kind": "tree_right"}],
    }


def build_document() -> dict[str, object]:
    zero = lit(0)
    selected_global = op("add", op("mul", reg(0), lit(64)), reg(1))
    selected_parent = shift(
        "shr", selected_global, op("add", reg(2), lit(1))
    )
    selected_bit = op(
        "and", shift("shr", reg(1), reg(2)), lit(1)
    )
    leaf_parent = shift("shr", reg(5), op("add", reg(2), lit(1)))
    leaf_bit = op("and", shift("shr", reg(5), reg(2)), lit(1))

    layouts: dict[str, object] = {}
    layouts["0"] = shake_layout(
        "signature_randomizer",
        "prf_msg",
        {"base": RANDOMIZER},
        [
            {"kind": "job_bytes", "field": "sk_prf", "length": 16},
            {"kind": "job_bytes", "field": "pub_seed", "length": 16},
            {"kind": "job_bytes", "field": "message"},
        ],
        1056,
    )
    layouts["1"] = shake_layout(
        "message_digest",
        "h_msg",
        {"base": DIGEST},
        [
            {"kind": "memory", "base": RANDOMIZER},
            {"kind": "job_bytes", "field": "pub_seed", "length": 16},
            {"kind": "job_bytes", "field": "root", "length": 16},
            {"kind": "job_bytes", "field": "message"},
        ],
        1056,
        output_bytes=34,
    )
    layouts["2"] = shake_layout(
        "fors_selected_secret",
        "prf",
        {"base": FORS_SIGNATURE, "index_reg": 0, "stride": 7},
        adrs_components(6, reg(5), zero, selected_global)
        + [{"kind": "job_bytes", "field": "sk_seed", "length": 16}],
        64,
    )
    layouts["3"] = shake_layout(
        "fors_auth_secret",
        "prf",
        {"base": WORK},
        adrs_components(6, reg(5), zero, reg(7))
        + [{"kind": "job_bytes", "field": "sk_seed", "length": 16}],
        64,
    )
    layouts["4"] = shake_layout(
        "fors_leaf",
        "f",
        {"base": TREE_ROOT},
        adrs_components(3, reg(5), zero, reg(7))
        + [{"kind": "memory", "base": WORK}],
        64,
    )
    for height in range(1, 6):
        layouts[str(4 + height)] = tree_layout(
            f"fors_auth_subtree_h{height}", height, 3, reg(5)
        )
    layouts["10"] = shake_layout(
        "fors_selected_leaf_recovery",
        "f",
        {"base": CURRENT_ROOT},
        adrs_components(3, reg(5), zero, selected_global)
        + [{"kind": "memory", "base": FORS_SIGNATURE, "index_reg": 0, "stride": 7}],
        64,
    )
    layouts["11"] = shake_layout(
        "fors_auth_path_recovery",
        "h",
        {"base": CURRENT_ROOT},
        adrs_components(3, reg(5), op("add", reg(2), lit(1)), selected_parent)
        + [
            {
                "kind": "ordered_pair",
                "condition": selected_bit,
                "when_zero": [
                    {"kind": "memory", "base": CURRENT_ROOT},
                    {
                        "kind": "memory",
                        "base": FORS_SIGNATURE + 1,
                        "base_reg": 2,
                        "index_reg": 0,
                        "stride": 7,
                    },
                ],
                "when_nonzero": [
                    {
                        "kind": "memory",
                        "base": FORS_SIGNATURE + 1,
                        "base_reg": 2,
                        "index_reg": 0,
                        "stride": 7,
                    },
                    {"kind": "memory", "base": CURRENT_ROOT},
                ],
            }
        ],
        80,
    )
    layouts["12"] = shake_layout(
        "fors_roots_compress",
        "t_l",
        {"base": CURRENT_ROOT},
        adrs_components(4, reg(5), zero, zero)
        + [{"kind": "memory_range", "base": FORS_ROOTS, "count": 33}],
        576,
    )
    layouts["13"] = shake_layout(
        "wots_private_element",
        "prf",
        {"base": WOTS_VALUES, "index_reg": 1},
        adrs_components(5, reg(0), reg(1), zero)
        + [{"kind": "job_bytes", "field": "sk_seed", "length": 16}],
        64,
    )
    layouts["14"] = shake_layout(
        "wots_chain_f",
        "f",
        {"base": WOTS_VALUES, "index_reg": 1},
        adrs_components(0, reg(0), reg(1), reg(7))
        + [{"kind": "memory", "base": WOTS_VALUES, "index_reg": 1}],
        64,
    )
    layouts["15"] = shake_layout(
        "wots_public_key_compress_leaf",
        "t_l",
        {"base": WORK},
        adrs_components(1, reg(0), zero, zero)
        + [{"kind": "memory_range", "base": WOTS_VALUES, "count": 35}],
        608,
    )
    layouts["16"] = tree_layout("xmss_auth_subtree_h1", 1, 2, zero)
    layouts["17"] = tree_layout("xmss_auth_subtree_h2", 2, 2, zero)
    layouts["18"] = shake_layout(
        "wots_signature_recovery_f",
        "f",
        {"base": WOTS_VALUES, "index_reg": 1},
        adrs_components(0, reg(0), reg(1), op("add", reg(7), reg(2)))
        + [{"kind": "memory", "base": WOTS_VALUES, "index_reg": 1}],
        64,
    )
    layouts["19"] = shake_layout(
        "wots_public_key_compress_recovered",
        "t_l",
        {"base": CURRENT_ROOT},
        adrs_components(1, reg(0), zero, zero)
        + [{"kind": "memory_range", "base": WOTS_VALUES, "count": 35}],
        608,
    )
    layouts["20"] = shake_layout(
        "xmss_auth_path_recovery",
        "h",
        {"base": CURRENT_ROOT},
        adrs_components(2, zero, op("add", reg(2), lit(1)), leaf_parent)
        + [
            {
                "kind": "ordered_pair",
                "condition": leaf_bit,
                "when_zero": [
                    {"kind": "memory", "base": CURRENT_ROOT},
                    {"kind": "memory", "base": XMSS_AUTH, "base_reg": 2},
                ],
                "when_nonzero": [
                    {"kind": "memory", "base": XMSS_AUTH, "base_reg": 2},
                    {"kind": "memory", "base": CURRENT_ROOT},
                ],
            }
        ],
        80,
    )

    digest_int = mem(DIGEST)
    fors_shift = binary(
        "sub",
        lit(272),
        op("mul", lit(6), op("add", reg(0), lit(1))),
    )
    fors_start = op(
        "add",
        op("mul", reg(0), lit(64)),
        shift(
            "shl",
            op("xor", shift("shr", reg(1), reg(6)), lit(1)),
            reg(6),
        ),
    )
    xmss_start = shift(
        "shl",
        op("xor", shift("shr", reg(5), reg(6)), lit(1)),
        reg(6),
    )
    loads = {
        "0": {
            "name": "digest_tree_address",
            "transform": "integer_expression",
            "expression": op("and", shift("shr", digest_int, lit(8)), lit((1 << 63) - 1)),
            "bytes": 12,
            "destination": {"base": TREE_ADDRESS},
        },
        "1": {
            "name": "digest_leaf_index",
            "transform": "integer_expression",
            "expression": op("and", digest_int, lit(7)),
            "bytes": 1,
            "destination": {"base": LEAF_INDEX},
        },
        "2": {
            "name": "leaf_index_register",
            "source": {"kind": "memory", "base": LEAF_INDEX},
            "destination_reg": 5,
            "endian": "big",
        },
        "3": {
            "name": "fors_selected_index",
            "transform": "integer_expression",
            "expression": op("and", shift("shr", digest_int, fors_shift), lit(63)),
            "destination_reg": 1,
        },
        "4": {
            "name": "fors_auth_subtree_start",
            "transform": "integer_expression",
            "expression": fors_start,
            "destination_reg": 3,
        },
        "5": {
            "name": "subtree_current_leaf",
            "transform": "integer_expression",
            "expression": op("add", reg(3), reg(2)),
            "destination_reg": 7,
        },
        "6": {
            "name": "fors_signature_pointer",
            "transform": "integer_expression",
            "expression": op("mul", reg(0), lit(7)),
            "destination_reg": 6,
        },
        "7": {
            "name": "xmss_auth_subtree_start",
            "transform": "integer_expression",
            "expression": xmss_start,
            "destination_reg": 3,
        },
        "8": {
            "name": "xmss_subtree_current_leaf",
            "transform": "integer_expression",
            "expression": op("add", reg(3), reg(2)),
            "destination_reg": 0,
        },
        "9": {
            "name": "wots_chain_lengths",
            "source": {"kind": "memory", "base": CURRENT_ROOT},
            "transform": "base_w_checksum",
            "log_w": 4,
            "len1": 32,
            "len2": 3,
            "destination": {"base": WOTS_DIGITS},
        },
        "10": {
            "name": "wots_digit_register",
            "source": {"kind": "memory", "base": WOTS_DIGITS, "index_reg": 1},
            "destination_reg": 7,
            "endian": "big",
        },
        "11": {
            "name": "wots_recovery_bound",
            "transform": "integer_expression",
            "expression": binary("sub", lit(15), reg(7)),
            "bytes": 1,
            "destination": {"base": DYNAMIC_BOUND},
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
            "name": "save_fors_auth_root",
            "source": {"base": TREE_ROOT},
            "destination": {"base": FORS_SIGNATURE + 1, "base_reg": 6, "index_reg": 0, "stride": 7},
        },
        "1": {
            "name": "save_fors_root",
            "source": {"base": CURRENT_ROOT},
            "destination": {"base": FORS_ROOTS, "index_reg": 0},
        },
        "2": {
            "name": "leaf_to_tree_root",
            "source": {"base": WORK},
            "destination": {"base": TREE_ROOT},
        },
        "3": {
            "name": "save_xmss_auth_root",
            "source": {"base": TREE_ROOT},
            "destination": {"base": XMSS_AUTH, "base_reg": 6},
        },
    }

    program: list[dict[str, object]] = [
        {"label": "entry"},
        {"op": "HASH_LAYOUT", "imm": 0},
        {"op": "EMIT", "rd": RANDOMIZER},
        {"op": "HASH_LAYOUT", "imm": 1},
        {"op": "LOAD", "imm": 0},
        {"op": "LOAD", "imm": 1},
        {"op": "LOAD", "imm": 2},
        {"op": "LOOP_SETUP", "rs": 0, "imm": 33},
        {"op": "LOAD", "imm": 3},
        {"op": "HASH_LAYOUT", "imm": 2},
    ]
    for height in range(6):
        program.extend(
            [
                {"op": "MOVI", "rd": 6, "imm": height},
                {"op": "LOAD", "imm": 4},
            ]
        )
        if height == 0:
            program.extend(
                [
                    {"op": "MOVI", "rd": 2, "imm": 0},
                    {"op": "LOAD", "imm": 5},
                    {"op": "HASH_LAYOUT", "imm": 3},
                    {"op": "HASH_LAYOUT", "imm": 4},
                ]
            )
        else:
            program.extend(
                [
                    {"op": "LOOP_SETUP", "rs": 2, "imm": 1 << height},
                    {"op": "LOAD", "imm": 5},
                    {"op": "HASH_LAYOUT", "imm": 3},
                    {"op": "HASH_LAYOUT", "imm": 4},
                    {"op": "TREE_PUSH", "rd": TREE_ROOT, "imm": 4 + height},
                    {"op": "LOOP_END"},
                ]
            )
        program.append({"op": "STORE", "imm": 0})
    program.extend(
        [
            {"op": "LOAD", "imm": 6},
            *({"op": "EMIT", "flags": 1, "rd": 0, "rs": 6, "imm": offset} for offset in range(7)),
            {"op": "LOOP_END"},
            {"op": "LOOP_SETUP", "rs": 0, "imm": 33},
            {"op": "LOAD", "imm": 3},
            {"op": "HASH_LAYOUT", "imm": 10},
            {"op": "LOOP_SETUP", "rs": 2, "imm": 6},
            {"op": "HASH_LAYOUT", "imm": 11},
            {"op": "LOOP_END"},
            {"op": "STORE", "imm": 1},
            {"op": "LOOP_END"},
            {"op": "HASH_LAYOUT", "imm": 12},
            # The first 21 layers need their recovered root for the next
            # layer.  The final layer only emits its XMSS signature.
            {"op": "LOOP_SETUP", "rs": 4, "imm": 21},
            {"op": "CALL", "target": "xmss_sign_layer"},
            {"op": "LOOP_SETUP", "rs": 1, "imm": 35},
            {"op": "LOAD", "imm": 10},
            {"op": "LOAD", "imm": 11},
            {"op": "MOVI", "rd": 6, "imm": DYNAMIC_BOUND},
            {"op": "LOOP_SETUP", "flags": 1, "rd": 6, "rs": 2, "target": "after_wots_recovery_chain"},
            {"op": "HASH_LAYOUT", "imm": 18},
            {"op": "LOOP_END"},
            {"label": "after_wots_recovery_chain"},
            {"op": "LOOP_END"},
            {"op": "HASH_LAYOUT", "imm": 19},
            {"op": "LOOP_SETUP", "rs": 2, "imm": 3},
            {"op": "HASH_LAYOUT", "imm": 20},
            {"op": "LOOP_END"},
            {"op": "LOAD", "imm": 12},
            {"op": "LOAD", "imm": 13},
            {"op": "LOOP_END"},
            {"op": "CALL", "target": "xmss_sign_layer"},
            {"op": "HALT"},
            {"label": "xmss_sign_layer"},
            {"op": "LOAD", "imm": 2},
        ]
    )
    for height in range(3):
        program.extend(
            [
                {"op": "MOVI", "rd": 6, "imm": height},
                {"op": "LOAD", "imm": 7},
            ]
        )
        if height == 0:
            program.extend(
                [
                    {"op": "MOVI", "rd": 2, "imm": 0},
                    {"op": "LOAD", "imm": 8},
                    {"op": "CALL", "target": "wots_pkgen"},
                    {"op": "STORE", "imm": 2},
                ]
            )
        else:
            program.extend(
                [
                    {"op": "LOOP_SETUP", "rs": 2, "imm": 1 << height},
                    {"op": "LOAD", "imm": 8},
                    {"op": "CALL", "target": "wots_pkgen"},
                    {"op": "TREE_PUSH", "rd": WORK, "imm": 15 + height},
                    {"op": "LOOP_END"},
                ]
            )
        program.append({"op": "STORE", "imm": 3})
    program.extend(
        [
            {"op": "ADDI", "rd": 0, "rs": 5, "imm": 0},
            {"op": "LOAD", "imm": 9},
            {"op": "LOOP_SETUP", "rs": 1, "imm": 35},
            {"op": "HASH_LAYOUT", "imm": 13},
            {"op": "ADDI", "rd": 6, "rs": 1, "imm": WOTS_DIGITS},
            {"op": "LOOP_SETUP", "flags": 1, "rd": 6, "rs": 7, "target": "after_wots_sign_chain"},
            {"op": "HASH_LAYOUT", "imm": 14},
            {"op": "LOOP_END"},
            {"label": "after_wots_sign_chain"},
            {"op": "EMIT", "flags": 1, "rd": WOTS_VALUES, "rs": 1},
            {"op": "LOOP_END"},
            {"op": "EMIT", "rd": XMSS_AUTH},
            {"op": "EMIT", "rd": XMSS_AUTH + 1},
            {"op": "EMIT", "rd": XMSS_AUTH + 2},
            {"op": "RET"},
            {"label": "wots_pkgen"},
            {"op": "LOOP_SETUP", "rs": 1, "imm": 35},
            {"op": "HASH_LAYOUT", "imm": 13},
            {"op": "LOOP_SETUP", "rs": 7, "imm": 15},
            {"op": "HASH_LAYOUT", "imm": 14},
            {"op": "LOOP_END"},
            {"op": "LOOP_END"},
            {"op": "HASH_LAYOUT", "imm": 15},
            {"op": "RET"},
        ]
    )
    return {
        "schema_version": 1,
        "micro_isa_version": "0.1",
        "name": "fips205-slh-dsa-shake-128f-sign",
        "entry": "entry",
        "bounds": {
            "scratch_slots": 256,
            "max_loop_bound": 35,
            "max_dynamic_instructions": 500000,
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
