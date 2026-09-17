import json
from pathlib import Path
import unittest

from model.microcode_assembler.isa import Opcode
from scripts.report_microcode_isa_usage import PROGRAMS, build_report


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "manifests/experiments/microcode_isa_usage_v0.2.0.json"


class MicrocodeIsaUsageTests(unittest.TestCase):
    def test_all_nine_operations_have_compiled_programs(self) -> None:
        report = build_report()
        self.assertEqual(len(PROGRAMS), 9)
        self.assertEqual(set(report["programs"]), set(PROGRAMS))
        self.assertEqual(report["isa_opcode_count"], 12)
        self.assertEqual(set(report["static_usage_matrix"]), {op.name for op in Opcode})

    def test_frozen_report_is_current(self) -> None:
        self.assertEqual(json.loads(MANIFEST.read_text()), build_report())


if __name__ == "__main__":
    unittest.main()
