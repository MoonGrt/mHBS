import hashlib
import json
from pathlib import Path
import unittest

from model.reference.xmss import (
    XMSS_SHAKE256_10_256,
    xmss_seed_keypair,
    xmss_set_index,
    xmss_sign,
    xmss_verify,
)


KAT_PATH = Path(__file__).resolve().parent / "kat" / "xmss_shake256_10_256_idx5.json"


class XmssOracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.vector = json.loads(KAT_PATH.read_text(encoding="utf-8"))
        seed = bytes.fromhex(cls.vector["seed"])
        cls.message = bytes.fromhex(cls.vector["message"])
        cls.public_key, secret_key = xmss_seed_keypair(seed)
        secret_key = xmss_set_index(secret_key, cls.vector["signing_index"])
        cls.signature, cls.updated_secret_key = xmss_sign(secret_key, cls.message)

    def test_matches_pinned_rfc8391_reference_implementation(self) -> None:
        params = XMSS_SHAKE256_10_256
        vector = self.vector
        self.assertEqual(self.public_key.hex(), vector["public_key"])
        self.assertEqual(self.signature[4:36].hex(), vector["randomizer"])
        wots_end = 36 + params.wots_sig_bytes
        self.assertEqual(
            hashlib.sha256(self.signature[36:wots_end]).hexdigest(),
            vector["wots_signature_sha256"],
        )
        self.assertEqual(
            hashlib.sha256(self.signature[wots_end:]).hexdigest(),
            vector["authentication_path_sha256"],
        )
        self.assertEqual(
            hashlib.sha256(self.signature).hexdigest(), vector["signature_sha256"]
        )
        self.assertEqual(len(self.signature), vector["signature_bytes"])
        self.assertEqual(
            int.from_bytes(self.updated_secret_key[: params.index_bytes], "big"),
            vector["updated_index"],
        )

    def test_signature_verifies_and_mutation_fails(self) -> None:
        self.assertTrue(xmss_verify(self.public_key, self.message, self.signature))
        mutated = bytearray(self.signature)
        mutated[len(mutated) // 2] ^= 1
        self.assertFalse(xmss_verify(self.public_key, self.message, bytes(mutated)))

    def test_parameter_notation_matches_paper(self) -> None:
        params = XMSS_SHAKE256_10_256
        self.assertEqual(params.wots_w, 1 << 4)
        self.assertEqual(params.wots_len, 67)
        self.assertEqual(params.full_height, 10)
        self.assertEqual(params.sig_bytes, 2500)


if __name__ == "__main__":
    unittest.main()
