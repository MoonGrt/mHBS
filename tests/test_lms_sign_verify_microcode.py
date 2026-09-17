import json
from pathlib import Path
import unittest

from model.interpreter import MicroInterpreter
from model.microcode_assembler import load_and_assemble
from model.reference.lms import (
    RFC8554_TEST2,
    lms_public_key_encoding,
    lms_sign,
    lms_verify,
)
from scripts.generate_lms_sign_verify_microcode import (
    build_sign_document,
    build_verify_document,
)
from scripts.run_lms_sign_verify_microcode import (
    LEAF_INDEX,
    MESSAGE,
    RANDOMIZER,
    SIGN_PROGRAM,
    VERIFY_PROGRAM,
    trace_observer,
)


class LmsSignVerifyMicrocodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.identifier = RFC8554_TEST2["identifier"]
        cls.seed = RFC8554_TEST2["seed"]
        cls.root = RFC8554_TEST2["expected_root"]
        cls.public_key = lms_public_key_encoding(cls.identifier, cls.root)
        digest, cls.sign_counts, observe = trace_observer()
        cls.signature, cls.next_q = lms_sign(
            MESSAGE,
            cls.identifier,
            cls.seed,
            LEAF_INDEX,
            RANDOMIZER,
            observe=observe,
        )
        cls.oracle_sign_digest = digest.hexdigest()
        cls.sign_image = load_and_assemble(SIGN_PROGRAM)
        cls.sign_result = MicroInterpreter(cls.sign_image, trace_mode="none").execute(
            {
                "identifier": cls.identifier,
                "seed": cls.seed,
                "q": LEAF_INDEX,
                "randomizer": RANDOMIZER,
                "message": MESSAGE,
            }
        )

    def test_checked_in_programs_match_generator(self) -> None:
        self.assertEqual(json.loads(SIGN_PROGRAM.read_text()), build_sign_document())
        self.assertEqual(json.loads(VERIFY_PROGRAM.read_text()), build_verify_document())

    def test_sign_matches_reference_signature_and_hash_trace(self) -> None:
        self.assertTrue(self.sign_result.done)
        self.assertIsNone(self.sign_result.error)
        self.assertEqual(self.sign_result.output, self.signature)
        self.assertEqual(len(self.signature), 2508)
        self.assertEqual(self.next_q, LEAF_INDEX + 1)
        self.assertEqual(self.sign_result.hash_trace_sha256, self.oracle_sign_digest)
        self.assertEqual(self.sign_result.counters["hash_calls"], 1101392)

    def test_verify_reconstructs_root_and_matches_hash_trace(self) -> None:
        digest, counts, observe = trace_observer()
        self.assertTrue(
            lms_verify(
                self.public_key,
                MESSAGE,
                self.signature,
                observe=observe,
            )
        )
        image = load_and_assemble(VERIFY_PROGRAM)
        result = MicroInterpreter(image, trace_mode="none").execute(
            {
                "identifier": self.identifier,
                "signature": self.signature,
                "message": MESSAGE,
            }
        )
        self.assertTrue(result.done)
        self.assertIsNone(result.error)
        self.assertEqual(result.output, self.root)
        self.assertEqual(result.hash_trace_sha256, digest.hexdigest())
        self.assertEqual(sum(counts.values()), 493)

    def test_one_bit_mutation_is_rejected(self) -> None:
        mutated = bytearray(self.signature)
        mutated[40] ^= 1
        mutated = bytes(mutated)
        result = MicroInterpreter(load_and_assemble(VERIFY_PROGRAM)).execute(
            {"identifier": self.identifier, "signature": mutated, "message": MESSAGE}
        )
        self.assertNotEqual(result.output, self.root)
        self.assertFalse(lms_verify(self.public_key, MESSAGE, mutated))


if __name__ == "__main__":
    unittest.main()
