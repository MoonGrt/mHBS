"""Small, dependency-free RFC 8554 LMS/LM-OTS reference implementation."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Callable


D_PBLC = b"\x80\x80"
D_MESG = b"\x81\x81"
D_LEAF = b"\x82\x82"
D_INTR = b"\x83\x83"
LMS_SHA256_M32_H10 = 6


@dataclass(frozen=True)
class LmotsParams:
    typecode: int
    n: int
    w: int
    p: int
    ls: int


LMOTS_SHA256_N32_W1 = LmotsParams(1, 32, 1, 265, 7)
LMOTS_SHA256_N32_W2 = LmotsParams(2, 32, 2, 133, 6)
LMOTS_SHA256_N32_W4 = LmotsParams(3, 32, 4, 67, 4)
LMOTS_SHA256_N32_W8 = LmotsParams(4, 32, 8, 34, 0)


def u32(value: int) -> bytes:
    return value.to_bytes(4, "big", signed=False)


def u16(value: int) -> bytes:
    return value.to_bytes(2, "big", signed=False)


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def lmots_private_element(identifier: bytes, q: int, i: int, seed: bytes) -> bytes:
    if len(identifier) != 16 or len(seed) != 32:
        raise ValueError("RFC 8554 deterministic generation requires I=16 and SEED=32 bytes")
    return sha256(identifier + u32(q) + u16(i) + b"\xff" + seed)


def lmots_public_key(
    identifier: bytes,
    q: int,
    seed: bytes,
    params: LmotsParams = LMOTS_SHA256_N32_W4,
    observe: Callable[[str, bytes, bytes], None] | None = None,
) -> bytes:
    ys: list[bytes] = []
    for i in range(params.p):
        inp = identifier + u32(q) + u16(i) + b"\xff" + seed
        tmp = sha256(inp)
        if observe:
            observe("lmots_prf", inp, tmp)
        for j in range((1 << params.w) - 1):
            inp = identifier + u32(q) + u16(i) + bytes([j]) + tmp
            tmp = sha256(inp)
            if observe:
                observe("ots_chain", inp, tmp)
        ys.append(tmp)
    inp = identifier + u32(q) + D_PBLC + b"".join(ys)
    result = sha256(inp)
    if observe:
        observe("ots_compress", inp, result)
    return result


def _coefficient(value: bytes, index: int, width: int) -> int:
    bit = index * width
    return (value[bit // 8] >> (8 - width - (bit % 8))) & ((1 << width) - 1)


def _lmots_coefficients(digest: bytes, params: LmotsParams) -> list[int]:
    checksum = sum(
        (1 << params.w) - 1 - _coefficient(digest, index, params.w)
        for index in range((8 * params.n) // params.w)
    )
    checksum <<= params.ls
    expanded = digest + u16(checksum)
    return [_coefficient(expanded, index, params.w) for index in range(params.p)]


def lmots_sign(
    message: bytes,
    identifier: bytes,
    q: int,
    seed: bytes,
    randomizer: bytes,
    params: LmotsParams = LMOTS_SHA256_N32_W4,
    observe: Callable[[str, bytes, bytes], None] | None = None,
) -> bytes:
    """Return the RFC 8554 LM-OTS signature encoding."""
    if len(identifier) != 16 or len(seed) != params.n or len(randomizer) != params.n:
        raise ValueError("LM-OTS input length mismatch")
    digest_input = identifier + u32(q) + D_MESG + randomizer + message
    digest = sha256(digest_input)
    if observe:
        observe("lmots_message", digest_input, digest)
    coefficients = _lmots_coefficients(digest, params)
    values: list[bytes] = []
    for index, steps in enumerate(coefficients):
        private_input = identifier + u32(q) + u16(index) + b"\xff" + seed
        value = sha256(private_input)
        if observe:
            observe("lmots_prf", private_input, value)
        for chain_index in range(steps):
            chain_input = (
                identifier + u32(q) + u16(index) + bytes([chain_index]) + value
            )
            value = sha256(chain_input)
            if observe:
                observe("ots_chain", chain_input, value)
        values.append(value)
    return u32(params.typecode) + randomizer + b"".join(values)


def lmots_public_key_from_signature(
    message: bytes,
    signature: bytes,
    identifier: bytes,
    q: int,
    params: LmotsParams = LMOTS_SHA256_N32_W4,
    observe: Callable[[str, bytes, bytes], None] | None = None,
) -> bytes:
    """Compute RFC 8554 Algorithm 4b's LM-OTS public-key candidate."""
    expected = 4 + params.n * (params.p + 1)
    if len(identifier) != 16 or len(signature) != expected:
        raise ValueError("LM-OTS signature length mismatch")
    if int.from_bytes(signature[:4], "big") != params.typecode:
        raise ValueError("LM-OTS signature type mismatch")
    randomizer = signature[4 : 4 + params.n]
    digest_input = identifier + u32(q) + D_MESG + randomizer + message
    digest = sha256(digest_input)
    if observe:
        observe("lmots_message", digest_input, digest)
    coefficients = _lmots_coefficients(digest, params)
    values: list[bytes] = []
    offset = 4 + params.n
    for index, start in enumerate(coefficients):
        value = signature[offset + index * params.n : offset + (index + 1) * params.n]
        for chain_index in range(start, (1 << params.w) - 1):
            chain_input = (
                identifier + u32(q) + u16(index) + bytes([chain_index]) + value
            )
            value = sha256(chain_input)
            if observe:
                observe("ots_chain", chain_input, value)
        values.append(value)
    public_input = identifier + u32(q) + D_PBLC + b"".join(values)
    result = sha256(public_input)
    if observe:
        observe("ots_compress", public_input, result)
    return result


