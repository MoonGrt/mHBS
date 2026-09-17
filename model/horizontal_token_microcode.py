"""Lossless template/RLE encoding for 128-bit horizontal microcode.

The control word remains the architectural representation.  Compression is
only a storage encoding: a small distributed template table holds every bit
except the two context indices, while a 64-bit token supplies affine context
indices for one or more consecutive issues.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Sequence

from model.horizontal_microcode import HorizontalWord, OP_HALT, OP_ISSUE


TOKEN_SINGLE = 0
TOKEN_RUN = 1
TOKEN_LOOP = 2
TOKEN_HALT = 3
MAX_TEMPLATES = 64
MAX_CONTEXT = (1 << 13) - 1
MAX_REPEAT = 32
MAX_STRIDE = 31

LANE0_INDEX_SHIFT = 52
LANE1_INDEX_SHIFT = 4
INDEX_BITS = 24
INDEX_MASK = (1 << INDEX_BITS) - 1
WORD_INDEX_MASK = (INDEX_MASK << LANE0_INDEX_SHIFT) | (
    INDEX_MASK << LANE1_INDEX_SHIFT
)


def template_word(word: HorizontalWord) -> int:
    """Return the encoded control template with both context indices clear."""

    return word.encode() & ~WORD_INDEX_MASK


def context_indices(word: HorizontalWord) -> tuple[int, int]:
    encoded = word.encode()
    return (
        (encoded >> LANE0_INDEX_SHIFT) & INDEX_MASK,
        (encoded >> LANE1_INDEX_SHIFT) & INDEX_MASK,
    )


@dataclass(frozen=True)
class HorizontalToken:
    kind: int
    template_id: int = 0
    context0: int = 0
    context1: int = 0
    repeat: int = 1
    stride0: int = 0
    stride1: int = 0
    back_count: int = 0
    loop_repeats: int = 0
    context_delta: int = 0

    def encode(self) -> int:
        if self.kind == TOKEN_HALT:
            if any((self.template_id, self.context0, self.context1,
                    self.stride0, self.stride1, self.back_count,
                    self.loop_repeats, self.context_delta)) \
                    or self.repeat != 1:
                raise ValueError("HALT token has nonzero payload")
        elif self.kind == TOKEN_LOOP:
            if any((self.template_id, self.context0, self.context1,
                    self.stride0, self.stride1)) or self.repeat != 1:
                raise ValueError("LOOP token has issue payload")
            if not 1 <= self.back_count <= 4096:
                raise ValueError("LOOP back_count out of range")
            if not 1 <= self.loop_repeats <= 31:
                raise ValueError("LOOP repeat count out of range")
            if not 1 <= self.context_delta <= MAX_CONTEXT:
                raise ValueError("LOOP context delta out of range")
            return (
                (self.kind << 62)
                | ((self.back_count - 1) << 50)
                | (self.loop_repeats << 45)
                | (self.context_delta << 32)
            )
        elif self.kind == TOKEN_SINGLE:
            if self.repeat != 1 or self.stride0 or self.stride1:
                raise ValueError("SINGLE token cannot repeat")
        elif self.kind == TOKEN_RUN:
            if self.repeat < 2:
                raise ValueError("RUN token must repeat at least twice")
        else:
            raise ValueError(f"unknown token kind {self.kind}")
        for value, limit, name in (
            (self.template_id, MAX_TEMPLATES - 1, "template_id"),
            (self.context0, MAX_CONTEXT, "context0"),
            (self.context1, MAX_CONTEXT, "context1"),
            (self.repeat, MAX_REPEAT, "repeat"),
            (self.stride0, MAX_STRIDE, "stride0"),
            (self.stride1, MAX_STRIDE, "stride1"),
        ):
            if not 0 <= value <= limit:
                raise ValueError(f"{name} out of range: {value}")
        return (
            (self.kind << 62)
            | (self.template_id << 56)
            | (self.context0 << 43)
            | (self.context1 << 30)
            | ((self.repeat - 1) << 25)
            | (self.stride0 << 20)
            | (self.stride1 << 15)
        )

    @classmethod
    def decode(cls, encoded: int) -> "HorizontalToken":
        if not 0 <= encoded < (1 << 64):
            raise ValueError("token does not fit 64 bits")
        kind = (encoded >> 62) & 0x3
        if kind == TOKEN_LOOP:
            if encoded & 0xFFFFFFFF:
                raise ValueError("reserved LOOP bits are nonzero")
            return cls(
                kind=kind,
                back_count=((encoded >> 50) & 0xFFF) + 1,
                loop_repeats=(encoded >> 45) & 0x1F,
                context_delta=(encoded >> 32) & 0x1FFF,
            )
        if encoded & 0x7FFF:
            raise ValueError("reserved token bits are nonzero")
        return cls(
            kind=kind,
            template_id=(encoded >> 56) & 0x3F,
            context0=(encoded >> 43) & 0x1FFF,
            context1=(encoded >> 30) & 0x1FFF,
            repeat=((encoded >> 25) & 0x1F) + 1,
            stride0=(encoded >> 20) & 0x1F,
            stride1=(encoded >> 15) & 0x1F,
        )


def _repeat_safe(word: HorizontalWord) -> bool:
    return not (
        word.wait_mask or word.consume_mask
        or word.lane0_track or word.lane1_track
    )


def _token_signature(token: HorizontalToken) -> tuple[int, ...]:
    return (token.kind, token.template_id, token.repeat,
            token.stride0, token.stride1)


def _context_delta(
    templates: Sequence[int], left: HorizontalToken, right: HorizontalToken
) -> list[int]:
    template = templates[left.template_id]
    deltas: list[int] = []
    if (template >> 107) & 1:
        deltas.append(right.context0 - left.context0)
    if (template >> 106) & 1:
        deltas.append(right.context1 - left.context1)
    return deltas


def fold_outer_loops(
    templates: Sequence[int], tokens: Sequence[HorizontalToken],
    *, maximum_body: int = 256,
) -> list[HorizontalToken]:
    """Fold adjacent affine copies of a token block into a single loop.

    Loops are intentionally non-nested, keeping the RTL to one counter, one
    backward displacement, and one context bias register.
    """

    signatures = [_token_signature(token) for token in tokens]
    folded: list[HorizontalToken] = []
    cursor = 0
    while cursor < len(tokens):
        best: tuple[int, int, int] | None = None
        limit = min(maximum_body, (len(tokens) - cursor) // 2)
        for body_length in range(2, limit + 1):
            second = cursor + body_length
            if signatures[cursor] != signatures[second]:
                continue
            if (signatures[cursor:second]
                    != signatures[second:second + body_length]):
                continue
            first_block = tokens[cursor:second]
            second_block = tokens[second:second + body_length]
            deltas = [
                delta
                for left, right in zip(first_block, second_block)
                for delta in _context_delta(templates, left, right)
            ]
            if not deltas or len(set(deltas)) != 1:
                continue
            context_delta = deltas[0]
            if not 1 <= context_delta <= MAX_CONTEXT:
                continue
            repetitions = 2
            while repetitions < 32:
                begin = cursor + repetitions * body_length
                end = begin + body_length
                if end > len(tokens):
                    break
                candidate = tokens[begin:end]
                if [_token_signature(token) for token in candidate] \
                        != signatures[cursor:second]:
                    break
                candidate_deltas = [
                    delta
                    for left, right in zip(first_block, candidate)
                    for delta in _context_delta(templates, left, right)
                ]
                if (not candidate_deltas
                        or any(delta != repetitions * context_delta
                               for delta in candidate_deltas)):
                    break
                repetitions += 1
            saving = body_length * (repetitions - 1) - 1
            if best is None or saving > best[0]:
                best = (saving, body_length, repetitions)

        if best is None or best[0] <= 0:
            folded.append(tokens[cursor])
            cursor += 1
            continue
        _, body_length, repetitions = best
        second = cursor + body_length
        deltas = [
            delta
            for left, right in zip(tokens[cursor:second],
                                   tokens[second:second + body_length])
            for delta in _context_delta(templates, left, right)
        ]
        folded.extend(tokens[cursor:second])
        folded.append(HorizontalToken(
            kind=TOKEN_LOOP,
            back_count=body_length,
            loop_repeats=repetitions - 1,
            context_delta=deltas[0],
        ))
        cursor += body_length * repetitions
    return folded


def compress_horizontal_program(
    words: Sequence[HorizontalWord],
) -> tuple[list[int], list[HorizontalToken], dict[str, int | float]]:
    """Compress an ISSUE...HALT program and prove lossless expansion."""

    if not words or words[-1].opcode != OP_HALT:
        raise ValueError("horizontal program must end in HALT")
    if any(word.opcode != OP_ISSUE for word in words[:-1]):
        raise ValueError("token compressor currently accepts ISSUE words only")

    templates: list[int] = []
    template_ids: dict[int, int] = {}
    tokens: list[HorizontalToken] = []
    issue_words = list(words[:-1])
    cursor = 0
    while cursor < len(issue_words):
        first = issue_words[cursor]
        skeleton = template_word(first)
        template_id = template_ids.get(skeleton)
        if template_id is None:
            template_id = len(templates)
            if template_id >= MAX_TEMPLATES:
                raise ValueError("program needs more than 64 templates")
            template_ids[skeleton] = template_id
            templates.append(skeleton)
        base0, base1 = context_indices(first)

        run = 1
        stride0 = 0
        stride1 = 0
        if cursor + 1 < len(issue_words) and _repeat_safe(first):
            second = issue_words[cursor + 1]
            next0, next1 = context_indices(second)
            delta0, delta1 = next0 - base0, next1 - base1
            if (template_word(second) == skeleton
                    and 0 <= delta0 <= MAX_STRIDE
                    and 0 <= delta1 <= MAX_STRIDE):
                stride0, stride1 = delta0, delta1
                run = 2
                while run < MAX_REPEAT and cursor + run < len(issue_words):
                    candidate = issue_words[cursor + run]
                    index0, index1 = context_indices(candidate)
                    if (template_word(candidate) != skeleton
                            or index0 != base0 + run * stride0
                            or index1 != base1 + run * stride1):
                        break
                    run += 1

        tokens.append(HorizontalToken(
            kind=TOKEN_RUN if run > 1 else TOKEN_SINGLE,
            template_id=template_id,
            context0=base0,
            context1=base1,
            repeat=run,
            stride0=stride0 if run > 1 else 0,
            stride1=stride1 if run > 1 else 0,
        ))
        cursor += run
    base_issue_tokens = len(tokens)
    tokens = fold_outer_loops(templates, tokens)
    tokens.append(HorizontalToken(kind=TOKEN_HALT))

    expanded = expand_horizontal_program(templates, tokens)
    expected = [word.encode() for word in words]
    if expanded != expected:
        raise ValueError("token compression is not bit-exact")

    token_bits = len(tokens) * 64
    template_bits = len(templates) * 128
    metrics: dict[str, int | float] = {
        "issue_words": len(issue_words),
        "tokens": len(tokens),
        "issue_tokens": len(tokens) - 1,
        "base_issue_tokens": base_issue_tokens,
        "templates": len(templates),
        "run_tokens": sum(token.kind == TOKEN_RUN for token in tokens),
        "loop_tokens": sum(token.kind == TOKEN_LOOP for token in tokens),
        "expanded_words": len(expanded),
        "token_bytes": token_bits // 8,
        "template_bytes": template_bits // 8,
        "total_bytes": (token_bits + template_bits) // 8,
        "equivalent_ramb36_bits": ceil(token_bits / 36864),
        "compression_ratio": (
            (token_bits + template_bits) / (len(words) * 128)
        ),
    }
    return templates, tokens, metrics


def expand_horizontal_program(
    templates: Sequence[int], tokens: Sequence[HorizontalToken]
) -> list[int]:
    words: list[int] = []
    pc = 0
    loop_active = False
    loop_remaining = 0
    context_bias = 0
    steps = 0
    while pc < len(tokens):
        steps += 1
        if steps > 10 * len(tokens) + 10000:
            raise ValueError("token expansion did not terminate")
        token = tokens[pc]
        if token.kind == TOKEN_HALT:
            words.append(HorizontalWord(opcode=OP_HALT).encode())
            pc += 1
            continue
        if token.kind == TOKEN_LOOP:
            if token.back_count > pc:
                raise ValueError("LOOP jumps before program start")
            if not loop_active:
                loop_active = True
                loop_remaining = token.loop_repeats
                context_bias = token.context_delta
                pc -= token.back_count
            elif loop_remaining > 1:
                loop_remaining -= 1
                context_bias += token.context_delta
                pc -= token.back_count
            else:
                loop_active = False
                loop_remaining = 0
                context_bias = 0
                pc += 1
            continue
        if token.template_id >= len(templates):
            raise ValueError("token refers to an absent template")
        template = templates[token.template_id]
        valid0 = bool((template >> 107) & 1)
        valid1 = bool((template >> 106) & 1)
        for iteration in range(token.repeat):
            index0 = token.context0 + iteration * token.stride0 \
                + (context_bias if valid0 else 0)
            index1 = token.context1 + iteration * token.stride1 \
                + (context_bias if valid1 else 0)
            if index0 > MAX_CONTEXT or index1 > MAX_CONTEXT:
                raise ValueError("expanded context index exceeds 13 bits")
            words.append(
                template
                | (index0 << LANE0_INDEX_SHIFT)
                | (index1 << LANE1_INDEX_SHIFT)
            )
        pc += 1
    return words
