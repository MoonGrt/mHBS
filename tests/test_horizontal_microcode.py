from __future__ import annotations

import unittest

from model.horizontal_microcode import (
    ContextCommand,
    HorizontalWord,
    OP_HALT,
    OP_ISSUE,
    compile_barrier_program,
)


class HorizontalMicrocodeTests(unittest.TestCase):
    def test_context_round_trip(self) -> None:
        command = ContextCommand(6, 0xABC, 7, 0x654321)
        self.assertEqual(ContextCommand.decode(command.encode()), command)

    def test_word_round_trip(self) -> None:
        word = HorizontalWord(
            OP_ISSUE, 3, 3, True, True, 0, 1,
            ContextCommand(4, index=10).encode(),
            ContextCommand(5, index=11).encode(),
            True, True,
        )
        self.assertEqual(HorizontalWord.decode(word.encode()), word)

    def test_static_pairing_keeps_direct_dependency_separate(self) -> None:
        tasks = [
            {"task_id": 0, "start": 0, "lane": 0,
             "dependencies": [], "hash_class": "prf", "permutations": 1},
            {"task_id": 1, "start": 12, "lane": 1,
             "dependencies": [0], "hash_class": "f", "permutations": 1},
            {"task_id": 2, "start": 12, "lane": 0,
             "dependencies": [], "hash_class": "h", "permutations": 1},
        ]
        words, metrics = compile_barrier_program(tasks)
        self.assertEqual([word.opcode for word in words],
                         [OP_ISSUE, OP_ISSUE, OP_HALT])
        self.assertEqual(metrics["singleton_batches"], 1)
        self.assertEqual(metrics["tasks"], 3)
        self.assertEqual(metrics["u2_active_cycle_projection"], 24)


if __name__ == "__main__":
    unittest.main()
