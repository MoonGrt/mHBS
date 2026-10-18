"""Independent RFC 8554 LMS oracle with RFC 9858 SHAKE256/256 sets.

LMOTS_SHAKE_N32_W4 is type 0x0b; LMS heights 10/15/20 are types
0x10/0x11/0x12.  Private elements follow RFC 8554 Appendix A, as required
by SP 800-208 §6.1.  Trees are generated through an O(h) streaming stack.
No VM, image compiler, historical macro model or persistent tree cache is
used.  Random C and a durably reserved signature index belong to the caller.

Sources: https://www.rfc-editor.org/rfc/rfc8554.html
https://www.rfc-editor.org/rfc/rfc9858.html
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
from typing import Callable, Sequence

Observe = Callable[[str, bytes, bytes], None]
N = 32
CHAINS = 67
LMOTS_TYPE = 0x0B
D_PBLC = b"\x80\x80"
D_MESG = b"\x81\x81"
D_LEAF = b"\x82\x82"
D_INTR = b"\x83\x83"


@dataclass(frozen=True)
class LmsParams:
    name: str
    h: int
    lms_type: int
    lmots_type: int = LMOTS_TYPE
    n: int = N
    w: int = 4
    chains: int = CHAINS

    @property
    def signature_bytes(self) -> int:
        return 12 + N * (1 + CHAINS + self.h)

    @property
    def payload_bytes(self) -> int:
        return self.signature_bytes - 12

    @property
    def capacity(self) -> int:
        return 1 << self.h


PARAMS = {p.name: p for p in (
    LmsParams("lms_h10", 10, 0x10),
    LmsParams("lms_h15", 15, 0x11),
    LmsParams("lms_h20", 20, 0x12),
)}


def get_params(value: str | LmsParams) -> LmsParams:
    if isinstance(value, LmsParams):
        if PARAMS.get(value.name) != value:
            raise ValueError("unsupported LMS parameter set")
        return value
    try:
        return PARAMS[value]
    except (KeyError, TypeError):
        raise ValueError(f"unsupported LMS profile: {value!r}") from None


def _node(value: bytes, name: str = "node") -> bytes:
    if not isinstance(value, bytes) or len(value) != N:
        raise ValueError(f"LMS {name} must contain exactly 32 bytes")
    return value


def _identifier(value: bytes) -> bytes:
    if not isinstance(value, bytes) or len(value) != 16:
        raise ValueError("LMS identifier must contain exactly 16 bytes")
    return value


def _uint(value: int, bits: int, name: str) -> int:
    if type(value) is not int or not 0 <= value < 1 << bits:
        raise ValueError(f"LMS {name} is outside unsigned {bits}-bit range")
    return value


def check_index(params: str | LmsParams, index: int) -> int:
    p = get_params(params)
    _uint(index, 32, "index")
    if index >= p.capacity:
        raise ValueError("LMS signature index exhausted")
    return index


@dataclass(frozen=True)
class PublicKey:
    params: LmsParams
    identifier: bytes
    root: bytes

    def __post_init__(self) -> None:
        get_params(self.params)
        _identifier(self.identifier)
        _node(self.root, "root")

    def to_bytes(self) -> bytes:
        return (self.params.lms_type.to_bytes(4, "big") +
                self.params.lmots_type.to_bytes(4, "big") + self.identifier + self.root)

    @classmethod
    def from_bytes(cls, encoded: bytes, params: str | LmsParams | None = None) -> PublicKey:
        if not isinstance(encoded, bytes) or len(encoded) != 56:
            raise ValueError("LMS public key must contain exactly 56 bytes")
        lms_type, lmots_type = int.from_bytes(encoded[:4], "big"), int.from_bytes(encoded[4:8], "big")
        found = next((p for p in PARAMS.values() if p.lms_type == lms_type), None)
        if (found is None or lmots_type != LMOTS_TYPE or
                (params is not None and found != get_params(params))):
            raise ValueError("LMS public-key type mismatch")
        return cls(found, encoded[8:24], encoded[24:56])


@dataclass(frozen=True)
class PrivateKey:
    params: LmsParams
    secret_seed: bytes
    identifier: bytes
    root: bytes
    next_index: int = 0

    def __post_init__(self) -> None:
        p = get_params(self.params)
        _node(self.secret_seed, "secret seed")
        _identifier(self.identifier)
        _node(self.root, "root")
        if type(self.next_index) is not int or not 0 <= self.next_index <= p.capacity:
            raise ValueError("LMS next index out of range")

    @property
    def public_key(self) -> PublicKey:
        return PublicKey(self.params, self.identifier, self.root)

    @property
    def exhausted(self) -> bool:
        return self.next_index == self.params.capacity


@dataclass(frozen=True)
class SignResult:
    signature: bytes
    nodes: tuple[bytes, ...]
    used_index: int
    next_index: int
    exhausted: bool


def _hash(kind: str, data: bytes, observe: Observe | None = None) -> bytes:
    result = hashlib.shake_256(data).digest(N)
    if observe is not None:
        observe(kind, data, result)
    return result


def secret_element(secret_seed: bytes, identifier: bytes, leaf: int, chain_index: int,
                   observe: Observe | None = None) -> bytes:
    _node(secret_seed, "secret seed")
    _identifier(identifier)
    _uint(leaf, 20, "leaf")
    if type(chain_index) is not int or not 0 <= chain_index < CHAINS:
        raise ValueError("LMS chain index out of range")
    return _hash("lms_prf", identifier + leaf.to_bytes(4, "big") +
                 chain_index.to_bytes(2, "big") + b"\xff" + secret_seed, observe)


def chain(node: bytes, start: int, count: int, identifier: bytes, leaf: int,
          chain_index: int, observe: Observe | None = None) -> bytes:
    _node(node)
    _identifier(identifier)
    _uint(leaf, 20, "leaf")
    if (type(start) is not int or type(count) is not int or
            not 0 <= start <= 15 or not 0 <= count <= 15 - start):
        raise ValueError("LMS chain range exceeds the 15-step bound")
    if type(chain_index) is not int or not 0 <= chain_index < CHAINS:
        raise ValueError("LMS chain index out of range")
    prefix = identifier + leaf.to_bytes(4, "big") + chain_index.to_bytes(2, "big")
    for step in range(start, start + count):
        node = _hash("lms_f", prefix + bytes((step,)) + node, observe)
    return node


def digits(digest: bytes) -> tuple[int, ...]:
    _node(digest, "message digest")
    values = [nibble for byte in digest for nibble in (byte >> 4, byte & 15)]
    checksum = sum(15 - d for d in values) << 4
    # RFC8554: coef(Q || u16str(Cksm(Q)), i, 4), i=0..66.
    encoded = digest + checksum.to_bytes(2, "big")
    return tuple((encoded[i // 2] >> (4 if i % 2 == 0 else 0)) & 15 for i in range(CHAINS))


def message_digest(identifier: bytes, index: int, randomizer: bytes, message: bytes,
                   observe: Observe | None = None) -> bytes:
    _identifier(identifier)
    _uint(index, 20, "index")
    _node(randomizer, "randomizer")
    if not isinstance(message, bytes):
        raise ValueError("LMS message must be bytes")
    return _hash("lms_h_msg", identifier + index.to_bytes(4, "big") + D_MESG + randomizer + message, observe)


def public_compress(identifier: bytes, leaf: int, endpoints: Sequence[bytes],
                    observe: Observe | None = None) -> bytes:
    _identifier(identifier)
    _uint(leaf, 20, "leaf")
    if len(endpoints) != CHAINS:
        raise ValueError("LMOTS public key requires exactly 67 endpoints")
    return _hash("lms_public", identifier + leaf.to_bytes(4, "big") + D_PBLC +
                 b"".join(_node(v) for v in endpoints), observe)


def leaf_hash(params: str | LmsParams, identifier: bytes, leaf: int, public: bytes,
              observe: Observe | None = None) -> bytes:
    p = get_params(params)
    check_index(p, leaf)
    _identifier(identifier)
    _node(public, "LMOTS public key")
    return _hash("lms_leaf", identifier + (p.capacity + leaf).to_bytes(4, "big") + D_LEAF + public, observe)


def parent_hash(identifier: bytes, heap_index: int, left: bytes, right: bytes,
                observe: Observe | None = None) -> bytes:
    _identifier(identifier)
    _uint(heap_index, 20, "parent heap index")
    if heap_index == 0:
        raise ValueError("LMS heap numbering starts at one")
    _node(left, "left node")
    _node(right, "right node")
    return _hash("lms_h", identifier + heap_index.to_bytes(4, "big") + D_INTR + left + right, observe)


def lmots_public_key(secret_seed: bytes, identifier: bytes, leaf: int,
                     observe: Observe | None = None) -> bytes:
    endpoints = tuple(chain(secret_element(secret_seed, identifier, leaf, i, observe),
                            0, 15, identifier, leaf, i, observe) for i in range(CHAINS))
    return public_compress(identifier, leaf, endpoints, observe)


def lmots_sign(secret_seed: bytes, identifier: bytes, leaf: int, digest: bytes,
               observe: Observe | None = None) -> tuple[bytes, ...]:
    return tuple(chain(secret_element(secret_seed, identifier, leaf, i, observe),
                       0, digit, identifier, leaf, i, observe)
                 for i, digit in enumerate(digits(digest)))


def lmots_public_from_signature(nodes: Sequence[bytes], digest: bytes, identifier: bytes,
                                leaf: int, observe: Observe | None = None) -> bytes:
    if len(nodes) != CHAINS:
        raise ValueError("LMOTS signature requires exactly 67 nodes")
    endpoints = tuple(chain(_node(node), digit, 15 - digit, identifier, leaf, i, observe)
                      for i, (node, digit) in enumerate(zip(nodes, digits(digest))))
    return public_compress(identifier, leaf, endpoints, observe)


def _build_tree(params: LmsParams, secret_seed: bytes, identifier: bytes,
                target: int | None, target_digits: Sequence[int] | None,
                observe: Observe | None) -> tuple[bytes, tuple[bytes, ...], tuple[bytes, ...]]:
    _node(secret_seed, "secret seed")
    _identifier(identifier)
    if target is not None:
        check_index(params, target)
    if target_digits is not None and (len(target_digits) != CHAINS or
            any(type(d) is not int or not 0 <= d <= 15 for d in target_digits)):
        raise ValueError("invalid LMOTS target digits")
    stack: list[tuple[int, int, bytes]] = []
    auth: list[bytes | None] = [None] * params.h
    captures: list[bytes] = []
    for leaf in range(params.capacity):
        endpoints = []
        for i in range(CHAINS):
            value = secret_element(secret_seed, identifier, leaf, i, observe)
            wanted = target_digits[i] if target_digits is not None and leaf == target else None
            if wanted == 0:
                captures.append(value)
            for step in range(15):
                value = chain(value, step, 1, identifier, leaf, i, observe)
                if wanted == step + 1:
                    captures.append(value)
            endpoints.append(value)
        node = leaf_hash(params, identifier, leaf, public_compress(identifier, leaf, endpoints, observe), observe)
        level, index = 0, leaf
        if target is not None and index == (target ^ 1):
            auth[0] = node
        while stack and stack[-1][0] == level:
            _, left_index, left = stack.pop()
            if left_index + 1 != index or not index & 1:
                raise AssertionError("LMS streaming tree adjacency error")
            index >>= 1
            level += 1
            node = parent_hash(identifier, (1 << (params.h - level)) + index, left, node, observe)
            if target is not None and level < params.h and index == ((target >> level) ^ 1):
                auth[level] = node
        stack.append((level, index, node))
    if len(stack) != 1 or stack[0][:2] != (params.h, 0):
        raise AssertionError("LMS streaming tree did not produce a root")
    if target is not None and any(v is None for v in auth):
        raise AssertionError("LMS authentication path incomplete")
    return stack[0][2], tuple(v for v in auth if v is not None), tuple(captures)


def tree_root_and_auth(params: str | LmsParams, secret_seed: bytes, identifier: bytes,
                       target: int | None = None, observe: Observe | None = None
                       ) -> tuple[bytes, tuple[bytes, ...]]:
    root, auth, _ = _build_tree(get_params(params), secret_seed, identifier, target, None, observe)
    return root, auth


def keygen(params: str | LmsParams, secret_seed: bytes, identifier: bytes,
           observe: Observe | None = None) -> tuple[PrivateKey, PublicKey]:
    p = get_params(params)
    root, _ = tree_root_and_auth(p, secret_seed, identifier, observe=observe)
    private = PrivateKey(p, secret_seed, identifier, root)
    return private, private.public_key


def signature_from_nodes(params: str | LmsParams, index: int, nodes: Sequence[bytes]) -> bytes:
    p = get_params(params)
    check_index(p, index)
    if len(nodes) != 1 + CHAINS + p.h:
        raise ValueError("LMS signature node count mismatch")
    values = tuple(_node(v) for v in nodes)
    return (index.to_bytes(4, "big") + p.lmots_type.to_bytes(4, "big") +
            b"".join(values[:1 + CHAINS]) + p.lms_type.to_bytes(4, "big") +
            b"".join(values[1 + CHAINS:]))


def signature_to_nodes(params: str | LmsParams, signature: bytes) -> tuple[int, tuple[bytes, ...]]:
    p = get_params(params)
    if not isinstance(signature, bytes) or len(signature) != p.signature_bytes:
        raise ValueError("LMS signature length mismatch")
    index = check_index(p, int.from_bytes(signature[:4], "big"))
    middle = 8 + N * (1 + CHAINS)
    if (int.from_bytes(signature[4:8], "big") != p.lmots_type or
            int.from_bytes(signature[middle:middle + 4], "big") != p.lms_type):
        raise ValueError("LMS signature type mismatch")
    payload = signature[8:middle] + signature[middle + 4:]
    return index, tuple(payload[offset:offset + N] for offset in range(0, len(payload), N))


def sign(key: PrivateKey, message: bytes, randomizer: bytes, index: int | None = None,
         observe: Observe | None = None) -> SignResult:
    q = check_index(key.params, key.next_index if index is None else index)
    digest = message_digest(key.identifier, q, randomizer, message, observe)
    root, auth, captures = _build_tree(key.params, key.secret_seed, key.identifier, q, digits(digest), observe)
    if not hmac.compare_digest(root, key.root):
        raise ValueError("LMS private key root does not match its seed and identifier")
    nodes = (randomizer,) + captures + auth
    return SignResult(signature_from_nodes(key.params, q, nodes), nodes, q, q + 1,
                      q + 1 == key.params.capacity)


def sign_with_auth(key: PrivateKey, message: bytes, randomizer: bytes, auth: Sequence[bytes],
                   index: int | None = None, observe: Observe | None = None) -> SignResult:
    """Sign a supplied path for real-height, layered Verify tests only.

    This does not claim that every sibling belongs to the seed-derived tree.
    Use ``sign`` for full-tree signing and its full work-count oracle.
    """
    q = check_index(key.params, key.next_index if index is None else index)
    if len(auth) != key.params.h:
        raise ValueError("LMS authentication path height mismatch")
    path = tuple(_node(v, "authentication node") for v in auth)
    digest = message_digest(key.identifier, q, randomizer, message, observe)
    nodes = (randomizer,) + lmots_sign(key.secret_seed, key.identifier, q, digest, observe) + path
    return SignResult(signature_from_nodes(key.params, q, nodes), nodes, q, q + 1,
                      q + 1 == key.params.capacity)


def root_from_nodes(public: PublicKey, message: bytes, index: int, nodes: Sequence[bytes],
                    observe: Observe | None = None) -> bytes:
    check_index(public.params, index)
    if len(nodes) != 1 + CHAINS + public.params.h:
        raise ValueError("LMS signature node count mismatch")
    values = tuple(_node(v) for v in nodes)
    digest = message_digest(public.identifier, index, values[0], message, observe)
    lmots_public = lmots_public_from_signature(values[1:1 + CHAINS], digest, public.identifier, index, observe)
    node = leaf_hash(public.params, public.identifier, index, lmots_public, observe)
    heap = public.params.capacity + index
    for sibling in values[1 + CHAINS:]:
        left, right = (sibling, node) if heap & 1 else (node, sibling)
        heap >>= 1
        node = parent_hash(public.identifier, heap, left, right, observe)
    return node


def verify(public: PublicKey | bytes, message: bytes, signature: bytes,
           observe: Observe | None = None) -> bool:
    try:
        pk = PublicKey.from_bytes(public) if isinstance(public, bytes) else public
        if not isinstance(pk, PublicKey):
            return False
        index, nodes = signature_to_nodes(pk.params, signature)
        candidate = root_from_nodes(pk, message, index, nodes, observe)
        return hmac.compare_digest(candidate, pk.root)
    except (ValueError, TypeError, OverflowError):
        return False
