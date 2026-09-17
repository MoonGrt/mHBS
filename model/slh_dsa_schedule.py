"""Hash-granularity SLH-DSA dependency and KxU scheduling model.

The model deliberately schedules complete SHAKE calls, not individual Keccak
permutations.  A multi-block SHAKE call stays on one lane and every task is
released only after its algorithmic predecessors complete.  This makes the
reported KxU latency a realizable hash-service schedule rather than the old
``ceil(total_permutations / K)`` occupancy bound.

The supported profile is FIPS 205 SLH-DSA-SHAKE-128f.  Keygen, Sign, and
Verify graphs share the same fixed F/PRF/H/T_l message templates.  Sign tasks
also carry the canonical signature offset of every value that must be emitted,
which allows the scheduler to account for ordered signature streaming.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
import heapq
import math
from typing import Iterable, Sequence

from model.reference.slh_dsa import (
    SLH_DSA_SHAKE_128F,
    SlhDsaParams,
    _base_2b,
    _fors_pk_from_sig,
    _hash_message,
    _set_tree_address,
    _set_type_and_clear,
    _wots_digits,
    _xmss_pk_from_sig,
    sign_internal,
    FORS_TREE,
)


@dataclass
class HashTask:
    task_id: int
    name: str
    operation: str
    phase: str
    hash_class: str
    permutations: int
    dependencies: tuple[int, ...] = ()
    signature_offset: int | None = None
    signature_bytes: int = 0


@dataclass
class HashTaskGraph:
    operation: str
    params: SlhDsaParams
    tasks: list[HashTask] = field(default_factory=list)
    signature_bytes: int = 0
    final_tasks: tuple[int, ...] = ()

    def add(
        self,
        hash_class: str,
        phase: str,
        dependencies: Iterable[int] = (),
        *,
        permutations: int | None = None,
        name: str | None = None,
        signature_offset: int | None = None,
        signature_bytes: int = 0,
    ) -> int:
        deps = tuple(dict.fromkeys(int(item) for item in dependencies))
        task_id = len(self.tasks)
        if any(item < 0 or item >= task_id for item in deps):
            raise ValueError(f"task {task_id} has invalid dependency {deps}")
        if permutations is None:
            permutations = 5 if hash_class == "t_l" else 1
        if permutations <= 0:
            raise ValueError("permutations must be positive")
        if signature_offset is not None:
            if signature_offset < 0 or signature_bytes <= 0:
                raise ValueError("signature producer needs a valid byte range")
        self.tasks.append(
            HashTask(
                task_id=task_id,
                name=name or f"{phase}:{hash_class}:{task_id}",
                operation=self.operation,
                phase=phase,
                hash_class=hash_class,
                permutations=permutations,
                dependencies=deps,
                signature_offset=signature_offset,
                signature_bytes=signature_bytes,
            )
        )
        return task_id

    def mark_signature(self, task_id: int, offset: int, size: int) -> None:
        task = self.tasks[task_id]
        if task.signature_offset is not None:
            raise ValueError(f"task {task_id} already produces signature data")
        task.signature_offset = offset
        task.signature_bytes = size

    def hash_class_counts(self) -> dict[str, int]:
        return dict(sorted(Counter(task.hash_class for task in self.tasks).items()))

    @property
    def permutation_count(self) -> int:
        return sum(task.permutations for task in self.tasks)

    def validate_signature_map(self) -> None:
        if self.signature_bytes == 0:
            if any(task.signature_offset is not None for task in self.tasks):
                raise ValueError("non-Sign graph contains signature producers")
            return
        covered = bytearray(self.signature_bytes)
        for task in self.tasks:
            if task.signature_offset is None:
                continue
            start = task.signature_offset
            end = start + task.signature_bytes
            if end > self.signature_bytes:
                raise ValueError(f"signature range {start}:{end} is out of bounds")
            if any(covered[start:end]):
                raise ValueError(f"overlapping signature range {start}:{end}")
            covered[start:end] = b"\x01" * task.signature_bytes
        if any(value == 0 for value in covered):
            raise ValueError("signature producer map has holes")


@dataclass(frozen=True)
class ScheduleConfig:
    lanes: int
    unroll: int
    issue_width: int = 1
    hash_overhead_cycles: int = 3
    output_bytes_per_cycle: int = 8
    policy: str = "critical"

    def __post_init__(self) -> None:
        if self.lanes <= 0:
            raise ValueError("K/lanes must be positive")
        if self.unroll <= 0 or self.unroll > 24:
            raise ValueError("U/unroll must be in 1..24")
        if self.issue_width <= 0:
            raise ValueError("issue_width must be positive")
        if self.hash_overhead_cycles < 0:
            raise ValueError("hash_overhead_cycles must be non-negative")
        if self.output_bytes_per_cycle <= 0:
            raise ValueError("output_bytes_per_cycle must be positive")
        if self.policy not in {"fifo", "critical", "signature"}:
            raise ValueError("policy must be fifo, critical, or signature")

    @property
    def rounds_cycles(self) -> int:
        return math.ceil(24 / self.unroll)

    def duration(self, task: HashTask) -> int:
        return task.permutations * self.rounds_cycles + self.hash_overhead_cycles


@dataclass
class ScheduleResult:
    config: ScheduleConfig
    operation: str
    hash_cycles: int
    completion_cycles: int
    signature_stream_cycles: int
    active_lane_cycles: int
    lane_active_cycles: tuple[int, ...]
    lane_task_counts: tuple[int, ...]
    task_start: tuple[int, ...]
    task_finish: tuple[int, ...]
    task_lane: tuple[int, ...]
    critical_path_cycles: int
    issue_stall_cycles: int
    maximum_ready_depth: int
    maximum_signature_reorder_bytes: int

    @property
    def lane_utilization(self) -> float:
        denominator = self.config.lanes * self.hash_cycles
        return self.active_lane_cycles / denominator if denominator else 0.0

    def summary(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "configuration": {
                "K": self.config.lanes,
                "U": self.config.unroll,
                "issue_width": self.config.issue_width,
                "hash_overhead_cycles": self.config.hash_overhead_cycles,
                "output_bytes_per_cycle": self.config.output_bytes_per_cycle,
                "policy": self.config.policy,
            },
            "hash_cycles": self.hash_cycles,
            "completion_cycles": self.completion_cycles,
            "signature_stream_cycles": self.signature_stream_cycles,
            "critical_path_cycles": self.critical_path_cycles,
            "active_lane_cycles": self.active_lane_cycles,
            "lane_utilization": self.lane_utilization,
            "lane_active_cycles": list(self.lane_active_cycles),
            "lane_task_counts": list(self.lane_task_counts),
            "issue_stall_cycles": self.issue_stall_cycles,
            "maximum_ready_depth": self.maximum_ready_depth,
            "maximum_signature_reorder_bytes": self.maximum_signature_reorder_bytes,
        }


def _combine_tree(
    graph: HashTaskGraph,
    nodes: Sequence[int],
    phase: str,
) -> int:
    if not nodes or len(nodes) & (len(nodes) - 1):
        raise ValueError("binary tree requires a nonzero power-of-two leaf count")
    level = list(nodes)
    height = 1
    while len(level) > 1:
        level = [
            graph.add(
                "h",
                phase,
                (level[index], level[index + 1]),
                name=f"{phase}:parent_h{height}_{index // 2}",
            )
            for index in range(0, len(level), 2)
        ]
        height += 1
    return level[0]


def _add_wots_pkgen(
    graph: HashTaskGraph,
    phase: str,
    dependencies: Sequence[int] = (),
) -> int:
    endpoints: list[int] = []
    for chain in range(graph.params.wots_len):
        value = graph.add(
            "prf", phase, dependencies, name=f"{phase}:chain{chain}:prf"
        )
        for step in range(graph.params.w - 1):
            value = graph.add(
                "f", phase, (value,), name=f"{phase}:chain{chain}:f{step}"
            )
        endpoints.append(value)
    return graph.add("t_l", phase, endpoints, name=f"{phase}:compress")


def build_keygen_graph(
    params: SlhDsaParams = SLH_DSA_SHAKE_128F,
) -> HashTaskGraph:
    graph = HashTaskGraph("keygen", params)
    leaves = [
        _add_wots_pkgen(graph, f"keygen:leaf{leaf}")
        for leaf in range(1 << params.hp)
    ]
    root = _combine_tree(graph, leaves, "keygen:top_tree")
    graph.final_tasks = (root,)
    return graph


def _add_fors_leaf(
    graph: HashTaskGraph,
    phase: str,
    dependencies: Sequence[int],
) -> int:
    secret = graph.add("prf", phase, dependencies, name=f"{phase}:secret")
    return graph.add("f", phase, (secret,), name=f"{phase}:leaf")


def _add_fors_subtree(
    graph: HashTaskGraph,
    phase: str,
    height: int,
    dependencies: Sequence[int],
) -> int:
    leaves = [
        _add_fors_leaf(graph, f"{phase}:leaf{leaf}", dependencies)
        for leaf in range(1 << height)
    ]
    return leaves[0] if height == 0 else _combine_tree(graph, leaves, phase)


def _add_xmss_auth_subtree(
    graph: HashTaskGraph,
    phase: str,
    height: int,
    dependencies: Sequence[int],
) -> int:
    leaves = [
        _add_wots_pkgen(graph, f"{phase}:leaf{leaf}", dependencies)
        for leaf in range(1 << height)
    ]
    return leaves[0] if height == 0 else _combine_tree(graph, leaves, phase)


def _sign_context(
    message: bytes,
    secret_key: bytes,
    params: SlhDsaParams,
) -> tuple[bytes, list[list[int]]]:
    """Return the exact signature and per-XMSS-layer WOTS digits."""
    signature = sign_internal(params, message, secret_key)
    public_seed = secret_key[2 * params.n : 3 * params.n]
    public_root = secret_key[3 * params.n : 4 * params.n]
    randomizer = signature[: params.n]
    digest = _hash_message(params, randomizer, public_seed, public_root, message)
    fors_bytes = (params.k * params.a + 7) // 8
    tree_bits = params.h - params.hp
    tree_bytes = (tree_bits + 7) // 8
    leaf_bytes = (params.hp + 7) // 8
    message_digest = digest[:fors_bytes]
    offset = fors_bytes
    tree_index = int.from_bytes(digest[offset : offset + tree_bytes], "big") % (
        1 << tree_bits
    )
    offset += tree_bytes
    leaf_index = int.from_bytes(digest[offset : offset + leaf_bytes], "big") % (
        1 << params.hp
    )
    fors_signature_bytes = params.k * (params.a + 1) * params.n
    fors_signature = signature[params.n : params.n + fors_signature_bytes]
    address = [0] * 8
    _set_tree_address(address, tree_index)
    _set_type_and_clear(address, FORS_TREE)
    address[5] = leaf_index
    root = _fors_pk_from_sig(
        params, fors_signature, message_digest, public_seed, address
    )
    hypertree = signature[params.n + fors_signature_bytes :]
    xmss_bytes = (params.wots_len + params.hp) * params.n
    digits: list[list[int]] = []
    for layer in range(params.d):
        digits.append(_wots_digits(params, root))
        part = hypertree[layer * xmss_bytes : (layer + 1) * xmss_bytes]
        _set_tree_address(address, tree_index)
        address[0] = layer
        root = _xmss_pk_from_sig(
            params, leaf_index, part, root, public_seed, address
        )
        if layer < params.d - 1:
            leaf_index = tree_index % (1 << params.hp)
            tree_index >>= params.hp
    return signature, digits


def build_sign_graph(
    message: bytes,
    secret_key: bytes,
    params: SlhDsaParams = SLH_DSA_SHAKE_128F,
) -> HashTaskGraph:
    signature, layer_digits = _sign_context(message, secret_key, params)
    graph = HashTaskGraph("sign", params, signature_bytes=len(signature))
    prf_perms = (2 * params.n + len(message)) // 136 + 1
    hmsg_perms = (3 * params.n + len(message)) // 136 + 1
    randomizer = graph.add(
        "prf_msg",
        "sign:message",
        permutations=prf_perms,
        name="sign:randomizer",
        signature_offset=0,
        signature_bytes=params.n,
    )
    digest = graph.add(
        "h_msg",
        "sign:message",
        (randomizer,),
        permutations=hmsg_perms,
        name="sign:message_digest",
    )

    # FORS signature consists of one selected secret and `a` authentication
    # roots for each of the k trees.  Recovery tasks consume those exact
    # producers, so the graph proves that every emitted value is algorithmic.
    fors_roots: list[int] = []
    fors_base = params.n
    for tree in range(params.k):
        phase = f"sign:fors{tree}"
        selected = graph.add(
            "prf",
            phase,
            (digest,),
            name=f"{phase}:selected_secret",
            signature_offset=fors_base + (tree * (params.a + 1)) * params.n,
            signature_bytes=params.n,
        )
        auth: list[int] = []
        for height in range(params.a):
            root = _add_fors_subtree(
                graph, f"{phase}:auth{height}", height, (digest,)
            )
            graph.mark_signature(
                root,
                fors_base + (tree * (params.a + 1) + height + 1) * params.n,
                params.n,
            )
            auth.append(root)
        node = graph.add("f", phase, (selected,), name=f"{phase}:recover_leaf")
        for height, sibling in enumerate(auth):
            node = graph.add(
                "h",
                phase,
                (node, sibling),
                name=f"{phase}:recover_h{height}",
            )
        fors_roots.append(node)
    current_root = graph.add(
        "t_l", "sign:fors_roots", fors_roots, name="sign:fors_roots:compress"
    )

    hypertree_base = params.n + params.k * (params.a + 1) * params.n
    final_signature_tasks: list[int] = []
    for layer, digits in enumerate(layer_digits):
        phase = f"sign:xmss{layer}"
        layer_base = hypertree_base + layer * (params.wots_len + params.hp) * params.n
        auth_roots: list[int] = []
        # Tree/leaf addresses for every layer derive from H_msg, so auth
        # subtrees can be prepared independently of the previous layer root.
        for height in range(params.hp):
            root = _add_xmss_auth_subtree(
                graph, f"{phase}:auth{height}", height, (digest,)
            )
            graph.mark_signature(
                root,
                layer_base + params.wots_len * params.n + height * params.n,
                params.n,
            )
            auth_roots.append(root)

        endpoints: list[int] = []
        signature_values: list[int] = []
        for chain, digit in enumerate(digits):
            value = graph.add(
                "prf",
                phase,
                (current_root,),
                name=f"{phase}:selected_chain{chain}:prf",
            )
            if digit == 0:
                graph.mark_signature(
                    value, layer_base + chain * params.n, params.n
                )
                signature_values.append(value)
            steps = digit if layer == params.d - 1 else params.w - 1
            for step in range(1, steps + 1):
                value = graph.add(
                    "f",
                    phase,
                    (value,),
                    name=f"{phase}:selected_chain{chain}:f{step - 1}",
                )
                if step == digit:
                    graph.mark_signature(
                        value, layer_base + chain * params.n, params.n
                    )
                    signature_values.append(value)
            endpoints.append(value)
        final_signature_tasks.extend(signature_values)
        final_signature_tasks.extend(auth_roots)
        if layer < params.d - 1:
            current_root = graph.add(
                "t_l", phase, endpoints, name=f"{phase}:recover_compress"
            )
            for height, sibling in enumerate(auth_roots):
                current_root = graph.add(
                    "h",
                    phase,
                    (current_root, sibling),
                    name=f"{phase}:recover_h{height}",
                )

    graph.final_tasks = tuple(final_signature_tasks)
    graph.validate_signature_map()
    return graph


def build_verify_graph(
    message: bytes,
    signature: bytes,
    public_key: bytes,
    params: SlhDsaParams = SLH_DSA_SHAKE_128F,
) -> HashTaskGraph:
    expected = params.n + params.k * (params.a + 1) * params.n + (
        params.h + params.d * params.wots_len
    ) * params.n
    if len(signature) != expected or len(public_key) != 2 * params.n:
        raise ValueError("invalid SLH-DSA signature or public-key length")
    graph = HashTaskGraph("verify", params)
    hmsg_perms = (3 * params.n + len(message)) // 136 + 1
    digest_task = graph.add(
        "h_msg",
        "verify:message",
        permutations=hmsg_perms,
        name="verify:message_digest",
    )

    fors_roots: list[int] = []
    for tree in range(params.k):
        phase = f"verify:fors{tree}"
        node = graph.add("f", phase, (digest_task,), name=f"{phase}:leaf")
        for height in range(params.a):
            node = graph.add("h", phase, (node,), name=f"{phase}:h{height}")
        fors_roots.append(node)
    current_root = graph.add(
        "t_l", "verify:fors_roots", fors_roots, name="verify:fors_roots:compress"
    )

    # Reuse the same byte-exact reference walk as Sign to obtain the changing
    # message/digits for all 22 XMSS layers without weakening graph semantics.
    _signature, layer_digits = _verify_layer_digits(
        message, signature, public_key, params
    )
    for layer, digits in enumerate(layer_digits):
        phase = f"verify:xmss{layer}"
        endpoints: list[int] = []
        for chain, digit in enumerate(digits):
            remaining = params.w - 1 - digit
            value: int | None = None
            for step in range(remaining):
                dependencies = (current_root,) if value is None else (value,)
                value = graph.add(
                    "f",
                    phase,
                    dependencies,
                    name=f"{phase}:chain{chain}:f{digit + step}",
                )
            if value is not None:
                endpoints.append(value)
        node = graph.add(
            "t_l",
            phase,
            (current_root, *endpoints),
            name=f"{phase}:compress",
        )
        for height in range(params.hp):
            node = graph.add("h", phase, (node,), name=f"{phase}:h{height}")
        current_root = node
    graph.final_tasks = (current_root,)
    return graph


def _fors_address(tree_index: int, leaf_index: int) -> list[int]:
    address = [0] * 8
    _set_tree_address(address, tree_index)
    _set_type_and_clear(address, FORS_TREE)
    address[5] = leaf_index
    return address


def _verify_layer_digits(
    message: bytes,
    signature: bytes,
    public_key: bytes,
    params: SlhDsaParams,
) -> tuple[bytes, list[list[int]]]:
    """Walk Verify with the reference functions and return layer messages."""
    public_seed = public_key[: params.n]
    public_root = public_key[params.n :]
    randomizer = signature[: params.n]
    digest = _hash_message(params, randomizer, public_seed, public_root, message)
    fors_bytes = (params.k * params.a + 7) // 8
    tree_bits = params.h - params.hp
    tree_bytes = (tree_bits + 7) // 8
    leaf_bytes = (params.hp + 7) // 8
    message_digest = digest[:fors_bytes]
    offset = fors_bytes
    tree_index = int.from_bytes(digest[offset : offset + tree_bytes], "big") % (
        1 << tree_bits
    )
    offset += tree_bytes
    leaf_index = int.from_bytes(digest[offset : offset + leaf_bytes], "big") % (
        1 << params.hp
    )
    fors_signature_bytes = params.k * (params.a + 1) * params.n
    address = _fors_address(tree_index, leaf_index)
    root = _fors_pk_from_sig(
        params,
        signature[params.n : params.n + fors_signature_bytes],
        message_digest,
        public_seed,
        address,
    )
    hypertree = signature[params.n + fors_signature_bytes :]
    xmss_bytes = (params.wots_len + params.hp) * params.n
    digits: list[list[int]] = []
    for layer in range(params.d):
        digits.append(_wots_digits(params, root))
        part = hypertree[layer * xmss_bytes : (layer + 1) * xmss_bytes]
        address = [0] * 8
        address[0] = layer
        _set_tree_address(address, tree_index)
        root = _xmss_pk_from_sig(
            params, leaf_index, part, root, public_seed, address
        )
        if layer < params.d - 1:
            leaf_index = tree_index % (1 << params.hp)
            tree_index >>= params.hp
    return root, digits


def _critical_priorities(
    graph: HashTaskGraph, config: ScheduleConfig
) -> list[int]:
    dependents: list[list[int]] = [[] for _ in graph.tasks]
    for task in graph.tasks:
        for dependency in task.dependencies:
            dependents[dependency].append(task.task_id)
    priority = [0] * len(graph.tasks)
    for task in reversed(graph.tasks):
        tail = max((priority[item] for item in dependents[task.task_id]), default=0)
        priority[task.task_id] = config.duration(task) + tail
    return priority


def schedule_graph(
    graph: HashTaskGraph,
    config: ScheduleConfig,
) -> ScheduleResult:
    count = len(graph.tasks)
    indegree = [len(task.dependencies) for task in graph.tasks]
    dependents: list[list[int]] = [[] for _ in graph.tasks]
    for task in graph.tasks:
        for dependency in task.dependencies:
            dependents[dependency].append(task.task_id)
    critical = _critical_priorities(graph, config)

    def ready_key(task_id: int) -> tuple[int, int, int]:
        task = graph.tasks[task_id]
        if config.policy == "fifo":
            return (task_id, 0, task_id)
        if config.policy == "signature":
            signature_key = (
                task.signature_offset
                if task.signature_offset is not None
                else graph.signature_bytes + task_id
            )
            return (signature_key, -critical[task_id], task_id)
        return (-critical[task_id], task.signature_offset or 0, task_id)

    ready: list[tuple[int, int, int]] = []
    for task in graph.tasks:
        if indegree[task.task_id] == 0:
            heapq.heappush(ready, ready_key(task.task_id))
    running: list[tuple[int, int, int]] = []
    lane_free = [0] * config.lanes
    lane_active = [0] * config.lanes
    lane_tasks = [0] * config.lanes
    starts = [-1] * count
    finishes = [-1] * count
    lanes = [-1] * count
    completed = 0
    now = 0
    issue_stalls = 0
    maximum_ready = len(ready)

    while completed < count:
        while running and running[0][0] <= now:
            finish, lane, task_id = heapq.heappop(running)
            lane_free[lane] = finish
            completed += 1
            for child in dependents[task_id]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    heapq.heappush(ready, ready_key(child))
            maximum_ready = max(maximum_ready, len(ready))

        free_lanes = [lane for lane, free in enumerate(lane_free) if free <= now]
        issued = 0
        while ready and free_lanes and issued < config.issue_width:
            _key0, _key1, task_id = heapq.heappop(ready)
            lane = free_lanes.pop(0)
            task = graph.tasks[task_id]
            duration = config.duration(task)
            finish = now + duration
            starts[task_id] = now
            finishes[task_id] = finish
            lanes[task_id] = lane
            lane_free[lane] = finish
            lane_active[lane] += duration
            lane_tasks[lane] += 1
            heapq.heappush(running, (finish, lane, task_id))
            issued += 1

        if completed == count:
            break
        if ready and any(free <= now for free in lane_free):
            # Ready work and a free lane remain, but the microcode issue width
            # has been consumed for this cycle.
            issue_stalls += 1
            now += 1
        elif running:
            now = max(now + (1 if issued else 0), running[0][0])
        elif ready:
            now += 1
        else:
            raise ValueError("task graph is cyclic or disconnected")

    hash_cycles = max(finishes, default=0)
    if any(value < 0 for value in starts + finishes + lanes):
        raise AssertionError("scheduler left a task unassigned")
    for task in graph.tasks:
        if any(finishes[parent] > starts[task.task_id] for parent in task.dependencies):
            raise AssertionError(f"dependency violation at task {task.task_id}")

    signature_stream_cycles = 0
    completion_cycles = hash_cycles
    maximum_reorder_bytes = 0
    if graph.signature_bytes:
        producers = sorted(
            (task for task in graph.tasks if task.signature_offset is not None),
            key=lambda task: task.signature_offset,
        )
        stream_time = 0
        emitted = 0
        for task in producers:
            ready_time = finishes[task.task_id]
            maximum_reorder_bytes = max(
                maximum_reorder_bytes,
                sum(
                    other.signature_bytes
                    for other in producers
                    if other.signature_offset is not None
                    and other.signature_offset >= emitted
                    and finishes[other.task_id] <= ready_time
                ),
            )
            stream_time = max(stream_time, ready_time)
            stream_time += math.ceil(
                task.signature_bytes / config.output_bytes_per_cycle
            )
            emitted += task.signature_bytes
        signature_stream_cycles = stream_time
        completion_cycles = max(hash_cycles, stream_time)

    return ScheduleResult(
        config=config,
        operation=graph.operation,
        hash_cycles=hash_cycles,
        completion_cycles=completion_cycles,
        signature_stream_cycles=signature_stream_cycles,
        active_lane_cycles=sum(lane_active),
        lane_active_cycles=tuple(lane_active),
        lane_task_counts=tuple(lane_tasks),
        task_start=tuple(starts),
        task_finish=tuple(finishes),
        task_lane=tuple(lanes),
        critical_path_cycles=max(critical, default=0),
        issue_stall_cycles=issue_stalls,
        maximum_ready_depth=maximum_ready,
        maximum_signature_reorder_bytes=maximum_reorder_bytes,
    )


def phase_counts(graph: HashTaskGraph) -> dict[str, dict[str, int]]:
    result: dict[str, Counter[str]] = defaultdict(Counter)
    for task in graph.tasks:
        family = ":".join(task.phase.split(":")[:2])
        result[family][task.hash_class] += 1
    return {
        phase: dict(sorted(counts.items()))
        for phase, counts in sorted(result.items())
    }
