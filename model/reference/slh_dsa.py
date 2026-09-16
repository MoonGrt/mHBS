"""Small dependency-free FIPS 205 SLH-DSA reference model.

The supported boundary is deterministic internal key generation, signing and
verification for SLH-DSA-SHAKE-128f.  The implementation follows the final
FIPS 205 algorithms and deliberately favors auditable byte strings over
performance.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Callable, Sequence


Observe = Callable[[str, bytes, bytes], None]

WOTS_HASH = 0
WOTS_PK = 1
TREE = 2
FORS_TREE = 3
FORS_ROOTS = 4
WOTS_PRF = 5
FORS_PRF = 6


@dataclass(frozen=True)
class SlhDsaParams:
    name: str
    n: int
    h: int
    d: int
    hp: int
    a: int
    k: int
    lg_w: int
    w: int
    wots_len1: int
    wots_len2: int
    wots_len: int
    m: int


SLH_DSA_SHAKE_128F = SlhDsaParams(
    name="SLH-DSA-SHAKE-128f",
    n=16,
    h=66,
    d=22,
    hp=3,
    a=6,
    k=33,
    lg_w=4,
    w=16,
    wots_len1=32,
    wots_len2=3,
    wots_len=35,
    m=34,
)


def _to_bytes(value: int, length: int) -> bytes:
    return value.to_bytes(length, "big", signed=False)


def _address_bytes(address: Sequence[int]) -> bytes:
    if len(address) != 8:
        raise ValueError("SLH-DSA address must contain eight 32-bit words")
    return b"".join(_to_bytes(word, 4) for word in address)


def _set_type_and_clear(address: list[int], address_type: int) -> None:
    address[4] = address_type
    address[5:] = [0, 0, 0]


def _set_tree_address(address: list[int], tree: int) -> None:
    encoded = _to_bytes(tree, 12)
    address[1:4] = [int.from_bytes(encoded[offset : offset + 4], "big") for offset in (0, 4, 8)]


def _shake(
    kind: str,
    data: bytes,
    output_length: int,
    observe: Observe | None,
) -> bytes:
    result = hashlib.shake_256(data).digest(output_length)
    if observe is not None:
        observe(kind, data, result)
    return result


def _prf(
    params: SlhDsaParams,
    public_seed: bytes,
    secret_seed: bytes,
    address: Sequence[int],
    observe: Observe | None = None,
) -> bytes:
    if len(public_seed) != params.n or len(secret_seed) != params.n:
        raise ValueError("SLH-DSA PRF seed length mismatch")
    return _shake(
        "prf",
        public_seed + _address_bytes(address) + secret_seed,
        params.n,
        observe,
    )


def _f(
    params: SlhDsaParams,
    public_seed: bytes,
    address: Sequence[int],
    message: bytes,
    observe: Observe | None = None,
) -> bytes:
    if len(message) != params.n:
        raise ValueError("SLH-DSA F input length mismatch")
    return _shake(
        "f",
        public_seed + _address_bytes(address) + message,
        params.n,
        observe,
    )


def _h(
    params: SlhDsaParams,
    public_seed: bytes,
    address: Sequence[int],
    message: bytes,
    observe: Observe | None = None,
) -> bytes:
    if len(message) != 2 * params.n:
        raise ValueError("SLH-DSA H input length mismatch")
    return _shake(
        "h",
        public_seed + _address_bytes(address) + message,
        params.n,
        observe,
    )


def _t_l(
    params: SlhDsaParams,
    public_seed: bytes,
    address: Sequence[int],
    message: bytes,
    observe: Observe | None = None,
) -> bytes:
    if len(message) % params.n:
        raise ValueError("SLH-DSA T_l input is not an n-byte array")
    return _shake(
        "t_l",
        public_seed + _address_bytes(address) + message,
        params.n,
        observe,
    )


def _prf_message(
    params: SlhDsaParams,
    secret_prf: bytes,
    optional_randomness: bytes,
    message: bytes,
    observe: Observe | None = None,
) -> bytes:
    return _shake(
        "prf_msg",
        secret_prf + optional_randomness + message,
        params.n,
        observe,
    )


def _hash_message(
    params: SlhDsaParams,
    randomizer: bytes,
    public_seed: bytes,
    public_root: bytes,
    message: bytes,
    observe: Observe | None = None,
) -> bytes:
    return _shake(
        "h_msg",
        randomizer + public_seed + public_root + message,
        params.m,
        observe,
    )


def _base_2b(value: bytes, bits_per_digit: int, output_length: int) -> list[int]:
    if len(value) * 8 < bits_per_digit * output_length:
        raise ValueError("base_2b input is too short")
    input_index = 0
    bits = 0
    total = 0
    output: list[int] = []
    for _ in range(output_length):
        while bits < bits_per_digit:
            total = (total << 8) + value[input_index]
            input_index += 1
            bits += 8
        bits -= bits_per_digit
        output.append((total >> bits) & ((1 << bits_per_digit) - 1))
    return output


def _wots_digits(params: SlhDsaParams, message: bytes) -> list[int]:
    if len(message) != params.n:
        raise ValueError("SLH-DSA WOTS+ message length mismatch")
    digits = _base_2b(message, params.lg_w, params.wots_len1)
    checksum = sum(params.w - 1 - digit for digit in digits)
    checksum_bits = params.wots_len2 * params.lg_w
    checksum <<= (8 - (checksum_bits % 8)) % 8
    checksum_bytes = _to_bytes(checksum, (checksum_bits + 7) // 8)
    return digits + _base_2b(checksum_bytes, params.lg_w, params.wots_len2)


def _chain(
    params: SlhDsaParams,
    value: bytes,
    start: int,
    steps: int,
    public_seed: bytes,
    address: list[int],
    observe: Observe | None = None,
) -> bytes:
    if start < 0 or steps < 0 or start + steps > params.w:
        raise ValueError("SLH-DSA WOTS+ chain range is invalid")
    result = value
    for index in range(start, start + steps):
        address[7] = index
        result = _f(params, public_seed, address, result, observe)
    return result


def _wots_pkgen(
    params: SlhDsaParams,
    secret_seed: bytes,
    public_seed: bytes,
    address: list[int],
    observe: Observe | None = None,
) -> bytes:
    key_pair_address = address[5]
    secret_address = list(address)
    _set_type_and_clear(secret_address, WOTS_PRF)
    secret_address[5] = key_pair_address
    public_values: list[bytes] = []
    for chain_index in range(params.wots_len):
        secret_address[6] = chain_index
        secret_value = _prf(
            params, public_seed, secret_seed, secret_address, observe
        )
        address[6] = chain_index
        public_values.append(
            _chain(
                params,
                secret_value,
                0,
                params.w - 1,
                public_seed,
                address,
                observe,
            )
        )
    public_key_address = list(address)
    _set_type_and_clear(public_key_address, WOTS_PK)
    public_key_address[5] = key_pair_address
    return _t_l(
        params,
        public_seed,
        public_key_address,
        b"".join(public_values),
        observe,
    )


def _wots_sign(
    params: SlhDsaParams,
    message: bytes,
    secret_seed: bytes,
    public_seed: bytes,
    address: list[int],
    observe: Observe | None = None,
) -> bytes:
    digits = _wots_digits(params, message)
    key_pair_address = address[5]
    secret_address = list(address)
    _set_type_and_clear(secret_address, WOTS_PRF)
    secret_address[5] = key_pair_address
    signature: list[bytes] = []
    for chain_index, steps in enumerate(digits):
        secret_address[6] = chain_index
        secret_value = _prf(params, public_seed, secret_seed, secret_address, observe)
        address[6] = chain_index
        signature.append(
            _chain(params, secret_value, 0, steps, public_seed, address, observe)
        )
    return b"".join(signature)


def _wots_pk_from_sig(
    params: SlhDsaParams,
    signature: bytes,
    message: bytes,
    public_seed: bytes,
    address: list[int],
    observe: Observe | None = None,
) -> bytes:
    if len(signature) != params.wots_len * params.n:
        raise ValueError("SLH-DSA WOTS+ signature length mismatch")
    digits = _wots_digits(params, message)
    values: list[bytes] = []
    for chain_index, start in enumerate(digits):
        address[6] = chain_index
        value = signature[chain_index * params.n : (chain_index + 1) * params.n]
        values.append(
            _chain(
                params,
                value,
                start,
                params.w - 1 - start,
                public_seed,
                address,
                observe,
            )
        )
    public_key_address = list(address)
    key_pair_address = address[5]
    _set_type_and_clear(public_key_address, WOTS_PK)
    public_key_address[5] = key_pair_address
    return _t_l(
        params,
        public_seed,
        public_key_address,
        b"".join(values),
        observe,
    )


def _xmss_node(
    params: SlhDsaParams,
    secret_seed: bytes,
    node_index: int,
    height: int,
    public_seed: bytes,
    address: list[int],
    observe: Observe | None = None,
) -> bytes:
    if height < 0 or height > params.hp:
        raise ValueError("SLH-DSA XMSS node height is invalid")
    if node_index < 0 or node_index >= 1 << (params.hp - height):
        raise ValueError("SLH-DSA XMSS node index is invalid")
    if height == 0:
        _set_type_and_clear(address, WOTS_HASH)
        address[5] = node_index
        return _wots_pkgen(params, secret_seed, public_seed, address, observe)
    left = _xmss_node(
        params, secret_seed, 2 * node_index, height - 1, public_seed, address, observe
    )
    right = _xmss_node(
        params,
        secret_seed,
        2 * node_index + 1,
        height - 1,
        public_seed,
        address,
        observe,
    )
    _set_type_and_clear(address, TREE)
    address[6] = height
    address[7] = node_index
    return _h(params, public_seed, address, left + right, observe)


def _xmss_sign(
    params: SlhDsaParams,
    message: bytes,
    secret_seed: bytes,
    leaf_index: int,
    public_seed: bytes,
    address: list[int],
    observe: Observe | None = None,
) -> bytes:
    if not 0 <= leaf_index < (1 << params.hp):
        raise ValueError("SLH-DSA XMSS signing leaf is invalid")
    authentication: list[bytes] = []
    for height in range(params.hp):
        sibling = (leaf_index >> height) ^ 1
        authentication.append(
            _xmss_node(
                params,
                secret_seed,
                sibling,
                height,
                public_seed,
                address,
                observe,
            )
        )
    _set_type_and_clear(address, WOTS_HASH)
    address[5] = leaf_index
    wots_signature = _wots_sign(
        params, message, secret_seed, public_seed, address, observe
    )
    return wots_signature + b"".join(authentication)


def _xmss_pk_from_sig(
    params: SlhDsaParams,
    leaf_index: int,
    signature: bytes,
    message: bytes,
    public_seed: bytes,
    address: list[int],
    observe: Observe | None = None,
) -> bytes:
    expected = (params.wots_len + params.hp) * params.n
    if len(signature) != expected:
        raise ValueError("SLH-DSA XMSS signature length mismatch")
    wots_bytes = params.wots_len * params.n
    _set_type_and_clear(address, WOTS_HASH)
    address[5] = leaf_index
    node = _wots_pk_from_sig(
        params,
        signature[:wots_bytes],
        message,
        public_seed,
        address,
        observe,
    )
    authentication = signature[wots_bytes:]
    _set_type_and_clear(address, TREE)
    # Algorithm 11 starts the authentication-path reduction at the XMSS leaf
    # index.  setTypeAndClear resets the tree index, so restore it explicitly
    # before the first parent-address calculation.
    address[7] = leaf_index
    for height in range(params.hp):
        sibling = authentication[height * params.n : (height + 1) * params.n]
        address[6] = height + 1
        if ((leaf_index >> height) & 1) == 0:
            address[7] = address[7] // 2
            node = _h(params, public_seed, address, node + sibling, observe)
        else:
            address[7] = (address[7] - 1) // 2
            node = _h(params, public_seed, address, sibling + node, observe)
    return node


def _fors_secret(
    params: SlhDsaParams,
    secret_seed: bytes,
    public_seed: bytes,
    address: list[int],
    index: int,
    observe: Observe | None = None,
) -> bytes:
    secret_address = list(address)
    key_pair_address = address[5]
    _set_type_and_clear(secret_address, FORS_PRF)
    secret_address[5] = key_pair_address
    secret_address[7] = index
    return _prf(params, public_seed, secret_seed, secret_address, observe)


def _fors_node(
    params: SlhDsaParams,
    secret_seed: bytes,
    node_index: int,
    height: int,
    public_seed: bytes,
    address: list[int],
    observe: Observe | None = None,
) -> bytes:
    if height == 0:
        secret = _fors_secret(
            params, secret_seed, public_seed, address, node_index, observe
        )
        address[6] = 0
        address[7] = node_index
        return _f(params, public_seed, address, secret, observe)
    left = _fors_node(
        params, secret_seed, 2 * node_index, height - 1, public_seed, address, observe
    )
    right = _fors_node(
        params,
        secret_seed,
        2 * node_index + 1,
        height - 1,
        public_seed,
        address,
        observe,
    )
    address[6] = height
    address[7] = node_index
    return _h(params, public_seed, address, left + right, observe)


def _fors_sign(
    params: SlhDsaParams,
    message_digest: bytes,
    secret_seed: bytes,
    public_seed: bytes,
    address: list[int],
    observe: Observe | None = None,
) -> bytes:
    indices = _base_2b(message_digest, params.a, params.k)
    signature: list[bytes] = []
    for tree, selected in enumerate(indices):
        signature.append(
            _fors_secret(
                params,
                secret_seed,
                public_seed,
                address,
                tree * (1 << params.a) + selected,
                observe,
            )
        )
        for height in range(params.a):
            sibling = (selected >> height) ^ 1
            signature.append(
                _fors_node(
                    params,
                    secret_seed,
                    tree * (1 << (params.a - height)) + sibling,
                    height,
                    public_seed,
                    address,
                    observe,
                )
            )
    return b"".join(signature)


def _fors_pk_from_sig(
    params: SlhDsaParams,
    signature: bytes,
    message_digest: bytes,
    public_seed: bytes,
    address: list[int],
    observe: Observe | None = None,
) -> bytes:
    expected = params.k * (params.a + 1) * params.n
    if len(signature) != expected:
        raise ValueError("SLH-DSA FORS signature length mismatch")
    indices = _base_2b(message_digest, params.a, params.k)
    roots: list[bytes] = []
    for tree, selected in enumerate(indices):
        offset = tree * (params.a + 1) * params.n
        node = signature[offset : offset + params.n]
        address[6] = 0
        address[7] = tree * (1 << params.a) + selected
        node = _f(params, public_seed, address, node, observe)
        for height in range(params.a):
            auth_offset = offset + (height + 1) * params.n
            sibling = signature[auth_offset : auth_offset + params.n]
            address[6] = height + 1
            if ((selected >> height) & 1) == 0:
                address[7] //= 2
                node = _h(params, public_seed, address, node + sibling, observe)
            else:
                address[7] = (address[7] - 1) // 2
                node = _h(params, public_seed, address, sibling + node, observe)
        roots.append(node)
    public_key_address = list(address)
    key_pair_address = address[5]
    _set_type_and_clear(public_key_address, FORS_ROOTS)
    public_key_address[5] = key_pair_address
    return _t_l(params, public_seed, public_key_address, b"".join(roots), observe)


def _hypertree_sign(
    params: SlhDsaParams,
    message: bytes,
    secret_seed: bytes,
    public_seed: bytes,
    tree_index: int,
    leaf_index: int,
    observe: Observe | None = None,
) -> bytes:
    address = [0] * 8
    _set_tree_address(address, tree_index)
    temporary = _xmss_sign(
        params, message, secret_seed, leaf_index, public_seed, address, observe
    )
    output = bytearray(temporary)
    root = _xmss_pk_from_sig(
        params, leaf_index, temporary, message, public_seed, address, observe
    )
    for layer in range(1, params.d):
        leaf_index = tree_index % (1 << params.hp)
        tree_index >>= params.hp
        address[0] = layer
        _set_tree_address(address, tree_index)
        temporary = _xmss_sign(
            params, root, secret_seed, leaf_index, public_seed, address, observe
        )
        output.extend(temporary)
        if layer < params.d - 1:
            root = _xmss_pk_from_sig(
                params, leaf_index, temporary, root, public_seed, address, observe
            )
    return bytes(output)


def _hypertree_verify(
    params: SlhDsaParams,
    message: bytes,
    signature: bytes,
    public_seed: bytes,
    tree_index: int,
    leaf_index: int,
    public_root: bytes,
    observe: Observe | None = None,
) -> bool:
    xmss_bytes = (params.wots_len + params.hp) * params.n
    if len(signature) != params.d * xmss_bytes:
        return False
    address = [0] * 8
    _set_tree_address(address, tree_index)
    root = message
    for layer in range(params.d):
        temporary = signature[layer * xmss_bytes : (layer + 1) * xmss_bytes]
        root = _xmss_pk_from_sig(
            params, leaf_index, temporary, root, public_seed, address, observe
        )
        if layer < params.d - 1:
            leaf_index = tree_index % (1 << params.hp)
            tree_index >>= params.hp
            address[0] = layer + 1
            _set_tree_address(address, tree_index)
    return root == public_root


def keygen_internal(
    params: SlhDsaParams,
    secret_seed: bytes,
    secret_prf: bytes,
    public_seed: bytes,
    observe: Observe | None = None,
) -> tuple[bytes, bytes]:
    for name, value in (
        ("secret_seed", secret_seed),
        ("secret_prf", secret_prf),
        ("public_seed", public_seed),
    ):
        if len(value) != params.n:
            raise ValueError(f"{name} length mismatch")
    address = [0] * 8
    address[0] = params.d - 1
    public_root = _xmss_node(
        params,
        secret_seed,
        0,
        params.hp,
        public_seed,
        address,
        observe,
    )
    secret_key = secret_seed + secret_prf + public_seed + public_root
    public_key = public_seed + public_root
    return secret_key, public_key


def sign_internal(
    params: SlhDsaParams,
    message: bytes,
    secret_key: bytes,
    additional_randomness: bytes | None = None,
    observe: Observe | None = None,
) -> bytes:
    if len(secret_key) != 4 * params.n:
        raise ValueError("SLH-DSA private key length mismatch")
    secret_seed = secret_key[: params.n]
    secret_prf = secret_key[params.n : 2 * params.n]
    public_seed = secret_key[2 * params.n : 3 * params.n]
    public_root = secret_key[3 * params.n :]
    optional_randomness = public_seed if additional_randomness is None else additional_randomness
    if len(optional_randomness) != params.n:
        raise ValueError("SLH-DSA additional randomness length mismatch")

    randomizer = _prf_message(
        params, secret_prf, optional_randomness, message, observe
    )
    digest = _hash_message(
        params, randomizer, public_seed, public_root, message, observe
    )
    fors_bytes = (params.k * params.a + 7) // 8
    tree_bits = params.h - params.hp
    tree_bytes = (tree_bits + 7) // 8
    leaf_bytes = (params.hp + 7) // 8
    message_digest = digest[:fors_bytes]
    offset = fors_bytes
    tree_index = int.from_bytes(digest[offset : offset + tree_bytes], "big") % (
        1 << tree_bits
    )
    offset += tree_bytes
    leaf_index = int.from_bytes(digest[offset : offset + leaf_bytes], "big") % (
        1 << params.hp
    )

    address = [0] * 8
    _set_tree_address(address, tree_index)
    _set_type_and_clear(address, FORS_TREE)
    address[5] = leaf_index
    fors_signature = _fors_sign(
        params, message_digest, secret_seed, public_seed, address, observe
    )
    fors_public_key = _fors_pk_from_sig(
        params, fors_signature, message_digest, public_seed, address, observe
    )
    hypertree_signature = _hypertree_sign(
        params,
        fors_public_key,
        secret_seed,
        public_seed,
        tree_index,
        leaf_index,
        observe,
    )
    signature = randomizer + fors_signature + hypertree_signature
    expected = params.n + params.k * (params.a + 1) * params.n + (
        params.h + params.d * params.wots_len
    ) * params.n
    if len(signature) != expected:
        raise AssertionError("SLH-DSA signature length invariant failed")
    return signature


def verify_internal(
    params: SlhDsaParams,
    message: bytes,
    signature: bytes,
    public_key: bytes,
    observe: Observe | None = None,
) -> bool:
    if len(public_key) != 2 * params.n:
        return False
    expected = params.n + params.k * (params.a + 1) * params.n + (
        params.h + params.d * params.wots_len
    ) * params.n
    if len(signature) != expected:
        return False
    public_seed = public_key[: params.n]
    public_root = public_key[params.n :]
    randomizer = signature[: params.n]
    digest = _hash_message(
        params, randomizer, public_seed, public_root, message, observe
    )
    fors_bytes = (params.k * params.a + 7) // 8
    tree_bits = params.h - params.hp
    tree_bytes = (tree_bits + 7) // 8
    leaf_bytes = (params.hp + 7) // 8
    message_digest = digest[:fors_bytes]
    offset = fors_bytes
    tree_index = int.from_bytes(digest[offset : offset + tree_bytes], "big") % (
        1 << tree_bits
    )
    offset += tree_bytes
    leaf_index = int.from_bytes(digest[offset : offset + leaf_bytes], "big") % (
        1 << params.hp
    )

    fors_signature_bytes = params.k * (params.a + 1) * params.n
    fors_signature = signature[
        params.n : params.n + fors_signature_bytes
    ]
    hypertree_signature = signature[params.n + fors_signature_bytes :]
    address = [0] * 8
    _set_tree_address(address, tree_index)
    _set_type_and_clear(address, FORS_TREE)
    address[5] = leaf_index
    fors_public_key = _fors_pk_from_sig(
        params, fors_signature, message_digest, public_seed, address, observe
    )
    return _hypertree_verify(
        params,
        fors_public_key,
        hypertree_signature,
        public_seed,
        tree_index,
        leaf_index,
        public_root,
        observe,
    )


def shake_permutations(input_length: int, output_length: int) -> int:
    """Count SHAKE256 rate permutations for the model's short outputs."""
    rate = 136
    absorb = input_length // rate + 1
    squeeze = max(0, (output_length + rate - 1) // rate - 1)
    return absorb + squeeze
