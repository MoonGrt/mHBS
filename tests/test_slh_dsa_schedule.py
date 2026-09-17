import json
from pathlib import Path
import unittest

from model.microcode_assembler import load_and_assemble
from model.interpreter import MicroInterpreter
from model.microcode_frequency import profile_microcode
from model.reference.slh_dsa import SLH_DSA_SHAKE_128F, sign_internal
from model.slh_dsa_schedule import (
    ScheduleConfig,
    build_keygen_graph,
    build_sign_graph,
    build_verify_graph,
    schedule_graph,
)


ROOT = Path(__file__).resolve().parents[1]
SIGN_KAT = ROOT / "tests/kat/slh_dsa_shake_128f_siggen_acvp_tc137.json"
SIGN_PROGRAM = ROOT / "microcode/slh_dsa/slh_dsa_shake_128f_sign.json"


class SlhDsaScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.vector = json.loads(SIGN_KAT.read_text(encoding="utf-8"))
        cls.message = bytes.fromhex(cls.vector["message"])
        cls.secret_key = bytes.fromhex(cls.vector["sk"])
        cls.public_key = bytes.fromhex(cls.vector["pk"])
        cls.signature = sign_internal(
            SLH_DSA_SHAKE_128F, cls.message, cls.secret_key
        )
        cls.keygen = build_keygen_graph()
        cls.sign = build_sign_graph(cls.message, cls.secret_key)
        cls.verify = build_verify_graph(
            cls.message, cls.signature, cls.public_key
        )

    def test_complete_graphs_match_reference_workloads(self) -> None:
        self.assertEqual(
            self.keygen.hash_class_counts(),
            {"f": 4200, "h": 7, "prf": 280, "t_l": 8},
        )
        self.assertEqual(len(self.keygen.tasks), 4495)
        self.assertEqual(self.keygen.permutation_count, 4527)
        self.assertEqual(
            self.sign.hash_class_counts(),
            {
                "f": 94257,
                "h": 2230,
                "h_msg": 1,
                "prf": 8272,
                "prf_msg": 1,
                "t_l": 176,
            },
        )
        self.assertEqual(len(self.sign.tasks), 104937)
        self.assertEqual(self.sign.permutation_count, 105641)
        self.assertEqual(
            self.verify.hash_class_counts(),
            {"f": 6153, "h": 264, "h_msg": 1, "t_l": 23},
        )
        self.assertEqual(len(self.verify.tasks), 6441)
        self.assertEqual(self.verify.permutation_count, 6533)

    def test_sign_signature_producer_map_is_exact(self) -> None:
        self.sign.validate_signature_map()
        producers = [
            task for task in self.sign.tasks if task.signature_offset is not None
        ]
        self.assertEqual(len(producers), 1068)
        self.assertEqual(sum(task.signature_bytes for task in producers), 17088)
        self.assertEqual(
            sorted(task.signature_offset for task in producers),
            list(range(0, 17088, 16)),
        )

    def test_kxu_scheduler_is_dependency_safe_and_deterministic(self) -> None:
        result = schedule_graph(
            self.sign,
            ScheduleConfig(lanes=2, unroll=2, issue_width=1),
        )
        self.assertEqual(result.hash_cycles, 791272)
        self.assertEqual(result.completion_cycles, 791274)
        self.assertEqual(result.active_lane_cycles, 1582503)
        self.assertGreater(result.lane_utilization, 0.999)
        for task in self.sign.tasks:
            self.assertTrue(
                all(
                    result.task_finish[parent]
                    <= result.task_start[task.task_id]
                    for parent in task.dependencies
                )
            )

    def test_k_and_u_each_reduce_sign_latency(self) -> None:
        k1u1 = schedule_graph(self.sign, ScheduleConfig(1, 1))
        k1u2 = schedule_graph(self.sign, ScheduleConfig(1, 2))
        k2u1 = schedule_graph(self.sign, ScheduleConfig(2, 1))
        k2u2 = schedule_graph(self.sign, ScheduleConfig(2, 2))
        self.assertLess(k1u2.completion_cycles, k1u1.completion_cycles)
        self.assertLess(k2u1.completion_cycles, k1u1.completion_cycles)
        self.assertLess(k2u2.completion_cycles, k1u2.completion_cycles)
        self.assertLess(k2u2.completion_cycles, k2u1.completion_cycles)

    def test_fifo_policy_nearly_matches_critical_with_small_output_reorder(self) -> None:
        result = schedule_graph(
            self.sign,
            ScheduleConfig(lanes=2, unroll=2, issue_width=1, policy="fifo"),
        )
        self.assertEqual(result.completion_cycles, 791286)
        self.assertLessEqual(result.maximum_signature_reorder_bytes, 96)

    def test_existing_sign_microcode_frequency(self) -> None:
        image = load_and_assemble(SIGN_PROGRAM)
        job = {
            "sk_seed": self.secret_key[:16],
            "sk_prf": self.secret_key[16:32],
            "pub_seed": self.secret_key[32:48],
            "root": self.secret_key[48:64],
            "message": self.message,
        }
        execution = MicroInterpreter(image, trace_mode="full").execute(job)
        profile = profile_microcode(image, execution)
        self.assertEqual(profile["static_words"], 165)
        self.assertEqual(profile["dynamic_instructions"], 29432)
        self.assertEqual(profile["dynamic_opcode_counts"]["HASH"], 11268)
        self.assertEqual(profile["dynamic_opcode_counts"]["TREE_PUSH"], 2178)
        self.assertEqual(profile["hash_calls"], 104937)
        self.assertEqual(profile["keccak_permutations"], 105641)
        self.assertEqual(profile["emit_bytes"], 17088)
        fixed = profile["fixed_hash_granularity_schedule"]
        self.assertEqual(fixed["pair_instructions"], 47600)
        self.assertEqual(fixed["lane_permutations"], [56072, 49569])
        self.assertEqual(fixed["hash_cycles"], 696492)
        self.assertAlmostEqual(fixed["lane_utilization"], 0.9101, places=3)


if __name__ == "__main__":
    unittest.main()
