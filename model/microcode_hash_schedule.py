"""Hash-granularity scheduling derived exclusively from executed microcode.

The interpreter supplies generic provenance for HASH requests and the
internal parent Hashes performed by TREE_PUSH.  This module does not know
about FORS, XMSS, WOTS, or any other algorithm phase.
"""

from __future__ import annotations

from dataclasses import dataclass
import heapq
import math
from typing import Any

from model.interpreter import ExecutionResult


@dataclass(frozen=True)
class TraceHashTask:
    task_id: int
    instruction_seq: int
    pc: int
    layout_id: int
    hash_class: str
    permutations: int
    dependencies: tuple[int, ...]
    original_lane: int
    source_opcode: str


@dataclass(frozen=True)
class TraceScheduleResult:
    policy: str
    window_entries: int
    lanes: int
    unroll: int
    issue_width: int
    request_fifo_depth: int
    hash_overhead_cycles: int
    respect_instruction_release: bool
    hash_cycles: int
    active_lane_cycles: int
    lane_active_cycles: tuple[int, ...]
    lane_task_counts: tuple[int, ...]
    maximum_window_occupancy: int
    maximum_ready_in_window: int
    maximum_request_fifo_depth: int
    task_start: tuple[int, ...]
    task_finish: tuple[int, ...]
    task_lane: tuple[int, ...]

    @property
    def lane_utilization(self) -> float:
        denominator = self.lanes * self.hash_cycles
        return self.active_lane_cycles / denominator if denominator else 0.0

    def summary(self) -> dict[str, Any]:
        return {
            "configuration": {
                "policy": self.policy,
                "window_entries": self.window_entries,
                "K": self.lanes,
                "U": self.unroll,
                "issue_width": self.issue_width,
                "request_fifo_depth": self.request_fifo_depth,
                "hash_overhead_cycles": self.hash_overhead_cycles,
                "respect_instruction_release": self.respect_instruction_release,
            },
            "hash_cycles": self.hash_cycles,
            "active_lane_cycles": self.active_lane_cycles,
            "lane_active_cycles": list(self.lane_active_cycles),
            "lane_task_counts": list(self.lane_task_counts),
            "lane_utilization": self.lane_utilization,
            "maximum_window_occupancy": self.maximum_window_occupancy,
            "maximum_ready_in_window": self.maximum_ready_in_window,
            "maximum_request_fifo_depth": self.maximum_request_fifo_depth,
        }


def extract_hash_tasks(result: ExecutionResult) -> tuple[TraceHashTask, ...]:
    """Extract the exact Hash request DAG from a full interpreter trace."""
    if len(result.trace) != result.counters["dynamic_instructions"]:
        raise ValueError("Hash dependency extraction requires trace_mode='full'")
    rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for instruction in result.trace:
        if instruction["opcode"] == "HASH":
            for hash_event in instruction.get("hash_lanes", (instruction,)):
                rows.append((instruction, hash_event))
        elif instruction["opcode"] == "TREE_PUSH":
            for hash_event in instruction.get("tree_hashes", ()):
                rows.append((instruction, hash_event))
    rows.sort(key=lambda item: int(item[1]["hash_id"]))

    tasks: list[TraceHashTask] = []
    for expected_id, (instruction, event) in enumerate(rows):
        task_id = int(event["hash_id"])
        if task_id != expected_id:
            raise ValueError("microcode Hash IDs are not contiguous")
        dependencies = tuple(int(value) for value in event["dependency_hash_ids"])
        if any(value < 0 or value >= task_id for value in dependencies):
            raise ValueError(f"invalid Hash dependency at task {task_id}")
        tasks.append(
            TraceHashTask(
                task_id=task_id,
                instruction_seq=int(instruction["seq"]),
                pc=int(instruction["pc"]),
                layout_id=int(instruction["layout_id"]),
                hash_class=str(event["hash_class"]),
                permutations=int(event["hash_input_length"]) // 136 + 1,
                dependencies=dependencies,
                original_lane=int(event.get("lane", 1)),
                source_opcode=str(instruction["opcode"]),
            )
        )
    if len(tasks) != result.counters["hash_calls"]:
        raise ValueError("trace Hash task count does not match interpreter counter")
    if sum(task.permutations for task in tasks) != result.counters[
        "keccak_permutations"
    ]:
        raise ValueError("trace permutation count does not match interpreter counter")
    return tuple(tasks)


