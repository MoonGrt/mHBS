import unittest

from scripts.parse_slh_dsa_rtl_profile import parse_profile


CURRENT_PROFILE = """\
PROFILE sequencer idle=23 fetch=221811 run=221811 hash_req=102968 hash_wait=5609510 bound_wait=3010 data_req=5542 data_wait=62250 tree_req=2178 tree_wait=54329
PROFILE composer idle=776890 layout_wait=102968 layout_product=102968 layout_validate=102968 hash_start=102968 contig_prep=0 contig_req=0 contig_wait=0 comp_req=102968 comp_wait=102968 comp_product=102968 comp_validate=835169 src_a_req=310222 src_a_wait=630294 src_b_req=0 src_b_wait=0 emit_word=1155945 block_send=103677 digest_wait=1544520 write_req=205939 prefetch_wait=0
PROFILE prefetch hits=732201 bubble_entries=0 bubble_cycles=0 validation_stalls=0
PASS no-DMA complete SLH-DSA Sign cycles=6283432 hash=102968+1969 tree=2178 data=5542 inst=221811 scratch=630294/205939 blocks=103672+1969 components=835169
"""


class SlhDsaRtlProfileTests(unittest.TestCase):
    def test_current_rate_wide_profile_is_partitioned_exactly(self) -> None:
        parsed = parse_profile(CURRENT_PROFILE)
        self.assertEqual(parsed["result"]["cycles"], 6_283_432)
        self.assertEqual(parsed["result"]["hash"], [102_968, 1_969])
        self.assertEqual(parsed["derived"]["partition_sum"], 6_283_432)
        self.assertEqual(
            parsed["derived"]["composer_partition"]["component_control"],
            1_144_073,
        )
        self.assertEqual(
            parsed["derived"]["sequencer_fetch_and_run"], 443_622
        )

    def test_missing_pass_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "PASS line"):
            parse_profile(CURRENT_PROFILE.split("PASS", 1)[0])

    def test_non_exhaustive_partition_is_rejected(self) -> None:
        broken = CURRENT_PROFILE.replace("idle=776890", "idle=776889", 1)
        with self.assertRaisesRegex(ValueError, "does not equal"):
            parse_profile(broken)


if __name__ == "__main__":
    unittest.main()
