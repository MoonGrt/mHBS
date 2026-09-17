import json
from pathlib import Path
import unittest

from model.interpreter import MicroInterpreter
from model.microcode_assembler import load_and_assemble
from model.microcode_hash_schedule import extract_hash_tasks, schedule_hash_tasks
from model.reference.slh_dsa import SLH_DSA_SHAKE_128F, sign_internal


ROOT = Path(__file__).resolve().parents[1]
SIGN_KAT = ROOT / "tests/kat/slh_dsa_shake_128f_siggen_acvp_tc137.json"
KEYGEN_KAT = ROOT / "tests/kat/slh_dsa_shake_128f_keygen_acvp_tc31.json"
MANIFEST = (
    ROOT
    / "manifests/experiments/slh_dsa_microcode_hash_schedule_v0.1.0.json"
)


class MicrocodeHashScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        vector = json.loads(SIGN_KAT.read_text(encoding="utf-8"))
        key_vector = json.loads(KEYGEN_KAT.read_text(encoding="utf-8"))
        secret_key = bytes.fromhex(vector["sk"])
        public_key = bytes.fromhex(vector["pk"])
        message = bytes.fromhex(vector["message"])
        signature = sign_internal(SLH_DSA_SHAKE_128F, message, secret_key)
        programs = {
            "keygen": (
                ROOT / "microcode/slh_dsa/slh_dsa_shake_128f_keygen.json",
                {
                    "sk_seed": bytes.fromhex(key_vector["sk_seed"]),
                    "sk_prf": bytes.fromhex(key_vector["sk_prf"]),
                    "pub_seed": bytes.fromhex(key_vector["pk_seed"]),
                },
            ),
            "sign": (
                ROOT / "microcode/slh_dsa/slh_dsa_shake_128f_sign.json",
                {
                    "sk_seed": secret_key[:16],
                    "sk_prf": secret_key[16:32],
                    "pub_seed": secret_key[32:48],
                    "root": secret_key[48:64],
                    "message": message,
                },
            ),
            "verify": (
                ROOT / "microcode/slh_dsa/slh_dsa_shake_128f_verify.json",
                {
                    "signature": signature,
                    "pub_seed": public_key[:16],
                    "public_root": public_key[16:],
                    "message": message,
                },
            ),
        }
        cls.tasks = {}
        cls.executions = {}
        for operation, (path, job) in programs.items():
            result = MicroInterpreter(
                load_and_assemble(path), trace_mode="full"
            ).execute(job)
            if not result.done:
                raise RuntimeError(result.error)
            cls.executions[operation] = result
            cls.tasks[operation] = extract_hash_tasks(result)

    def test_trace_exactly_preserves_interpreter_hash_work(self) -> None:
        expected = {
            "keygen": (4495, 4527),
            "sign": (104937, 105641),
            "verify": (6441, 6533),
        }
        for operation, (hashes, permutations) in expected.items():
            tasks = self.tasks[operation]
            self.assertEqual(len(tasks), hashes)
            self.assertEqual(sum(task.permutations for task in tasks), permutations)
            self.assertEqual(
                len(tasks), self.executions[operation].counters["hash_calls"]
            )

    def test_dependencies_come_from_generic_microcode_trace(self) -> None:
        for operation, tasks in self.tasks.items():
            with self.subTest(operation=operation):
                self.assertTrue(
                    all(
                        dependency < task.task_id
                        for task in tasks
                        for dependency in task.dependencies
                    )
                )
                self.assertTrue(
                    all(
                        task.source_opcode in {"HASH", "TREE_PUSH"}
                        for task in tasks
                    )
                )

    def test_generic_fifo_window16_schedule(self) -> None:
        expected_pure = {"keygen": 27263, "sign": 633900, "verify": 40740}
        expected_wrapper3 = {"keygen": 34017, "sign": 791310, "verify": 50646}
        for operation, cycles in expected_pure.items():
            pure = schedule_hash_tasks(
                self.tasks[operation], policy="window_fifo", window_entries=16
            )
            wrapped = schedule_hash_tasks(
                self.tasks[operation],
                policy="window_fifo",
                window_entries=16,
                hash_overhead_cycles=3,
            )
            self.assertEqual(pure.hash_cycles, cycles)
            self.assertEqual(wrapped.hash_cycles, expected_wrapper3[operation])
            self.assertLessEqual(pure.maximum_window_occupancy, 16)
            self.assertLessEqual(pure.maximum_request_fifo_depth, 4)

    def test_window_improves_over_strict_program_order(self) -> None:
        expected_program_order = {
            "keygen": 51065,
            "sign": 668802,
            "verify": 70815,
        }
        for operation, cycles in expected_program_order.items():
            strict = schedule_hash_tasks(
                self.tasks[operation],
                policy="program_order",
                window_entries=1,
            )
            optimized = schedule_hash_tasks(
                self.tasks[operation], policy="window_fifo", window_entries=16
            )
            self.assertEqual(strict.hash_cycles, cycles)
            self.assertLess(optimized.hash_cycles, strict.hash_cycles)

    def test_manifest_is_reproducible(self) -> None:
        from scripts.simulate_microcode_hash_schedule import build_report

        self.assertEqual(json.loads(MANIFEST.read_text()), build_report())


if __name__ == "__main__":
    unittest.main()
