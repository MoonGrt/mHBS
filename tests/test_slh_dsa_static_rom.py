import hashlib
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "manifests/programs/slh_dsa_shake_128f_static_rom_v0.1.0.json"
TOP = ROOT / "rtl/top/micro_hbs_slh_dsa_static_top.sv"


class SlhDsaStaticRomTests(unittest.TestCase):
    def test_images_and_integrity_fold_match_manifest(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        folded = 0
        for image in manifest["images"]:
            path = ROOT / image["path"]
            payload = path.read_bytes()
            self.assertEqual(hashlib.sha256(payload).hexdigest(), image["sha256"])
            words = [int(line, 16) for line in payload.decode("ascii").splitlines()]
            self.assertEqual(len(words), image["words"])
            self.assertTrue(all(word.bit_length() <= image["width"] for word in words))
            for word in words:
                for offset in range(0, image["width"], 64):
                    folded ^= (word >> offset) & ((1 << 64) - 1)
        self.assertEqual(f"{folded:016x}", manifest["image_integrity"]["expected"])

    def test_product_port_list_has_no_configuration_surface(self) -> None:
        source = TOP.read_text(encoding="utf-8")
        header = re.search(
            r"module\s+micro_hbs_slh_dsa_static_top\b.*?\)\s*\(",
            source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(header)
        port_end = source.find(");", header.end())
        ports = source[header.end():port_end]
        self.assertNotIn("_cfg_", ports)
        self.assertNotIn("program_we", ports)
        self.assertNotIn("job_entry", ports)


if __name__ == "__main__":
    unittest.main()
