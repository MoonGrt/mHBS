import hashlib
import unittest

from model.treehash import StorageMode, build_tree, storage_latency_projection


def parent_hash(height: int, start: int, left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(height.to_bytes(1, "big") + start.to_bytes(4, "big") + left + right).digest()


def full_reference(leaves: list[bytes]) -> tuple[bytes, list[list[bytes]]]:
    levels = [leaves]
    height = 1
    while len(levels[-1]) > 1:
        previous = levels[-1]
        levels.append(
            [
                parent_hash(height, i * (1 << (height - 1)), previous[i], previous[i + 1])
                for i in range(0, len(previous), 2)
            ]
        )
        height += 1
    return levels[-1][0], levels


class TreeHashTests(unittest.TestCase):
    def test_modes_preserve_root_and_authentication_path(self) -> None:
        height = 10
        target = 731
        leaves = [hashlib.sha256(f"leaf-{i}".encode()).digest() for i in range(1 << height)]
        expected_root, levels = full_reference(leaves)
        expected_auth = [levels[level][(target >> level) ^ 1] for level in range(height)]
        peaks = {}
        for mode in StorageMode:
            root, auth, metrics = build_tree(leaves, height, parent_hash, mode, target)
            self.assertEqual(root, expected_root)
            self.assertEqual(auth, expected_auth)
            self.assertEqual(metrics.parent_hashes, (1 << height) - 1)
            peaks[mode] = metrics.logical_peak_bytes(32, len(auth))
        self.assertLess(peaks[StorageMode.TREEHASH_MIN], peaks[StorageMode.FULL_CACHE])

    def test_h10_projection_exposes_latency_tradeoff(self) -> None:
        rows = {row["mode"]: row for row in storage_latency_projection(10, 32, 4)}
        self.assertEqual(rows["FULL_CACHE"]["retained_bytes"], 65504)
        self.assertEqual(rows["TREEHASH_MIN"]["retained_bytes"], 672)
        self.assertEqual(rows["SUBTREE_CACHE"]["cache_nodes"], 127)
        self.assertEqual(rows["SUBTREE_CACHE"]["auth_cache_hits"], 6)
        self.assertEqual(rows["SUBTREE_CACHE"]["auth_cache_misses"], 4)
        self.assertEqual(rows["SUBTREE_CACHE"]["auth_recompute_leaves"], 15)
        self.assertEqual(rows["SUBTREE_CACHE"]["auth_recompute_parents"], 11)
        self.assertEqual(rows["SUBTREE_CACHE"]["auth_recompute_node_upper_bound"], 26)
        self.assertEqual(rows["SUBTREE_CACHE"]["warm_active_subtree_extra_nodes"], 30)
        self.assertEqual(rows["SUBTREE_CACHE"]["warm_active_subtree_total_cache_nodes"], 157)
        self.assertEqual(rows["TREEHASH_MIN"]["auth_recompute_node_upper_bound"], 2047)


if __name__ == "__main__":
    unittest.main()
