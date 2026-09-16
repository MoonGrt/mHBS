import hashlib
from pathlib import Path
import unittest

from model.interpreter import MicroInterpreter
from model.microcode_assembler import Instruction, Opcode, load_and_assemble
from model.microcode_assembler.assembler import AssemblyError, assemble_document
from model.microcode_verifier import VerificationError, verify_image
from model.reference.lms import RFC8554_TEST2, lmots_public_key


ROOT = Path(__file__).resolve().parents[1]
PROGRAM = ROOT / "microcode/lms/lmots_public_w4.json"
XMSS_KEYGEN_PROGRAM = ROOT / "microcode/xmss/xmss_shake256_h10_w4_keygen.json"
XMSS_SIGN_PROGRAM = ROOT / "microcode/xmss/xmss_shake256_h10_w4_sign.json"
SLH_SIGN_PROGRAM = ROOT / "microcode/slh_dsa/slh_dsa_shake_128f_sign.json"


class MicrocodeTests(unittest.TestCase):
    def test_instruction_round_trip(self) -> None:
        inst = Instruction(Opcode.HASH_LAYOUT, flags=3, rd=7, rs=9, imm=0x12345678)
        self.assertEqual(Instruction.decode(inst.encode()), inst)

    def test_illegal_opcode_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "illegal opcode"):
            Instruction.decode(0xFF00000000000000)

    def test_assembler_rejects_unknown_opcode(self) -> None:
        with self.assertRaises(AssemblyError):
            assemble_document({"program": [{"op": "DO_MAGIC"}]})

    def test_hash_layout_omitted_flags_default_to_lane0(self) -> None:
        image = assemble_document(
            {
                "layouts": {"0": {}},
                "program": [
                    {"label": "entry"},
                    {"op": "HASH_LAYOUT", "imm": 0},
                    {"op": "HALT"},
                ],
            }
        )
        self.assertEqual(image["instructions"][0].flags, 1)
        self.assertEqual(image["words"][0], 0x0301000000000000)
        self.assertTrue(verify_image(image)["verified"])

    def test_hash_layout_explicit_zero_lane_mask_is_rejected(self) -> None:
        image = assemble_document(
            {
                "layouts": {"0": {}},
                "program": [
                    {"label": "entry"},
                    {"op": "HASH_LAYOUT", "flags": 0, "imm": 0},
                    {"op": "HALT"},
                ],
            }
        )
        self.assertEqual(image["instructions"][0].flags, 0)
        with self.assertRaisesRegex(VerificationError, "lane mask must be nonzero"):
            verify_image(image)

    def test_hash_layout_explicit_nonzero_lane_mask_is_preserved(self) -> None:
        image = assemble_document(
            {
                "layouts": {"0": {}},
                "program": [
                    {"label": "entry"},
                    {"op": "HASH_LAYOUT", "flags": 3, "imm": 0},
                    {"op": "HALT"},
                ],
            }
        )
        self.assertEqual(image["instructions"][0].flags, 3)
        self.assertEqual(image["words"][0], 0x0303000000000000)
        self.assertTrue(verify_image(image)["verified"])

    def test_verifier_rejects_opcode_specific_flags(self) -> None:
        for opcode, flags in (("NOP", 1), ("LOOP_SETUP", 2), ("EMIT", 2)):
            with self.subTest(opcode=opcode, flags=flags):
                program = [
                    {"label": "entry"},
                    {"op": opcode, "flags": flags, "imm": 1},
                ]
                if opcode == "LOOP_SETUP":
                    program.append({"op": "LOOP_END"})
                program.append({"op": "HALT"})
                image = assemble_document(
                    {"program": program}
                )
                with self.assertRaisesRegex(VerificationError, "invalid flags"):
                    verify_image(image)

    def test_verifier_rejects_loop_underflow(self) -> None:
        image = assemble_document(
            {"program": [{"label": "entry"}, {"op": "LOOP_END"}, {"op": "HALT"}]}
        )
        with self.assertRaisesRegex(VerificationError, "underflow"):
            verify_image(image)

    def test_verifier_rejects_missing_layout(self) -> None:
        image = assemble_document(
            {"program": [{"label": "entry"}, {"op": "HASH_LAYOUT", "imm": 9}, {"op": "HALT"}]}
        )
        with self.assertRaisesRegex(VerificationError, "undefined layout"):
            verify_image(image)

    def test_verifier_rejects_call_stack_overflow(self) -> None:
        image = assemble_document(
            {
                "program": [
                    {"label": "entry"},
                    {"op": "CALL", "target": "entry"},
                    {"op": "HALT"},
                ]
            }
        )
        with self.assertRaisesRegex(VerificationError, "call depth"):
            verify_image(image)

    def test_runtime_rejects_uninitialized_scratch_read(self) -> None:
        document = {
            "bounds": {"scratch_slots": 2},
            "layouts": {
                "0": {
                    "hash": "sha256",
                    "output_bytes": 32,
                    "destination": {"base": 1},
                    "components": [{"kind": "memory", "base": 0}],
                }
            },
            "program": [
                {"label": "entry"},
                {"op": "HASH_LAYOUT", "imm": 0},
                {"op": "HALT"},
            ],
        }
        result = MicroInterpreter(assemble_document(document)).execute({})
        self.assertFalse(result.done)
        self.assertEqual(result.error, "ERR_UNINITIALIZED_READ")
        self.assertEqual(result.output, b"")

    def test_xor_uses_static_descriptor_and_emits_exact_bytes(self) -> None:
        document = {
            "bounds": {"scratch_slots": 4},
            "loads": {
                "0": {
                    "source": {"kind": "job_bytes", "field": "left", "length": 4},
                    "destination": {"base": 0},
                },
                "1": {
                    "source": {"kind": "job_bytes", "field": "right", "length": 4},
                    "destination": {"base": 1},
                },
            },
            "xors": {
                "0": {
                    "source_a": {"base": 0},
                    "source_b": {"base": 1},
                    "destination": {"base": 2},
                }
            },
            "program": [
                {"label": "entry"},
                {"op": "LOAD", "imm": 0},
                {"op": "LOAD", "imm": 1},
                {"op": "XOR", "imm": 0},
                {"op": "EMIT", "rd": 2},
                {"op": "HALT"},
            ],
        }
        result = MicroInterpreter(assemble_document(document)).execute(
            {"left": bytes.fromhex("00ff55aa"), "right": bytes.fromhex("f00f0ff0")}
        )
        self.assertTrue(result.done)
        self.assertIsNone(result.error)
        self.assertEqual(result.output, bytes.fromhex("f0f05a5a"))
        xor_event = next(event for event in result.trace if event["opcode"] == "XOR")
        self.assertEqual(xor_event["memory_event"], "xor")
        self.assertEqual(xor_event["output_bytes"], 4)

    def test_verifier_rejects_missing_xor_descriptor(self) -> None:
        image = assemble_document(
            {"program": [{"label": "entry"}, {"op": "XOR", "imm": 7}, {"op": "HALT"}]}
        )
        with self.assertRaisesRegex(VerificationError, "undefined XOR descriptor"):
            verify_image(image)

    def test_lmots_interpreter_matches_independent_oracle_trace(self) -> None:
        image = load_and_assemble(PROGRAM)
        verification = verify_image(image)
        self.assertEqual(verification["word_count"], 9)
        self.assertEqual(verification["image_bytes"], 72)
        oracle_trace: list[tuple[str, str, str]] = []

        def observe(kind: str, data: bytes, output: bytes) -> None:
            oracle_trace.append((kind, hashlib.sha256(data).hexdigest(), output.hex()))

        job = {"identifier": RFC8554_TEST2["identifier"], "q": 5, "seed": RFC8554_TEST2["seed"]}
        expected = lmots_public_key(job["identifier"], job["q"], job["seed"], observe=observe)
        result = MicroInterpreter(image).execute(job)
        self.assertTrue(result.done)
        self.assertIsNone(result.error)
        self.assertEqual(result.output, expected)
        self.assertEqual(result.counters["accepted_job_commands"], 1)
        self.assertEqual(result.counters["host_control_writes_during_busy"], 0)
        self.assertEqual(result.counters["external_task_descriptors"], 0)
        self.assertEqual(result.counters["external_hash_descriptors"], 0)
        self.assertEqual(result.counters["hash_calls"], 1073)
        self.assertEqual(result.counters["dynamic_instructions"], 2215)
        model_trace = [
            (event["hash_class"], event["hash_input_digest"], event["hash_output"])
            for event in result.trace
            if event["opcode"] == "HASH_LAYOUT"
        ]
        self.assertEqual(model_trace, oracle_trace)

    def test_bad_job_fails_closed(self) -> None:
        result = MicroInterpreter(load_and_assemble(PROGRAM)).execute(
            {"identifier": b"too short", "q": 0, "seed": bytes(32)}
        )
        self.assertFalse(result.done)
        self.assertEqual(result.error, "ERR_JOB_FIELD_LENGTH")
        self.assertEqual(result.output, b"")
        self.assertEqual(result.memory, {})

    def test_xmss_keygen_image_is_bounded_without_xmss_opcode(self) -> None:
        image = load_and_assemble(XMSS_KEYGEN_PROGRAM)
        verification = verify_image(image)
        self.assertEqual(verification["word_count"], 93)
        self.assertEqual(verification["image_bytes"], 744)
        self.assertEqual(verification["max_loop_depth"], 3)
        self.assertNotIn("XMSS", {instruction.opcode.name for instruction in image["instructions"]})

    def test_xmss_sign_image_is_bounded_without_xmss_opcode(self) -> None:
        image = load_and_assemble(XMSS_SIGN_PROGRAM)
        verification = verify_image(image)
        self.assertEqual(verification["word_count"], 114)
        self.assertEqual(verification["image_bytes"], 912)
        self.assertEqual(verification["max_loop_depth"], 3)
        self.assertNotIn("XMSS", {instruction.opcode.name for instruction in image["instructions"]})

    def test_slh_dsa_sign_image_is_bounded_without_algorithm_opcode(self) -> None:
        image = load_and_assemble(SLH_SIGN_PROGRAM)
        verification = verify_image(image)
        self.assertEqual(verification["word_count"], 144)
        self.assertEqual(verification["image_bytes"], 1152)
        self.assertLessEqual(verification["max_loop_depth"], 4)
        opcode_names = {instruction.opcode.name for instruction in image["instructions"]}
        self.assertNotIn("SLH_DSA", opcode_names)
        self.assertNotIn("FORS", opcode_names)
        self.assertNotIn("XMSS", opcode_names)


if __name__ == "__main__":
    unittest.main()
