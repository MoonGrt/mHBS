import unittest
from dataclasses import replace

from model.generic_hbs_macrocode import (
    DescriptorKind,
    Macro,
    all_images,
    compile_keygen_image,
    compile_sign_image,
    validate_image,
)


class GenericHbsMacrocodeTests(unittest.TestCase):
    def test_images_are_bounded_and_terminate(self) -> None:
        for image in all_images():
            with self.subTest(image=image.name):
                validate_image(image)
                self.assertLessEqual(len(image.tokens), 384)
                self.assertLessEqual(len(image.templates), 64)
                self.assertLessEqual(len(image.descriptors), 512)
                self.assertEqual(image.expanded[-1] >> 124, 0xF)

    def test_sign_program_has_only_generic_macros(self) -> None:
        image = compile_sign_image()
        macros = set()
        for word in image.expanded[:-1]:
            if word >> 124 == 1 and ((word >> 107) & 1):
                macros.add((word >> 96) & 0xF)
        self.assertEqual(
            macros,
            {Macro.HASH, Macro.TREE, Macro.TRANSFORM},
        )
        self.assertEqual(image.output_bytes, 17088)

    def test_keygen_program_is_tree_then_emit(self) -> None:
        image = compile_keygen_image()
        macros = [
            (word >> 96) & 0xF for word in image.expanded[:-1]
            if word >> 124 == 1
        ]
        self.assertEqual(macros, [Macro.TREE, Macro.EMIT])
        self.assertEqual(image.output_bytes, 96)

    def test_descriptor_table_contains_all_record_classes(self) -> None:
        kinds = {
            word >> 60
            for word in compile_sign_image().descriptors
            if word
        }
        self.assertTrue({
            DescriptorKind.HASH,
            DescriptorKind.SEGMENT,
            DescriptorKind.ADDRESS,
            DescriptorKind.CHAIN,
            DescriptorKind.TREE,
            DescriptorKind.ROUTE,
            DescriptorKind.ACTION,
            DescriptorKind.TRANSFORM,
            DescriptorKind.EMIT,
            DescriptorKind.IMAGE,
        }.issubset(kinds))

    def test_bad_descriptor_reference_is_rejected(self) -> None:
        image = compile_sign_image()
        descriptors = list(image.descriptors)
        descriptors[1] = (descriptors[1] & ~(0xff << 52)) | (63 << 52)
        with self.assertRaises(ValueError):
            validate_image(replace(image, descriptors=tuple(descriptors)))

    def test_early_halt_is_rejected(self) -> None:
        image = compile_keygen_image()
        expanded = (0xF << 124,) + image.expanded
        with self.assertRaises(ValueError):
            validate_image(replace(image, expanded=expanded))


if __name__ == "__main__":
    unittest.main()
