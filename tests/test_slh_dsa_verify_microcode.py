import json
from pathlib import Path
import unittest

from model.interpreter import MicroInterpreter
from model.microcode_assembler import load_and_assemble
from model.reference.slh_dsa import SLH_DSA_SHAKE_128F, verify_internal
from scripts.run_slh_dsa_verify_microcode import (
    PROGRAM,
    build_verify_job,
    load_kat_inputs,
    oracle_trace,
)


ROOT = Path(__file__).resolve().parents[1]


class SlhDsaVerifyMicrocodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.vector, cls.public_key, cls.message, cls.signature = load_kat_inputs()
        cls.image = load_and_assemble(PROGRAM)
        cls.result = MicroInterpreter(cls.image, trace_mode="none").execute(
            build_verify_job(cls.public_key, cls.message, cls.signature)
        )

    def test_valid_signature_reconstructs_root_and_exact_hash_trace(self) -> None:
        accepted, digest, counts = oracle_trace(
            self.public_key, self.message, self.signature
        )
        self.assertTrue(accepted)
        self.assertTrue(self.result.done)
        self.assertIsNone(self.result.error)
        self.assertEqual(self.result.output, self.public_key[16:])
        self.assertEqual(self.result.hash_trace_sha256, digest)
        self.assertEqual(
            counts,
            {"f": 6153, "h": 264, "h_msg": 1, "t_l": 23},
        )
        self.assertEqual(self.result.counters["dynamic_instructions"], 18036)
        self.assertEqual(self.result.counters["hash_calls"], 6441)
        self.assertEqual(self.result.counters["keccak_permutations"], 6533)

    def test_one_bit_signature_mutation_reconstructs_different_root(self) -> None:
        mutated = bytearray(self.signature)
        mutated[16] ^= 1
        mutated = bytes(mutated)
        result = MicroInterpreter(self.image, trace_mode="none").execute(
            build_verify_job(self.public_key, self.message, mutated)
        )
        self.assertTrue(result.done)
        self.assertIsNone(result.error)
        self.assertNotEqual(result.output, self.public_key[16:])
        self.assertFalse(
            verify_internal(
                SLH_DSA_SHAKE_128F,
                self.message,
                mutated,
                self.public_key,
            )
        )

    def test_program_is_compact_and_uses_eight_opcode_types(self) -> None:
        self.assertEqual(self.image["word_count"], 38)
        self.assertEqual(self.image["image_bytes"], 304)
        self.assertEqual(
            {instruction.opcode.name for instruction in self.image["instructions"]},
            {
                "OUTPUT",
                "HALT",
                "HASH",
                "DATA_LOAD",
                "LOOP_END",
                "LOOP_BEGIN",
                "SET_REG",
                "DATA_MOVE",
            },
        )

    def test_short_signature_is_rejected_at_job_admission(self) -> None:
        with self.assertRaisesRegex(ValueError, "input length mismatch"):
            build_verify_job(self.public_key, self.message, self.signature[:-1])


if __name__ == "__main__":
    unittest.main()
