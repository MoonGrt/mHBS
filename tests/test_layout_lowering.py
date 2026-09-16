import json
import hashlib
from pathlib import Path
import unittest

from model.interpreter import MicroInterpreter
from model.layout_lowering import (
    COMP_AFFINE_BE32,
    COMP_LITERAL_BE,
    COMP_REGISTER_BE32,
    COMP_SCRATCH,
    COMP_SCRATCH_XOR,
    COMP_ZERO,
    COMP_SHIFTED_AFFINE_BE32,
    COMP_SELECT_SCRATCH,
    LayoutLoweringError,
    decode_component_word,
    decode_layout_descriptor,
    lower_layouts,
)
from model.microcode_assembler.assembler import assemble_document


ROOT = Path(__file__).resolve().parents[1]
XMSS_KEYGEN = ROOT / "microcode/xmss/xmss_shake256_h10_w4_keygen.json"
XMSS_SIGN = ROOT / "microcode/xmss/xmss_shake256_h10_w4_sign.json"
XMSS_KAT = ROOT / "tests/kat/xmss_shake256_10_256_idx5.json"
XMSS_LAYOUT_MANIFEST = (
    ROOT / "manifests/programs/xmss_sign_layout_image_v0.1.0.json"
)
SLH_SIGN = ROOT / "microcode/slh_dsa/slh_dsa_shake_128f_sign.json"


class LayoutLoweringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = json.loads(XMSS_KEYGEN.read_text(encoding="utf-8"))
        cls.job_slots = {"sk_seed": 248, "pub_seed": 249}
        cls.result = lower_layouts(
            cls.document, range(8), job_field_slots=cls.job_slots
        )

    def test_xmss_hash_layouts_lower_to_versioned_component_image(self) -> None:
        self.assertEqual(len(self.result.layouts), 8)
        self.assertEqual(
            [item.message_bytes for item in self.result.layouts],
            [128, 96, 96, 96, 96, 96, 96, 128],
        )
        self.assertEqual(len(self.result.sha256), 64)
        for item in self.result.layouts:
            fields = decode_layout_descriptor(item.descriptor)
            self.assertEqual(fields["format_version"], 1)
            self.assertEqual(fields["capability"], 1)
            self.assertEqual(fields["input_mode"], 2)
            self.assertEqual(fields["component_pc"], item.component_pc)
            self.assertEqual(fields["component_count"], item.component_count)
            self.assertEqual(fields["source_count"], item.component_count)
        kinds = {decode_component_word(word)["kind"]
                 for word in self.result.components}
        self.assertEqual(
            kinds,
            {COMP_LITERAL_BE, COMP_ZERO, COMP_REGISTER_BE32,
             COMP_SCRATCH, COMP_SCRATCH_XOR},
        )

    @staticmethod
    def _slot(fields: dict[str, int], prefix: str,
              regs: list[int]) -> int:
        flags = fields["flags"]
        flag_base = 0 if prefix == "a" else 2
        value = fields[f"{prefix}_base"]
        if flags & (1 << flag_base):
            value += regs[fields[f"{prefix}_reg0"]] * fields[f"{prefix}_scale0"]
        if flags & (1 << (flag_base + 1)):
            value += regs[fields[f"{prefix}_reg1"]] * fields[f"{prefix}_scale1"]
        return value

    def _rtl_compose(self, layout_index: int, regs: list[int],
                     scratch: bytes) -> bytes:
        layout = self.result.layouts[layout_index]
        output = bytearray()
        for word in self.result.components[
            layout.component_pc:layout.component_pc + layout.component_count
        ]:
            fields = decode_component_word(word)
            count = fields["byte_count"]
            kind = fields["kind"]
            if kind == COMP_LITERAL_BE:
                output.extend(fields["immediate"].to_bytes(4, "big")[-count:])
            elif kind == COMP_ZERO:
                output.extend(bytes(count))
            elif kind == COMP_REGISTER_BE32:
                output.extend(regs[fields["immediate"] & 7].to_bytes(4, "big"))
            elif kind in {COMP_SCRATCH, COMP_SCRATCH_XOR}:
                a = self._slot(fields, "a", regs) * 32
                value = scratch[a:a+count]
                if kind == COMP_SCRATCH_XOR:
                    b = self._slot(fields, "b", regs) * 32
                    right = scratch[b:b+count]
                    value = bytes(x ^ y for x, y in zip(value, right, strict=True))
                output.extend(value)
            else:
                self.fail(f"unexpected kind {kind}")
        return bytes(output)

    def test_lowered_xmss_messages_equal_json_interpreter(self) -> None:
        image = assemble_document(self.document)
        interpreter = MicroInterpreter(image, trace_mode="none")
        interpreter.pc = 0
        regs = [1, 2, 3, 1, 4, 10, 20, 0]
        job = {
            "sk_seed": bytes(range(0x10, 0x30)),
            "pub_seed": bytes(range(0x40, 0x60)),
        }
        memory = {
            slot: bytes(((slot * 17 + index) & 0xFF) for index in range(32))
            for slot in range(256)
        }
        scratch = bytearray(256 * 32)
        for slot, value in memory.items():
            scratch[slot*32:(slot+1)*32] = value
        for field, slot in self.job_slots.items():
            scratch[slot*32:(slot+1)*32] = job[field]

        for layout_id in range(8):
            with self.subTest(layout_id=layout_id):
                expected = interpreter._compose(
                    self.document["layouts"][str(layout_id)],
                    job, regs, memory,
                )
                self.assertEqual(
                    self._rtl_compose(layout_id, regs, bytes(scratch)),
                    expected,
                )

    def test_variable_job_field_requires_frozen_length(self) -> None:
        document = {
            "layouts": {"0": {
                "hash": "shake256", "output_bytes": 32,
                "destination": {"base": 0},
                "components": [{"kind": "job_bytes", "field": "message"}],
            }}
        }
        with self.assertRaisesRegex(LayoutLoweringError, "missing byte length"):
            lower_layouts(document, [0], job_field_slots={"message": 1})

    def test_slh_16_byte_slots_split_long_job_message_offline(self) -> None:
        document = {
            "layouts": {"0": {
                "hash": "shake256", "output_bytes": 16,
                "max_input_bytes": 1024,
                "destination": {"base": 7},
                "components": [{"kind": "job_bytes", "field": "message"}],
            }}
        }
        result = lower_layouts(
            document, [0], slot_bytes=16,
            job_field_slots={"message": 300},
            job_field_lengths={"message": 1000},
        )
        self.assertEqual(result.layouts[0].message_bytes, 1000)
        self.assertEqual(result.layouts[0].component_count, 5)
        decoded = [decode_component_word(word) for word in result.components]
        self.assertEqual([item["byte_count"] for item in decoded],
                         [240, 240, 240, 240, 40])
        self.assertEqual([item["a_base"] for item in decoded],
                         [300, 315, 330, 345, 360])

    def test_slh_memory_length_table_preserves_digest_width(self) -> None:
        document = {
            "layouts": {"0": {
                "hash": "shake256", "output_bytes": 16,
                "destination": {"base": 4},
                "components": [{"kind": "memory", "base": 231}],
            }}
        }
        result = lower_layouts(
            document, [0], slot_bytes=16, job_field_slots={},
            memory_lengths={231: 34},
        )
        self.assertEqual(result.layouts[0].message_bytes, 34)
        self.assertEqual(
            decode_component_word(result.components[0])["byte_count"], 34
        )

    def test_slh_word_expression_lowers_to_affine_component(self) -> None:
        document = {"layouts": {"2": {
            "hash": "shake256", "output_bytes": 16,
            "destination": {"base": 0},
            "components": [{"kind": "word_array", "words": [{
                "kind": "expr", "expression": {"op": "add", "args": [
                    {"op": "mul", "args": [
                        {"kind": "reg", "reg": 0},
                        {"kind": "literal_int", "value": 64},
                    ]},
                    {"kind": "reg", "reg": 1},
                ]},
            }]}],
        }}}
        result = lower_layouts(document, [2], slot_bytes=16,
                               job_field_slots={})
        component = decode_component_word(result.components[0])
        self.assertEqual(component["kind"], COMP_AFFINE_BE32)
        self.assertEqual(component["byte_count"], 4)
        self.assertEqual(component["flags"], 3)
        self.assertEqual(
            component["a_base"]
            + 38 * component["a_scale0"]
            + 7 * component["a_scale1"],
            38 * 64 + 7,
        )

    def test_slh_fors_recovery_lowers_without_algorithm_opcode(self) -> None:
        document = json.loads(SLH_SIGN.read_text(encoding="utf-8"))
        result = lower_layouts(
            document, [10, 11, 12], slot_bytes=16,
            job_field_slots={"pub_seed": 258},
            memory_lengths={232: 12},
        )
        self.assertEqual(
            [(item.layout_id, item.message_bytes) for item in result.layouts],
            [(10, 64), (11, 80), (12, 576)],
        )
        kinds = [decode_component_word(word)["kind"]
                 for word in result.components]
        self.assertIn(COMP_SHIFTED_AFFINE_BE32, kinds)
        self.assertEqual(kinds.count(COMP_SELECT_SCRATCH), 2)
        range_layout = result.layouts[2]
        self.assertEqual(range_layout.component_count, 11)

    def test_static_slot_relocation_is_applied_to_sources_and_destinations(self) -> None:
        document = {
            "layouts": {
                "0": {
                    "hash": "shake256", "output_bytes": 34,
                    "destination": {"base": 231},
                    "components": [{"kind": "memory", "base": 231}],
                }
            }
        }
        result = lower_layouts(
            document, [0], slot_bytes=16, job_field_slots={},
            memory_lengths={231: 34}, memory_slot_map={231: 240},
        )
        descriptor = decode_layout_descriptor(result.layouts[0].descriptor)
        component = decode_component_word(result.components[0])
        self.assertEqual(descriptor["destination"] >> 24, 240)
        self.assertEqual(component["a_base"], 240)

    def test_committed_xmss_sign_layout_image_is_deterministic(self) -> None:
        manifest = json.loads(XMSS_LAYOUT_MANIFEST.read_text(encoding="utf-8"))
        document = json.loads(XMSS_SIGN.read_text(encoding="utf-8"))
        vector = json.loads(XMSS_KAT.read_text(encoding="utf-8"))
        result = lower_layouts(
            document, manifest["layout_ids"],
            job_field_slots=manifest["job_field_slots"],
            job_field_lengths={
                "message": len(bytes.fromhex(vector["message"]))
            },
        )
        layout_path = ROOT / manifest["layout_hex"]["path"]
        component_path = ROOT / manifest["component_hex"]["path"]
        self.assertEqual(layout_path.read_text(encoding="ascii"), result.layout_hex())
        self.assertEqual(
            component_path.read_text(encoding="ascii"), result.component_hex()
        )
        self.assertEqual(manifest["image_sha256"], result.sha256)
        self.assertEqual(
            manifest["layout_hex"]["sha256"],
            hashlib.sha256(layout_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            manifest["component_hex"]["sha256"],
            hashlib.sha256(component_path.read_bytes()).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
