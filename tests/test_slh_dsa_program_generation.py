import json
from pathlib import Path
import unittest

from scripts.generate_slh_dsa_sign_microcode import build_document


ROOT = Path(__file__).resolve().parents[1]
PROGRAM = ROOT / "microcode" / "slh_dsa" / "slh_dsa_shake_128f_sign.json"


class SlhDsaProgramGenerationTests(unittest.TestCase):
    def test_checked_in_sign_program_matches_generator(self) -> None:
        self.assertEqual(
            json.loads(PROGRAM.read_text(encoding="utf-8")),
            build_document(),
        )


if __name__ == "__main__":
    unittest.main()
