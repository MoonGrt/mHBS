"""Streaming TreeHash model and storage-mode accounting."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Iterable


class StorageMode(str, Enum):
    FULL_CACHE = "FULL_CACHE"
    SUBTREE_CACHE = "SUBTREE_CACHE"
    TREEHASH_MIN = "TREEHASH_MIN"


@dataclass(frozen=True)
class Node:
    value: bytes
    height: int
    start_leaf: int


@dataclass
class TreeHashMetrics:
    leaf_count: int = 0
    parent_hashes: int = 0
    pushes: int = 0
    pops: int = 0
    cache_writes: int = 0
    peak_stack_nodes: int = 0
    peak_cached_nodes: int = 0

    def logical_peak_bytes(self, n: int, auth_nodes: int) -> int:
        return (self.peak_stack_nodes + self.peak_cached_nodes + auth_nodes) * n


class TreeHash:
    def __init__(
        self,
        tree_height: int,
        parent_hash: Callable[[int, int, bytes, bytes], bytes],
        mode: StorageMode = StorageMode.TREEHASH_MIN,
        target_leaf: int | None = None,
        subtree_height: int = 4,
    ):
        if not 1 <= tree_height <= 31:
            raise ValueError("tree_height outside 1..31")
        if target_leaf is not None and not 0 <= target_leaf < (1 << tree_height):
            raise ValueError("target_leaf outside tree")
        if not 1 <= subtree_height <= tree_height:
            raise ValueError("subtree_height outside tree")
        self.tree_height = tree_height
        self.parent_hash = parent_hash
        self.mode = mode
        self.target_leaf = target_leaf
        self.subtree_height = subtree_height
        self.stack: list[Node] = []
        self.cache: dict[tuple[int, int], bytes] = {}
        self.auth_path: dict[int, bytes] = {}
        self.metrics = TreeHashMetrics()
        self._next_leaf = 0

    def _retain(self, node: Node) -> None:
        retain = self.mode == StorageMode.FULL_CACHE
        if self.mode == StorageMode.SUBTREE_CACHE:
            retain = node.height >= self.subtree_height
        if retain:
            self.cache[(node.height, node.start_leaf)] = node.value
            self.metrics.cache_writes += 1
            self.metrics.peak_cached_nodes = max(self.metrics.peak_cached_nodes, len(self.cache))

    def push(self, value: bytes) -> list[dict[str, int | str]]:
        if self._next_leaf >= (1 << self.tree_height):
            raise ValueError("too many leaves")
        if not value:
            raise ValueError("empty node")
        node = Node(value=value, height=0, start_leaf=self._next_leaf)
        self._next_leaf += 1
        self.metrics.leaf_count += 1
        self.metrics.pushes += 1
        events: list[dict[str, int | str]] = []
        self._retain(node)
        while self.stack and self.stack[-1].height == node.height:
            left = self.stack.pop()
            self.metrics.pops += 1
            if left.start_leaf + (1 << left.height) != node.start_leaf:
                raise AssertionError("non-adjacent equal-height nodes")
            if self.target_leaf is not None:
                if left.start_leaf <= self.target_leaf < left.start_leaf + (1 << left.height):
                    self.auth_path[left.height] = node.value
                elif node.start_leaf <= self.target_leaf < node.start_leaf + (1 << node.height):
                    self.auth_path[node.height] = left.value
            parent_height = node.height + 1
            parent_start = left.start_leaf
            parent = self.parent_hash(parent_height, parent_start, left.value, node.value)
            self.metrics.parent_hashes += 1
            events.append(
                {
                    "event": "reduce",
                    "child_height": node.height,
                    "parent_height": parent_height,
                    "parent_start_leaf": parent_start,
                }
            )
            node = Node(parent, parent_height, parent_start)
            self._retain(node)
        self.stack.append(node)
        self.metrics.peak_stack_nodes = max(self.metrics.peak_stack_nodes, len(self.stack))
        return events

    def finish(self) -> tuple[bytes, list[bytes], TreeHashMetrics]:
        if self._next_leaf != (1 << self.tree_height):
            raise ValueError("incomplete tree")
        if len(self.stack) != 1 or self.stack[0].height != self.tree_height:
            raise AssertionError("tree did not reduce to one root")
        auth = []
        if self.target_leaf is not None:
            if set(self.auth_path) != set(range(self.tree_height)):
                raise AssertionError("incomplete authentication path")
            auth = [self.auth_path[level] for level in range(self.tree_height)]
        return self.stack[0].value, auth, self.metrics


def build_tree(
    leaves: Iterable[bytes],
    tree_height: int,
    parent_hash: Callable[[int, int, bytes, bytes], bytes],
    mode: StorageMode,
    target_leaf: int | None = None,
    subtree_height: int = 4,
) -> tuple[bytes, list[bytes], TreeHashMetrics]:
    tree = TreeHash(tree_height, parent_hash, mode, target_leaf, subtree_height)
    for leaf in leaves:
        tree.push(leaf)
    return tree.finish()


def storage_latency_projection(tree_height: int, n: int, subtree_height: int = 4) -> list[dict[str, int | str]]:
    """Architecture-independent node-count Pareto, not an RTL cycle claim."""
    leaves = 1 << tree_height
    full_nodes = (1 << (tree_height + 1)) - 1
    upper_nodes = (1 << (tree_height - subtree_height + 1)) - 1
    lower_auth_leaves = (1 << subtree_height) - 1
    lower_auth_parents = lower_auth_leaves - subtree_height
    lower_auth_nodes = lower_auth_leaves + lower_auth_parents
    return [
        {
            "mode": StorageMode.FULL_CACHE.value,
            "retained_nodes": full_nodes,
            "retained_bytes": full_nodes * n,
            "cache_nodes": full_nodes,
            "working_nodes": 0,
            "auth_cache_hits": tree_height,
            "auth_cache_misses": 0,
            "auth_recompute_leaves": 0,
            "auth_recompute_parents": 0,
            "auth_recompute_node_upper_bound": 0,
        },
        {
            "mode": StorageMode.SUBTREE_CACHE.value,
            "retained_nodes": upper_nodes + tree_height + 1,
            "retained_bytes": (upper_nodes + tree_height + 1) * n,
            "cache_nodes": upper_nodes,
            "working_nodes": tree_height + 1,
            "auth_cache_hits": tree_height - subtree_height,
            "auth_cache_misses": subtree_height,
            "auth_recompute_leaves": lower_auth_leaves,
            "auth_recompute_parents": lower_auth_parents,
            "auth_recompute_node_upper_bound": lower_auth_nodes,
            # The height=subtree_height root is already in the persistent
            # upper cache, so the active window only adds levels 0..h-1.
            "warm_active_subtree_extra_nodes": (1 << (subtree_height + 1)) - 2,
            "warm_active_subtree_total_cache_nodes": (
                upper_nodes + (1 << (subtree_height + 1)) - 2
            ),
            "warm_active_subtree_auth_recompute_nodes": 0,
        },
        {
            "mode": StorageMode.TREEHASH_MIN.value,
            "retained_nodes": 2 * tree_height + 1,
            "retained_bytes": (2 * tree_height + 1) * n,
            "cache_nodes": 0,
            "working_nodes": 2 * tree_height + 1,
            "auth_cache_hits": 0,
            "auth_cache_misses": tree_height,
            "auth_recompute_leaves": leaves,
            "auth_recompute_parents": leaves - 1,
            "auth_recompute_node_upper_bound": 2 * leaves - 1,
        },
    ]
