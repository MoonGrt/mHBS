import unittest

from model.reference.lms_shake import (
    LMS_SHAKE_H10_W4,
    keygen,
    sign,
    tree_and_authentication,
    verify,
)


class LmsShakeOracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.identifier = bytes.fromhex("00112233445566778899aabbccddeeff")
        cls.seed = bytes(range(32))
        cls.randomizer = bytes(range(32, 64))
        cls.message = b"micro-hbs shake-lms research profile"
        cls.state, cls.public_key = keygen(cls.identifier, cls.seed, initial_q=5)

    def test_lengths_private_typecodes_and_determinism(self) -> None:
        self.assertEqual(len(self.state), LMS_SHAKE_H10_W4.state_bytes)
        self.assertEqual(len(self.public_key), LMS_SHAKE_H10_W4.public_key_bytes)
        self.assertEqual(self.public_key[:4].hex(), "80000006")
        self.assertEqual(self.public_key[4:8].hex(), "80000003")
        self.assertEqual(keygen(self.identifier, self.seed, 5),
                         (self.state, self.public_key))

    def test_sign_verify_and_state_advance(self) -> None:
        signature, updated = sign(
            self.state, self.message, self.randomizer
        )
        self.assertEqual(len(signature), LMS_SHAKE_H10_W4.signature_bytes)
        self.assertEqual(int.from_bytes(signature[:4], "big"), 5)
        self.assertEqual(int.from_bytes(updated[:4], "big"), 6)
        self.assertTrue(verify(self.public_key, self.message, signature))
        self.assertFalse(verify(self.public_key, self.message + b"!", signature))

    def test_cached_authentication_avoids_tree_recomputation(self) -> None:
        _root, auth = tree_and_authentication(
            self.identifier, self.seed, 5
        )
        kinds = []
        signature, _ = sign(
            self.state,
            self.message,
            self.randomizer,
            observe=lambda kind, _inp, _out: kinds.append(kind),
            cached_authentication=auth,
        )
        self.assertTrue(signature)
        self.assertNotIn("merkle_leaf", kinds)
        self.assertNotIn("merkle_internal", kinds)

    def test_exhausted_state_rejected(self) -> None:
        exhausted = (1 << 10).to_bytes(4, "big") + self.state[4:]
        with self.assertRaises(ValueError):
            sign(exhausted, self.message, self.randomizer)


if __name__ == "__main__":
    unittest.main()
