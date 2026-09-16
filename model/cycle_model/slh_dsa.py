"""RTL-calibrated cycle accounting for complete SLH-DSA Hash traces.

This module deliberately does not claim a complete RTL latency.  It combines
three contracts which are already executable in the project:

* the complete, oracle-equal ordered Hash trace;
* the current synchronous Microsequencer's FETCH/RUN cost;
* the U2 SHAKE stream and 64-bit output-stream no-stall service costs.

All unimplemented full-top costs remain explicit in the returned report.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any


SHAKE256_RATE_BYTES = 136
U2_PERMUTATION_ROUND_CYCLES = 12
# Measured by tb_micro_hbs_shake256_stream_cycles for 1/2/5 blocks.
U2_STREAM_CYCLES_PER_BLOCK = 15
MICROSEQUENCER_FETCH_RUN_CYCLES = 2
# One request, one synchronous response and one accepted 64-bit output beat.
OUTPUT_STREAM_CYCLES_PER_WORD_NO_STALL = 3


def shake_permutations(input_bytes: int, output_bytes: int) -> int:
    if input_bytes < 0 or output_bytes <= 0:
        raise ValueError("invalid SHAKE input/output length")
    absorb = input_bytes // SHAKE256_RATE_BYTES + 1
    squeeze = max(0, (output_bytes + SHAKE256_RATE_BYTES - 1)
                  // SHAKE256_RATE_BYTES - 1)
    return absorb + squeeze


@dataclass
class _ClassCounter:
    calls: int = 0
    permutations: int = 0
    rtl_u2_stream_cycles: int = 0
    input_bytes: int = 0
    output_bytes: int = 0


class ShakeTraceMeter:
    """Accumulate exact message lengths while the independent oracle runs."""

    def __init__(self) -> None:
        self.calls = 0
        self.permutations = 0
        self.rtl_u2_stream_cycles = 0
        self.input_bytes = 0
        self.output_bytes = 0
        self._classes: dict[str, _ClassCounter] = defaultdict(_ClassCounter)

    def observe(self, kind: str, data: bytes, value: bytes) -> None:
        permutations = shake_permutations(len(data), len(value))
        stream_cycles = permutations * U2_STREAM_CYCLES_PER_BLOCK
        self.calls += 1
        self.permutations += permutations
        self.rtl_u2_stream_cycles += stream_cycles
        self.input_bytes += len(data)
        self.output_bytes += len(value)
        counter = self._classes[kind]
        counter.calls += 1
        counter.permutations += permutations
        counter.rtl_u2_stream_cycles += stream_cycles
        counter.input_bytes += len(data)
        counter.output_bytes += len(value)

    def class_breakdown(self) -> dict[str, dict[str, int]]:
        return {
            name: {
                "hash_calls": counter.calls,
                "keccak_permutations": counter.permutations,
                "rtl_u2_stream_cycles": counter.rtl_u2_stream_cycles,
                "input_bytes": counter.input_bytes,
                "output_bytes": counter.output_bytes,
            }
            for name, counter in sorted(self._classes.items())
        }


def build_current_u2_report(
    *,
    operation: str,
    dynamic_instructions: int,
    operation_output_bytes: int,
    meter: ShakeTraceMeter,
    frequency_mhz: float = 100.0,
) -> dict[str, Any]:
    if dynamic_instructions <= 0 or operation_output_bytes <= 0:
        raise ValueError("operation counters must be positive")
    if frequency_mhz <= 0:
        raise ValueError("frequency must be positive")

    instruction_cycles = (
        dynamic_instructions * MICROSEQUENCER_FETCH_RUN_CYCLES
    )
    output_words = (operation_output_bytes + 7) // 8
    output_cycles = output_words * OUTPUT_STREAM_CYCLES_PER_WORD_NO_STALL
    accounted_cycles = (
        instruction_cycles + meter.rtl_u2_stream_cycles + output_cycles
    )
    p1_round_floor = meter.permutations * U2_PERMUTATION_ROUND_CYCLES
    p2_round_floor = (
        (meter.permutations + 1) // 2 * U2_PERMUTATION_ROUND_CYCLES
    )

    return {
        "classification": "rtl_calibrated_partial_cycle_measurement",
        "paper_comparable": False,
        "complete_rtl_cycle_count": False,
        "accounted_cycles_are_lower_bound": True,
        "operation": operation,
        "configuration": {
            "current_microcode_effective_parallel_lanes": 1,
            "keccak_unroll": 2,
            "frequency_mhz": frequency_mhz,
            "shake_rate_bytes": SHAKE256_RATE_BYTES,
            "rtl_u2_stream_cycles_per_absorb_or_squeeze_block": (
                U2_STREAM_CYCLES_PER_BLOCK
            ),
            "microsequencer_fetch_run_cycles_per_instruction": (
                MICROSEQUENCER_FETCH_RUN_CYCLES
            ),
            "output_stream_cycles_per_64bit_word_no_stall": (
                OUTPUT_STREAM_CYCLES_PER_WORD_NO_STALL
            ),
        },
        "measured_trace": {
            "dynamic_instructions": dynamic_instructions,
            "hash_calls": meter.calls,
            "keccak_permutations": meter.permutations,
            "hash_input_bytes": meter.input_bytes,
            "hash_output_bytes": meter.output_bytes,
            "operation_output_bytes": operation_output_bytes,
            "hash_class_breakdown": meter.class_breakdown(),
        },
        "cycle_breakdown": {
            "microsequencer_fetch_run_cycles": instruction_cycles,
            "rtl_u2_shake_stream_cycles": meter.rtl_u2_stream_cycles,
            "rtl_64bit_output_stream_cycles_no_stall": output_cycles,
            "accounted_cycles": accounted_cycles,
            "p1_u2_keccak_round_floor_cycles": p1_round_floor,
            "ideal_p2_u2_keccak_round_floor_cycles": p2_round_floor,
            "accounted_latency_ms_at_frequency": (
                accounted_cycles / (frequency_mhz * 1000.0)
            ),
        },
        "excluded_from_accounted_cycles": [
            "complete descriptor-driven composer latency beyond immediate rate-block delivery",
            "AGU and non-output Scratchpad traffic",
            "TreeHash/cache arbitration not overlapped with Hash service",
            "barrier and static P2 lane-tail effects",
            "DMA and external output backpressure",
        ],
    }
