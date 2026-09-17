"""Encoding and offline pairing for the 128-bit horizontal μHBS ISA.

This module contains no SLH-DSA control opcodes.  The 48-bit lane command is
an index/argument tuple for a generic hash-context materializer.  Algorithm
knowledge stays in the compiler and static context tables.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Iterable, Mapping, Sequence


OP_NOP = 0x0
OP_ISSUE = 0x1
OP_WAIT = 0x2
OP_HALT = 0xF

HASH_RECIPES = {
    "prf_msg": 1,
    "h_msg": 2,
    "prf": 3,
    "f": 4,
    "h": 5,
    "t_l": 6,
}


@dataclass(frozen=True)
class ContextCommand:
    """Generic context-table lookup plus compact affine arguments."""

    recipe: int
    destination: int = 0
    argument_register: int = 0
    index: int = 0

    def encode(self) -> int:
        for value, width, name in (
            (self.recipe, 8, "recipe"),
            (self.destination, 12, "destination"),
            (self.argument_register, 4, "argument_register"),
            (self.index, 24, "index"),
        ):
            if not 0 <= value < (1 << width):
                raise ValueError(f"{name} does not fit {width} bits: {value}")
        return (
            (self.recipe << 40)
            | (self.destination << 28)
            | (self.argument_register << 24)
            | self.index
        )

    @classmethod
    def decode(cls, encoded: int) -> "ContextCommand":
        if not 0 <= encoded < (1 << 48):
            raise ValueError("context command does not fit 48 bits")
        return cls(
            recipe=(encoded >> 40) & 0xFF,
            destination=(encoded >> 28) & 0xFFF,
            argument_register=(encoded >> 24) & 0xF,
            index=encoded & 0xFFFFFF,
        )


@dataclass(frozen=True)
class HorizontalWord:
    opcode: int
    wait_mask: int = 0
    consume_mask: int = 0
    lane0_valid: bool = False
    lane1_valid: bool = False
    lane0_event: int = 0
    lane1_event: int = 0
    lane0_command: int = 0
    lane1_command: int = 0
    lane0_track: bool = False
    lane1_track: bool = False

    def encode(self) -> int:
        for value, width, name in (
            (self.opcode, 4, "opcode"),
            (self.wait_mask, 8, "wait_mask"),
            (self.consume_mask, 8, "consume_mask"),
            (self.lane0_event, 3, "lane0_event"),
            (self.lane1_event, 3, "lane1_event"),
            (self.lane0_command, 48, "lane0_command"),
            (self.lane1_command, 48, "lane1_command"),
        ):
            if not 0 <= value < (1 << width):
                raise ValueError(f"{name} does not fit {width} bits: {value}")
        if self.lane0_valid and self.lane1_valid \
                and self.lane0_track and self.lane1_track \
                and self.lane0_event == self.lane1_event:
            raise ValueError("two lanes cannot allocate the same event")
        return (
            (self.opcode << 124)
            | (self.wait_mask << 116)
            | (self.consume_mask << 108)
            | (int(self.lane0_valid) << 107)
            | (int(self.lane1_valid) << 106)
            | (self.lane0_event << 103)
            | (self.lane1_event << 100)
            | (self.lane0_command << 52)
            | (self.lane1_command << 4)
            | (int(self.lane0_track) << 3)
            | (int(self.lane1_track) << 2)
        )

    @classmethod
    def decode(cls, encoded: int) -> "HorizontalWord":
        if not 0 <= encoded < (1 << 128):
            raise ValueError("horizontal word does not fit 128 bits")
        if encoded & 0x3:
            raise ValueError("reserved low bits are nonzero")
        return cls(
            opcode=(encoded >> 124) & 0xF,
            wait_mask=(encoded >> 116) & 0xFF,
            consume_mask=(encoded >> 108) & 0xFF,
            lane0_valid=bool((encoded >> 107) & 1),
            lane1_valid=bool((encoded >> 106) & 1),
            lane0_event=(encoded >> 103) & 7,
            lane1_event=(encoded >> 100) & 7,
            lane0_command=(encoded >> 52) & ((1 << 48) - 1),
            lane1_command=(encoded >> 4) & ((1 << 48) - 1),
            lane0_track=bool((encoded >> 3) & 1),
            lane1_track=bool((encoded >> 2) & 1),
        )


def _independent(left: Mapping[str, object], right: Mapping[str, object]) -> bool:
    left_id = int(left["task_id"])
    right_id = int(right["task_id"])
    left_dependencies = {int(value) for value in left.get("dependencies", ())}
    right_dependencies = {int(value) for value in right.get("dependencies", ())}
    return left_id not in right_dependencies and right_id not in left_dependencies


def pair_offline_schedule(
    tasks: Iterable[Mapping[str, object]],
) -> list[tuple[Mapping[str, object], ...]]:
    """Pair adjacent independent tasks in an already-valid static schedule."""

    ordered = sorted(tasks, key=lambda task: (
        int(task.get("start", 0)), int(task.get("lane", 0)),
        int(task["task_id"]),
    ))
    batches: list[tuple[Mapping[str, object], ...]] = []
    pending: Mapping[str, object] | None = None
    for task in ordered:
        if pending is None:
            pending = task
        elif _independent(pending, task):
            batches.append((pending, task))
            pending = None
        else:
            batches.append((pending,))
            pending = task
    if pending is not None:
        batches.append((pending,))
    return batches


def compile_barrier_program(
    tasks: Iterable[Mapping[str, object]],
) -> tuple[list[HorizontalWord], dict[str, int | float]]:
    """Compile a safe two-lane program with one barrier between task pairs.

    This intentionally simple first lowering uses only events 0 and 1.  It is
    a correctness baseline for later affine-loop/context folding, not the
    final ROM-density strategy.
    """

    batches = pair_offline_schedule(tasks)
    words: list[HorizontalWord] = []
    previous_mask = 0
    active_cycles = 0
    service_cycles = 0
    singleton_batches = 0
    permutations = 0
    for batch in batches:
        if len(batch) == 1:
            singleton_batches += 1
        current_mask = (1 << len(batch)) - 1
        commands = []
        durations = []
        for task in batch:
            hash_class = str(task["hash_class"])
            if hash_class not in HASH_RECIPES:
                raise ValueError(f"unknown hash recipe: {hash_class}")
            task_id = int(task["task_id"])
            commands.append(ContextCommand(
                recipe=HASH_RECIPES[hash_class], index=task_id
            ).encode())
            task_permutations = int(task["permutations"])
            permutations += task_permutations
            durations.append(task_permutations * 12)
        active_cycles += max(durations)
        # Direct U2 lane: one acceptance boundary plus 12 active cycles per
        # permutation. Fetch of the next word overlaps this service time.
        service_cycles += max(durations) + 1
        words.append(HorizontalWord(
            opcode=OP_ISSUE,
            wait_mask=previous_mask,
            consume_mask=previous_mask,
            lane0_valid=True,
            lane1_valid=len(batch) == 2,
            lane0_event=0,
            lane1_event=1,
            lane0_command=commands[0],
            lane1_command=commands[1] if len(commands) == 2 else 0,
            lane0_track=True,
            lane1_track=len(batch) == 2,
        ))
        previous_mask = current_mask
    words.append(HorizontalWord(opcode=OP_HALT))
    bits = len(words) * 128
    metrics: dict[str, int | float] = {
        "tasks": sum(len(batch) for batch in batches),
        "permutations": permutations,
        "issue_words": len(batches),
        "program_words": len(words),
        "program_bytes": bits // 8,
        "equivalent_ramb36": ceil(bits / 36864),
        "singleton_batches": singleton_batches,
        "u2_active_cycle_projection": active_cycles,
        "direct_lane_service_cycle_projection": service_cycles + 3,
        "lane_slot_utilization": (
            sum(len(batch) for batch in batches) / (2 * len(batches))
            if batches else 0.0
        ),
    }
    return words, metrics