def _lms_root_and_authentication(
    identifier: bytes,
    seed: bytes,
    target_leaf: int,
    height: int,
    params: LmotsParams,
    observe: Callable[[str, bytes, bytes], None] | None,
) -> tuple[bytes, list[bytes]]:
    """Streaming TreeHash with authentication-path capture."""
    if not 0 <= target_leaf < (1 << height):
        raise ValueError("LMS target leaf outside tree")
    stack: list[tuple[int, int, bytes]] = []
    authentication: dict[int, bytes] = {}
    leaf_base = 1 << height
    target_node = leaf_base + target_leaf
    for q in range(1 << height):
        ots = lmots_public_key(identifier, q, seed, params, observe)
        node_index = leaf_base + q
        leaf_input = identifier + u32(node_index) + D_LEAF + ots
        node = sha256(leaf_input)
        if observe:
            observe("merkle_leaf", leaf_input, node)
        node_height = 0
        if node_index == (target_node ^ 1):
            authentication[0] = node
        while stack and stack[-1][0] == node_height:
            _, left_index, left = stack.pop()
            parent_index = left_index // 2
            internal_input = identifier + u32(parent_index) + D_INTR + left + node
            node = sha256(internal_input)
            if observe:
                observe("merkle_internal", internal_input, node)
            node_height += 1
            node_index = parent_index
            if node_height < height and node_index == ((target_node >> node_height) ^ 1):
                authentication[node_height] = node
        stack.append((node_height, node_index, node))
    if len(stack) != 1 or set(authentication) != set(range(height)):
        raise AssertionError("LMS TreeHash authentication capture failed")
    return stack[0][2], [authentication[level] for level in range(height)]


def lms_public_key_encoding(
    identifier: bytes,
    root: bytes,
    params: LmotsParams = LMOTS_SHA256_N32_W4,
) -> bytes:
    if len(identifier) != 16 or len(root) != 32:
        raise ValueError("LMS public-key input length mismatch")
    return u32(LMS_SHA256_M32_H10) + u32(params.typecode) + identifier + root


def lms_sign(
    message: bytes,
    identifier: bytes,
    seed: bytes,
    q: int,
    randomizer: bytes,
    params: LmotsParams = LMOTS_SHA256_N32_W4,
    observe: Callable[[str, bytes, bytes], None] | None = None,
) -> tuple[bytes, int]:
    """Return one LMS H10 signature and the mandatory next leaf index."""
    if not 0 <= q < (1 << 10):
        raise ValueError("LMS private key exhausted")
    ots_signature = lmots_sign(
        message, identifier, q, seed, randomizer, params, observe
    )
    _root, authentication = _lms_root_and_authentication(
        identifier, seed, q, 10, params, observe
    )
    signature = u32(q) + ots_signature + u32(LMS_SHA256_M32_H10) + b"".join(authentication)
    return signature, q + 1


