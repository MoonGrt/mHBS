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
            self.assertEqual((image.descriptors[50] >> 52) & 0xFF,
                             int(image.family))
            if image.family == StatefulFamily.XMSS:
                self.assertEqual((profile >> 12) & 1, 0)
            else:
                self.assertEqual((profile >> 12) & 1, 1)


if __name__ == "__main__":
    unittest.main()
