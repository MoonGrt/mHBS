"""Small, dependency-free RFC 8554 LMS/LM-OTS reference implementation.

This module intentionally implements only deterministic public-key generation
needed by the first μHBS vertical slice. It does not import another project.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Callable


D_PBLC = b"\x80\x80"
D_LEAF = b"\x82\x82"
D_INTR = b"\x83\x83"


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
