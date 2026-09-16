import hashlib
import json
from pathlib import Path
import unittest

from model.interpreter import MicroInterpreter
from model.microcode_assembler import load_and_assemble
from model.reference.xmss import xmss_verify
from scripts.run_xmss_verify_microcode import (
    PROGRAM,
    build_verify_job,
    load_kat_inputs,
    oracle_trace,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "manifests/programs/xmss_shake256_h10_w4_verify_v0.1.0.json"


class XmssVerifyMicrocodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.image = load_and_assemble(PROGRAM)
        cls.vector, cls.public_key, cls.message, cls.signature = load_kat_inputs()
        cls.result = MicroInterpreter(cls.image, trace_mode="none").execute(
            build_verify_job(cls.public_key, cls.message, cls.signature)
        )

    def test_valid_signature_reconstructs_root_and_exact_ordered_trace(self) -> None:
        job = build_verify_job(self.public_key, self.message, self.signature)
        rebound_signature = (
            job["index"].to_bytes(4, "big")
            + job["randomizer"]
            + b"".join(job[f"wots_signature_{index:02d}"] for index in range(67))
            + b"".join(
                job[f"authentication_node_{height:02d}"] for height in range(10)
            )
        )
        self.assertEqual(rebound_signature, self.signature)
        oracle_accepts, oracle_digest, class_counts = oracle_trace(
            self.public_key, self.message, self.signature
        )
        self.assertTrue(oracle_accepts)
        self.assertTrue(self.result.done)
        self.assertIsNone(self.result.error)
        self.assertEqual(self.result.output, self.public_key[:32])
        self.assertEqual(self.result.hash_trace_sha256, oracle_digest)
        self.assertEqual(
            class_counts,
            {"hash_message": 1, "prf": 1248, "thash_f": 510, "thash_h": 76},
        )
        self.assertEqual(self.result.counters["dynamic_instructions"], 2826)
        self.assertEqual(self.result.counters["hash_calls"], 1835)
        self.assertEqual(self.result.counters["keccak_permutations"], 1836)
        self.assertEqual(self.result.counters["accepted_job_commands"], 1)
        self.assertEqual(self.result.counters["host_control_writes_during_busy"], 0)
        self.assertEqual(self.result.counters["external_task_descriptors"], 0)
        self.assertEqual(self.result.counters["external_hash_descriptors"], 0)

        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(
            self.result.counters["dynamic_instructions"],
            manifest["dynamic_instructions"],
        )
        self.assertEqual(self.result.counters["hash_calls"], manifest["shake256_calls"])
        self.assertEqual(
            self.result.counters["keccak_permutations"],
            manifest["keccak_permutations"],
        )
        self.assertEqual(class_counts, manifest["hash_class_counts"])
        self.assertEqual(self.result.hash_trace_sha256, manifest["hash_trace_sha256"])

    def test_one_bit_signature_mutation_reconstructs_a_different_root(self) -> None:
        mutated = bytearray(self.signature)
        bit_offset = 4 + 32
        mutated[bit_offset] ^= 1
        mutated = bytes(mutated)
        difference = int.from_bytes(self.signature, "big") ^ int.from_bytes(mutated, "big")
        self.assertEqual(difference.bit_count(), 1)
        result = MicroInterpreter(self.image, trace_mode="none").execute(
            build_verify_job(self.public_key, self.message, mutated)
        )
        self.assertTrue(result.done)
        self.assertIsNone(result.error)
        self.assertNotEqual(result.output, self.public_key[:32])
        self.assertFalse(xmss_verify(self.public_key, self.message, mutated))

    def test_image_and_manifest_are_frozen_and_algorithm_agnostic(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(
            hashlib.sha256(PROGRAM.read_bytes()).hexdigest(), manifest["source_sha256"]
        )
        self.assertEqual(self.image["sha256"], manifest["program_sha256"])
        self.assertEqual(self.image["word_count"], manifest["static_words"])
        self.assertEqual(self.image["image_bytes"], manifest["static_bytes"])
        verification = MicroInterpreter(self.image).verification
        self.assertEqual(verification["max_loop_depth"], manifest["maximum_loop_depth"])
        self.assertEqual(verification["max_call_depth"], manifest["maximum_call_depth"])
        opcode_names = {instruction.opcode.name for instruction in self.image["instructions"]}
        self.assertNotIn("XMSS", opcode_names)
        self.assertNotIn("VERIFY", opcode_names)


if __name__ == "__main__":
    unittest.main()
