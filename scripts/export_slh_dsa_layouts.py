#!/usr/bin/env python3
"""Export the directly executable SLH-DSA Sign prehash layouts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.layout_lowering import lower_layouts  # noqa: E402
from model.data_lowering import (  # noqa: E402
    AddressExpression,
    LogicalDescriptor,
    descriptor_from_program_move,
    lower_logical_data,
)
from model.reference.slh_dsa import (  # noqa: E402
    FORS_TREE,
    SLH_DSA_SHAKE_128F,
    _fors_pk_from_sig,
    _fors_sign,
    _hash_message,
    _set_tree_address,
    _set_type_and_clear,
    sign_internal,
)


SOURCE = ROOT / "microcode/slh_dsa/slh_dsa_shake_128f_sign.json"
KAT = ROOT / "tests/kat/slh_dsa_shake_128f_siggen_acvp_tc137.json"
OUTPUT_DIR = ROOT / "manifests/programs/rtl_images"
LAYOUT_HEX = OUTPUT_DIR / "slh_dsa_shake_128f_sign_prehash_layouts.hex"
COMPONENT_HEX = OUTPUT_DIR / "slh_dsa_shake_128f_sign_prehash_components.hex"
BITFIELD_HEX = OUTPUT_DIR / "slh_dsa_shake_128f_sign_digest_bitfields.hex"
EXPR_DESCRIPTOR_HEX = OUTPUT_DIR / "slh_dsa_shake_128f_sign_expr_descriptors.hex"
EXPR_TOKEN_HEX = OUTPUT_DIR / "slh_dsa_shake_128f_sign_expr_tokens.hex"
BASE_W_DESCRIPTOR_HEX = OUTPUT_DIR / "slh_dsa_shake_128f_sign_base_w_descriptor.hex"
WIDE_SHIFT_DESCRIPTOR_HEX = OUTPUT_DIR / "slh_dsa_shake_128f_sign_wide_shift_descriptor.hex"
DATA_DESCRIPTOR_HEX = OUTPUT_DIR / "slh_dsa_shake_128f_sign_data_descriptors.hex"
DATA_BINDING_HEX = OUTPUT_DIR / "slh_dsa_shake_128f_sign_data_bindings.hex"
TREE_DESCRIPTOR_HEX = OUTPUT_DIR / "slh_dsa_shake_128f_sign_tree_descriptors.hex"
FORS_EXPECTED_HEX = OUTPUT_DIR / "slh_dsa_shake_128f_fors_signature_expected.hex"
FORS_ROOT_EXPECTED_HEX = OUTPUT_DIR / "slh_dsa_shake_128f_fors_root_expected.hex"
SIGNATURE_EXPECTED_HEX = OUTPUT_DIR / "slh_dsa_shake_128f_signature_expected.hex"
MANIFEST = ROOT / "manifests/programs/slh_dsa_sign_layout_image_v0.1.0.json"


def _bitfield_descriptor(*, source: int, input_bytes: int, bit_offset: int,
                         bit_width: int, destination_is_reg: bool,
                         destination_reg: int = 0, destination: int = 0,
                         output_bytes: int = 0, use_index: bool = False,
                         index_reg: int = 0, stride: int = 0) -> int:
    return (
        (1 << 120) | (1 << 112) | (source << 96)
        | (input_bytes << 80) | (bit_offset << 64) | (stride << 56)
        | (index_reg << 53) | (int(use_index) << 52)
        | (bit_width << 45) | (int(destination_is_reg) << 44)
        | (destination_reg << 41) | (destination << 25)
        | (output_bytes << 20)
    )


_EXPR_OPCODES = {
    "add": 0x10, "sub": 0x11, "xor": 0x12, "and": 0x13,
    "or": 0x14, "shl": 0x15, "shr": 0x16,
}


def _expr_token(opcode: int, immediate: int = 0) -> int:
    if not 0 <= immediate < (1 << 56):
        raise ValueError(f"expression immediate out of range: {immediate}")
    return (opcode << 56) | immediate


def _literal_value(node: object) -> int | None:
    if isinstance(node, dict) and node.get("kind") == "literal_int":
        return int(node["value"])
    return None


def _lower_expr(node: dict) -> list[int]:
    kind = node.get("kind")
    if kind == "literal_int":
        return [_expr_token(0x01, int(node["value"]))]
    if kind == "reg":
        return [_expr_token(0x02, int(node["reg"]))]
    op = node.get("op")
    if op == "mul":
        args = list(node["args"])
        if len(args) != 2:
            raise ValueError("only binary constant multiplication is supported")
        constant = _literal_value(args[0])
        value = args[1]
        if constant is None:
            constant = _literal_value(args[1])
            value = args[0]
        if constant is None or constant < 0:
            raise ValueError("multiplication requires a non-negative literal")
        if constant == 0:
            return [_expr_token(0x01, 0)]
        tokens: list[int] = []
        first = True
        for bit in range(constant.bit_length()):
            if not (constant & (1 << bit)):
                continue
            tokens.extend(_lower_expr(value))
            if bit:
                tokens.extend([_expr_token(0x01, bit), _expr_token(0x15)])
            if not first:
                tokens.append(_expr_token(0x10))
            first = False
        return tokens
    if op in {"add", "xor", "and", "or"}:
        args = list(node["args"])
        if len(args) < 2:
            raise ValueError(f"{op} needs at least two operands")
        tokens = _lower_expr(args[0])
        for arg in args[1:]:
            tokens.extend(_lower_expr(arg))
            tokens.append(_expr_token(_EXPR_OPCODES[op]))
        return tokens
    if op in {"sub"}:
        return (_lower_expr(node["left"]) + _lower_expr(node["right"])
                + [_expr_token(_EXPR_OPCODES[op])])
    if op in {"shl", "shr"}:
        return (_lower_expr(node["value"]) + _lower_expr(node["shift"])
                + [_expr_token(_EXPR_OPCODES[op])])
    raise ValueError(f"unsupported expression node: {node}")


def _expr_descriptor(*, start_pc: int, count: int,
                     destination_reg: int | None = None,
                     destination_word: int = 0, output_bytes: int = 0) -> int:
    return (
        (1 << 56) | (start_pc << 48) | (count << 40)
        | (int(destination_reg is not None) << 39)
        | ((destination_reg or 0) << 36) | (destination_word << 20)
        | (output_bytes << 15)
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    document = json.loads(SOURCE.read_text(encoding="utf-8"))
    vector = json.loads(KAT.read_text(encoding="utf-8"))
    message_bytes = len(bytes.fromhex(vector["message"]))
    field_slots = {
        "sk_seed": 256,
        "sk_prf": 257,
        "pub_seed": 258,
        "root": 259,
        "opt_rand": 260,
        "message": 261,
    }
    result = lower_layouts(
        document,
        [0, 1, 2, 3, 4, 10, 11, 12, 13, 14, 15, 18, 19, 20, 21, 22, 23],
        slot_bytes=16,
        job_field_slots=field_slots,
        job_field_lengths={"message": message_bytes},
        memory_lengths={232: 12, 233: 1, 236: 16},
        # The abstract model stores variable-length values per logical slot.
        # Give the 34-byte H_msg object a disjoint three-slot physical extent;
        # otherwise logical destinations 232/233 would alias its live bytes.
        memory_slot_map={231: 240},
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LAYOUT_HEX.write_text(result.layout_hex(), encoding="ascii")
    COMPONENT_HEX.write_text(result.component_hex(), encoding="ascii")
    bitfields = [
        _bitfield_descriptor(source=480, input_bytes=34, bit_offset=201,
                             bit_width=63, destination_is_reg=False,
                             destination=464, output_bytes=12),
        _bitfield_descriptor(source=480, input_bytes=34, bit_offset=269,
                             bit_width=3, destination_is_reg=False,
                             destination=466, output_bytes=1),
        _bitfield_descriptor(source=466, input_bytes=1, bit_offset=0,
                             bit_width=8, destination_is_reg=True,
                             destination_reg=5),
        _bitfield_descriptor(source=480, input_bytes=34, bit_offset=0,
                             bit_width=6, destination_is_reg=True,
                             destination_reg=1, use_index=True,
                             index_reg=0, stride=6),
        _bitfield_descriptor(source=500, input_bytes=35, bit_offset=0,
                             bit_width=8, destination_is_reg=True,
                             destination_reg=7, use_index=True,
                             index_reg=1, stride=8),
        _bitfield_descriptor(source=464, input_bytes=12, bit_offset=93,
                             bit_width=3, destination_is_reg=False,
                             destination=466, output_bytes=1),
        _bitfield_descriptor(source=500, input_bytes=35, bit_offset=0,
                             bit_width=8, destination_is_reg=True,
                             destination_reg=2, use_index=True,
                             index_reg=1, stride=16),
        _bitfield_descriptor(source=500, input_bytes=35, bit_offset=8,
                             bit_width=8, destination_is_reg=True,
                             destination_reg=3, use_index=True,
                             index_reg=1, stride=16),
    ]
    BITFIELD_HEX.write_text(
        "".join(f"{word:032x}\n" for word in bitfields), encoding="ascii"
    )
    expression_load_ids = [4, 5, 6, 7, 8, 11]
    expression_tokens: list[int] = []
    expression_descriptors: list[int] = []
    for load_id in expression_load_ids:
        load = document["loads"][str(load_id)]
        lowered = _lower_expr(load["expression"])
        start_pc = len(expression_tokens)
        expression_tokens.extend(lowered)
        if "destination_reg" in load:
            descriptor = _expr_descriptor(
                start_pc=start_pc, count=len(lowered),
                destination_reg=int(load["destination_reg"]),
            )
        else:
            logical_slot = int(load["destination"]["base"])
            descriptor = _expr_descriptor(
                start_pc=start_pc, count=len(lowered),
                destination_word=logical_slot * 2,
                output_bytes=int(load["bytes"]),
            )
        expression_descriptors.append(descriptor)
    if len(expression_tokens) > 64:
        raise ValueError("SLH-DSA expression token image exceeds 64 words")
    EXPR_DESCRIPTOR_HEX.write_text(
        "".join(f"{word:016x}\n" for word in expression_descriptors),
        encoding="ascii",
    )
    EXPR_TOKEN_HEX.write_text(
        "".join(f"{word:016x}\n" for word in expression_tokens),
        encoding="ascii",
    )
    base_w_descriptor = (
        (1 << 56) | (1 << 48) | (468 << 32) | (500 << 16) | (16 << 8)
    )
    BASE_W_DESCRIPTOR_HEX.write_text(
        f"{base_w_descriptor:016x}\n", encoding="ascii"
    )
    wide_shift_descriptor = (
        (1 << 56) | (1 << 48) | (464 << 32) | (464 << 16)
        | (12 << 8) | (1 << 7) | 3
    )
    WIDE_SHIFT_DESCRIPTOR_HEX.write_text(
        f"{wide_shift_descriptor:016x}\n", encoding="ascii"
    )
    data_image = lower_logical_data(
        [],
        [descriptor_from_program_move(document, move_id, byte_count=16)
         for move_id in range(4)] + [
            LogicalDescriptor(
                descriptor_id=4, operation="OUTPUT", byte_count=16,
                source_a=AddressExpression(base=0),
            )
        ],
        logical_slot_count=512,
        logical_slot_bytes=16,
        scratch_capacity_words=1024,
        register_bounds={0: (0, 32), 6: (0, 6)},
    )
    DATA_DESCRIPTOR_HEX.write_text(data_image.descriptor_hex(), encoding="ascii")
    DATA_BINDING_HEX.write_text(data_image.binding_hex(), encoding="ascii")
    tree_layout_ids = [5, 6, 7, 8, 9, 16, 17]
    tree_descriptors: list[int] = []
    for layout_id in tree_layout_ids:
        layout = document["layouts"][str(layout_id)]
        address_type = 3 if layout_id <= 9 else 2
        use_keypair_reg = layout_id <= 9
        root_word = int(layout["root_destination"]) * 2
        tree_descriptors.append(
            (1 << 56) | (int(layout["tree_height"]) << 48)
            | (address_type << 40) | (int(use_keypair_reg) << 39)
            | ((5 if use_keypair_reg else 0) << 36) | (root_word << 20)
        )
    TREE_DESCRIPTOR_HEX.write_text(
        "".join(f"{word:016x}\n" for word in tree_descriptors),
        encoding="ascii",
    )
    # Test-only oracle image.  It is generated offline from the independent
    # FIPS 205 reference model and never enters the synthesizable design.
    secret_key = bytes.fromhex(vector["sk"])
    message = bytes.fromhex(vector["message"])
    public_seed = secret_key[32:48]
    public_root = secret_key[48:64]
    digest = _hash_message(
        SLH_DSA_SHAKE_128F,
        bytes.fromhex(vector["signature_r"]),
        public_seed,
        public_root,
        message,
    )
    fors_bytes = (SLH_DSA_SHAKE_128F.k * SLH_DSA_SHAKE_128F.a + 7) // 8
    tree_bytes = (SLH_DSA_SHAKE_128F.h - SLH_DSA_SHAKE_128F.hp + 7) // 8
    message_digest = digest[:fors_bytes]
    tree_index = int.from_bytes(
        digest[fors_bytes:fors_bytes + tree_bytes], "big"
    ) & ((1 << (SLH_DSA_SHAKE_128F.h - SLH_DSA_SHAKE_128F.hp)) - 1)
    leaf_index = digest[fors_bytes + tree_bytes] & (
        (1 << SLH_DSA_SHAKE_128F.hp) - 1
    )
    address = [0] * 8
    _set_tree_address(address, tree_index)
    _set_type_and_clear(address, FORS_TREE)
    address[5] = leaf_index
    fors_signature = _fors_sign(
        SLH_DSA_SHAKE_128F,
        message_digest,
        secret_key[:16],
        public_seed,
        address,
    )
    expected_fors_bytes = (
        SLH_DSA_SHAKE_128F.k * (SLH_DSA_SHAKE_128F.a + 1)
        * SLH_DSA_SHAKE_128F.n
    )
    if len(fors_signature) != expected_fors_bytes:
        raise AssertionError("unexpected FORS signature length")
    fors_words = [
        int.from_bytes(fors_signature[offset:offset + 8], "little")
        for offset in range(0, len(fors_signature), 8)
    ]
    FORS_EXPECTED_HEX.write_text(
        "".join(f"{word:016x}\n" for word in fors_words), encoding="ascii"
    )
    fors_root = _fors_pk_from_sig(
        SLH_DSA_SHAKE_128F, fors_signature, message_digest,
        public_seed, address.copy(),
    )
    fors_root_words = [
        int.from_bytes(fors_root[offset:offset + 8], "little")
        for offset in range(0, len(fors_root), 8)
    ]
    FORS_ROOT_EXPECTED_HEX.write_text(
        "".join(f"{word:016x}\n" for word in fors_root_words),
        encoding="ascii",
    )
    signature = sign_internal(
        SLH_DSA_SHAKE_128F, message, secret_key,
        additional_randomness=public_seed,
    )
    if signature[:16] != bytes.fromhex(vector["signature_r"]):
        raise AssertionError("reference randomizer differs from NIST KAT")
    if signature[16:16 + len(fors_signature)] != fors_signature:
        raise AssertionError("reference FORS signature is internally inconsistent")
    if hashlib.sha256(signature).hexdigest() != vector["signature_sha256"]:
        raise AssertionError("reference signature differs from NIST KAT digest")
    signature_words = [
        int.from_bytes(signature[offset:offset + 8], "little")
        for offset in range(0, len(signature), 8)
    ]
    SIGNATURE_EXPECTED_HEX.write_text(
        "".join(f"{word:016x}\n" for word in signature_words),
        encoding="ascii",
    )
    record = {
        "schema_version": 1,
        "artifact_kind": "micro_hbs_slh_dsa_layout_component_image",
        "source": str(SOURCE.relative_to(ROOT)),
        "source_sha256": _sha256(SOURCE),
        "kat": str(KAT.relative_to(ROOT)),
        "kat_sha256": _sha256(KAT),
        "layout_ids": [item.layout_id for item in result.layouts],
        "layout_count": len(result.layouts),
        "component_count": len(result.components),
        "logical_slot_bytes": 16,
        "job_field_slots": field_slots,
        "memory_slot_map": {"231": 240},
        "frozen_message_bytes": message_bytes,
        "image_sha256": result.sha256,
        "layout_hex": {
            "path": str(LAYOUT_HEX.relative_to(ROOT)),
            "sha256": _sha256(LAYOUT_HEX),
            "line_count": len(result.layouts),
        },
        "component_hex": {
            "path": str(COMPONENT_HEX.relative_to(ROOT)),
            "sha256": _sha256(COMPONENT_HEX),
            "line_count": len(result.components),
        },
        "bitfield_hex": {
            "path": str(BITFIELD_HEX.relative_to(ROOT)),
            "sha256": _sha256(BITFIELD_HEX),
            "line_count": len(bitfields),
            "load_ids": [0, 1, 2, 3, 10, 12, 14, 15],
        },
        "expression_descriptor_hex": {
            "path": str(EXPR_DESCRIPTOR_HEX.relative_to(ROOT)),
            "sha256": _sha256(EXPR_DESCRIPTOR_HEX),
            "line_count": len(expression_descriptors),
            "load_ids": expression_load_ids,
        },
        "expression_token_hex": {
            "path": str(EXPR_TOKEN_HEX.relative_to(ROOT)),
            "sha256": _sha256(EXPR_TOKEN_HEX),
            "line_count": len(expression_tokens),
        },
        "base_w_descriptor_hex": {
            "path": str(BASE_W_DESCRIPTOR_HEX.relative_to(ROOT)),
            "sha256": _sha256(BASE_W_DESCRIPTOR_HEX),
            "line_count": 1,
            "load_ids": [9],
            "packed_digit_physical_word": 500,
        },
        "wide_shift_descriptor_hex": {
            "path": str(WIDE_SHIFT_DESCRIPTOR_HEX.relative_to(ROOT)),
            "sha256": _sha256(WIDE_SHIFT_DESCRIPTOR_HEX),
            "line_count": 1,
            "load_ids": [13],
            "width_bits": 96,
        },
        "data_descriptor_hex": {
            "path": str(DATA_DESCRIPTOR_HEX.relative_to(ROOT)),
            "sha256": _sha256(DATA_DESCRIPTOR_HEX),
            "line_count": len(data_image.descriptors),
            "move_ids": [0, 1, 2, 3],
            "format_version": data_image.descriptor_format_version,
        },
        "data_binding_hex": {
            "path": str(DATA_BINDING_HEX.relative_to(ROOT)),
            "sha256": _sha256(DATA_BINDING_HEX),
            "line_count": len(data_image.bindings),
        },
        "tree_descriptor_hex": {
            "path": str(TREE_DESCRIPTOR_HEX.relative_to(ROOT)),
            "sha256": _sha256(TREE_DESCRIPTOR_HEX),
            "line_count": len(tree_descriptors),
            "layout_ids": tree_layout_ids,
            "maximum_tree_height": 5,
        },
        "fors_expected_hex": {
            "path": str(FORS_EXPECTED_HEX.relative_to(ROOT)),
            "sha256": _sha256(FORS_EXPECTED_HEX),
            "line_count": len(fors_words),
            "bytes": len(fors_signature),
            "role": "test_only_independent_reference_oracle",
        },
        "fors_root_expected_hex": {
            "path": str(FORS_ROOT_EXPECTED_HEX.relative_to(ROOT)),
            "sha256": _sha256(FORS_ROOT_EXPECTED_HEX),
            "line_count": len(fors_root_words),
            "bytes": len(fors_root),
            "role": "test_only_independent_reference_oracle",
        },
        "signature_expected_hex": {
            "path": str(SIGNATURE_EXPECTED_HEX.relative_to(ROOT)),
            "sha256": _sha256(SIGNATURE_EXPECTED_HEX),
            "line_count": len(signature_words),
            "bytes": len(signature),
            "signature_sha256": hashlib.sha256(signature).hexdigest(),
            "role": "test_only_independent_reference_oracle",
        },
        "execution_contract": {
            "offline_export_only": True,
            "runtime_task_ingress": False,
            "runtime_hash_ingress": False,
            "message_payload_stream_only": True,
        },
        "limitations": [
            "All non-tree-context Sign layouts are lowered; layouts 5-9 and "
            "16-17 are consumed by the descriptor-driven TreeHash adapter.",
            "The KAT image freezes a one-byte message; the loader and lowering "
            "format support bounded longer messages through offline component splitting.",
        ],
    }
    MANIFEST.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"exported {len(result.layouts)} SLH-DSA layouts / "
        f"{len(result.components)} components ({result.sha256})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
