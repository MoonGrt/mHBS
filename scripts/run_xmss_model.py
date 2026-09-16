#!/usr/bin/env python3
"""Run the deterministic XMSS Keygen/Sign oracle cross-check."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.reference.xmss import (  # noqa: E402
    XMSS_SHAKE256_10_256,
    xmss_seed_keypair,
    xmss_set_index,
    xmss_sign,
    xmss_verify,
)


KAT_PATH = ROOT / "tests" / "kat" / "xmss_shake256_10_256_idx5.json"


def main() -> int:
    vector = json.loads(KAT_PATH.read_text(encoding="utf-8"))
    seed = bytes.fromhex(vector["seed"])
    message = bytes.fromhex(vector["message"])
    public_key, secret_key = xmss_seed_keypair(seed)
    signature, updated = xmss_sign(
        xmss_set_index(secret_key, vector["signing_index"]), message
    )
    actual_digest = hashlib.sha256(signature).hexdigest()
    checks = {
        "public_key_match": public_key.hex() == vector["public_key"],
        "signature_digest_match": actual_digest == vector["signature_sha256"],
        "signature_verifies": xmss_verify(public_key, message, signature),
        "updated_index_match": int.from_bytes(updated[:4], "big") == vector["updated_index"],
    }
    result = {
        "profile": XMSS_SHAKE256_10_256.name,
        "paper_notation": {"n_bytes": 32, "h": 10, "w_bits": 4, "len": 67},
        "rfc_notation": {"wots_w": 16, "oid": "0x00000010"},
        "source_commit": vector["upstream_commit"],
        "signature_bytes": len(signature),
        "signature_sha256": actual_digest,
        "checks": checks,
        "status": "PASS" if all(checks.values()) else "FAIL",
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
