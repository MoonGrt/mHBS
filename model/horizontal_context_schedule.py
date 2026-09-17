"""Offline schedule for generic HASH/TREE_PUSH execution contexts.

Unlike hash-by-hash scheduling, one context retains a complete repeat chain
or the parent sequence produced by one TREE_PUSH instruction.  This is the
granularity implemented by the horizontal control RTL.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import ceil
from typing import Any

from model.horizontal_microcode import ContextCommand, HorizontalWord, OP_HALT, OP_ISSUE
from model.interpreter import ExecutionResult


@dataclass(frozen=True)
class HashContext:
    context_id: int
    instruction_seq: int
    pc: int
    source_opcode: str
    layout_id: int
    destination: int
    hash_ids: tuple[int, ...]
    dependencies: tuple[int, ...]
    lane_cycles: tuple[int, ...]

    @property
    def width(self) -> int:
        return len(self.lane_cycles)


@dataclass(frozen=True)
class ScheduledContext:
    context: HashContext
    start: int
    finish: int
    lanes: tuple[int, ...]
    wait_dependencies: tuple[int, ...]


def extract_hash_contexts(result: ExecutionResult) -> tuple[HashContext, ...]:
    if len(result.trace) != result.counters["dynamic_instructions"]:
        raise ValueError("context extraction requires trace_mode='full'")
    rows: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    hash_owner: dict[int, int] = {}
    for instruction in result.trace:
        events: list[dict[str, Any]]
        if instruction["opcode"] == "HASH":
            events = list(instruction.get("hash_lanes", ()))
        elif instruction["opcode"] == "TREE_PUSH":
            events = list(instruction.get("tree_hashes", ()))
        else:
            events = []
        if not events:
            continue
        context_id = len(rows)
        for event in events:
            hash_id = int(event["hash_id"])
            if hash_id in hash_owner:
                raise ValueError(f"duplicate hash id {hash_id}")
            hash_owner[hash_id] = context_id
        rows.append((instruction, events))

    contexts: list[HashContext] = []
    for context_id, (instruction, events) in enumerate(rows):
        dependencies = {
            hash_owner[int(dependency)]
            for event in events
            for dependency in event["dependency_hash_ids"]
            if hash_owner[int(dependency)] != context_id
        }
        original_lane_cycles: dict[int, int] = defaultdict(int)
        for event in events:
            permutations = int(event["hash_input_length"]) // 136 + 1
            original_lane_cycles[int(event.get("lane", 0))] += permutations * 12
        if len(original_lane_cycles) > 1:
            lane_cycles = tuple(
                original_lane_cycles[lane]
                for lane in sorted(original_lane_cycles)
            )
        else:
            lane_cycles = (sum(original_lane_cycles.values()),)
        destination = int(instruction.get("effective_address", 0))
        contexts.append(HashContext(
            context_id=context_id,
            instruction_seq=int(instruction["seq"]),
            pc=int(instruction["pc"]),
            source_opcode=str(instruction["opcode"]),
            layout_id=int(instruction["layout_id"]),
            destination=destination,
            hash_ids=tuple(int(event["hash_id"]) for event in events),
            dependencies=tuple(sorted(dependencies)),
            lane_cycles=lane_cycles,
        ))
    if sum(len(context.hash_ids) for context in contexts) != result.counters["hash_calls"]:
        raise ValueError("context grouping changed the Hash count")
    return tuple(contexts)


def schedule_contexts(
    contexts: tuple[HashContext, ...], *, boundary_cycles: int = 0
) -> tuple[ScheduledContext, ...]:
    """Program-order list schedule on two equivalent lanes."""

    lane_free = [0, 0]
    finishes: list[int] = []
    scheduled: list[ScheduledContext] = []
    for context in contexts:
        dependency_ready = max(
            (finishes[dependency] for dependency in context.dependencies),
            default=0,
        )
        critical_dependencies = tuple(
            dependency for dependency in context.dependencies
            if finishes[dependency] == dependency_ready
        )
        if context.width == 2:
            lanes = (0, 1)
            resource_ready = max(lane_free)
            duration = max(context.lane_cycles) + boundary_cycles
            start = max(resource_ready, dependency_ready)
            lane_free = [start + duration, start + duration]
        else:
            lane = min(
                range(2),
                key=lambda item: max(lane_free[item], dependency_ready),
            )
            lanes = (lane,)
            resource_ready = lane_free[lane]
            duration = context.lane_cycles[0] + boundary_cycles
            start = max(resource_ready, dependency_ready)
            lane_free[lane] = start + duration
        wait_dependencies = (
            critical_dependencies if dependency_ready > resource_ready else ()
        )
        finish = start + duration
        finishes.append(finish)
        scheduled.append(ScheduledContext(
            context=context,
            start=start,
            finish=finish,
            lanes=lanes,
            wait_dependencies=wait_dependencies,
        ))

    for item in scheduled:
        if any(scheduled[dependency].finish > item.start
               for dependency in item.context.dependencies):
            raise ValueError("context schedule violates a dependency")
    for lane in range(2):
        lane_items = [item for item in scheduled if lane in item.lanes]
        lane_items.sort(key=lambda item: item.start)
        if any(left.finish > right.start
               for left, right in zip(lane_items, lane_items[1:])):
            raise ValueError("context schedule overlaps one physical lane")
    return tuple(scheduled)


def _allocate_wait_events(
    scheduled: tuple[ScheduledContext, ...],
) -> tuple[dict[int, tuple[int, ...]], dict[int, int], int]:
    consumers: dict[int, list[int]] = defaultdict(list)
    for item in scheduled:
        for producer in item.wait_dependencies:
            consumers[producer].append(item.context.context_id)

    intervals = sorted(
        (
            scheduled[producer].start,
            max(scheduled[consumer].start for consumer in producer_consumers),
            producer,
        )
        for producer, producer_consumers in consumers.items()
    )
    active: list[tuple[int, tuple[int, ...]]] = []
    producer_events: dict[int, tuple[int, ...]] = {}
    consumer_last: dict[int, int] = {}
    maximum_events = 0
    for start, end, producer in intervals:
        active = [(release, tags) for release, tags in active if release > start]
        used = {tag for _, tags in active for tag in tags}
        needed = len(scheduled[producer].lanes)
        free = [tag for tag in range(8) if tag not in used]
        if len(free) < needed:
            raise ValueError("eight event bits are insufficient")
        tags = tuple(free[:needed])
        producer_events[producer] = tags
        active.append((end, tags))
        maximum_events = max(maximum_events, sum(len(tags) for _, tags in active))
        for consumer in consumers[producer]:
            consumer_last[consumer] = max(consumer_last.get(consumer, -1), producer)
    return producer_events, consumer_last, maximum_events


def compile_context_program(
    scheduled: tuple[ScheduledContext, ...],
) -> tuple[list[HorizontalWord], dict[str, int | float]]:
    producer_events, _consumer_last, maximum_events = _allocate_wait_events(scheduled)
    by_start: dict[int, list[ScheduledContext]] = defaultdict(list)
    for item in scheduled:
        by_start[item.start].append(item)

    words: list[HorizontalWord] = []
    for start in sorted(by_start):
        items = by_start[start]
        lane_items: dict[int, ScheduledContext] = {}
        for item in items:
            for lane in item.lanes:
                if lane in lane_items:
                    raise ValueError("two contexts target one lane in one issue word")
                lane_items[lane] = item
        wait_mask = 0
        consume_mask = 0
        for item in items:
            for producer in item.wait_dependencies:
                for tag in producer_events[producer]:
                    wait_mask |= 1 << tag
                    consume_mask |= 1 << tag

        commands = [0, 0]
        events = [0, 0]
        tracks = [False, False]
        for lane, item in lane_items.items():
            context = item.context
            recipe = context.layout_id | (
                0x80 if context.source_opcode == "TREE_PUSH" else 0
            )
            commands[lane] = ContextCommand(
                recipe=recipe,
                # The context table is the single source of truth for the
                # destination.  Keeping it in both the table and command made
                # otherwise identical schedule words needlessly different.
                destination=0,
                argument_register=lane if context.width == 2 else 0,
                index=context.context_id,
            ).encode()
            if context.context_id in producer_events:
                tags = producer_events[context.context_id]
                tag_index = item.lanes.index(lane)
                events[lane] = tags[tag_index]
                tracks[lane] = True
        words.append(HorizontalWord(
            opcode=OP_ISSUE,
            wait_mask=wait_mask,
            consume_mask=consume_mask,
            lane0_valid=0 in lane_items,
            lane1_valid=1 in lane_items,
            lane0_event=events[0],
            lane1_event=events[1],
            lane0_command=commands[0],
            lane1_command=commands[1],
            lane0_track=tracks[0],
            lane1_track=tracks[1],
        ))
    words.append(HorizontalWord(opcode=OP_HALT))

    makespan = max((item.finish for item in scheduled), default=0)
    active_cycles = sum(sum(item.context.lane_cycles) for item in scheduled)
    bits = len(words) * 128
    metrics: dict[str, int | float] = {
        "contexts": len(scheduled),
        "issue_words": len(words) - 1,
        "program_words": len(words),
        "program_bytes": bits // 8,
        "equivalent_ramb36": ceil(bits / 36864),
        "tracked_producers": len(producer_events),
        "maximum_live_events": maximum_events,
        "hash_active_cycles": active_cycles,
        "hash_makespan": makespan,
        "lane_utilization": active_cycles / (2 * makespan) if makespan else 0.0,
    }
    return words, metrics
