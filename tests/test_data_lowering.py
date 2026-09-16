import json
from pathlib import Path
import unittest

from model.data_lowering import (
    AddressExpression,
    DataLoweringError,
    LogicalDescriptor,
    LogicalObject,
    decode_binding_word,
    decode_descriptor_word,
    descriptor_from_program_move,
    evaluate_physical_address,
    lower_logical_data,
)


ROOT = Path(__file__).resolve().parents[1]


class DataLoweringTests(unittest.TestCase):
    def _static_inputs(self):
        objects = [
            LogicalObject("tail13", 0, bytes(range(13))),
            LogicalObject("mask", 2, bytes.fromhex("8877665544332211")),
        ]
        descriptors = [
            LogicalDescriptor(
                4, "EMIT", 13, source_a=AddressExpression(base=0)
            ),
            LogicalDescriptor(
                2, "XOR", 8,
                source_a=AddressExpression(base=0),
                source_b=AddressExpression(base=2),
                destination=AddressExpression(base=3),
            ),
        ]
        return objects, descriptors

    def test_v1_static_lowering_tail_bytes_and_determinism(self) -> None:
        objects, descriptors = self._static_inputs()
        first = lower_logical_data(
            objects, descriptors, logical_slot_count=4,
            logical_slot_bytes=16, scratch_capacity_words=8,
        )
        second = lower_logical_data(
            reversed(objects), reversed(descriptors), logical_slot_count=4,
            logical_slot_bytes=16, scratch_capacity_words=8,
        )
        self.assertEqual(first, second)
        self.assertEqual(first.descriptor_format_version, 1)
        self.assertEqual(first.slot_stride_words, 2)
        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(first.descriptor_hex(), second.descriptor_hex())
        self.assertEqual(first.scratch_words[0], 0x0706050403020100)
        self.assertEqual(first.scratch_words[1], 0x0000000C0B0A0908)
        self.assertEqual(first.scratch_words[4], 0x1122334455667788)
        self.assertEqual(sum(first.initialized_words), 3)
        self.assertEqual(first.placements[0].last_bytes, 5)

        xor_fields = decode_descriptor_word(first.descriptors[0].word)
        emit_fields = decode_descriptor_word(first.descriptors[1].word)
        self.assertEqual(xor_fields["format_version"], 1)
        self.assertEqual(xor_fields["flags"], 0x0004)
        self.assertEqual(xor_fields["source_a"], 0)
        self.assertEqual(xor_fields["source_b"], 4)
        self.assertEqual(xor_fields["destination"], 6)
        self.assertEqual(xor_fields["word_count"], 1)
        self.assertEqual(emit_fields["flags"], 0x0008)
        self.assertEqual(emit_fields["word_count"], 2)
        self.assertEqual(emit_fields["last_bytes"], 5)
        self.assertEqual(emit_fields["reserved"], 0)
        self.assertTrue(all(len(line) == 32 for line in first.descriptor_hex().splitlines()))
        self.assertTrue(all(len(line) == 16 for line in first.scratch_hex().splitlines()))

    def test_v1_shared_unit_stride_register_is_encodable(self) -> None:
        result = lower_logical_data(
            [], [LogicalDescriptor(
                0, "STORE", 8,
                source_a=AddressExpression(base=2, index_reg=3),
                destination=AddressExpression(base=8, index_reg=3),
            )],
            logical_slot_count=16, logical_slot_bytes=8,
            scratch_capacity_words=16, register_bounds={3: (0, 3)},
        )
        fields = decode_descriptor_word(result.descriptors[0].word)
        self.assertEqual(result.descriptor_format_version, 1)
        self.assertEqual(result.descriptors[0].shared_index_reg, 3)
        self.assertEqual(fields["address_mode"], 0b0101)
        self.assertEqual(result.bindings, ())

    def test_all_four_data_operations_encode_in_v1(self) -> None:
        descriptors = [
            LogicalDescriptor(0, "LOAD", 4,
                              source_a=AddressExpression(base=1)),
            LogicalDescriptor(1, "STORE", 8,
                              source_a=AddressExpression(base=1),
                              destination=AddressExpression(base=2)),
            LogicalDescriptor(2, "XOR", 8,
                              source_a=AddressExpression(base=1),
                              source_b=AddressExpression(base=2),
                              destination=AddressExpression(base=3)),
            LogicalDescriptor(3, "EMIT", 5,
                              source_a=AddressExpression(base=3)),
        ]
        result = lower_logical_data(
            [], descriptors, logical_slot_count=4, logical_slot_bytes=8,
            scratch_capacity_words=4,
        )
        fields = [decode_descriptor_word(item.word)
                  for item in result.descriptors]
        self.assertEqual([item["flags"] for item in fields], [1, 2, 4, 8])
        self.assertEqual([item["word_count"] for item in fields], [1, 1, 1, 1])
        self.assertEqual([item["last_bytes"] for item in fields], [4, 8, 8, 5])

    def test_existing_xmss_multiregister_move_lowers_to_v2_side_table(self) -> None:
        path = ROOT / "microcode/xmss/xmss_shake256_h10_w4_keygen.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        logical = descriptor_from_program_move(document, 0, byte_count=32)
        self.assertEqual(logical.source_a.base_reg, 5)
        self.assertEqual(logical.source_a.index_reg, 7)
        self.assertEqual(logical.destination.base_reg, 6)
        self.assertEqual(logical.destination.index_reg, 3)

        result = lower_logical_data(
            [], [logical], logical_slot_count=256, logical_slot_bytes=32,
            scratch_capacity_words=1024,
            register_bounds={5: (0, 135), 7: (0, 66),
                             6: (67, 137), 3: (0, 33)},
        )
        self.assertEqual(result.descriptor_format_version, 2)
        self.assertEqual(len(result.bindings), 2)
        descriptor = result.descriptors[0]
        fields = decode_descriptor_word(descriptor.word)
        self.assertEqual(fields["format_version"], 2)
        self.assertEqual(fields["flags"], 0x0002)
        self.assertEqual(fields["word_count"], 4)
        self.assertEqual(fields["last_bytes"], 8)
        self.assertEqual(fields["address_mode"], 0b0101)
        self.assertEqual(fields["reserved"], 2 << 12)

        source_binding = decode_binding_word(result.bindings[0].word)
        destination_binding = decode_binding_word(result.bindings[1].word)
        self.assertEqual(source_binding, {
            "operand": "source_a", "use_base_reg": 1, "base_reg": 5,
            "use_index_reg": 1, "index_reg": 7,
            "base_scale_words": 4, "index_stride_words": 4,
            "reserved": 0,
        })
        self.assertEqual(destination_binding["operand"], "destination")
        self.assertEqual(destination_binding["base_reg"], 6)
        self.assertEqual(destination_binding["index_reg"], 3)

        binding_words = [item.word for item in result.bindings]
        registers = {5: 0, 7: 66, 6: 67, 3: 33}
        self.assertEqual(
            evaluate_physical_address(
                descriptor.word, binding_words, "source_a", registers
            ),
            (0 + 66) * 4,
        )
        self.assertEqual(
            evaluate_physical_address(
                descriptor.word, binding_words, "destination", registers
            ),
            (67 + 33) * 4,
        )
        self.assertTrue(all(len(line) == 16 for line in result.binding_hex().splitlines()))

    def test_table_wide_v2_keeps_common_v1_fields(self) -> None:
        descriptors = [
            LogicalDescriptor(1, "EMIT", 13,
                              source_a=AddressExpression(base=4)),
            LogicalDescriptor(2, "STORE", 8,
                              source_a=AddressExpression(base=0, base_reg=1),
                              destination=AddressExpression(base=8)),
        ]
        result = lower_logical_data(
            [], descriptors, logical_slot_count=16, logical_slot_bytes=16,
            scratch_capacity_words=32, register_bounds={1: (0, 3)},
        )
        self.assertEqual(result.descriptor_format_version, 2)
        static = decode_descriptor_word(result.descriptors[0].word)
        self.assertEqual(static["format_version"], 2)
        self.assertEqual(static["source_a"], 8)
        self.assertEqual(static["word_count"], 2)
        self.assertEqual(static["last_bytes"], 5)
        self.assertEqual(static["reserved"], 0)

    def test_overlap_and_bounds_fail_before_producing_an_image(self) -> None:
        cases = [
            dict(objects=[LogicalObject("a", 0, b"a"),
                          LogicalObject("b", 0, b"b")],
                 descriptors=[], logical_slot_count=2,
                 logical_slot_bytes=8, scratch_capacity_words=2),
            dict(objects=[LogicalObject("wide", 0, b"x" * 9)],
                 descriptors=[], logical_slot_count=2,
                 logical_slot_bytes=8, scratch_capacity_words=2),
            dict(objects=[], descriptors=[], logical_slot_count=3,
                 logical_slot_bytes=16, scratch_capacity_words=5),
        ]
        for arguments in cases:
            with self.subTest(arguments=arguments):
                with self.assertRaises(DataLoweringError):
                    lower_logical_data(**arguments)

        dynamic_oob = LogicalDescriptor(
            0, "EMIT", 8,
            source_a=AddressExpression(base=14, index_reg=2, stride=2),
        )
        with self.assertRaisesRegex(DataLoweringError, "out of bounds"):
            lower_logical_data(
                [], [dynamic_oob], logical_slot_count=16,
                logical_slot_bytes=8, scratch_capacity_words=16,
                register_bounds={2: (0, 1)},
            )
        with self.assertRaisesRegex(DataLoweringError, "missing bounds"):
            lower_logical_data(
                [], [dynamic_oob], logical_slot_count=16,
                logical_slot_bytes=8, scratch_capacity_words=16,
            )

    def test_load_width_and_duplicate_descriptor_fail_closed(self) -> None:
        with self.assertRaisesRegex(DataLoweringError, "one word"):
            lower_logical_data(
                [], [LogicalDescriptor(
                    0, "LOAD", 9, source_a=AddressExpression(base=0)
                )], logical_slot_count=2, logical_slot_bytes=16,
                scratch_capacity_words=4,
            )
        duplicate = [
            LogicalDescriptor(7, "EMIT", 1,
                              source_a=AddressExpression(base=0)),
            LogicalDescriptor(7, "EMIT", 1,
                              source_a=AddressExpression(base=1)),
        ]
        with self.assertRaisesRegex(DataLoweringError, "duplicate descriptor"):
            lower_logical_data(
                [], duplicate, logical_slot_count=2,
                logical_slot_bytes=8, scratch_capacity_words=2,
            )


if __name__ == "__main__":
    unittest.main()
