import hashlib
import json
from collections import Counter
from pathlib import Path
import unittest

from model.reference.slh_dsa import (
    SLH_DSA_SHAKE_128F,
    keygen_internal,
    shake_permutations,
    sign_internal,
    verify_internal,
)


ROOT = Path(__file__).resolve().parents[1]
KAT_PATH = ROOT / "tests" / "kat" / "slh_dsa_shake_128f_keygen_acvp_tc31.json"
SIGN_KAT_PATH = (
    ROOT / "tests" / "kat" / "slh_dsa_shake_128f_siggen_acvp_tc137.json"
)


class SlhDsaOracleTests(unittest.TestCase):
    def test_shake_128f_keygen_matches_nist_acvp_tc31(self) -> None:
        kat = json.loads(KAT_PATH.read_text(encoding="utf-8"))
        counts: Counter[str] = Counter()
        permutations = 0
        trace = hashlib.sha256()

        def observe(kind: str, data: bytes, result: bytes) -> None:
            nonlocal permutations
            counts[kind] += 1
            permutations += shake_permutations(len(data), len(result))
            trace.update(len(kind).to_bytes(2, "big"))
            trace.update(kind.encode("ascii"))
            trace.update(len(data).to_bytes(4, "big"))
            trace.update(data)
            trace.update(result)

        secret_key, public_key = keygen_internal(
            SLH_DSA_SHAKE_128F,
            bytes.fromhex(kat["sk_seed"]),
            bytes.fromhex(kat["sk_prf"]),
            bytes.fromhex(kat["pk_seed"]),
            observe,
        )
        self.assertEqual(secret_key.hex(), kat["sk"])
        self.assertEqual(public_key.hex(), kat["pk"])
        self.assertEqual(counts, {"prf": 280, "f": 4200, "t_l": 8, "h": 7})
        self.assertEqual(sum(counts.values()), 4495)
        self.assertEqual(permutations, 4527)
        self.assertEqual(
            trace.hexdigest(),
            "7826cbace035bd81d1ee76db9eec0a2b135210b8c0a3d337d66a8218ab03bd53",
        )

    def test_parameter_invariants(self) -> None:
        params = SLH_DSA_SHAKE_128F
        self.assertEqual(params.hp * params.d, params.h)
        self.assertEqual(params.wots_len, 2 * params.n + 3)
        self.assertEqual(params.w, 1 << params.lg_w)

    def test_shake_128f_sign_matches_nist_acvp_tc137(self) -> None:
        kat = json.loads(SIGN_KAT_PATH.read_text(encoding="utf-8"))
        counts: Counter[str] = Counter()
        permutations = 0
        trace = hashlib.sha256()

        def observe(kind: str, data: bytes, result: bytes) -> None:
            nonlocal permutations
            counts[kind] += 1
            permutations += shake_permutations(len(data), len(result))
            trace.update(len(kind).to_bytes(2, "big"))
            trace.update(kind.encode("ascii"))
            trace.update(len(data).to_bytes(4, "big"))
            trace.update(data)
            trace.update(result)

        signature = sign_internal(
            SLH_DSA_SHAKE_128F,
            bytes.fromhex(kat["message"]),
            bytes.fromhex(kat["sk"]),
            observe=observe,
        )
        self.assertEqual(len(signature), kat["signature_length"])
        self.assertEqual(hashlib.sha256(signature).hexdigest(), kat["signature_sha256"])
        self.assertEqual(signature[:16].hex(), kat["signature_r"])
        self.assertEqual(signature[:64].hex(), kat["signature_first_64"])
        self.assertEqual(signature[-64:].hex(), kat["signature_last_64"])
        self.assertEqual(
            counts,
            {
                "prf_msg": 1,
                "h_msg": 1,
                "prf": 8272,
                "f": 94257,
                "h": 2230,
                "t_l": 176,
            },
        )
        self.assertEqual(sum(counts.values()), 104937)
        self.assertEqual(permutations, 105641)
        self.assertEqual(
            trace.hexdigest(),
            "46d6b690e89412270f8f68f28bc78c742d5c87769a91ddb9049d66e3ab09d52b",
        )
        self.assertTrue(
            verify_internal(
                SLH_DSA_SHAKE_128F,
                bytes.fromhex(kat["message"]),
                signature,
                bytes.fromhex(kat["pk"]),
            )
        )
        corrupted = bytearray(signature)
        corrupted[len(corrupted) // 2] ^= 1
        self.assertFalse(
            verify_internal(
                SLH_DSA_SHAKE_128F,
                bytes.fromhex(kat["message"]),
                bytes(corrupted),
                bytes.fromhex(kat["pk"]),
            )
        )


if __name__ == "__main__":
    unittest.main()
