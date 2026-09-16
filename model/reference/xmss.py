"""Dependency-free RFC 8391 XMSS reference model for the μHBS profiles.

The strict profile is XMSS-SHAKE256_10_256 (OID 0x00000010).  The module
uses the RFC notation where the Winternitz base is 16; the Unified HBS paper
calls the same setting ``w=4`` because it reports log2(base).

This intentionally favors readable, traceable code over speed.  It is an
independent oracle and does not import RTL-project code or another repository.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Callable, Sequence


Observe = Callable[[str, bytes, bytes], None]

XMSS_ADDR_TYPE_OTS = 0
XMSS_ADDR_TYPE_LTREE = 1
XMSS_ADDR_TYPE_HASHTREE = 2


@dataclass(frozen=True)
class XmssParams:
    name: str
    oid: int | None
    n: int
    full_height: int
    wots_w: int
    wots_log_w: int
    wots_len1: int
    wots_len2: int
    wots_len: int
    padding_len: int = 32
    index_bytes: int = 4

    @property
    def wots_sig_bytes(self) -> int:
        return self.wots_len * self.n

    @property
    def sig_bytes(self) -> int:
        return self.index_bytes + self.n + self.wots_sig_bytes + self.full_height * self.n

    @property
    def pk_bytes(self) -> int:
        return 2 * self.n

    @property
    def sk_bytes(self) -> int:
        return self.index_bytes + 4 * self.n


XMSS_SHAKE256_10_256 = XmssParams(
    name="XMSS-SHAKE256_10_256",
    oid=0x00000010,
    n=32,
    full_height=10,
    wots_w=16,
    wots_log_w=4,
    wots_len1=64,
    wots_len2=3,
    wots_len=67,
)

# Non-standard study point matching the paper's ``w=2, len=133`` notation.
XMSS_SHAKE256_10_256_W4_STUDY = XmssParams(
    name="XMSS-SHAKE256_10_256_W4_STUDY",
    oid=None,
    n=32,
    full_height=10,
    wots_w=4,
    wots_log_w=2,
    wots_len1=128,
    wots_len2=5,
    wots_len=133,
)


def _to_bytes(value: int, length: int) -> bytes:
    return value.to_bytes(length, "big", signed=False)


def _core_hash(kind: str, data: bytes, n: int, observe: Observe | None) -> bytes:
    result = hashlib.shake_256(data).digest(n)
    if observe is not None:
        observe(kind, data, result)
    return result


def _addr_bytes(addr: Sequence[int]) -> bytes:
    if len(addr) != 8:
        raise ValueError("XMSS address must have eight 32-bit words")
    return b"".join(_to_bytes(word, 4) for word in addr)


def _set_tree_addr(addr: list[int], tree: int) -> None:
    addr[1] = (tree >> 32) & 0xFFFFFFFF
    addr[2] = tree & 0xFFFFFFFF


def _prf(
    params: XmssParams,
    key: bytes,
    value: bytes,
    observe: Observe | None = None,
) -> bytes:
    if len(key) != params.n or len(value) != 32:
        raise ValueError("XMSS PRF requires an n-byte key and a 32-byte input")
    data = _to_bytes(3, params.padding_len) + key + value
    return _core_hash("prf", data, params.n, observe)


def _prf_keygen(
    params: XmssParams,
    key: bytes,
    value: bytes,
    observe: Observe | None = None,
) -> bytes:
    if len(key) != params.n or len(value) != params.n + 32:
        raise ValueError("XMSS PRF_keygen input length mismatch")
    data = _to_bytes(4, params.padding_len) + key + value
    return _core_hash("prf_keygen", data, params.n, observe)


def _thash_f(
    params: XmssParams,
    value: bytes,
    pub_seed: bytes,
    addr: list[int],
    observe: Observe | None = None,
) -> bytes:
    if len(value) != params.n or len(pub_seed) != params.n:
        raise ValueError("XMSS F input length mismatch")
    addr[7] = 0
    key = _prf(params, pub_seed, _addr_bytes(addr), observe)
    addr[7] = 1
    mask = _prf(params, pub_seed, _addr_bytes(addr), observe)
    masked = bytes(left ^ right for left, right in zip(value, mask, strict=True))
    data = _to_bytes(0, params.padding_len) + key + masked
    return _core_hash("thash_f", data, params.n, observe)


def _thash_h(
    params: XmssParams,
    value: bytes,
    pub_seed: bytes,
    addr: list[int],
    observe: Observe | None = None,
) -> bytes:
    if len(value) != 2 * params.n or len(pub_seed) != params.n:
        raise ValueError("XMSS H input length mismatch")
    addr[7] = 0
    key = _prf(params, pub_seed, _addr_bytes(addr), observe)
    masks = bytearray()
    for selector in (1, 2):
        addr[7] = selector
        masks.extend(_prf(params, pub_seed, _addr_bytes(addr), observe))
    masked = bytes(left ^ right for left, right in zip(value, masks, strict=True))
    data = _to_bytes(1, params.padding_len) + key + masked
    return _core_hash("thash_h", data, params.n, observe)


def _expand_seed(
    params: XmssParams,
    sk_seed: bytes,
    pub_seed: bytes,
    addr: list[int],
    observe: Observe | None = None,
) -> list[bytes]:
    seeds: list[bytes] = []
    addr[6] = 0
    addr[7] = 0
    for chain in range(params.wots_len):
        addr[5] = chain
        seeds.append(
            _prf_keygen(params, sk_seed, pub_seed + _addr_bytes(addr), observe)
        )
    return seeds


def _gen_chain(
    params: XmssParams,
    value: bytes,
    start: int,
    steps: int,
    pub_seed: bytes,
    addr: list[int],
    observe: Observe | None = None,
) -> bytes:
    result = value
    for step in range(start, min(start + steps, params.wots_w)):
        addr[6] = step
        result = _thash_f(params, result, pub_seed, addr, observe)
    return result


def _base_w(params: XmssParams, value: bytes, out_len: int) -> list[int]:
    in_index = 0
    total = 0
    bits = 0
    output: list[int] = []
    for _ in range(out_len):
        if bits == 0:
            total = value[in_index]
            in_index += 1
            bits = 8
        bits -= params.wots_log_w
        output.append((total >> bits) & (params.wots_w - 1))
    return output


def _chain_lengths(params: XmssParams, message_digest: bytes) -> list[int]:
    if len(message_digest) != params.n:
        raise ValueError("WOTS+ input must be one n-byte digest")
    lengths = _base_w(params, message_digest, params.wots_len1)
    checksum = sum(params.wots_w - 1 - value for value in lengths)
    checksum_bits = params.wots_len2 * params.wots_log_w
    checksum <<= 8 - (checksum_bits % 8)
    checksum_bytes = _to_bytes(checksum, (checksum_bits + 7) // 8)
    lengths.extend(_base_w(params, checksum_bytes, params.wots_len2))
    return lengths


def _wots_pkgen(
    params: XmssParams,
    sk_seed: bytes,
    pub_seed: bytes,
    addr: list[int],
    observe: Observe | None = None,
) -> list[bytes]:
    seeds = _expand_seed(params, sk_seed, pub_seed, addr, observe)
    public_elements: list[bytes] = []
    for chain, seed in enumerate(seeds):
        addr[5] = chain
        public_elements.append(
            _gen_chain(params, seed, 0, params.wots_w - 1, pub_seed, addr, observe)
        )
    return public_elements


def _wots_sign(
    params: XmssParams,
    message_digest: bytes,
    sk_seed: bytes,
    pub_seed: bytes,
    addr: list[int],
    observe: Observe | None = None,
) -> bytes:
    seeds = _expand_seed(params, sk_seed, pub_seed, addr, observe)
    lengths = _chain_lengths(params, message_digest)
    signature = bytearray()
    for chain, (seed, steps) in enumerate(zip(seeds, lengths, strict=True)):
        addr[5] = chain
        signature.extend(_gen_chain(params, seed, 0, steps, pub_seed, addr, observe))
    return bytes(signature)


def _wots_pk_from_sig(
    params: XmssParams,
    signature: bytes,
    message_digest: bytes,
    pub_seed: bytes,
    addr: list[int],
    observe: Observe | None = None,
) -> list[bytes]:
    if len(signature) != params.wots_sig_bytes:
        raise ValueError("WOTS+ signature length mismatch")
    lengths = _chain_lengths(params, message_digest)
    result: list[bytes] = []
    for chain, start in enumerate(lengths):
        addr[5] = chain
        value = signature[chain * params.n : (chain + 1) * params.n]
        result.append(
            _gen_chain(
                params,
                value,
                start,
                params.wots_w - 1 - start,
                pub_seed,
                addr,
                observe,
            )
        )
    return result


def _l_tree(
    params: XmssParams,
    public_elements: Sequence[bytes],
    pub_seed: bytes,
    addr: list[int],
    observe: Observe | None = None,
) -> bytes:
    nodes = list(public_elements)
    if len(nodes) != params.wots_len or any(len(node) != params.n for node in nodes):
        raise ValueError("L-tree input shape mismatch")
    height = 0
    while len(nodes) > 1:
        next_nodes: list[bytes] = []
        addr[5] = height
        for index in range(len(nodes) // 2):
            addr[6] = index
            next_nodes.append(
                _thash_h(params, nodes[2 * index] + nodes[2 * index + 1], pub_seed, addr, observe)
            )
        if len(nodes) & 1:
            next_nodes.append(nodes[-1])
        nodes = next_nodes
        height += 1
    return nodes[0]


def _gen_leaf(
    params: XmssParams,
    sk_seed: bytes,
    pub_seed: bytes,
    leaf_index: int,
    observe: Observe | None = None,
) -> bytes:
    ots_addr = [0] * 8
    ots_addr[3] = XMSS_ADDR_TYPE_OTS
    ots_addr[4] = leaf_index
    ltree_addr = [0] * 8
    ltree_addr[3] = XMSS_ADDR_TYPE_LTREE
    ltree_addr[4] = leaf_index
    public_elements = _wots_pkgen(params, sk_seed, pub_seed, ots_addr, observe)
    return _l_tree(params, public_elements, pub_seed, ltree_addr, observe)


def _treehash(
    params: XmssParams,
    sk_seed: bytes,
    pub_seed: bytes,
    auth_leaf_index: int,
    observe: Observe | None = None,
) -> tuple[bytes, tuple[bytes, ...]]:
    if not 0 <= auth_leaf_index < (1 << params.full_height):
        raise ValueError("XMSS authentication leaf index out of range")
    auth_path: list[bytes | None] = [None] * params.full_height
    stack: list[tuple[int, int, bytes]] = []
    node_addr = [0] * 8
    node_addr[3] = XMSS_ADDR_TYPE_HASHTREE

    for leaf_index in range(1 << params.full_height):
        node = _gen_leaf(params, sk_seed, pub_seed, leaf_index, observe)
        height = 0
        tree_index = leaf_index
        if (auth_leaf_index ^ 1) == leaf_index:
            auth_path[0] = node

        while stack and stack[-1][0] == height:
            left_height, left_index, left = stack.pop()
            if left_height != height or tree_index != left_index + 1:
                raise AssertionError("non-adjacent XMSS TreeHash nodes")
            parent_index = left_index // 2
            node_addr[5] = height
            node_addr[6] = parent_index
            node = _thash_h(params, left + node, pub_seed, node_addr, observe)
            height += 1
            tree_index = parent_index
            if ((auth_leaf_index >> height) ^ 1) == tree_index:
                auth_path[height] = node
        stack.append((height, tree_index, node))

    if len(stack) != 1 or stack[0][0] != params.full_height or stack[0][1] != 0:
        raise AssertionError("XMSS TreeHash did not reduce to one root")
    if any(node is None for node in auth_path):
        raise AssertionError("XMSS TreeHash did not capture a complete authentication path")
    return stack[0][2], tuple(node for node in auth_path if node is not None)


def xmss_seed_keypair(
    seed: bytes,
    params: XmssParams = XMSS_SHAKE256_10_256,
    observe: Observe | None = None,
) -> tuple[bytes, bytes]:
    """Return ``(public_key, secret_key)`` without an external OID prefix."""
    if len(seed) != 3 * params.n:
        raise ValueError("XMSS deterministic seed must be exactly 3*n bytes")
    sk_seed = seed[: params.n]
    sk_prf = seed[params.n : 2 * params.n]
    pub_seed = seed[2 * params.n :]
    root, _ = _treehash(params, sk_seed, pub_seed, 0, observe)
    public_key = root + pub_seed
    secret_key = b"\x00" * params.index_bytes + sk_seed + sk_prf + root + pub_seed
    return public_key, secret_key


def xmss_set_index(
    secret_key: bytes,
    index: int,
    params: XmssParams = XMSS_SHAKE256_10_256,
) -> bytes:
    if len(secret_key) != params.sk_bytes:
        raise ValueError("XMSS secret-key length mismatch")
    if not 0 <= index < (1 << params.full_height):
        raise ValueError("XMSS index out of range")
    return _to_bytes(index, params.index_bytes) + secret_key[params.index_bytes :]


def _hash_message(
    params: XmssParams,
    randomizer: bytes,
    root: bytes,
    index: int,
    message: bytes,
    observe: Observe | None = None,
) -> bytes:
    data = (
        _to_bytes(2, params.padding_len)
        + randomizer
        + root
        + _to_bytes(index, params.n)
        + message
    )
    return _core_hash("hash_message", data, params.n, observe)


def xmss_sign(
    secret_key: bytes,
    message: bytes,
    params: XmssParams = XMSS_SHAKE256_10_256,
    observe: Observe | None = None,
) -> tuple[bytes, bytes]:
    """Return ``(signature, updated_secret_key)`` for one stateful index."""
    if len(secret_key) != params.sk_bytes:
        raise ValueError("XMSS secret-key length mismatch")
    index = int.from_bytes(secret_key[: params.index_bytes], "big")
    if index >= (1 << params.full_height) - 1:
        raise ValueError("XMSS signing key exhausted under reference policy")
    offset = params.index_bytes
    sk_seed = secret_key[offset : offset + params.n]
    sk_prf = secret_key[offset + params.n : offset + 2 * params.n]
    root = secret_key[offset + 2 * params.n : offset + 3 * params.n]
    pub_seed = secret_key[offset + 3 * params.n : offset + 4 * params.n]

    randomizer = _prf(params, sk_prf, _to_bytes(index, 32), observe)
    message_digest = _hash_message(params, randomizer, root, index, message, observe)
    ots_addr = [0] * 8
    ots_addr[3] = XMSS_ADDR_TYPE_OTS
    ots_addr[4] = index
    wots_signature = _wots_sign(
        params, message_digest, sk_seed, pub_seed, ots_addr, observe
    )
    recomputed_root, auth_path = _treehash(
        params, sk_seed, pub_seed, index, observe
    )
    if recomputed_root != root:
        raise AssertionError("secret-key root disagrees with deterministic TreeHash")
    signature = (
        _to_bytes(index, params.index_bytes)
        + randomizer
        + wots_signature
        + b"".join(auth_path)
    )
    if len(signature) != params.sig_bytes:
        raise AssertionError("XMSS signature serialization length mismatch")
    updated = _to_bytes(index + 1, params.index_bytes) + secret_key[params.index_bytes :]
    return signature, updated


def xmss_verify(
    public_key: bytes,
    message: bytes,
    signature: bytes,
    params: XmssParams = XMSS_SHAKE256_10_256,
    observe: Observe | None = None,
) -> bool:
    if len(public_key) != params.pk_bytes or len(signature) != params.sig_bytes:
        return False
    root = public_key[: params.n]
    pub_seed = public_key[params.n :]
    index = int.from_bytes(signature[: params.index_bytes], "big")
    if index >= 1 << params.full_height:
        return False
    offset = params.index_bytes
    randomizer = signature[offset : offset + params.n]
    offset += params.n
    wots_signature = signature[offset : offset + params.wots_sig_bytes]
    offset += params.wots_sig_bytes
    auth_path = [
        signature[offset + level * params.n : offset + (level + 1) * params.n]
        for level in range(params.full_height)
    ]

    message_digest = _hash_message(params, randomizer, root, index, message, observe)
    ots_addr = [0] * 8
    ots_addr[3] = XMSS_ADDR_TYPE_OTS
    ots_addr[4] = index
    public_elements = _wots_pk_from_sig(
        params, wots_signature, message_digest, pub_seed, ots_addr, observe
    )
    ltree_addr = [0] * 8
    ltree_addr[3] = XMSS_ADDR_TYPE_LTREE
    ltree_addr[4] = index
    node = _l_tree(params, public_elements, pub_seed, ltree_addr, observe)

    node_addr = [0] * 8
    node_addr[3] = XMSS_ADDR_TYPE_HASHTREE
    for height, sibling in enumerate(auth_path):
        node_addr[5] = height
        node_addr[6] = index >> (height + 1)
        if (index >> height) & 1:
            node = _thash_h(params, sibling + node, pub_seed, node_addr, observe)
        else:
            node = _thash_h(params, node + sibling, pub_seed, node_addr, observe)
    return node == root
