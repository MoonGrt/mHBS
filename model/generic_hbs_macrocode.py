"""Static HASH/CHAIN/TREE macrocode for the compact K2/U2 HBS core.

The storage encoding deliberately reuses the product token sequencer.  Only
the 48-bit command payload changes: it now names an algorithm-independent
macro, descriptor, result route, flags, and an opaque 24-bit coordinate.
Descriptors are immutable 64-bit records.  They contain no message or key
material and are selected at synthesis time through ``$readmemh`` images.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Iterable, Sequence

from model.static_task_microcode import (
    StaticTaskToken,
    TOKEN_HALT,
    TOKEN_LOOP,
    TOKEN_RUN,
    TOKEN_SINGLE,
    coordinate,
    expand,
    issue_word,
)


class Macro(IntEnum):
    HASH = 1
    CHAIN = 2
    TREE_PUSH = 3
    # Source compatibility for the v2 whole-tree compiler.  New images must
    # use TREE_PUSH semantics; the numeric command encoding is unchanged.
    TREE = TREE_PUSH
    TRANSFORM = 4
    EMIT = 5


class DescriptorKind(IntEnum):
    HASH = 1
    SEGMENT = 2
    ADDRESS = 3
    CHAIN = 4
    TREE = 5
    ROUTE = 6
    ACTION = 7
    TRANSFORM = 8
    EMIT = 9
    IMAGE = 10
    PROFILE = 11
    RECIPE = 12


class SegmentKind(IntEnum):
    JOB_FIELD = 1
    MESSAGE = 2
    VALUE = 3
    ADDRESS = 4
    NODE_LEFT = 5
    NODE_RIGHT = 6
    ENDPOINTS = 7
    CONSTANT = 8


class JobField(IntEnum):
    SK_SEED = 0
    SK_PRF = 1
    PK_SEED = 2
    PK_ROOT = 3
    OPT_RAND = 4


class Action(IntEnum):
    WRITE_VALUE = 1
    WRITE_SCALAR = 2
    EMIT_DIGEST = 3
    STORE_ENDPOINT = 4
    SET_CURRENT = 5


class Transform(IntEnum):
    BASE_W = 1
    INDEX_STEP = 2


FLAG_CAPTURE = 0x1
FLAG_AUTH = 0x2
FLAG_EMIT = 0x4
FLAG_EXTERNAL_ROOT = 0x8


def macro_command(
    macro: Macro,
    descriptor_id: int,
    route_id: int,
    flags: int = 0,
    coord: int = 0,
) -> int:
    for name, value, width in (
        ("macro", int(macro), 4),
        ("descriptor_id", descriptor_id, 8),
        ("route_id", route_id, 8),
        ("flags", flags, 4),
        ("coordinate", coord, 24),
    ):
        if not 0 <= value < (1 << width):
            raise ValueError(f"{name} does not fit {width} bits: {value}")
    return (
        int(macro) << 44
        | descriptor_id << 36
        | route_id << 28
        | flags << 24
        | coord
    )


def descriptor_word(kind: DescriptorKind, payload: int) -> int:
    if not 0 <= payload < (1 << 60):
        raise ValueError("descriptor payload does not fit 60 bits")
    return int(kind) << 60 | payload


def hash_descriptor(
    *, segment_base: int, segment_count: int, address_id: int = 0,
    output_bytes: int = 16, max_blocks: int = 1, flags: int = 0,
) -> int:
    if not 1 <= segment_count <= 8:
        raise ValueError("HASH segment_count must be in 1..8")
    if not 1 <= output_bytes <= 34:
        raise ValueError("HASH output_bytes must be in 1..34")
    if not 1 <= max_blocks <= 7:
        raise ValueError("HASH max_blocks must be in 1..7")
    payload = (
        segment_base << 52
        | segment_count << 48
        | address_id << 40
        | output_bytes << 32
        | max_blocks << 28
        | flags << 20
    )
    return descriptor_word(DescriptorKind.HASH, payload)


def segment_descriptor(
    kind: SegmentKind,
    *, selector: int = 0,
    length: int = 0,
    offset: int = 0,
    immediate: int = 0,
) -> int:
    for name, value, width in (
        ("selector", selector, 4),
        ("length", length, 12),
        ("offset", offset, 16),
        ("immediate", immediate, 24),
    ):
        if not 0 <= value < (1 << width):
            raise ValueError(f"segment {name} does not fit {width} bits")
    payload = (
        int(kind) << 56
        | selector << 52
        | length << 40
        | offset << 24
        | immediate
    )
    return descriptor_word(DescriptorKind.SEGMENT, payload)


def address_descriptor(*, address_type: int) -> int:
    # Eight nibble selectors: layer, zero, tree-hi, tree-lo, type,
    # keypair, field6, field7.  The map is data, not hidden task logic.
    selectors = (1, 0, 2, 3, 4, 5, 6, 7)
    mapping = 0
    for selector in selectors:
        mapping = mapping << 4 | selector
    return descriptor_word(
        DescriptorKind.ADDRESS,
        mapping << 20 | (address_type & 0xFF) << 12,
    )


def chain_descriptor(
    *, seed_recipe: int, endpoint_count: int, hash_count: int,
    prefix_domain: int, preserve_counter: bool, reduce_recipe: int = 0,
) -> int:
    payload = (
        seed_recipe << 52
        | endpoint_count << 44
        | hash_count << 39
        | prefix_domain << 36
        | int(preserve_counter) << 35
        | reduce_recipe << 27
    )
    return descriptor_word(DescriptorKind.CHAIN, payload)


def tree_descriptor(
    *, chain_id: int, height: int, parent_recipe: int,
    target_selector: int, leaf_index_mode: int, keypair_mode: int,
    flags: int = 0,
) -> int:
    if not 1 <= height <= 6:
        raise ValueError("TREE height must be in 1..6")
    payload = (
        chain_id << 52
        | height << 48
        | parent_recipe << 40
        | target_selector << 32
        | leaf_index_mode << 24
        | keypair_mode << 16
        | flags << 8
    )
    return descriptor_word(DescriptorKind.TREE, payload)


def route_descriptor(*, action_base: int, action_count: int) -> int:
    if not 1 <= action_count <= 4:
        raise ValueError("route action count must be in 1..4")
    return descriptor_word(
        DescriptorKind.ROUTE,
        action_base << 52 | action_count << 48,
    )


def action_descriptor(
    action: Action,
    *, destination: int = 0,
    source_offset: int = 0,
    width: int = 0,
    immediate: int = 0,
) -> int:
    payload = (
        int(action) << 56
        | destination << 48
        | source_offset << 40
        | width << 32
        | immediate
    )
    return descriptor_word(DescriptorKind.ACTION, payload)


def transform_descriptor(
    transform: Transform,
    *, source: int = 0,
    destination: int = 0,
    p0: int = 0,
    p1: int = 0,
) -> int:
    payload = (
        int(transform) << 56
        | source << 48
        | destination << 40
        | p0 << 32
        | p1
    )
    return descriptor_word(DescriptorKind.TRANSFORM, payload)


def emit_descriptor(*, segment_base: int, segment_count: int) -> int:
    if not 1 <= segment_count <= 8:
        raise ValueError("EMIT segment_count must be in 1..8")
    return descriptor_word(
        DescriptorKind.EMIT,
        segment_base << 52 | segment_count << 48,
    )


def image_descriptor(*, output_bytes: int) -> int:
    return descriptor_word(
        DescriptorKind.IMAGE,
        1 << 52 | 16 << 44 | 87 << 32 | output_bytes,
    )


@dataclass(frozen=True)
class CompiledMacroImage:
    name: str
    tokens: tuple[int, ...]
    templates: tuple[int, ...]
    descriptors: tuple[int, ...]
    expanded: tuple[int, ...]
    output_bytes: int

    @property
    def descriptor_words(self) -> int:
        return len(self.descriptors)


def _place(records: dict[int, int], index: int, value: int) -> None:
    if index in records:
        raise ValueError(f"duplicate descriptor {index}")
    records[index] = value


def common_descriptors(*, output_bytes: int) -> tuple[int, ...]:
    """Build the immutable SHAKE-128f descriptor table.

    IDs are stable ABI for the first generic core.  Gaps remain illegal and
    read as zero, which is not a valid descriptor kind.
    """

    records: dict[int, int] = {}
    _place(records, 0, image_descriptor(output_bytes=output_bytes))

    # Hash recipes.
    _place(records, 1, hash_descriptor(
        segment_base=64, segment_count=3, output_bytes=16, max_blocks=1))
    _place(records, 2, hash_descriptor(
        segment_base=67, segment_count=4, output_bytes=34, max_blocks=1))
    _place(records, 3, hash_descriptor(
        segment_base=71, segment_count=3, address_id=32,
        output_bytes=16, max_blocks=5))
    _place(records, 4, hash_descriptor(
        segment_base=74, segment_count=3, address_id=33,
        output_bytes=16, max_blocks=1))
    _place(records, 5, hash_descriptor(
        segment_base=77, segment_count=3, address_id=34,
        output_bytes=16, max_blocks=1))
    _place(records, 6, hash_descriptor(
        segment_base=80, segment_count=4, address_id=35,
        output_bytes=16, max_blocks=1))
    _place(records, 7, hash_descriptor(
        segment_base=84, segment_count=3, address_id=36,
        output_bytes=16, max_blocks=5))
    _place(records, 8, hash_descriptor(
        segment_base=87, segment_count=4, address_id=38,
        output_bytes=16, max_blocks=1))
    _place(records, 9, hash_descriptor(
        segment_base=91, segment_count=3, address_id=38,
        output_bytes=16, max_blocks=5))

    # Generic chains and trees.  Chain hash_count includes the seed Hash.
    _place(records, 16, chain_descriptor(
        seed_recipe=4, endpoint_count=1, hash_count=2,
        prefix_domain=3, preserve_counter=True))
    _place(records, 17, chain_descriptor(
        seed_recipe=5, endpoint_count=35, hash_count=16,
        prefix_domain=0, preserve_counter=False, reduce_recipe=7))
    _place(records, 20, tree_descriptor(
        chain_id=16, height=6, parent_recipe=6,
        target_selector=1, leaf_index_mode=1, keypair_mode=1))
    _place(records, 21, tree_descriptor(
        chain_id=17, height=3, parent_recipe=8,
        target_selector=2, leaf_index_mode=0, keypair_mode=2))

    # FIPS 205 address mappings; only address_type differs.
    for descriptor_id, address_type in (
        (32, 4), (33, 6), (34, 5), (35, 3),
        (36, 1), (37, 0), (38, 2),
    ):
        _place(records, descriptor_id,
               address_descriptor(address_type=address_type))

    # Result routes and action programs.
    _place(records, 40, route_descriptor(action_base=100, action_count=2))
    _place(records, 41, route_descriptor(action_base=102, action_count=3))
    _place(records, 42, route_descriptor(action_base=105, action_count=1))
    _place(records, 43, route_descriptor(action_base=106, action_count=1))
    _place(records, 44, route_descriptor(action_base=107, action_count=1))
    _place(records, 45, route_descriptor(action_base=108, action_count=1))
    _place(records, 100, action_descriptor(
        Action.WRITE_VALUE, destination=0, width=16))
    _place(records, 101, action_descriptor(Action.EMIT_DIGEST, width=16))
    _place(records, 102, action_descriptor(
        Action.WRITE_VALUE, destination=1, width=34))
    _place(records, 103, action_descriptor(
        Action.WRITE_SCALAR, destination=0, source_offset=25, width=8))
    _place(records, 104, action_descriptor(
        Action.WRITE_SCALAR, destination=1, source_offset=33, width=1))
    _place(records, 105, action_descriptor(
        Action.SET_CURRENT, destination=2, width=16))
    _place(records, 106, action_descriptor(
        Action.STORE_ENDPOINT, destination=0, width=16))
    _place(records, 107, action_descriptor(
        Action.SET_CURRENT, destination=2, width=16))
    _place(records, 108, action_descriptor(
        Action.WRITE_VALUE, destination=3, width=16))

    _place(records, 48, transform_descriptor(
        Transform.BASE_W, source=2, destination=0, p0=4,
        p1=(32 << 16) | 3))
    _place(records, 49, transform_descriptor(
        Transform.INDEX_STEP, source=0, destination=1, p0=3))

    # Keygen output: SK.seed || SK.prf || PK.seed || root || PK.seed || root.
    _place(records, 50, emit_descriptor(segment_base=112, segment_count=6))

    # Segment programs.  length=0 is dynamic for MESSAGE/ENDPOINTS.
    segments = {
        64: (SegmentKind.JOB_FIELD, JobField.SK_PRF, 16),
        65: (SegmentKind.JOB_FIELD, JobField.OPT_RAND, 16),
        66: (SegmentKind.MESSAGE, 0, 0),
        67: (SegmentKind.VALUE, 0, 16),
        68: (SegmentKind.JOB_FIELD, JobField.PK_SEED, 16),
        69: (SegmentKind.JOB_FIELD, JobField.PK_ROOT, 16),
        70: (SegmentKind.MESSAGE, 0, 0),
        71: (SegmentKind.JOB_FIELD, JobField.PK_SEED, 16),
        72: (SegmentKind.ADDRESS, 0, 32),
        73: (SegmentKind.ENDPOINTS, 0, 0),
        74: (SegmentKind.JOB_FIELD, JobField.PK_SEED, 16),
        75: (SegmentKind.ADDRESS, 0, 32),
        76: (SegmentKind.JOB_FIELD, JobField.SK_SEED, 16),
        77: (SegmentKind.JOB_FIELD, JobField.PK_SEED, 16),
        78: (SegmentKind.ADDRESS, 0, 32),
        79: (SegmentKind.JOB_FIELD, JobField.SK_SEED, 16),
        80: (SegmentKind.JOB_FIELD, JobField.PK_SEED, 16),
        81: (SegmentKind.ADDRESS, 0, 32),
        82: (SegmentKind.NODE_LEFT, 0, 16),
        83: (SegmentKind.NODE_RIGHT, 0, 16),
        84: (SegmentKind.JOB_FIELD, JobField.PK_SEED, 16),
        85: (SegmentKind.ADDRESS, 0, 32),
        86: (SegmentKind.ENDPOINTS, 0, 0),
        87: (SegmentKind.JOB_FIELD, JobField.PK_SEED, 16),
        88: (SegmentKind.ADDRESS, 0, 32),
        89: (SegmentKind.NODE_LEFT, 0, 16),
        90: (SegmentKind.NODE_RIGHT, 0, 16),
        91: (SegmentKind.JOB_FIELD, JobField.PK_SEED, 16),
        92: (SegmentKind.ADDRESS, 0, 32),
        93: (SegmentKind.ENDPOINTS, 0, 0),
        112: (SegmentKind.JOB_FIELD, JobField.SK_SEED, 16),
        113: (SegmentKind.JOB_FIELD, JobField.SK_PRF, 16),
        114: (SegmentKind.JOB_FIELD, JobField.PK_SEED, 16),
        115: (SegmentKind.VALUE, 3, 16),
        116: (SegmentKind.JOB_FIELD, JobField.PK_SEED, 16),
        117: (SegmentKind.VALUE, 3, 16),
    }
    for index, (kind, selector, length) in segments.items():
        _place(records, index, segment_descriptor(
            kind, selector=int(selector), length=length,
            immediate=(33 if index == 73 else
                       35 if index in (86, 93) else 0)))

    size = max(records) + 1
    result = [0] * size
    for index, word in records.items():
        result[index] = word
    return tuple(result)


def _template(command0: int, *, first: bool = False) -> int:
    return issue_word(command0, first=first)


def compile_sign_image() -> CompiledMacroImage:
    templates = (
        _template(macro_command(Macro.HASH, 1, 40, FLAG_EMIT), first=True),
        _template(macro_command(Macro.HASH, 2, 41)),
        _template(macro_command(Macro.TREE, 20, 43,
                                FLAG_CAPTURE | FLAG_AUTH)),
        _template(macro_command(Macro.HASH, 3, 42)),
        _template(macro_command(Macro.TRANSFORM, 48, 0)),
        _template(macro_command(Macro.TREE, 21, 44,
                                FLAG_CAPTURE | FLAG_AUTH)),
        _template(macro_command(Macro.TRANSFORM, 49, 0)),
        _template(macro_command(Macro.TRANSFORM, 48, 0)),
        _template(macro_command(Macro.TREE, 21, 44,
                                FLAG_CAPTURE | FLAG_AUTH
                                | FLAG_EXTERNAL_ROOT)),
    )
    layer_step = coordinate(layer=1)
    tokens = (
        StaticTaskToken(TOKEN_SINGLE, template=0),
        StaticTaskToken(TOKEN_SINGLE, template=1),
        StaticTaskToken(
            TOKEN_RUN, template=2, coord0=coordinate(group=0),
            repeat=33, stride0=coordinate(group=1)),
        StaticTaskToken(TOKEN_SINGLE, template=3),
        StaticTaskToken(TOKEN_SINGLE, template=4),
        StaticTaskToken(TOKEN_SINGLE, template=5,
                        coord0=coordinate(layer=0)),
        StaticTaskToken(TOKEN_SINGLE, template=6),
        StaticTaskToken(TOKEN_SINGLE, template=7),
        StaticTaskToken(
            TOKEN_LOOP, back_count=3, loop_repeats=20,
            delta0=layer_step),
        StaticTaskToken(TOKEN_SINGLE, template=8,
                        coord0=coordinate(layer=21)),
        StaticTaskToken(TOKEN_HALT),
    )
    expanded = tuple(expand(templates, tokens))
    return CompiledMacroImage(
        name="slh-dsa-shake-128f-sign-generic-macro",
        tokens=tuple(token.encode() for token in tokens),
        templates=templates,
        descriptors=common_descriptors(output_bytes=17088),
        expanded=expanded,
        output_bytes=17088,
    )


def compile_keygen_image() -> CompiledMacroImage:
    templates = (
        _template(macro_command(Macro.TREE, 21, 45, 0,
                                coordinate(layer=21)), first=True),
        _template(macro_command(Macro.EMIT, 50, 0)),
    )
    tokens = (
        StaticTaskToken(TOKEN_SINGLE, template=0,
                        coord0=coordinate(layer=21)),
        StaticTaskToken(TOKEN_SINGLE, template=1),
        StaticTaskToken(TOKEN_HALT),
    )
    expanded = tuple(expand(templates, tokens))
    return CompiledMacroImage(
        name="slh-dsa-shake-128f-keygen-generic-macro",
        tokens=tuple(token.encode() for token in tokens),
        templates=templates,
        descriptors=common_descriptors(output_bytes=96),
        expanded=expanded,
        output_bytes=96,
    )


def validate_image(image: CompiledMacroImage) -> None:
    if len(image.tokens) > 384 or len(image.templates) > 64:
        raise ValueError("macro image exceeds token/template bounds")
    if len(image.descriptors) > 512:
        raise ValueError("macro image exceeds descriptor ROM")
    if not image.expanded or (image.expanded[-1] >> 124) != 0xF:
        raise ValueError("macro image does not terminate in HALT")
    if any((word >> 124) == 0xF for word in image.expanded[:-1]):
        raise ValueError("macro image reaches HALT before the final word")

    def record(index: int, expected: DescriptorKind, owner: str) -> int:
        if not 0 <= index < len(image.descriptors):
            raise ValueError(f"{owner} descriptor reference is out of range")
        word = image.descriptors[index]
        if word >> 60 != expected:
            raise ValueError(
                f"{owner} references {index}, expected {expected.name}"
            )
        return word

    for index, word in enumerate(image.descriptors):
        if word == 0:
            continue
        kind = word >> 60
        if kind not in {int(item) for item in DescriptorKind}:
            raise ValueError(f"invalid descriptor kind at {index}")
        if kind == DescriptorKind.HASH:
            count = (word >> 48) & 0xF
            base = (word >> 52) & 0xFF
            # The descriptor ABI reserves three bits for up to eight
            # segments.  This compact n=16 implementation caches four;
            # images requiring more must be rejected, never truncated.
            if count == 0 or count > 4 or base + count > len(image.descriptors):
                raise ValueError(f"invalid HASH segment range at {index}")
            for segment_index in range(base, base + count):
                record(segment_index, DescriptorKind.SEGMENT,
                       f"HASH {index}")
            address_id = (word >> 40) & 0xFF
            if address_id:
                record(address_id, DescriptorKind.ADDRESS,
                       f"HASH {index}")
            if not 1 <= ((word >> 28) & 0x7) <= 7:
                raise ValueError(f"invalid HASH block bound at {index}")
        elif kind == DescriptorKind.SEGMENT:
            segment_kind = (word >> 56) & 0xF
            if segment_kind not in {int(item) for item in SegmentKind}:
                raise ValueError(f"invalid segment source at {index}")
        elif kind == DescriptorKind.CHAIN:
            record((word >> 52) & 0xFF, DescriptorKind.HASH,
                   f"CHAIN {index}")
            if ((word >> 44) & 0xFF) == 0 or ((word >> 39) & 0x1F) == 0:
                raise ValueError(f"empty CHAIN at {index}")
            reduce_id = (word >> 27) & 0xFF
            if reduce_id:
                record(reduce_id, DescriptorKind.HASH,
                       f"CHAIN {index}")
        if kind == DescriptorKind.TREE:
            chain_id = (word >> 52) & 0xFF
            parent_id = (word >> 40) & 0xFF
            height = (word >> 48) & 0x7
            if not 1 <= height <= 6:
                raise ValueError(f"TREE {index} height is outside 1..6")
            record(chain_id, DescriptorKind.CHAIN, f"TREE {index}")
            record(parent_id, DescriptorKind.HASH, f"TREE {index}")
        elif kind == DescriptorKind.ROUTE:
            base = (word >> 52) & 0xFF
            count = (word >> 48) & 0x7
            if not 1 <= count <= 4:
                raise ValueError(f"invalid ROUTE action count at {index}")
            for action_index in range(base, base + count):
                record(action_index, DescriptorKind.ACTION,
                       f"ROUTE {index}")
        elif kind == DescriptorKind.EMIT:
            base = (word >> 52) & 0xFF
            count = (word >> 48) & 0xF
            if not 1 <= count <= 8:
                raise ValueError(f"invalid EMIT segment count at {index}")
            for segment_index in range(base, base + count):
                record(segment_index, DescriptorKind.SEGMENT,
                       f"EMIT {index}")

    expected_kind = {
        Macro.HASH: DescriptorKind.HASH,
        Macro.CHAIN: DescriptorKind.CHAIN,
        Macro.TREE: DescriptorKind.TREE,
        Macro.TRANSFORM: DescriptorKind.TRANSFORM,
        Macro.EMIT: DescriptorKind.EMIT,
    }
    completed_events = 0
    for word_index, word in enumerate(image.expanded[:-1]):
        if word >> 124 != 1:
            raise ValueError(f"expanded word {word_index} is not ISSUE")
        wait_mask = (word >> 116) & 0xFF
        consume_mask = (word >> 108) & 0xFF
        if wait_mask & ~completed_events:
            raise ValueError(f"event wait conflict at word {word_index}")
        if consume_mask & ~completed_events:
            raise ValueError(f"event consume conflict at word {word_index}")
        completed_events &= ~consume_mask
        lane_valid = ((word >> 107) & 1, (word >> 106) & 1)
        commands = ((word >> 52) & ((1 << 48) - 1),
                    (word >> 4) & ((1 << 48) - 1))
        if not any(lane_valid):
            raise ValueError(f"empty ISSUE word {word_index}")
        decoded: list[tuple[Macro, int]] = []
        for lane, valid in enumerate(lane_valid):
            if not valid:
                continue
            try:
                macro = Macro((commands[lane] >> 44) & 0xF)
            except ValueError as exc:
                raise ValueError(
                    f"unknown macro at word {word_index} lane {lane}"
                ) from exc
            descriptor_id = (commands[lane] >> 36) & 0xFF
            route_id = (commands[lane] >> 28) & 0xFF
            record(descriptor_id, expected_kind[macro],
                   f"word {word_index} lane {lane} {macro.name}")
            if route_id:
                record(route_id, DescriptorKind.ROUTE,
                       f"word {word_index} lane {lane}")
            decoded.append((macro, descriptor_id))
        if lane_valid[1]:
            if decoded[0][0] not in (Macro.HASH, Macro.CHAIN):
                raise ValueError(
                    f"exclusive macro uses slot 1 at word {word_index}"
                )
            if decoded[0] != decoded[1]:
                raise ValueError(
                    f"dual slots mismatch at word {word_index}"
                )
        allocate_mask = 0
        if lane_valid[0] and ((word >> 3) & 1):
            allocate_mask |= 1 << ((word >> 103) & 0x7)
        if lane_valid[1] and ((word >> 2) & 1):
            allocate_mask |= 1 << ((word >> 100) & 0x7)
        if allocate_mask & completed_events:
            raise ValueError(f"event allocation conflict at word {word_index}")
        # Macro execution is serialized by the current issue interface, so
        # allocated events are complete before the next word is accepted.
        completed_events |= allocate_mask


def render_words(words: Iterable[int], width: int) -> str:
    digits = width // 4
    return "".join(f"{word:0{digits}x}\n" for word in words)


def image_manifest(image: CompiledMacroImage) -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "name": image.name,
        "command_bits": 48,
        "token_bits": 128,
        "tokens": len(image.tokens),
        "templates": len(image.templates),
        "expanded_words": len(image.expanded),
        "descriptor_word_bits": 64,
        "descriptor_words": image.descriptor_words,
        "output_bytes": image.output_bytes,
        "runtime_writable": False,
    }


def all_images() -> Sequence[CompiledMacroImage]:
    images = (compile_sign_image(), compile_keygen_image())
    for image in images:
        validate_image(image)
    return images
