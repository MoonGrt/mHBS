"""Project-local SHAKE256/256 LMS research profile.

This module deliberately is *not* an RFC 8554 implementation.  It retains
the RFC byte encodings, domain separators, Merkle construction, and LM-OTS
coefficient rules, but replaces every SHA-256 invocation by SHAKE256 with a
32-byte output.  Private-use typecodes keep serialized objects from being
mistaken for interoperable RFC 8554 objects.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Callable

from model.reference.lms import (
    D_INTR,
    D_LEAF,
    D_MESG,
    D_PBLC,
    LMOTS_SHA256_N32_W4,
    LmotsParams,
    u16,
    u32,
)


Observe = Callable[[str, bytes, bytes], None]

LMS_SHAKE256_M32_H10 = 0x80000006
LMOTS_SHAKE256_N32_W4 = 0x80000003


@dataclass(frozen=True)
class LmsShakeParams:
    height: int = 10
    n: int = 32
    lmots: LmotsParams = LMOTS_SHA256_N32_W4
    lms_typecode: int = LMS_SHAKE256_M32_H10
    lmots_typecode: int = LMOTS_SHAKE256_N32_W4

    @property
    def signature_bytes(self) -> int:
        return 12 + self.n * (self.lmots.p + 1) + self.height * self.n

    @property
    def public_key_bytes(self) -> int:
        return 24 + self.n

    @property
    def state_bytes(self) -> int:
        return 4 + 16 + self.n + self.n


LMS_SHAKE_H10_W4 = LmsShakeParams()


def shake256(data: bytes) -> bytes:
    return hashlib.shake_256(data).digest(32)


def _hash(kind: str, data: bytes, observe: Observe | None) -> bytes:
    result = shake256(data)
    if observe is not None:
        observe(kind, data, result)
    return result


def _coefficient(value: bytes, index: int, width: int) -> int:
    bit = index * width
    return (value[bit // 8] >> (8 - width - (bit % 8))) & ((1 << width) - 1)


def lmots_coefficients(
    digest: bytes, params: LmsShakeParams = LMS_SHAKE_H10_W4
) -> list[int]:
    ots = params.lmots
    if len(digest) != params.n:
        raise ValueError("LM-OTS digest length mismatch")
    checksum = sum(
        (1 << ots.w) - 1 - _coefficient(digest, index, ots.w)
        for index in range((8 * params.n) // ots.w)
    )
    checksum <<= ots.ls
    expanded = digest + u16(checksum)
    return [_coefficient(expanded, index, ots.w) for index in range(ots.p)]


def private_element(
    identifier: bytes,
    q: int,
    chain: int,
    seed: bytes,
    observe: Observe | None = None,
) -> bytes:
    if len(identifier) != 16 or len(seed) != 32:
        raise ValueError("SHAKE-LMS requires I=16 and SEED=32 bytes")
    preimage = identifier + u32(q) + u16(chain) + b"\xff" + seed
    return _hash("lmots_prf", preimage, observe)


def _chain(
    value: bytes,
    identifier: bytes,
    q: int,
    chain: int,
    start: int,
    steps: int,
    observe: Observe | None,
) -> bytes:
    result = value
    stop = min(start + steps, 1 << LMS_SHAKE_H10_W4.lmots.w)
    for iteration in range(start, stop):
        preimage = identifier + u32(q) + u16(chain) + bytes([iteration]) + result
        result = _hash("ots_chain", preimage, observe)
    return result


def lmots_public_key(
    identifier: bytes,
    q: int,
    seed: bytes,
    params: LmsShakeParams = LMS_SHAKE_H10_W4,
    observe: Observe | None = None,
) -> bytes:
    endpoints = []
    for chain in range(params.lmots.p):
        value = private_element(identifier, q, chain, seed, observe)
        endpoints.append(
            _chain(
                value,
                identifier,
                q,
                chain,
                0,
                (1 << params.lmots.w) - 1,
                observe,
            )
        )
    preimage = identifier + u32(q) + D_PBLC + b"".join(endpoints)
    return _hash("ots_compress", preimage, observe)


def lmots_sign(
    message: bytes,
    identifier: bytes,
    q: int,
    seed: bytes,
    randomizer: bytes,
    params: LmsShakeParams = LMS_SHAKE_H10_W4,
    observe: Observe | None = None,
) -> bytes:
    if len(randomizer) != params.n:
        raise ValueError("LM-OTS randomizer length mismatch")
    digest = _hash(
        "lmots_message",
        identifier + u32(q) + D_MESG + randomizer + message,
        observe,
    )
    coefficients = lmots_coefficients(digest, params)
    values = []
    for chain, steps in enumerate(coefficients):
        value = private_element(identifier, q, chain, seed, observe)
        values.append(
            _chain(value, identifier, q, chain, 0, steps, observe)
        )
    return u32(params.lmots_typecode) + randomizer + b"".join(values)


def lmots_public_key_from_signature(
    message: bytes,
    signature: bytes,
    identifier: bytes,
    q: int,
    params: LmsShakeParams = LMS_SHAKE_H10_W4,
    observe: Observe | None = None,
) -> bytes:
    expected = 4 + params.n * (params.lmots.p + 1)
    if len(signature) != expected:
        raise ValueError("LM-OTS signature length mismatch")
    if int.from_bytes(signature[:4], "big") != params.lmots_typecode:
        raise ValueError("LM-OTS research typecode mismatch")
    randomizer = signature[4 : 4 + params.n]
    digest = _hash(
        "lmots_message",
        identifier + u32(q) + D_MESG + randomizer + message,
        observe,
    )
    coefficients = lmots_coefficients(digest, params)
    offset = 4 + params.n
    endpoints = []
    for chain, start in enumerate(coefficients):
        value = signature[
            offset + chain * params.n : offset + (chain + 1) * params.n
        ]
        endpoints.append(
            _chain(
                value,
                identifier,
                q,
                chain,
                start,
                (1 << params.lmots.w) - 1 - start,
                observe,
            )
        )
    return _hash(
        "ots_compress", identifier + u32(q) + D_PBLC + b"".join(endpoints), observe
    )


def tree_and_authentication(
    identifier: bytes,
    seed: bytes,
    target_leaf: int,
    params: LmsShakeParams = LMS_SHAKE_H10_W4,
    observe: Observe | None = None,
) -> tuple[bytes, tuple[bytes, ...]]:
    if not 0 <= target_leaf < (1 << params.height):
        raise ValueError("LMS target leaf outside tree")
    stack: list[tuple[int, int, bytes]] = []
    auth: dict[int, bytes] = {}
    leaf_base = 1 << params.height
    target_node = leaf_base + target_leaf
    for q in range(1 << params.height):
        ots = lmots_public_key(identifier, q, seed, params, observe)
        node_number = leaf_base + q
        node = _hash(
            "merkle_leaf", identifier + u32(node_number) + D_LEAF + ots, observe
        )
        height = 0
        if node_number == (target_node ^ 1):
            auth[0] = node
        while stack and stack[-1][0] == height:
            _, left_number, left = stack.pop()
            parent_number = left_number // 2
            node = _hash(
                "merkle_internal",
                identifier + u32(parent_number) + D_INTR + left + node,
                observe,
            )
            height += 1
            node_number = parent_number
            if height < params.height and node_number == ((target_node >> height) ^ 1):
                auth[height] = node
        stack.append((height, node_number, node))
    if len(stack) != 1 or set(auth) != set(range(params.height)):
        raise AssertionError("SHAKE-LMS TreeHash failed")
    return stack[0][2], tuple(auth[level] for level in range(params.height))


def public_key_encoding(
    identifier: bytes,
    root: bytes,
    params: LmsShakeParams = LMS_SHAKE_H10_W4,
) -> bytes:
    return (
        u32(params.lms_typecode)
        + u32(params.lmots_typecode)
        + identifier
        + root
    )


def keygen(
    identifier: bytes,
    seed: bytes,
    initial_q: int = 0,
    params: LmsShakeParams = LMS_SHAKE_H10_W4,
    observe: Observe | None = None,
) -> tuple[bytes, bytes]:
    if not 0 <= initial_q <= (1 << params.height):
        raise ValueError("initial LMS index out of range")
    root, _ = tree_and_authentication(identifier, seed, 0, params, observe)
    state = u32(initial_q) + identifier + seed + root
    return state, public_key_encoding(identifier, root, params)


def sign(
    state: bytes,
    message: bytes,
    randomizer: bytes,
    params: LmsShakeParams = LMS_SHAKE_H10_W4,
    observe: Observe | None = None,
    cached_authentication: tuple[bytes, ...] | None = None,
) -> tuple[bytes, bytes]:
    if len(state) != params.state_bytes:
        raise ValueError("SHAKE-LMS state length mismatch")
    q = int.from_bytes(state[:4], "big")
    if q >= 1 << params.height:
        raise ValueError("SHAKE-LMS signing key exhausted")
    identifier = state[4:20]
    seed = state[20:52]
    expected_root = state[52:84]
    ots_signature = lmots_sign(
        message, identifier, q, seed, randomizer, params, observe
    )
    if cached_authentication is None:
        root, authentication = tree_and_authentication(
            identifier, seed, q, params, observe
        )
        if root != expected_root:
            raise AssertionError("SHAKE-LMS state root mismatch")
    else:
        authentication = cached_authentication
        if len(authentication) != params.height:
            raise ValueError("cached authentication path length mismatch")
    signature = (
        u32(q)
        + ots_signature
        + u32(params.lms_typecode)
        + b"".join(authentication)
    )
    if len(signature) != params.signature_bytes:
        raise AssertionError("SHAKE-LMS signature serialization mismatch")
    updated = u32(q + 1) + state[4:]
    return signature, updated


def verify(
    public_key: bytes,
    message: bytes,
    signature: bytes,
    params: LmsShakeParams = LMS_SHAKE_H10_W4,
    observe: Observe | None = None,
) -> bool:
    if len(public_key) != params.public_key_bytes:
        return False
    if len(signature) != params.signature_bytes:
        return False
    if int.from_bytes(public_key[:4], "big") != params.lms_typecode:
        return False
    if int.from_bytes(public_key[4:8], "big") != params.lmots_typecode:
        return False
    q = int.from_bytes(signature[:4], "big")
    if q >= 1 << params.height:
        return False
    identifier = public_key[8:24]
    expected_root = public_key[24:]
    ots_bytes = 4 + params.n * (params.lmots.p + 1)
    lms_type_offset = 4 + ots_bytes
    if int.from_bytes(signature[lms_type_offset:lms_type_offset + 4], "big") != params.lms_typecode:
        return False
    try:
        ots_public = lmots_public_key_from_signature(
            message,
            signature[4:lms_type_offset],
            identifier,
            q,
            params,
            observe,
        )
    except ValueError:
        return False
    node_number = (1 << params.height) + q
    node = _hash(
        "merkle_leaf",
        identifier + u32(node_number) + D_LEAF + ots_public,
        observe,
    )
    offset = lms_type_offset + 4
    for level in range(params.height):
        sibling = signature[
            offset + level * params.n : offset + (level + 1) * params.n
        ]
        parent = node_number // 2
        children = node + sibling if node_number % 2 == 0 else sibling + node
        node = _hash(
            "merkle_internal", identifier + u32(parent) + D_INTR + children, observe
        )
        node_number = parent
    return node == expected_root
