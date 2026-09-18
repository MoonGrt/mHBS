import unittest

from model.static_task_microcode import (
    StaticTaskToken,
    TOKEN_HALT,
    TOKEN_LOOP,
    TOKEN_RUN,
    expand,
)
from scripts.compile_slh_dsa_static_task_microcode import build_program


class StaticTaskMicrocodeTests(unittest.TestCase):
    def test_product_image_expands_losslessly(self) -> None:
        templates, tokens, words = build_program()
        self.assertEqual(len(tokens), 29)
        self.assertEqual(len(templates), 13)
        self.assertEqual(len(words), 5812)
        self.assertEqual(words[-1] >> 124, 0xF)
        self.assertEqual(expand(templates, tokens), words)
        self.assertEqual(sum(token.kind == TOKEN_LOOP for token in tokens), 3)
        self.assertEqual(sum(token.kind == TOKEN_RUN for token in tokens), 7)

    def test_image_is_parameter_only(self) -> None:
        _, tokens, _ = build_program()
        encoded = b"".join(token.encode().to_bytes(16, "big")
                           for token in tokens)
        # The program contains coordinates and recipes only.  These sentinels
        # represent secret/message material and must never appear in the ROM.
        for sentinel in (b"sk_seed", b"sk_prf", b"message", b"tc137"):
            self.assertNotIn(sentinel, encoded)

    def test_invalid_token_fields_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            StaticTaskToken(TOKEN_RUN, repeat=1).encode()
        with self.assertRaises(ValueError):
            StaticTaskToken(TOKEN_LOOP, back_count=0,
                            loop_repeats=1).encode()
        self.assertEqual(StaticTaskToken(TOKEN_HALT).encode(), 3 << 126)


if __name__ == "__main__":
    unittest.main()
