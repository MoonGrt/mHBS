"""Strict standard wire-format adapters for 32-byte stateful node streams.

These routines do not execute microcode.  The hardware payload omits the
index and type codes: R/C, 67 chain signature nodes, then h auth nodes.
LMS's LMS type code occurs *between* its LMOTS signature and auth path on
the standard wire, so a payload is not simply the standard signature with
a fixed-length prefix removed.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Callable, Sequence

from model.reference import lms, xmss
from model.reference.stateful_shake import reference

MAX_U64 = (1 << 64) - 1
STATEFUL_NAMES = tuple(xmss.PARAMS) + tuple(lms.PARAMS)


def _module(profile: str, hash_backend="shake"):
    if profile in xmss.PARAMS:
        return reference("xmss",hash_backend)
    if profile in lms.PARAMS:
        return reference("lms",hash_backend)
    raise ValueError(f"unsupported standard stateful profile: {profile!r}")


def profile_params(profile: str, hash_backend="shake") -> xmss.XmssParams | lms.LmsParams:
    return _module(profile,hash_backend).get_params(profile)


def validate_message(message: bytes) -> bytes:
    if not isinstance(message, bytes) or not 0 <= len(message) <= 87:
        raise ValueError("stateful hardware messages must contain 0..87 bytes")
    return message


def payload_to_nodes(profile: str, payload: bytes, *, hash_backend="shake") -> tuple[bytes, ...]:
    p = profile_params(profile,hash_backend)
    if not isinstance(payload, bytes) or len(payload) != p.payload_bytes:
        raise ValueError("stateful hardware signature payload length mismatch")
    return tuple(payload[i:i + 32] for i in range(0, len(payload), 32))


def nodes_to_payload(profile: str, nodes: Sequence[bytes], *, hash_backend="shake") -> bytes:
    p = profile_params(profile,hash_backend)
    if len(nodes) != 68 + p.h:
        raise ValueError("stateful signature node count mismatch")
    if any(not isinstance(node, bytes) or len(node) != 32 for node in nodes):
        raise ValueError("stateful signature nodes must each contain exactly 32 bytes")
    return b"".join(nodes)


def nodes_to_signature(profile: str, index: int, nodes: Sequence[bytes], *, hash_backend="shake") -> bytes:
    module = _module(profile,hash_backend)
    # Validate the payload independently of reference signature assembly.
    nodes_to_payload(profile, nodes,hash_backend=hash_backend)
    return module.signature_from_nodes(profile, index, nodes)


def signature_to_nodes(profile: str, signature: bytes, *, hash_backend="shake") -> tuple[int, tuple[bytes, ...]]:
    return _module(profile,hash_backend).signature_to_nodes(profile, signature)


def payload_to_signature(profile: str, index: int, payload: bytes, *, hash_backend="shake") -> bytes:
    return nodes_to_signature(profile,index,payload_to_nodes(profile,payload,hash_backend=hash_backend),hash_backend=hash_backend)


def signature_to_payload(profile: str, signature: bytes, *, hash_backend="shake") -> tuple[int, bytes]:
    index, nodes = signature_to_nodes(profile, signature,hash_backend=hash_backend)
    return index, nodes_to_payload(profile, nodes,hash_backend=hash_backend)


def public_key_from_root(profile: str, root: bytes, *, public_seed: bytes | None = None,
                         identifier: bytes | None = None, hash_backend="shake") -> xmss.PublicKey | lms.PublicKey:
    p = profile_params(profile,hash_backend)
    if profile in xmss.PARAMS:
        if public_seed is None or identifier is not None:
            raise ValueError("XMSS key construction requires a public seed")
        return _module(profile,hash_backend).PublicKey(p, root, public_seed)
    if identifier is None or public_seed is not None:
        raise ValueError("LMS key construction requires an identifier")
    return _module(profile,hash_backend).PublicKey(p, identifier, root)


def decode_public_key(profile: str, encoded: bytes, *, hash_backend="shake") -> xmss.PublicKey | lms.PublicKey:
    return _module(profile,hash_backend).PublicKey.from_bytes(encoded, profile)


@dataclass(frozen=True)
class IndexReservation:
    """A caller-persisted reservation; reset/failure must not roll it back."""

    profile: str
    used_index: int
    next_index: int
    exhausted: bool


def reserve_sign_index(profile: str, next_index: int,
                        persist: Callable[[int], None], *, hash_backend="shake") -> IndexReservation:
    """Persist next=q+1 *before* returning permission to start Sign.

    ``persist`` must provide the application's durable, atomic update.
    Exceptions propagate; no reservation is returned on persistence failure.
    This helper cannot make an in-memory callback durable, prevent races
    between applications, or recover a rolled-back external database.
    """
    p = profile_params(profile,hash_backend)
    q = _module(profile,hash_backend).check_index(p, next_index)
    if not callable(persist):
        raise ValueError("a durable index-persistence callback is required")
    persist(q + 1)
    return IndexReservation(profile, q, q + 1, q + 1 == p.capacity)


class HashAudit:
    """O(1) trace storage, backend block counts, and unsigned-64 bounds.

    The optional callback receives the original complete input and result
    once per physical Hash.  The rolling SHA-256 digest uses length prefixes
    and a fixed ABI-independent framing; it never stores the full trace.
    SHAKE padding consumes ``len(data)//136 + 1`` permutations, including
    an exact-rate message; SHA256 consumes ``(len(data)+72)//64`` blocks.
    """

    def __init__(self, observe: Callable[[str, bytes, bytes], None] | None = None,
                 *, initial_hash_count: int = 0, initial_permutations: int = 0, hash_backend="shake") -> None:
        for label, value in (("hash count", initial_hash_count), ("permutation count", initial_permutations)):
            if type(value) is not int or not 0 <= value <= MAX_U64:
                raise ValueError(f"invalid unsigned-64 initial {label}")
        if hash_backend not in ("shake","sha2"): raise ValueError("unknown hash backend")
        self.hash_backend=hash_backend
        self.hash_count = initial_hash_count
        self.permutations = initial_permutations
        self.by_kind: dict[str, int] = {}
        self._digest = hashlib.sha256()
        self._work_digest = hashlib.sha256()
        self._observe = observe

    def __call__(self, kind: str, data: bytes, result: bytes) -> None:
        if not isinstance(kind, str) or not isinstance(data, bytes) or not isinstance(result, bytes) or len(result) != 32:
            raise ValueError("malformed stateful Hash observation")
        encoded_kind = kind.encode("ascii")
        if len(encoded_kind) > 65535:
            raise ValueError("Hash observation kind is too long")
        permutations = (len(data)+72)//64 if self.hash_backend == "sha2" else len(data)//136+1
        if self.hash_count == MAX_U64 or self.permutations > MAX_U64 - permutations:
            raise OverflowError("stateful Hash statistics exceed unsigned-64 range")
        self.hash_count += 1
        self.permutations += permutations
        self.by_kind[kind] = self.by_kind.get(kind, 0) + 1
        self._digest.update(len(encoded_kind).to_bytes(2, "big") + encoded_kind)
        self._digest.update(len(data).to_bytes(8, "big") + data + result)
        self._work_digest.update(len(data).to_bytes(4, "little") + data + result)
        if self._observe is not None:
            self._observe(kind, data, result)

    @property
    def trace_sha256(self) -> str:
        return self._digest.hexdigest()

    @property
    def work_trace_sha256(self) -> str:
        """Existing micro-flow framing, independent of algorithm kind labels."""
        return self._work_digest.hexdigest()

    def as_dict(self) -> dict:
        return {"hash_count": self.hash_count, "permutations": self.permutations,
                "by_kind": dict(self.by_kind), "trace_sha256": self.trace_sha256,
                "hash_trace_sha256": self.work_trace_sha256,
                "counts": [self.hash_count, self.permutations]}
