import unittest

from model.state_manager import IndexState, StateFault, StatefulIndexManager


class StateManagerTests(unittest.TestCase):
    def test_release_requires_persistence(self) -> None:
        manager = StatefulIndexManager(4)
        index = manager.reserve()
        with self.assertRaisesRegex(StateFault, "ERR_STATE_TRANSITION"):
            manager.release_signature(index)
        manager.persist(index)
        manager.release_signature(index)
        manager.consume(index)
        self.assertEqual(manager.records[index].state, IndexState.CONSUMED)

    def test_reset_burns_reserved_and_persisted_indices(self) -> None:
        manager = StatefulIndexManager(4)
        first = manager.reserve()
        second = manager.reserve()
        manager.persist(second)
        manager.cancel_or_reset()
        self.assertEqual(manager.records[first].state, IndexState.BURNED)
        self.assertEqual(manager.records[second].state, IndexState.BURNED)
        self.assertEqual(manager.reserve(), 2)

    def test_recovery_rejects_rollback(self) -> None:
        manager = StatefulIndexManager(8)
        index = manager.reserve()
        manager.persist(index)
        with self.assertRaisesRegex(StateFault, "ERR_STATE_ROLLBACK"):
            manager.recover(0)

    def test_exhaustion(self) -> None:
        manager = StatefulIndexManager(1)
        manager.reserve()
        with self.assertRaisesRegex(StateFault, "ERR_INDEX_EXHAUSTED"):
            manager.reserve()


if __name__ == "__main__":
    unittest.main()
