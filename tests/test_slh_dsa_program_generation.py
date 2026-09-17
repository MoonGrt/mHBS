import json
from pathlib import Path
import unittest

from scripts.generate_slh_dsa_sign_microcode import build_document as build_sign_document
from scripts.generate_slh_dsa_verify_microcode import build_document as build_verify_document


ROOT = Path(__file__).resolve().parents[1]
PROGRAM = ROOT / "microcode" / "slh_dsa" / "slh_dsa_shake_128f_sign.json"
VERIFY_PROGRAM = ROOT / "microcode" / "slh_dsa" / "slh_dsa_shake_128f_verify.json"


class SlhDsaProgramGenerationTests(unittest.TestCase):
    def test_checked_in_sign_program_matches_generator(self) -> None:
        self.assertEqual(
            json.loads(PROGRAM.read_text(encoding="utf-8")),
            build_sign_document(),
        )

    def test_checked_in_verify_program_matches_generator(self) -> None:
        self.assertEqual(
            json.loads(VERIFY_PROGRAM.read_text(encoding="utf-8")),
            build_verify_document(),
        )


if __name__ == "__main__":
    unittest.main()
