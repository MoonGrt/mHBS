#!/usr/bin/env python3
"""Generate byte-exact RTL vectors for the two cached stateful products."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.reference.lms_shake import (
    LMS_SHAKE_H10_W4,
    lmots_coefficients,
    public_key_encoding,
    sign as lms_sign,
    tree_and_authentication,
)
from model.reference.lms import u32
from model.reference.xmss import (
    XMSS_SHAKE256_10_256,
    _chain_lengths,
    xmss_seed_keypair,
    xmss_set_index,
    xmss_sign,
)


KAT = ROOT / "tests" / "kat"


def write_bytes(name: str, value: bytes) -> None:
    (KAT / name).write_text("".join(f"{byte:02x}\n" for byte in value), encoding="ascii")


def main() -> None:
    xmss_source = json.loads(
        (KAT / "xmss_shake256_10_256_idx5.json").read_text(encoding="utf-8")
    )
    seed = bytes.fromhex(xmss_source["seed"])
    message = bytes.fromhex(xmss_source["message"])
    q = int(xmss_source["signing_index"])
    public_key, secret_key_zero = xmss_seed_keypair(seed)
    secret_key = xmss_set_index(secret_key_zero, q)
    signature, _ = xmss_sign(secret_key, message)
    signature_q6, _ = xmss_sign(xmss_set_index(secret_key_zero, q + 1), message)
    xmss_keygen = secret_key + public_key
    write_bytes("xmss_stateful_keygen_bytes.mem", xmss_keygen)
    write_bytes("xmss_stateful_sign_bytes.mem", signature)
    write_bytes("xmss_stateful_sign_q6_bytes.mem", signature_q6)

    identifier = bytes(range(16))
    lms_seed = bytes(range(0x20, 0x40))
    randomizer = bytes(range(0x40, 0x60))
    lms_message = b"micro-hbs-lms-kat-v1"
    root, authentication = tree_and_authentication(identifier, lms_seed, q)
    state = u32(q) + identifier + lms_seed + root
    public_key_lms = public_key_encoding(identifier, root)
    signature_lms, _ = lms_sign(
        state, lms_message, randomizer,
        cached_authentication=authentication,
    )
    _, authentication_q6 = tree_and_authentication(identifier, lms_seed, q + 1)
    state_q6 = u32(q + 1) + identifier + lms_seed + root
    signature_lms_q6, _ = lms_sign(
        state_q6, lms_message, randomizer,
        cached_authentication=authentication_q6,
    )
    lms_keygen = state + public_key_lms
    write_bytes("lms_shake_stateful_keygen_bytes.mem", lms_keygen)
    write_bytes("lms_shake_stateful_sign_bytes.mem", signature_lms)
    write_bytes("lms_shake_stateful_sign_q6_bytes.mem", signature_lms_q6)

    # Recompute the two message digests only for published operation counts.
    # The values themselves remain checked byte-for-byte by the .mem files.
    from model.reference.xmss import _hash_message, _prf
    sk_prf = seed[32:64]
    xmss_randomizer = _prf(XMSS_SHAKE256_10_256, sk_prf, q.to_bytes(32, "big"))
    digest = _hash_message(
        XMSS_SHAKE256_10_256, xmss_randomizer, public_key[:32], q, message
    )
    xmss_digits = _chain_lengths(XMSS_SHAKE256_10_256, digest)
    xmss_randomizer_q6 = _prf(
        XMSS_SHAKE256_10_256, sk_prf, (q + 1).to_bytes(32, "big")
    )
    digest_q6 = _hash_message(
        XMSS_SHAKE256_10_256, xmss_randomizer_q6,
        public_key[:32], q + 1, message
    )
    xmss_digits_q6 = _chain_lengths(XMSS_SHAKE256_10_256, digest_q6)
    lms_digest = hashlib.shake_256(
        identifier + u32(q) + b"\x81\x81" + randomizer + lms_message
    ).digest(32)
    lms_digits = lmots_coefficients(lms_digest)
    lms_digest_q6 = hashlib.shake_256(
        identifier + u32(q + 1) + b"\x81\x81" + randomizer + lms_message
    ).digest(32)
    lms_digits_q6 = lmots_coefficients(lms_digest_q6)
    manifest = {
        "schema_version": 1,
        "xmss": {
            "profile": "XMSS-SHAKE256_10_256",
            "initial_q": q,
            "message": message.hex(),
            "keygen_bytes": len(xmss_keygen),
            "keygen_sha256": hashlib.sha256(xmss_keygen).hexdigest(),
            "sign_bytes": len(signature),
            "sign_sha256": hashlib.sha256(signature).hexdigest(),
            "keygen_contexts": 3_430_396,
            "keygen_permutations": 3_430_396,
            "sign_contexts": 2 + 67 + 3 * sum(xmss_digits),
            "sign_permutations": 3 + 67 + 3 * sum(xmss_digits),
            "second_sign_sha256": hashlib.sha256(signature_q6).hexdigest(),
            "second_sign_contexts": 2 + 67 + 3 * sum(xmss_digits_q6),
            "second_sign_permutations": 3 + 67 + 3 * sum(xmss_digits_q6),
        },
        "lms_shake_research": {
            "profile": "LMS-SHAKE256-M32-H10/LMOTS-SHAKE256-N32-W4",
            "interoperable_with_rfc8554": False,
            "initial_q": q,
            "identifier": identifier.hex(),
            "seed": lms_seed.hex(),
            "randomizer": randomizer.hex(),
            "message": lms_message.hex(),
            "keygen_bytes": len(lms_keygen),
            "keygen_sha256": hashlib.sha256(lms_keygen).hexdigest(),
            "sign_bytes": len(signature_lms),
            "sign_sha256": hashlib.sha256(signature_lms).hexdigest(),
            "keygen_contexts": 1_100_799,
            "keygen_permutations": 1_116_159,
            "sign_contexts": 1 + 67 + sum(lms_digits),
            "sign_permutations": 1 + 67 + sum(lms_digits),
            "second_sign_sha256": hashlib.sha256(signature_lms_q6).hexdigest(),
            "second_sign_contexts": 1 + 67 + sum(lms_digits_q6),
            "second_sign_permutations": 1 + 67 + sum(lms_digits_q6),
        },
    }
    (KAT / "stateful_hbs_rtl_vectors.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
