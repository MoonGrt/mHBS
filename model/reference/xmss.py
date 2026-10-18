"""Independent XMSS-SHAKE256/256 oracle (SP 800-208 §§5.3, 6.2).

The byte encodings and algorithms follow RFC 8391.  In particular, this is
SHAKE256, not the SHAKE128 instantiation with n=32 from the original RFC,
and WOTS secrets use SP 800-208's domain-4 PRFkeygen.  Key generation and
signing stream a tree through an O(h) stack; no BDS or persistent tree cache
is used.  ``sign`` is an oracle, not an index-persistence service: callers
must reserve its explicit index durably before starting a hardware job.

Sources:
https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-208.pdf
https://www.rfc-editor.org/rfc/rfc8391.html
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
from typing import Callable, Sequence

Observe = Callable[[str, bytes, bytes], None]
N = 32
CHAINS = 67


@dataclass(frozen=True)
class XmssParams:
    name: str
    h: int
    oid: int
    n: int = N
    w: int = 16
    chains: int = CHAINS

    @property
    def signature_bytes(self) -> int:
        return 4 + N * (1 + CHAINS + self.h)

    @property
    def payload_bytes(self) -> int:
        return self.signature_bytes - 4

    @property
    def capacity(self) -> int:
        return 1 << self.h


PARAMS = {p.name: p for p in (
    XmssParams("xmss_h10", 10, 0x10),
    XmssParams("xmss_h16", 16, 0x11),
    XmssParams("xmss_h20", 20, 0x12),
)}


def get_params(value: str | XmssParams) -> XmssParams:
    if isinstance(value, XmssParams):
        if PARAMS.get(value.name) != value:
            raise ValueError("unsupported XMSS parameter set")
        return value
    try:
        return PARAMS[value]
    except (KeyError, TypeError):
        raise ValueError(f"unsupported XMSS profile: {value!r}") from None


def _node(value: bytes, name: str = "node") -> bytes:
    if not isinstance(value, bytes) or len(value) != N:
        raise ValueError(f"XMSS {name} must contain exactly 32 bytes")
    return value


def _uint(value: int, bits: int, name: str) -> int:
    if type(value) is not int or not 0 <= value < 1 << bits:
        raise ValueError(f"XMSS {name} is outside unsigned {bits}-bit range")
    return value


def check_index(params: str | XmssParams, index: int) -> int:
    p = get_params(params)
    _uint(index, 32, "index")
    # The last usable index is 2**h - 1, not 2**h - 2.
    if index >= p.capacity:
        raise ValueError("XMSS signature index exhausted")
    return index


@dataclass(frozen=True)
class PublicKey:
    params: XmssParams
    root: bytes
    public_seed: bytes

    def __post_init__(self) -> None:
        get_params(self.params)
        _node(self.root, "root")
        _node(self.public_seed, "public seed")

    def to_bytes(self) -> bytes:
        return self.params.oid.to_bytes(4, "big") + self.root + self.public_seed

    @classmethod
    def from_bytes(cls, encoded: bytes, params: str | XmssParams | None = None) -> PublicKey:
        if not isinstance(encoded, bytes) or len(encoded) != 68:
            raise ValueError("XMSS public key must contain exactly 68 bytes")
        oid = int.from_bytes(encoded[:4], "big")
        found = next((p for p in PARAMS.values() if p.oid == oid), None)
        if found is None or (params is not None and found != get_params(params)):
            raise ValueError("XMSS public-key OID mismatch")
        return cls(found, encoded[4:36], encoded[36:68])


@dataclass(frozen=True)
class PrivateKey:
    params: XmssParams
    secret_seed: bytes
    secret_prf: bytes
    public_seed: bytes
    root: bytes
    next_index: int = 0

    def __post_init__(self) -> None:
        p = get_params(self.params)
        for label in ("secret_seed", "secret_prf", "public_seed", "root"):
            _node(getattr(self, label), label)
        if type(self.next_index) is not int or not 0 <= self.next_index <= p.capacity:
            raise ValueError("XMSS next index out of range")

    @property
    def public_key(self) -> PublicKey:
        return PublicKey(self.params, self.root, self.public_seed)

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


def _hash(kind: str, domain: int, key: bytes, message: bytes, observe: Observe | None) -> bytes:
    data = domain.to_bytes(N, "big") + key + message
    result = hashlib.shake_256(data).digest(N)
    if observe is not None:
        observe(kind, data, result)
    return result


def address(kind: int, *, leaf: int = 0, chain: int = 0, step: int = 0,
            level: int = 0, index: int = 0, key_mask: int = 0) -> bytes:
    """Serialize one single-tree XMSS address, with fixed layer/tree zero.

    The type-2 tree address's padding word is always zero.  Address height
    denotes the height of the *children* being combined, per RFC 8391.
    """
    if kind not in (0, 1, 2) or type(kind) is not int:
        raise ValueError("invalid XMSS address type")
    for label, value in (("leaf", leaf), ("chain", chain), ("step", step),
                         ("level", level), ("index", index), ("key mask", key_mask)):
        _uint(value, 32, label)
    if key_mask > 2:
        raise ValueError("invalid XMSS key/mask selector")
    if kind == 0:
        words = (0, 0, 0, 0, leaf, chain, step, key_mask)
    elif kind == 1:
        words = (0, 0, 0, 1, leaf, level, index, key_mask)
    else:
        words = (0, 0, 0, 2, 0, level, index, key_mask)
    return b"".join(w.to_bytes(4, "big") for w in words)


def prf(key: bytes, message: bytes, observe: Observe | None = None) -> bytes:
    _node(key, "PRF key")
    _node(message, "PRF message")
    return _hash("xmss_prf", 3, key, message, observe)


def secret_element(secret_seed: bytes, public_seed: bytes, leaf: int, chain_index: int,
                   observe: Observe | None = None) -> bytes:
    _node(secret_seed, "secret seed")
    _node(public_seed, "public seed")
    _uint(leaf, 20, "leaf")
    if type(chain_index) is not int or not 0 <= chain_index < CHAINS:
        raise ValueError("XMSS chain index out of range")
    return _hash("xmss_prf_keygen", 4, secret_seed,
                 public_seed + address(0, leaf=leaf, chain=chain_index), observe)


def chain(node: bytes, start: int, count: int, public_seed: bytes, leaf: int,
          chain_index: int, observe: Observe | None = None) -> bytes:
    _node(node)
    _node(public_seed, "public seed")
    _uint(leaf, 20, "leaf")
    if (type(start) is not int or type(count) is not int or
            not 0 <= start <= 15 or not 0 <= count <= 15 - start):
        raise ValueError("XMSS chain range exceeds the 15-step bound")
    if type(chain_index) is not int or not 0 <= chain_index < CHAINS:
        raise ValueError("XMSS chain index out of range")
    for step in range(start, start + count):
        key = prf(public_seed, address(0, leaf=leaf, chain=chain_index, step=step), observe)
        mask = prf(public_seed, address(0, leaf=leaf, chain=chain_index, step=step, key_mask=1), observe)
        node = _hash("xmss_f", 0, key, bytes(a ^ b for a, b in zip(node, mask)), observe)
    return node


def randomized_hash(left: bytes, right: bytes, public_seed: bytes, *, kind: int,
                    leaf: int = 0, level: int, index: int,
                    observe: Observe | None = None) -> bytes:
    _node(left, "left node")
    _node(right, "right node")
    _node(public_seed, "public seed")
    if kind not in (1, 2):
        raise ValueError("XMSS randomized hash requires an L-tree or tree address")
    keys = [prf(public_seed, address(kind, leaf=leaf, level=level, index=index,
                                    key_mask=k), observe) for k in range(3)]
    payload = bytes(a ^ b for a, b in zip(left, keys[1])) + bytes(a ^ b for a, b in zip(right, keys[2]))
    return _hash("xmss_h", 1, keys[0], payload, observe)


def digits(digest: bytes) -> tuple[int, ...]:
    _node(digest, "message digest")
    result = [nibble for byte in digest for nibble in (byte >> 4, byte & 15)]
    checksum = sum(15 - digit for digit in result)
    # RFC8391 Alg5: shift the 12 significant checksum bits to the left.
    result.extend(((checksum >> 8) & 15, (checksum >> 4) & 15, checksum & 15))
    return tuple(result)


def message_digest(randomizer: bytes, root: bytes, index: int, message: bytes,
                   observe: Observe | None = None) -> bytes:
    _node(randomizer, "randomizer")
    _node(root, "root")
    _uint(index, 32, "index")
    if not isinstance(message, bytes):
        raise ValueError("XMSS message must be bytes")
    return _hash("xmss_h_msg", 2, randomizer + root + index.to_bytes(N, "big"), message, observe)


def l_tree(nodes: Sequence[bytes], public_seed: bytes, leaf: int,
           observe: Observe | None = None) -> bytes:
    if len(nodes) != CHAINS:
        raise ValueError("XMSS L-tree requires exactly 67 endpoints")
    _node(public_seed, "public seed")
    _uint(leaf, 20, "leaf")
    work = [_node(v) for v in nodes]
    level = 0
    while len(work) > 1:
        pairs = len(work) // 2
        following = [randomized_hash(work[2 * i], work[2 * i + 1], public_seed,
                                    kind=1, leaf=leaf, level=level, index=i,
                                    observe=observe) for i in range(pairs)]
        if len(work) & 1:
            following.append(work[-1])
        work = following
        level += 1
    return work[0]


def wots_public_key(secret_seed: bytes, public_seed: bytes, leaf: int,
                    observe: Observe | None = None) -> tuple[bytes, ...]:
    return tuple(chain(secret_element(secret_seed, public_seed, leaf, i, observe),
                       0, 15, public_seed, leaf, i, observe) for i in range(CHAINS))


def wots_sign(secret_seed: bytes, public_seed: bytes, leaf: int, digest: bytes,
              observe: Observe | None = None) -> tuple[bytes, ...]:
    return tuple(chain(secret_element(secret_seed, public_seed, leaf, i, observe),
                       0, digit, public_seed, leaf, i, observe)
                 for i, digit in enumerate(digits(digest)))


def wots_public_from_signature(nodes: Sequence[bytes], digest: bytes, public_seed: bytes,
                              leaf: int, observe: Observe | None = None) -> tuple[bytes, ...]:
    if len(nodes) != CHAINS:
        raise ValueError("XMSS WOTS signature requires 67 nodes")
    return tuple(chain(_node(node), digit, 15 - digit, public_seed, leaf, i, observe)
                 for i, (node, digit) in enumerate(zip(nodes, digits(digest))))


def _build_tree(params: XmssParams, secret_seed: bytes, public_seed: bytes,
                target: int | None, target_digits: Sequence[int] | None,
                observe: Observe | None) -> tuple[bytes, tuple[bytes, ...], tuple[bytes, ...]]:
    _node(secret_seed, "secret seed")
    _node(public_seed, "public seed")
    if target is not None:
        check_index(params, target)
    if target_digits is not None and (len(target_digits) != CHAINS or
            any(type(d) is not int or not 0 <= d <= 15 for d in target_digits)):
        raise ValueError("invalid XMSS target digits")
    stack: list[tuple[int, int, bytes]] = []
    auth: list[bytes | None] = [None] * params.h
    captures: list[bytes] = []
    for leaf in range(params.capacity):
        endpoints = []
        for i in range(CHAINS):
            value = secret_element(secret_seed, public_seed, leaf, i, observe)
            wanted = target_digits[i] if target_digits is not None and leaf == target else None
            if wanted == 0:
                captures.append(value)
            for step in range(15):
                value = chain(value, step, 1, public_seed, leaf, i, observe)
                if wanted == step + 1:
                    captures.append(value)
            endpoints.append(value)
        node = l_tree(endpoints, public_seed, leaf, observe)
        level, index = 0, leaf
        if target is not None and index == (target ^ 1):
            auth[0] = node
        while stack and stack[-1][0] == level:
            _, left_index, left = stack.pop()
            if left_index + 1 != index or not index & 1:
                raise AssertionError("XMSS streaming tree adjacency error")
            index >>= 1
            node = randomized_hash(left, node, public_seed, kind=2, level=level,
                                   index=index, observe=observe)
            level += 1
            if target is not None and level < params.h and index == ((target >> level) ^ 1):
                auth[level] = node
        stack.append((level, index, node))
    if len(stack) != 1 or stack[0][:2] != (params.h, 0):
        raise AssertionError("XMSS streaming tree did not produce a root")
    if target is not None and any(v is None for v in auth):
        raise AssertionError("XMSS authentication path incomplete")
    return stack[0][2], tuple(v for v in auth if v is not None), tuple(captures)


def tree_root_and_auth(params: str | XmssParams, secret_seed: bytes, public_seed: bytes,
                       target: int | None = None, observe: Observe | None = None
                       ) -> tuple[bytes, tuple[bytes, ...]]:
    root, auth, _ = _build_tree(get_params(params), secret_seed, public_seed, target, None, observe)
    return root, auth


def keygen(params: str | XmssParams, secret_seed: bytes, secret_prf: bytes,
           public_seed: bytes, observe: Observe | None = None) -> tuple[PrivateKey, PublicKey]:
    p = get_params(params)
    _node(secret_prf, "secret PRF")
    root, _ = tree_root_and_auth(p, secret_seed, public_seed, observe=observe)
    private = PrivateKey(p, secret_seed, secret_prf, public_seed, root)
    return private, private.public_key


def signature_from_nodes(params: str | XmssParams, index: int, nodes: Sequence[bytes]) -> bytes:
    p = get_params(params)
    check_index(p, index)
    if len(nodes) != 1 + CHAINS + p.h:
        raise ValueError("XMSS signature node count mismatch")
    return index.to_bytes(4, "big") + b"".join(_node(node) for node in nodes)


def signature_to_nodes(params: str | XmssParams, signature: bytes) -> tuple[int, tuple[bytes, ...]]:
    p = get_params(params)
    if not isinstance(signature, bytes) or len(signature) != p.signature_bytes:
        raise ValueError("XMSS signature length mismatch")
    index = check_index(p, int.from_bytes(signature[:4], "big"))
    return index, tuple(signature[offset:offset + N] for offset in range(4, len(signature), N))


def sign(key: PrivateKey, message: bytes, index: int | None = None,
         observe: Observe | None = None) -> SignResult:
    q = check_index(key.params, key.next_index if index is None else index)
    randomizer = prf(key.secret_prf, q.to_bytes(N, "big"), observe)
    digest = message_digest(randomizer, key.root, q, message, observe)
    root, auth, captures = _build_tree(key.params, key.secret_seed, key.public_seed,
                                      q, digits(digest), observe)
    if not hmac.compare_digest(root, key.root):
        raise ValueError("XMSS private key root does not match its seeds")
    nodes = (randomizer,) + captures + auth
    return SignResult(signature_from_nodes(key.params, q, nodes), nodes, q, q + 1,
                      q + 1 == key.params.capacity)


def sign_with_auth(key: PrivateKey, message: bytes, auth: Sequence[bytes], index: int | None = None,
                   observe: Observe | None = None) -> SignResult:
    """Sign using supplied path; useful for layered real-height Verify tests.

    This does not attest that the supplied siblings came from the complete
    tree induced by the private seed.  ``sign`` is the full-tree oracle.
    """
    q = check_index(key.params, key.next_index if index is None else index)
    if len(auth) != key.params.h:
        raise ValueError("XMSS authentication path height mismatch")
    path = tuple(_node(v, "authentication node") for v in auth)
    randomizer = prf(key.secret_prf, q.to_bytes(N, "big"), observe)
    digest = message_digest(randomizer, key.root, q, message, observe)
    nodes = (randomizer,) + wots_sign(key.secret_seed, key.public_seed, q, digest, observe) + path
    return SignResult(signature_from_nodes(key.params, q, nodes), nodes, q, q + 1,
                      q + 1 == key.params.capacity)


def root_from_nodes(public: PublicKey, message: bytes, index: int, nodes: Sequence[bytes],
                    observe: Observe | None = None) -> bytes:
    check_index(public.params, index)
    if len(nodes) != 1 + CHAINS + public.params.h:
        raise ValueError("XMSS signature node count mismatch")
    values = tuple(_node(v) for v in nodes)
    digest = message_digest(values[0], public.root, index, message, observe)
    endpoints = wots_public_from_signature(values[1:1 + CHAINS], digest, public.public_seed, index, observe)
    node = l_tree(endpoints, public.public_seed, index, observe)
    for level, sibling in enumerate(values[1 + CHAINS:]):
        left, right = (sibling, node) if (index >> level) & 1 else (node, sibling)
        node = randomized_hash(left, right, public.public_seed, kind=2,
                               level=level, index=index >> (level + 1), observe=observe)
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