def _critical_priorities(
    tasks: tuple[TraceHashTask, ...], rounds_cycles: int, overhead: int
) -> list[int]:
    children: list[list[int]] = [[] for _ in tasks]
    for task in tasks:
        for dependency in task.dependencies:
            children[dependency].append(task.task_id)
    priorities = [0] * len(tasks)
    for task in reversed(tasks):
        duration = task.permutations * rounds_cycles + overhead
        priorities[task.task_id] = duration + max(
            (priorities[child] for child in children[task.task_id]), default=0
        )
    return priorities


def schedule_hash_tasks(
    tasks: tuple[TraceHashTask, ...],
    *,
    policy: str = "window_fifo",
    window_entries: int = 16,
    lanes: int = 2,
    unroll: int = 2,
    issue_width: int = 1,
    request_fifo_depth: int = 4,
    hash_overhead_cycles: int = 0,
    respect_instruction_release: bool = True,
) -> TraceScheduleResult:
    """Schedule trace-derived requests through a bounded generic issue window."""
    if policy not in {"program_order", "window_fifo", "window_critical"}:
        raise ValueError("unsupported scheduling policy")
    if window_entries <= 0 or lanes <= 0 or issue_width <= 0:
        raise ValueError("window, lanes, and issue width must be positive")
    if request_fifo_depth <= 0 or hash_overhead_cycles < 0:
        raise ValueError("invalid FIFO depth or Hash overhead")
    if not 1 <= unroll <= 24:
        raise ValueError("unroll must be in 1..24")

    count = len(tasks)
    rounds_cycles = math.ceil(24 / unroll)
    priorities = _critical_priorities(tasks, rounds_cycles, hash_overhead_cycles)
    remaining_dependencies = [len(task.dependencies) for task in tasks]
    children: list[list[int]] = [[] for _ in tasks]
    for task in tasks:
        for dependency in task.dependencies:
            children[dependency].append(task.task_id)
    completed = [False] * count
    pending: set[int] = set()
    ready_heap: list[tuple[int, int]] = []
    next_task = 0
    request_fifo: list[int] = []
    running: list[tuple[int, int, int]] = []
    lane_free = [0] * lanes
    lane_active = [0] * lanes
    lane_task_counts = [0] * lanes
    starts = [-1] * count
    finishes = [-1] * count
    assigned_lanes = [-1] * count
    completed_count = 0
    now = 0
    maximum_window = 0
    maximum_ready = 0
    maximum_fifo = 0

    def ready_key(task_id: int) -> tuple[int, int]:
        if policy == "window_critical":
            return (-priorities[task_id], task_id)
        return (task_id, task_id)

    def fill_window() -> None:
        nonlocal next_task, maximum_window
        while (
            next_task < count
            and len(pending) < window_entries
            and (
                not respect_instruction_release
                or tasks[next_task].instruction_seq <= now
            )
        ):
            pending.add(next_task)
            if remaining_dependencies[next_task] == 0:
                heapq.heappush(ready_heap, ready_key(next_task))
            next_task += 1
        maximum_window = max(maximum_window, len(pending))

    def next_ready() -> int | None:
        if policy == "program_order":
            head = min(pending, default=None)
            return (
                head
                if head is not None and remaining_dependencies[head] == 0
                else None
            )
        while ready_heap and ready_heap[0][1] not in pending:
            heapq.heappop(ready_heap)
        return ready_heap[0][1] if ready_heap else None

    def ready_count() -> int:
        if policy == "program_order":
            return int(next_ready() is not None)
        return sum(
            1
            for _key, task_id in ready_heap
            if task_id in pending and remaining_dependencies[task_id] == 0
        )

    def dispatch() -> None:
        free_lanes = [lane for lane, free in enumerate(lane_free) if free <= now]
        while request_fifo and free_lanes:
            task_id = request_fifo.pop(0)
            lane = free_lanes.pop(0)
            task = tasks[task_id]
            duration = (
                task.permutations * rounds_cycles + hash_overhead_cycles
            )
            finish = now + duration
            starts[task_id] = now
            finishes[task_id] = finish
            assigned_lanes[task_id] = lane
            lane_free[lane] = finish
            lane_active[lane] += duration
            lane_task_counts[lane] += 1
            heapq.heappush(running, (finish, lane, task_id))

    fill_window()
    while completed_count < count:
        while running and running[0][0] <= now:
            _finish, _lane, task_id = heapq.heappop(running)
            completed[task_id] = True
            completed_count += 1
            for child in children[task_id]:
                remaining_dependencies[child] -= 1
                if remaining_dependencies[child] == 0 and child in pending:
                    heapq.heappush(ready_heap, ready_key(child))

        fill_window()
        dispatch()
        maximum_ready = max(maximum_ready, ready_count())
        issued = 0
        while (
            next_ready() is not None
            and issued < issue_width
            and len(request_fifo) < request_fifo_depth
        ):
            task_id = next_ready()
            if task_id is None:
                break
            if policy != "program_order":
                heapq.heappop(ready_heap)
            pending.remove(task_id)
            request_fifo.append(task_id)
            issued += 1
            maximum_fifo = max(maximum_fifo, len(request_fifo))
            fill_window()
            maximum_ready = max(maximum_ready, ready_count())
        dispatch()

        if completed_count == count:
            break
        candidates: list[int] = []
        if next_ready() is not None and len(request_fifo) < request_fifo_depth:
            candidates.append(now + 1)
        if running:
            candidates.append(running[0][0])
        if request_fifo and any(free <= now for free in lane_free):
            candidates.append(now + 1)
        if (
            respect_instruction_release
            and next_task < count
            and len(pending) < window_entries
        ):
            candidates.append(max(now + 1, tasks[next_task].instruction_seq))
        if not candidates:
            raise ValueError(
                "trace schedule deadlocked; increase the window or check dependencies"
            )
        now = min(value for value in candidates if value > now)

    if any(value < 0 for value in starts + finishes + assigned_lanes):
        raise AssertionError("trace scheduler left a Hash task unassigned")
    for task in tasks:
        if any(finishes[parent] > starts[task.task_id] for parent in task.dependencies):
            raise AssertionError(f"dependency violation at Hash task {task.task_id}")
    expected_active = sum(
        task.permutations * rounds_cycles + hash_overhead_cycles for task in tasks
    )
    if sum(lane_active) != expected_active:
        raise AssertionError("scheduler changed Hash work")

    return TraceScheduleResult(
        policy=policy,
        window_entries=window_entries,
        lanes=lanes,
        unroll=unroll,
        issue_width=issue_width,
        request_fifo_depth=request_fifo_depth,
        hash_overhead_cycles=hash_overhead_cycles,
        respect_instruction_release=respect_instruction_release,
        hash_cycles=max(finishes, default=0),
        active_lane_cycles=sum(lane_active),
        lane_active_cycles=tuple(lane_active),
        lane_task_counts=tuple(lane_task_counts),
        maximum_window_occupancy=maximum_window,
        maximum_ready_in_window=maximum_ready,
        maximum_request_fifo_depth=maximum_fifo,
        task_start=tuple(starts),
        task_finish=tuple(finishes),
        task_lane=tuple(assigned_lanes),
    )
