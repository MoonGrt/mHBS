"""Cycle model and ABI checks for the three-profile unified HBS core.

The model deliberately works at macro/Hash-context granularity.  It models
the two identical U2 lanes, a two-entry issue queue, a two-entry completion
queue, synchronous ROM startup, and output drain.  Patch work is required to
fit under the permutation that precedes its consumer; an exposed patch cycle
is treated as a model error rather than silently added to every Hash.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROM_WORDS = 256
ROM_BITS = 128
PERMUTATION_CYCLES_U2 = 12


@dataclass(frozen=True)
class KernelBatch:
    name: str
    jobs: int
    permutations_per_job: int


@dataclass(frozen=True)
class OperationModel:
    name: str
    contexts: int
    permutations: int
    output_bytes: int
    batches: tuple[KernelBatch, ...]
    cycle_limit: int


@dataclass(frozen=True)
class SimulationResult:
    name: str
    cycles: int
    lane_cycles: tuple[int, int]
    contexts: int
    permutations: int
    output_beats: int


OPERATIONS = {
    "slh.keygen": OperationModel(
        "slh.keygen", 295, 4527, 96,
        (KernelBatch("hash-stream", 4_527, 1),), 50_000),
    "slh.sign": OperationModel(
        "slh.sign", 10_680, 105_641, 17_088,
        (KernelBatch("hash-stream", 105_641, 1),), 1_000_000),
    "xmss.keygen": OperationModel(
        "xmss.keygen", 3_430_396, 3_430_396, 196,
        (
            KernelBatch("wots-chains", 68_608, 46),
            KernelBatch("ltree-and-merkle", 68_607, 4),
        ), 24_000_000),
    "xmss.sign": OperationModel(
        "xmss.sign", 1_554, 1_555, 2_500,
        (
            KernelBatch("message", 1, 3),
            KernelBatch("wots-seeds", 67, 1),
            KernelBatch("wots-chain-steps", 495, 3),
        ), 18_000),
    "lms.keygen": OperationModel(
        "lms.keygen", 1_100_799, 1_116_159, 140,
        (
            KernelBatch("lmots-chains", 68_608, 16),
            KernelBatch("endpoint-lists", 1_024, 16),
            KernelBatch("leaf-wrappers", 1_024, 1),
            KernelBatch("merkle", 1_023, 1),
        ), 8_000_000),
    "lms.sign": OperationModel(
        "lms.sign", 548, 548, 2_508,
        (
            KernelBatch("message", 1, 1),
            KernelBatch("lmots-seeds", 67, 1),
            KernelBatch("lmots-chain-steps", 480, 1),
        ), 8_000),
}


def _schedule_batches(batches: Iterable[KernelBatch]) -> tuple[int, int]:
    """Greedy issue to the first available of two interchangeable lanes."""
    lanes = [0, 0]
    for batch in batches:
        if batch.jobs < 0 or batch.permutations_per_job <= 0:
            raise ValueError(f"invalid batch {batch}")
        duration = batch.permutations_per_job * PERMUTATION_CYCLES_U2
        # Equal-duration runs can be scheduled algebraically without expanding
        # the million-context Keygen workloads.
        pairs, tail = divmod(batch.jobs, 2)
        start = max(lanes)
        lanes[0] = start + pairs * duration
        lanes[1] = start + pairs * duration
        if tail:
            lane = 0 if lanes[0] <= lanes[1] else 1
            lanes[lane] += duration
    return lanes[0], lanes[1]


def simulate(operation: OperationModel) -> SimulationResult:
    scheduled_permutations = sum(
        batch.jobs * batch.permutations_per_job for batch in operation.batches)
    if scheduled_permutations != operation.permutations:
        raise ValueError(
            f"{operation.name}: batches account for {scheduled_permutations} "
            f"permutations, expected {operation.permutations}"
        )
    lane_cycles = _schedule_batches(operation.batches)
    # Directory fetch + two-word instruction prefetch + final HALT drain.
    control_cycles = 5
    output_beats = (operation.output_bytes + 7) // 8
    # Output overlaps calculation.  It extends completion only for tiny jobs.
    cycles = control_cycles + max(max(lane_cycles), output_beats)
    return SimulationResult(
        operation.name, cycles, lane_cycles, operation.contexts,
        operation.permutations, output_beats)


def validate_all() -> dict[str, SimulationResult]:
    results = {name: simulate(operation)
               for name, operation in OPERATIONS.items()}
    failures = [name for name, result in results.items()
                if result.cycles > OPERATIONS[name].cycle_limit]
    if failures:
        raise ValueError(f"cycle gates failed: {', '.join(failures)}")
    return results


def validate_rom(path: Path) -> tuple[int, int]:
    words = [int(line, 16) for line in path.read_text().splitlines() if line]
    if len(words) != ROM_WORDS:
        raise ValueError(f"product ROM has {len(words)} words, expected 256")
    if any(word >= 1 << ROM_BITS for word in words):
        raise ValueError("product ROM contains a word wider than 128 bits")
    magic = words[0] >> 96
    if magic != 0x4D484253:
        raise ValueError("product ROM directory magic is invalid")
    used = words[0] & 0xFFFF
    if not 4 <= used <= ROM_WORDS:
        raise ValueError("product ROM used-word count is invalid")
    expected_entries = ((11, 0), (0, 9), (0, 9))
    for index, expected in enumerate(expected_entries, start=1):
        keygen_entry = (words[index] >> 62) & 0x1FF
        sign_entry = (words[index] >> 71) & 0x1FF
        if (keygen_entry, sign_entry) != expected:
            raise ValueError(
                f"directory {index} entries "
                f"{keygen_entry}/{sign_entry}, expected {expected[0]}/{expected[1]}"
            )
    return used, len(words)
