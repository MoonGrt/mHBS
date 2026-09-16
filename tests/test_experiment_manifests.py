import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ExperimentManifestTests(unittest.TestCase):
    def test_all_recorded_source_hashes_are_current(self) -> None:
        manifests = sorted((ROOT / "manifests" / "experiments").glob("*.json"))
        self.assertTrue(manifests)
        checked = 0
        for manifest_path in manifests:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for relative_path, expected in manifest.get("source_sha256", {}).items():
                with self.subTest(manifest=manifest_path.name, source=relative_path):
                    source = ROOT / relative_path
                    self.assertTrue(source.is_file())
                    actual = hashlib.sha256(source.read_bytes()).hexdigest()
                    self.assertEqual(actual, expected)
                    checked += 1
        self.assertGreater(checked, 0)


if __name__ == "__main__":
    unittest.main()
