import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from model.microcode_assembler import Opcode, load_and_assemble
from model.rtl_image_export import RtlImageExportError, export_programs


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "manifests/programs/rtl_images_v0.1.0.json"

EXPECTED_IMAGES = {
    "microcode/lms/lmots_public_w4.json": (
        9,
        "7e5e035aa2863601c953fac8afcf6cf67f1e24132f69e400bf378490fd88eb63",
    ),
    "microcode/lms/lms_public_h10_w4.json": (
        13,
        "666f209b192894c3bce29df2cb802e0586a7628df9dcd8425edb66a159df89c0",
    ),
    "microcode/xmss/xmss_shake256_h10_w4_keygen.json": (
        93,
        "3476fabab809518692c924bcb270cc257b25de46fff2f6a0ea2b685774aa0f2e",
    ),
    "microcode/xmss/xmss_shake256_h10_w4_sign.json": (
        114,
        "a1c7a16eea923fc875ff7f25bde49343af6445eac76ab6023d02c83491ac661a",
    ),
    "microcode/xmss/xmss_shake256_h10_w4_verify.json": (
        177,
        "bd9f30f588dd199004dbe78317c956f890cacaf0beb536612932a712edfdfc81",
    ),
    "microcode/slh_dsa/slh_dsa_shake_128f_keygen.json": (
        12,
        "3acd65c14ef1d8fc1b49fb4ca7c4df7b9065dbfb0d6a07b5a88f2a56e04014dc",
    ),
    "microcode/slh_dsa/slh_dsa_shake_128f_sign.json": (
        144,
        "13f881f3d37012faad097fb163935d26c230de930dc1e76229ef42184b37e446",
    ),
}


def _write_program(path: Path, word_count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    program = [{"label": "entry"}]
    program.extend({"op": "NOP"} for _ in range(word_count - 1))
    program.append({"op": "HALT"})
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "micro_isa_version": "0.1",
                "name": f"boundary-{word_count}",
                "entry": "entry",
                "program": program,
            }
        ),
        encoding="utf-8",
    )


class RtlImageExportTests(unittest.TestCase):
    def test_committed_lms_xmss_slh_images_match_words_and_digests(self) -> None:
        manifest = json.loads(CATALOG.read_text(encoding="utf-8"))
        self.assertEqual(manifest["image_count"], len(EXPECTED_IMAGES))
        self.assertEqual(manifest["capacity_words"], 512)
        entries = {entry["source"]: entry for entry in manifest["images"]}
        self.assertEqual(set(entries), set(EXPECTED_IMAGES))
        self.assertEqual(
            {entry["program_family"] for entry in entries.values()},
            {"lms", "xmss", "slh_dsa"},
        )

        for source_name, (expected_words, expected_digest) in EXPECTED_IMAGES.items():
            with self.subTest(source=source_name):
                entry = entries[source_name]
                source = ROOT / source_name
                image = load_and_assemble(source)
                hex_path = ROOT / entry["readmemh"]["path"]
                hex_bytes = hex_path.read_bytes()
                lines = hex_bytes.decode("ascii").splitlines()

                self.assertEqual(entry["word_count"], expected_words)
                self.assertEqual(entry["readmemh"]["line_count"], expected_words)
                self.assertEqual(entry["program_sha256"], expected_digest)
                self.assertEqual(image["sha256"], expected_digest)
                self.assertEqual(
                    entry["source_sha256"],
                    hashlib.sha256(source.read_bytes()).hexdigest(),
                )
                self.assertEqual(
                    entry["readmemh"]["sha256"],
                    hashlib.sha256(hex_bytes).hexdigest(),
                )
                self.assertEqual(lines, [f"{word:016x}" for word in image["words"]])
                self.assertTrue(all(len(line) == 16 for line in lines))
                hash_instructions = [
                    instruction
                    for instruction in image["instructions"]
                    if instruction.opcode == Opcode.HASH_LAYOUT
                ]
                self.assertTrue(hash_instructions)
                self.assertTrue(
                    all(instruction.flags & 0x03 for instruction in hash_instructions)
                )
                reconstructed = b"".join(int(line, 16).to_bytes(8, "big") for line in lines)
                self.assertEqual(hashlib.sha256(reconstructed).hexdigest(), expected_digest)
                self.assertTrue(entry["execution_contract"]["offline_export_only"])
                self.assertFalse(entry["execution_contract"]["runtime_task_ingress"])
                self.assertFalse(entry["execution_contract"]["runtime_hash_ingress"])
                self.assertNotIn("HashFlow", source_name)

    def test_repeated_export_is_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "microcode/lms/example.json"
            source.parent.mkdir(parents=True)
            source.write_bytes(
                (ROOT / "microcode/lms/lmots_public_w4.json").read_bytes()
            )
            output = root / "manifests/programs/rtl_images"
            manifest_path = root / "manifests/programs/images.json"
            export_programs([source], output, manifest_path, root)
            first_manifest = manifest_path.read_bytes()
            first_hex = next(output.glob("*.hex")).read_bytes()
            export_programs([source], output, manifest_path, root)
            self.assertEqual(manifest_path.read_bytes(), first_manifest)
            self.assertEqual(next(output.glob("*.hex")).read_bytes(), first_hex)

    def test_exact_512_word_program_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "microcode/lms/exact_limit.json"
            _write_program(source, 512)
            output = root / "manifests/programs/rtl_images"
            manifest_path = root / "manifests/programs/images.json"
            manifest = export_programs([source], output, manifest_path, root)
            entry = manifest["images"][0]
            self.assertEqual(entry["word_count"], 512)
            self.assertEqual(entry["unused_capacity_words"], 0)
            self.assertEqual(len(next(output.glob("*.hex")).read_text().splitlines()), 512)

    def test_513_word_program_is_rejected_without_partial_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "microcode/slh_dsa/over_limit.json"
            _write_program(source, 513)
            output = root / "manifests/programs/rtl_images"
            manifest_path = root / "manifests/programs/images.json"
            with self.assertRaisesRegex(ValueError, "512-word"):
                export_programs([source], output, manifest_path, root)
            self.assertFalse(output.exists())
            self.assertFalse(manifest_path.exists())

    def test_configured_capacity_below_program_size_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "microcode/xmss/example.json"
            source.parent.mkdir(parents=True)
            source.write_bytes(
                (ROOT / "microcode/xmss/xmss_shake256_h10_w4_keygen.json").read_bytes()
            )
            with self.assertRaisesRegex(RtlImageExportError, "exceeds configured"):
                export_programs(
                    [source],
                    root / "manifests/programs/rtl_images",
                    root / "manifests/programs/images.json",
                    root,
                    capacity_words=92,
                )


if __name__ == "__main__":
    unittest.main()
