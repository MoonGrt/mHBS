import unittest

from model.cycle_model import ShakeTraceMeter, build_current_u2_report


class SlhDsaCycleModelTests(unittest.TestCase):
    def test_keygen_accounting_matches_frozen_complete_trace(self) -> None:
        meter = ShakeTraceMeter()
        for _ in range(4487):
            meter.observe("one_block", bytes(64), bytes(16))
        # The 8 WOTS public-key compressions use five absorb blocks rather
        # than one, adding 32 permutations to the 4,495 Hash calls.
        for _ in range(8):
            meter.observe("extra_blocks", bytes(608), bytes(16))
        report = build_current_u2_report(
            operation="Keygen",
            dynamic_instructions=9275,
            operation_output_bytes=16,
            meter=meter,
        )
        self.assertEqual(report["measured_trace"]["hash_calls"], 4495)
        self.assertFalse(report["complete_rtl_cycle_count"])
        self.assertTrue(report["accounted_cycles_are_lower_bound"])
        self.assertEqual(report["measured_trace"]["keccak_permutations"], 4527)
        self.assertEqual(report["cycle_breakdown"]["accounted_cycles"], 86461)
        self.assertEqual(
            report["cycle_breakdown"]["ideal_p2_u2_keccak_round_floor_cycles"],
            27168,
        )

    def test_sign_accounting_matches_frozen_complete_trace(self) -> None:
        meter = ShakeTraceMeter()
        for _ in range(104761):
            meter.observe("one_block", bytes(64), bytes(16))
        for _ in range(176):
            meter.observe("t_l", bytes(608), bytes(16))
        report = build_current_u2_report(
            operation="Sign",
            dynamic_instructions=221811,
            operation_output_bytes=17088,
            meter=meter,
        )
        self.assertEqual(report["measured_trace"]["hash_calls"], 104937)
        self.assertEqual(report["measured_trace"]["keccak_permutations"], 105641)
        self.assertEqual(report["cycle_breakdown"]["accounted_cycles"], 2034645)
        self.assertAlmostEqual(
            report["cycle_breakdown"]["accounted_latency_ms_at_frequency"],
            20.34645,
        )
        self.assertEqual(
            report["cycle_breakdown"]["ideal_p2_u2_keccak_round_floor_cycles"],
            633852,
        )


if __name__ == "__main__":
    unittest.main()
