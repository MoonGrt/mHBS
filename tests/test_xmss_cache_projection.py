import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "manifests" / "experiments" / "xmss_cache_sign_projection_v0.1.0.json"


class XmssCacheProjectionTests(unittest.TestCase):
    def test_projection_is_reproducible_and_bounded(self) -> None:
        subprocess.run(
            [sys.executable, "experiments/project_xmss_cache_sign.py"],
            cwd=ROOT,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        result = json.loads(MANIFEST.read_text(encoding="utf-8"))
        points = result["points"]
        self.assertEqual(result["assumptions"]["wots_leaf_shake_calls"], 3346)
        self.assertEqual(result["assumptions"]["sign_core_shake_calls"], 1554)
        self.assertEqual(points["FULL_CACHE_OR_WARM_ACTIVE_SUBTREE"]["ideal_p2_u2_cycles"], 9336)
        self.assertEqual(points["SUBTREE_UPPER_ONLY_COLD"]["shake256_calls"], 51788)
        self.assertEqual(points["SUBTREE_UPPER_ONLY_COLD"]["ideal_p2_u2_cycles"], 310740)
        self.assertEqual(points["TREEHASH_MIN"]["ideal_p2_u2_cycles"], 20591712)
        self.assertFalse(result["paper_comparable"])


if __name__ == "__main__":
    unittest.main()
