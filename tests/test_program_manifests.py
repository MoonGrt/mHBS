import hashlib
import json
from pathlib import Path
import unittest

from model.microcode_assembler import load_and_assemble


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = (
    ROOT / "manifests/programs/xmss_shake256_h10_w4_keygen_v0.1.0.json",
    ROOT / "manifests/programs/xmss_shake256_h10_w4_sign_v0.1.0.json",
    ROOT / "manifests/programs/slh_dsa_shake_128f_keygen_v0.1.0.json",
    ROOT / "manifests/programs/slh_dsa_shake_128f_sign_v0.1.0.json",
)


class ProgramManifestTests(unittest.TestCase):
    def test_program_manifests_bind_exact_sources_and_images(self) -> None:
        for manifest_path in MANIFESTS:
            with self.subTest(manifest=manifest_path.name):
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                source = ROOT / manifest["source"]
                image = load_and_assemble(source)
                self.assertEqual(
                    hashlib.sha256(source.read_bytes()).hexdigest(),
                    manifest["source_sha256"],
                )
                self.assertEqual(image["sha256"], manifest["program_sha256"])
                self.assertEqual(image["word_count"], manifest["static_words"])
                self.assertEqual(image["image_bytes"], manifest["static_bytes"])


if __name__ == "__main__":
    unittest.main()
