import unittest

from model.generic_hbs_macrocode import Macro
from model.stateful_hbs_macrocode import (
    RecipeShape,
    StatefulFamily,
    StatefulDescriptorKind,
    all_stateful_images,
)


class StatefulHbsMacrocodeTests(unittest.TestCase):
    def test_two_entry_static_images_are_bounded(self) -> None:
        for image in all_stateful_images():
            self.assertEqual(image.keygen_entry, 0)
            self.assertGreater(image.sign_entry, image.keygen_entry)
            self.assertLess(len(image.tokens), 384)
            self.assertLessEqual(len(image.descriptors), 512)
            self.assertEqual(image.descriptors[0] >> 60,
                             StatefulDescriptorKind.IMAGE_V2)

    def test_only_public_macros_appear(self) -> None:
        allowed = {int(macro) for macro in Macro}
        for image in all_stateful_images():
            for word in image.expanded_keygen[:-1] + image.expanded_sign[:-1]:
                self.assertIn((word >> 96) & 0xF, allowed)

    def test_images_contain_no_key_or_message_material(self) -> None:
        markers = (
            bytes(range(32)),
            b"micro-hbs shake-lms research profile",
        )
        for image in all_stateful_images():
            blob = b"".join(
                word.to_bytes(16, "big") for word in image.tokens + image.templates
            ) + b"".join(word.to_bytes(8, "big") for word in image.descriptors)
            for marker in markers:
                self.assertNotIn(marker, blob)

    def test_profile_role_map_selects_only_generic_shapes(self) -> None:
        allowed = {int(shape) for shape in RecipeShape}
        for image in all_stateful_images():
            profile = image.descriptors[1]
            chain = (profile >> 25) & 0xF
            parent = (profile >> 21) & 0xF
            hash_a = (profile >> 17) & 0xF
            hash_b = (profile >> 13) & 0xF
            self.assertIn(chain, allowed)
            self.assertIn(parent, allowed)
            self.assertIn(hash_a, allowed)
            self.assertTrue(hash_b == 0 or hash_b in allowed)
            emit_base = (image.descriptors[50] >> 52) & 0xFF
            emit_count = (image.descriptors[50] >> 48) & 0xF
            self.assertEqual(emit_base, 10)
            self.assertEqual(emit_count, 7 if image.family
                             == StatefulFamily.XMSS else 8)
            if image.family == StatefulFamily.XMSS:
                self.assertEqual((profile >> 12) & 1, 0)
            else:
                self.assertEqual((profile >> 12) & 1, 1)

    def test_tree_and_emit_control_are_in_profile_microcode(self) -> None:
        images = {image.family: image for image in all_stateful_images()}
        xmss = images[StatefulFamily.XMSS]
        lms = images[StatefulFamily.LMS_SHAKE_RESEARCH]

        def commands(image, operation):
            words = (image.expanded_keygen if operation == "keygen"
                     else image.expanded_sign)
            return [((word >> 96) & 0xF, (word >> 88) & 0xFF)
                    for word in words[:-1]]

        xmss_keygen = commands(xmss, "keygen")
        lms_keygen = commands(lms, "keygen")
        self.assertEqual(xmss_keygen.count((Macro.TREE_PUSH, 34)),
                         1024 * 67)
        self.assertNotIn((Macro.TREE_PUSH, 34), lms_keygen)
        self.assertEqual(lms_keygen.count((Macro.HASH, 43)), 1024)
        self.assertEqual(lms_keygen.count((Macro.HASH, 44)), 1024)

        expected_sign = [
            (Macro.HASH, 40),
            (Macro.TRANSFORM, 48),
            (Macro.EMIT, 51),
            (Macro.CHAIN, 41),
            (Macro.EMIT, 52),
        ]
        self.assertEqual(commands(xmss, "sign"), expected_sign)
        self.assertEqual(commands(lms, "sign"), expected_sign)


if __name__ == "__main__":
    unittest.main()