def lms_verify(
    public_key: bytes,
    message: bytes,
    signature: bytes,
    params: LmotsParams = LMOTS_SHA256_N32_W4,
    observe: Callable[[str, bytes, bytes], None] | None = None,
) -> bool:
    """Verify the RFC 8554 LMS SHA256/M32/H10, LM-OTS W4 profile."""
    expected_signature = 12 + params.n * (params.p + 1) + 10 * params.n
    if len(public_key) != 56 or len(signature) != expected_signature:
        return False
    if int.from_bytes(public_key[:4], "big") != LMS_SHA256_M32_H10:
        return False
    if int.from_bytes(public_key[4:8], "big") != params.typecode:
        return False
    q = int.from_bytes(signature[:4], "big")
    if q >= 1 << 10:
        return False
    ots_bytes = 4 + params.n * (params.p + 1)
    if int.from_bytes(signature[4:8], "big") != params.typecode:
        return False
    lms_type_offset = 4 + ots_bytes
    if int.from_bytes(signature[lms_type_offset : lms_type_offset + 4], "big") != LMS_SHA256_M32_H10:
        return False
    identifier = public_key[8:24]
    expected_root = public_key[24:]
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
    node_index = (1 << 10) + q
    leaf_input = identifier + u32(node_index) + D_LEAF + ots_public
    node = sha256(leaf_input)
    if observe:
        observe("merkle_leaf", leaf_input, node)
    path_offset = lms_type_offset + 4
    for height in range(10):
        sibling = signature[
            path_offset + height * params.n : path_offset + (height + 1) * params.n
        ]
        parent_index = node_index // 2
        children = node + sibling if node_index % 2 == 0 else sibling + node
        internal_input = identifier + u32(parent_index) + D_INTR + children
        node = sha256(internal_input)
        if observe:
            observe("merkle_internal", internal_input, node)
        node_index = parent_index
    return node == expected_root


def lms_public_key(
    identifier: bytes,
    seed: bytes,
    height: int = 10,
    params: LmotsParams = LMOTS_SHA256_N32_W4,
    observe: Callable[[str, bytes, bytes], None] | None = None,
) -> bytes:
    """Return T[1] using a streaming TreeHash stack."""
    if not 1 <= height <= 25:
        raise ValueError("unsupported LMS tree height")
    stack: list[tuple[int, int, bytes]] = []
    leaf_base = 1 << height
    for q in range(1 << height):
        ots = lmots_public_key(identifier, q, seed, params, observe)
        r = leaf_base + q
        inp = identifier + u32(r) + D_LEAF + ots
        node = sha256(inp)
        if observe:
            observe("merkle_leaf", inp, node)
        node_height = 0
        node_index = r
        while stack and stack[-1][0] == node_height:
            _, left_index, left = stack.pop()
            parent_index = left_index // 2
            if node_index != left_index + 1:
                raise AssertionError("non-adjacent TreeHash nodes")
            inp = identifier + u32(parent_index) + D_INTR + left + node
            node = sha256(inp)
            if observe:
                observe("merkle_internal", inp, node)
            node_height += 1
            node_index = parent_index
        stack.append((node_height, node_index, node))
    if len(stack) != 1 or stack[0][0] != height or stack[0][1] != 1:
        raise AssertionError("TreeHash did not reduce to T[1]")
    return stack[0][2]


RFC8554_TEST2 = {
    "identifier": bytes.fromhex("d08fabd4a2091ff0a8cb4ed834e74534"),
    "seed": bytes.fromhex(
        "558b8966c48ae9cb898b423c83443aae014a72f1b1ab5cc85cf1d892903b5439"
    ),
    "height": 10,
    "expected_root": bytes.fromhex(
        "32a58885cd9ba0431235466bff9651c6c92124404d45fa53cf161c28f1ad5a8e"
    ),
}
