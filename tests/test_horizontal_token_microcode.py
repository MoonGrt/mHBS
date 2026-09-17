from __future__ import annotations

import unittest

from model.horizontal_microcode import ContextCommand, HorizontalWord, OP_HALT, OP_ISSUE
from model.horizontal_token_microcode import (
    TOKEN_RUN,
    TOKEN_LOOP,
    compress_horizontal_program,
    expand_horizontal_program,
)


class HorizontalTokenMicrocodeTests(unittest.TestCase):
    @staticmethod
    def issue(index0: int, index1: int) -> HorizontalWord:
        return HorizontalWord(
            opcode=OP_ISSUE,
            lane0_valid=True,
            lane1_valid=True,
            lane0_command=ContextCommand(recipe=4, index=index0).encode(),
            lane1_command=ContextCommand(
                recipe=5, argument_register=1, index=index1
            ).encode(),
        )

    def test_affine_run_is_bit_exact(self) -> None:
        words = [self.issue(7 + i, 100 + 2 * i) for i in range(17)]
        words.append(HorizontalWord(opcode=OP_HALT))
        templates, tokens, metrics = compress_horizontal_program(words)
        self.assertEqual(len(templates), 1)
        self.assertEqual(tokens[0].kind, TOKEN_RUN)
        self.assertEqual(tokens[0].repeat, 17)
        self.assertEqual(tokens[0].stride0, 1)
        self.assertEqual(tokens[0].stride1, 2)
        self.assertEqual(expand_horizontal_program(templates, tokens),
                         [word.encode() for word in words])
        self.assertEqual(metrics["tokens"], 2)

    def test_tracked_words_are_not_folded(self) -> None:
        words = [
            HorizontalWord(
                opcode=OP_ISSUE, lane0_valid=True, lane0_track=True,
                lane0_event=0,
                lane0_command=ContextCommand(recipe=1, index=index).encode(),
            )
            for index in (1, 2)
        ] + [HorizontalWord(opcode=OP_HALT)]
        _, tokens, _ = compress_horizontal_program(words)
        self.assertEqual(len(tokens), 3)

    def test_outer_loop_is_bit_exact(self) -> None:
        words = []
        for outer in range(4):
            words.extend((
                self.issue(10 + outer * 4, 11 + outer * 4),
                HorizontalWord(
                    opcode=OP_ISSUE, lane0_valid=True, lane1_valid=True,
                    lane0_command=ContextCommand(
                        recipe=6, index=12 + outer * 4
                    ).encode(),
                    lane1_command=ContextCommand(
                        recipe=3, argument_register=1,
                        index=13 + outer * 4
                    ).encode(),
                ),
            ))
        words.append(HorizontalWord(opcode=OP_HALT))
        templates, tokens, metrics = compress_horizontal_program(words)
        self.assertEqual(sum(token.kind == TOKEN_LOOP for token in tokens), 1)
        self.assertEqual(metrics["loop_tokens"], 1)
        self.assertEqual(expand_horizontal_program(templates, tokens),
                         [word.encode() for word in words])


if __name__ == "__main__":
    unittest.main()
