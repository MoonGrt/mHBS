"""Static, data-independent horizontal task microcode for SLH-DSA-128f.

The program describes algorithm tasks, not a trace produced by one message.
Runtime-dependent WOTS bounds and selected authentication paths are resolved by
the RTL materializer from the message digest.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


TOKEN_SINGLE = 0
TOKEN_RUN = 1
TOKEN_LOOP = 2
TOKEN_HALT = 3

OP_ISSUE = 1

RECIPE_MSG_PRF = 1
RECIPE_MSG_DIGEST = 2
RECIPE_ADDR_CHAIN = 3
RECIPE_ADDR_PARENT = 4
RECIPE_LIST = 5
RECIPE_EMIT_AUTH = 6

MODE_FORS = 0
MODE_WOTS = 1
MODE_XMSS = 1

COMMIT_R = 1
COMMIT_HMSG = 2
COMMIT_FORS_LEAF = 3
COMMIT_FORS_PARENT = 4
COMMIT_FORS_ROOT = 5
COMMIT_WOTS_CHAIN = 6
COMMIT_WOTS_LEAF = 7
COMMIT_XMSS_PARENT = 8
COMMIT_EMIT_AUTH = 9


def coordinate(*, layer: int = 0, group: int = 0, height: int = 0,
               item: int = 0, variant: int = 0) -> int:
    for value, limit, name in (
        (layer, 31, "layer"), (group, 63, "group"),
        (height, 7, "height"), (item, 63, "item"),
        (variant, 15, "variant"),
    ):
        if not 0 <= value <= limit:
            raise ValueError(f"{name} out of range: {value}")
    return (layer << 19) | (group << 13) | (height << 10) \
        | (item << 4) | variant


def command(recipe: int, commit: int, mode: int, coord: int = 0) -> int:
    for value, width, name in (
        (recipe, 8, "recipe"), (commit, 12, "commit"),
        (mode, 4, "mode"), (coord, 24, "coordinate"),
    ):
        if not 0 <= value < (1 << width):
            raise ValueError(f"{name} does not fit {width} bits")
    return (recipe << 40) | (commit << 28) | (mode << 24) | coord


def issue_word(command0: int, command1: int = 0, *, lane1: bool = False,
               first: bool = False) -> int:
    """Create one horizontal word.

    Event zero represents completion of the whole materialized batch.  Lane 0
    owns the event even when lane 1 is also active.
    """

    wait = 0 if first else 1
    consume = wait
    return (
        (OP_ISSUE << 124)
        | (wait << 116)
        | (consume << 108)
        | (1 << 107)
        | (int(lane1) << 106)
        | (command0 << 52)
        | (command1 << 4)
        | (1 << 3)
    )


def template_word(word: int) -> int:
    # Coordinates occupy the low 24 bits of each 48-bit command.
    mask = ((1 << 24) - 1) << 52
    mask |= ((1 << 24) - 1) << 4
    return word & ~mask


@dataclass(frozen=True)
class StaticTaskToken:
    kind: int
    template: int = 0
    coord0: int = 0
    coord1: int = 0
    repeat: int = 1
    stride0: int = 0
    stride1: int = 0
    back_count: int = 0
    loop_repeats: int = 0
    delta0: int = 0
    delta1: int = 0

    def encode(self) -> int:
        if self.kind == TOKEN_HALT:
            return 3 << 126
        if self.kind == TOKEN_LOOP:
            if not 1 <= self.back_count <= 4096:
                raise ValueError("LOOP back_count out of range")
            if not 1 <= self.loop_repeats <= 63:
                raise ValueError("LOOP repeats out of range")
            if self.delta0 >= 1 << 24 or self.delta1 >= 1 << 24:
                raise ValueError("LOOP delta out of range")
            return (
                (2 << 126) | ((self.back_count - 1) << 114)
                | (self.loop_repeats << 108) | (self.delta0 << 84)
                | (self.delta1 << 60)
            )
        if self.kind not in (TOKEN_SINGLE, TOKEN_RUN):
            raise ValueError("invalid token kind")
        if not 0 <= self.template < 64:
            raise ValueError("template out of range")
        if not 1 <= self.repeat <= 64:
            raise ValueError("repeat out of range")
        if self.kind == TOKEN_SINGLE and (
                self.repeat != 1 or self.stride0 or self.stride1):
            raise ValueError("SINGLE has RUN fields")
        if self.kind == TOKEN_RUN and self.repeat < 2:
            raise ValueError("RUN must repeat")
        for value in (self.coord0, self.coord1,
                      self.stride0, self.stride1):
            if not 0 <= value < 1 << 24:
                raise ValueError("coordinate/stride out of range")
        return (
            (self.kind << 126) | (self.template << 120)
            | (self.coord0 << 96) | (self.coord1 << 72)
            | ((self.repeat - 1) << 66) | (self.stride0 << 42)
            | (self.stride1 << 18)
        )


def expand(templates: Sequence[int], tokens: Sequence[StaticTaskToken]) \
        -> list[int]:
    words: list[int] = []
    pc = 0
    # pc, remaining additional iterations, current bias0/1, delta0/1
    loops: list[list[int]] = []
    steps = 0
    while pc < len(tokens):
        steps += 1
        if steps > 100000:
            raise ValueError("program did not terminate")
        token = tokens[pc]
        bias0 = sum(frame[2] for frame in loops)
        bias1 = sum(frame[3] for frame in loops)
        if token.kind == TOKEN_HALT:
            words.append(0xF << 124)
            pc += 1
        elif token.kind == TOKEN_LOOP:
            if loops and loops[-1][0] == pc:
                frame = loops[-1]
                if frame[1] > 1:
                    frame[1] -= 1
                    frame[2] += frame[4]
                    frame[3] += frame[5]
                    pc -= token.back_count
                else:
                    loops.pop()
                    pc += 1
            else:
                if len(loops) == 2:
                    raise ValueError("loop stack overflow")
                loops.append([pc, token.loop_repeats, token.delta0,
                              token.delta1, token.delta0, token.delta1])
                pc -= token.back_count
        else:
            if token.template >= len(templates):
                raise ValueError("missing template")
            template = templates[token.template]
            for iteration in range(token.repeat):
                c0 = token.coord0 + bias0 + iteration * token.stride0
                c1 = token.coord1 + bias1 + iteration * token.stride1
                if c0 >= 1 << 24 or c1 >= 1 << 24:
                    raise ValueError("expanded coordinate overflow")
                words.append(template | (c0 << 52) | (c1 << 4))
            pc += 1
    return words
