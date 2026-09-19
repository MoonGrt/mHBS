import unittest
from pathlib import Path

from model.unified_hbs_execution import OPERATIONS, validate_all, validate_rom


ROOT = Path(__file__).resolve().parents[1]


class UnifiedHbsExecutionTests(unittest.TestCase):
    def test_six_operations_meet_cycle_gates(self):
        results = validate_all()
        self.assertEqual(set(results), set(OPERATIONS))
        self.assertEqual(results["slh.sign"].permutations, 105_641)
        self.assertEqual(results["xmss.keygen"].contexts, 3_430_396)
        self.assertEqual(results["lms.keygen"].permutations, 1_116_159)

    def test_two_lanes_are_balanced(self):
        for result in validate_all().values():
            largest_job = max(
                batch.permutations_per_job for batch in OPERATIONS[result.name].batches
            ) * 12
            self.assertLessEqual(
                abs(result.lane_cycles[0] - result.lane_cycles[1]), largest_job
            )

    def test_product_rom_bounds_and_directory(self):
        used, capacity = validate_rom(
            ROOT / "rtl/microcode/unified_hbs_product_rom.mem")
        self.assertEqual(used, 203)
        self.assertEqual(capacity, 256)


if __name__ == "__main__":
    unittest.main()
