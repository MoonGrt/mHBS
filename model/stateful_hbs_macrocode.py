"""Dual-entry static macrocode images for the n=32 stateful HBS cores.

The images describe Keygen and Sign with the same public HASH/CHAIN/TREE/
TRANSFORM/EMIT macro set used by the SLH-DSA core.  Family-specific byte
layouts live in immutable descriptors; neither secret material nor a message
is embedded in an image.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Sequence

from model.generic_hbs_macrocode import Macro, macro_command
from model.static_task_microcode import (
    StaticTaskToken,
    TOKEN_HALT,
    TOKEN_LOOP,
    TOKEN_RUN,
    TOKEN_SINGLE,
    expand,
    issue_word,
)


class StatefulFamily(IntEnum):
    XMSS = 1
    LMS_SHAKE_RESEARCH = 2


class StatefulDescriptorKind(IntEnum):
    HASH = 1
    CONSTANT = 2
    CHAIN = 4
    TREE_PUSH = 5
    TRANSFORM = 8
    EMIT = 9
    IMAGE_V2 = 10
    PROFILE = 11
    RECIPE = 12


class EmitSource(IntEnum):
    Q = 0
    SECRET_SEED = 1
    SECRET_PRF = 2
    ROOT = 3
    PUBLIC_SEED = 4
    IDENTIFIER = 5
    CONSTANT_0 = 6
    CONSTANT_1 = 7
    RANDOMIZER = 8
    CACHE_AUTH = 9


class RecipeShape(IntEnum):
    """Algorithm-neutral byte-flow and compound-Hash shapes."""

    KEYED_INDEX = 1
    ROOT_MESSAGE = 2
    MASKED_CHAIN = 3
    MASKED_PARENT = 4
    PREFIX_MESSAGE = 5
    PREFIX_CHAIN = 6
    PREFIX_LIST = 7
    PREFIX_VALUE = 8
    PREFIX_PARENT = 9
    PREFIX_PRIVATE = 10
    SEED_ADDRESS = 11


def _descriptor(kind: StatefulDescriptorKind, payload: int) -> int:
    if not 0 <= payload < 1 << 60:
        raise ValueError("stateful descriptor payload exceeds 60 bits")
    return int(kind) << 60 | payload


def _image_descriptor(
    *, keygen_entry: int, sign_entry: int,
    keygen_bytes: int, sign_bytes: int,
) -> int:
    payload = (
        (2 << 56)
        | (keygen_entry << 47)
        | (sign_entry << 38)
        | (keygen_bytes << 25)
        | (sign_bytes << 12)
    )
    return _descriptor(StatefulDescriptorKind.IMAGE_V2, payload)


def _profile_descriptor(family: StatefulFamily) -> int:
    # n=32, h=10, log2(w)=4, len=67, SHAKE256/256.
    # The low payload is a generic role map consumed by the RTL.  It selects
    # byte-flow recipe shapes without exposing XMSS/LMS opcodes:
    # chain, parent, first/second message Hash, list-reduce, auth-prefix.
    if family == StatefulFamily.XMSS:
        chain_shape = RecipeShape.MASKED_CHAIN
        parent_shape = RecipeShape.MASKED_PARENT
        hash_a_shape = RecipeShape.KEYED_INDEX
        hash_b_shape = RecipeShape.ROOT_MESSAGE
        list_reduce, auth_prefix = 0, 0
    else:
        chain_shape = RecipeShape.PREFIX_CHAIN
        parent_shape = RecipeShape.PREFIX_PARENT
        hash_a_shape, hash_b_shape = RecipeShape.PREFIX_MESSAGE, 0
        list_reduce, auth_prefix = 1, 1
    payload = (
        (int(family) << 56)
        | (32 << 48)
        | (10 << 43)
        | (4 << 39)
        | (67 << 31)
        | (int(family == StatefulFamily.XMSS) << 30)
        | (1 << 29)
        | (chain_shape << 25)
        | (parent_shape << 21)
        | (hash_a_shape << 17)
        | (hash_b_shape << 13)
        | (list_reduce << 12)
        | (auth_prefix << 11)
        | (62 << 5)
    )
    return _descriptor(StatefulDescriptorKind.PROFILE, payload)


def _recipe_descriptor(
    recipe: RecipeShape, *, stages: int, max_blocks: int,
    output_bytes: int = 32, result_target: int = 0,
) -> int:
    if not 1 <= stages <= 4:
        raise ValueError("compound recipe must contain one to four stages")
    if not 1 <= max_blocks <= 16:
        raise ValueError("stateful recipe block bound must be in 1..16")
    if not 0 <= result_target < 16:
        raise ValueError("stateful recipe result target exceeds four bits")
    payload = (
        (int(recipe) << 52)
        | (stages << 49)
        | ((max_blocks - 1) << 44)
        | (output_bytes << 36)
        | (result_target << 32)
    )
    return _descriptor(StatefulDescriptorKind.RECIPE, payload)


def _emit_descriptor(*, segment_base: int, segment_count: int,
                     output_bytes: int) -> int:
    return _descriptor(
        StatefulDescriptorKind.EMIT,
        (segment_base << 52) | (segment_count << 48) | output_bytes,
    )


def _emit_segment(source: EmitSource, length: int, *, repeat: int = 1,
                  last: bool = False) -> int:
    if not 1 <= length <= 32:
        raise ValueError("emit segment length must be in 1..32")
    if not 1 <= repeat <= 64:
        raise ValueError("emit segment repeat must be in 1..64")
    return _descriptor(
        StatefulDescriptorKind.CONSTANT,
        (int(source) << 56) | (length << 48) | (int(last) << 47)
        | ((repeat - 1) << 40),
    )


@dataclass(frozen=True)
class StatefulMacroImage:
    name: str
    family: StatefulFamily
    tokens: tuple[int, ...]
    templates: tuple[int, ...]
    descriptors: tuple[int, ...]
    keygen_entry: int
    sign_entry: int
    keygen_output_bytes: int
    sign_output_bytes: int
    expanded_keygen: tuple[int, ...]
    expanded_sign: tuple[int, ...]


def _template(command: int, *, first: bool = False) -> int:
    return issue_word(command, first=first)


def _compile(
    family: StatefulFamily,
    *, keygen_bytes: int,
    sign_bytes: int,
    recipe_words: Sequence[int],
) -> StatefulMacroImage:
    # Descriptor IDs are shared ABI, while the control stream is profile
    # specific.  In particular, the XMSS L-tree and LMS list reduction are
    # now expressed by microcode rather than a family branch in the RTL.
    if family == StatefulFamily.XMSS:
        keygen_templates = (
            _template(macro_command(Macro.TREE_PUSH, 31, 0), first=True),
            _template(macro_command(Macro.CHAIN, 42, 0)),
            _template(macro_command(Macro.TREE_PUSH, 34, 0)),
            _template(macro_command(Macro.TREE_PUSH, 35, 0)),
            _template(macro_command(Macro.EMIT, 50, 0)),
        )
        keygen_tokens = (
            StaticTaskToken(TOKEN_SINGLE, template=0),
            StaticTaskToken(TOKEN_SINGLE, template=1),
            # Push all 67 endpoints into reducer context zero.  Two RUNs are
            # used because the storage encoding limits a RUN to 64 words.
            StaticTaskToken(TOKEN_RUN, template=2, repeat=64,
                            stride0=1 << 10),
            StaticTaskToken(TOKEN_RUN, template=2, coord0=64 << 10,
                            repeat=3, stride0=1 << 10),
            StaticTaskToken(TOKEN_SINGLE, template=3),
            StaticTaskToken(TOKEN_LOOP, back_count=4, loop_repeats=31,
                            delta0=1),
            StaticTaskToken(TOKEN_LOOP, back_count=5, loop_repeats=31,
                            delta0=32),
            StaticTaskToken(TOKEN_SINGLE, template=4),
            StaticTaskToken(TOKEN_HALT),
        )
    else:
        keygen_templates = (
            _template(macro_command(Macro.TREE_PUSH, 31, 0), first=True),
            _template(macro_command(Macro.CHAIN, 42, 0)),
            _template(macro_command(Macro.HASH, 43, 0)),
            _template(macro_command(Macro.HASH, 44, 0)),
            _template(macro_command(Macro.TREE_PUSH, 35, 0)),
            _template(macro_command(Macro.EMIT, 50, 0)),
        )
        keygen_tokens = (
            StaticTaskToken(TOKEN_SINGLE, template=0),
            StaticTaskToken(TOKEN_SINGLE, template=1),
            StaticTaskToken(TOKEN_SINGLE, template=2),
            StaticTaskToken(TOKEN_SINGLE, template=3),
            StaticTaskToken(TOKEN_SINGLE, template=4),
            StaticTaskToken(TOKEN_LOOP, back_count=4, loop_repeats=31,
                            delta0=1),
            StaticTaskToken(TOKEN_LOOP, back_count=5, loop_repeats=31,
                            delta0=32),
            StaticTaskToken(TOKEN_SINGLE, template=5),
            StaticTaskToken(TOKEN_HALT),
        )
    sign_templates = (
        _template(macro_command(Macro.HASH, 40, 0), first=True),
        _template(macro_command(Macro.TRANSFORM, 48, 0)),
        _template(macro_command(Macro.EMIT, 51, 0)),
        _template(macro_command(Macro.CHAIN, 41, 0)),
        _template(macro_command(Macro.EMIT, 52, 0)),
    )
    templates = keygen_templates + sign_templates
    sign_tokens = (
        StaticTaskToken(TOKEN_SINGLE, template=len(keygen_templates)),
        StaticTaskToken(TOKEN_SINGLE, template=len(keygen_templates) + 1),
        StaticTaskToken(TOKEN_SINGLE, template=len(keygen_templates) + 2),
        StaticTaskToken(TOKEN_SINGLE, template=len(keygen_templates) + 3),
        StaticTaskToken(TOKEN_SINGLE, template=len(keygen_templates) + 4),
        StaticTaskToken(TOKEN_HALT),
    )
    keygen_entry = 0
    sign_entry = len(keygen_tokens)
    token_objects = keygen_tokens + sign_tokens

    records = [0] * 64
    records[0] = _image_descriptor(
        keygen_entry=keygen_entry,
        sign_entry=sign_entry,
        keygen_bytes=keygen_bytes,
        sign_bytes=sign_bytes,
    )
    records[1] = _profile_descriptor(family)
    for index, word in enumerate(recipe_words, start=2):
        records[index] = word
    records[31] = _descriptor(
        StatefulDescriptorKind.TREE_PUSH,
        (10 << 52) | (1 << 41),
    )
    records[32] = _descriptor(
        StatefulDescriptorKind.TREE_PUSH,
        (10 << 52) | (67 << 44) | (1 << 40),
    )
    records[33] = _descriptor(
        StatefulDescriptorKind.TREE_PUSH,
        (10 << 52) | (1 << 39),
    )
    # TREE_PUSH 34 consumes one endpoint selected by coordinate[16:10] and
    # feeds reducer context zero.  TREE_PUSH 35 feeds the completed leaf into
    # context one and caches the complete outer tree.
    records[34] = _descriptor(
        StatefulDescriptorKind.TREE_PUSH,
        (7 << 52) | (67 << 44) | (1 << 38),
    )
    records[35] = _descriptor(
        StatefulDescriptorKind.TREE_PUSH,
        (10 << 52) | (1 << 40),
    )
    records[40] = _recipe_descriptor(
        RecipeShape.KEYED_INDEX if family == StatefulFamily.XMSS
        else RecipeShape.PREFIX_MESSAGE,
        stages=2 if family == StatefulFamily.XMSS else 1,
        max_blocks=2, result_target=1)
    records[43] = _recipe_descriptor(
        RecipeShape.PREFIX_LIST, stages=1, max_blocks=16,
        result_target=2)
    records[44] = _recipe_descriptor(
        RecipeShape.PREFIX_VALUE, stages=1, max_blocks=1,
        result_target=3)
    records[41] = _descriptor(
        StatefulDescriptorKind.CHAIN,
        (67 << 48) | (15 << 40),
    )
    records[42] = _descriptor(
        StatefulDescriptorKind.CHAIN,
        (67 << 48) | (15 << 40) | (1 << 39),
    )
    records[48] = _descriptor(
        StatefulDescriptorKind.TRANSFORM,
        (4 << 52) | (64 << 44) | (3 << 36),
    )
    if family == StatefulFamily.XMSS:
        emit_sources = (
            (EmitSource.Q, 4),
            (EmitSource.SECRET_SEED, 32),
            (EmitSource.SECRET_PRF, 32),
            (EmitSource.ROOT, 32),
            (EmitSource.PUBLIC_SEED, 32),
            (EmitSource.ROOT, 32),
            (EmitSource.PUBLIC_SEED, 32),
        )
    else:
        emit_sources = (
            (EmitSource.Q, 4),
            (EmitSource.IDENTIFIER, 16),
            (EmitSource.SECRET_SEED, 32),
            (EmitSource.ROOT, 32),
            (EmitSource.CONSTANT_0, 4),
            (EmitSource.CONSTANT_1, 4),
            (EmitSource.IDENTIFIER, 16),
            (EmitSource.ROOT, 32),
        )
    records[50] = _emit_descriptor(
        segment_base=10, segment_count=len(emit_sources),
        output_bytes=keygen_bytes)
    if family == StatefulFamily.XMSS:
        header_sources = (
            (EmitSource.Q, 4, 1),
            (EmitSource.RANDOMIZER, 32, 1),
        )
        auth_sources = ((EmitSource.CACHE_AUTH, 32, 10),)
    else:
        header_sources = (
            (EmitSource.Q, 4, 1),
            (EmitSource.CONSTANT_1, 4, 1),
            (EmitSource.RANDOMIZER, 32, 1),
        )
        auth_sources = (
            (EmitSource.CONSTANT_0, 4, 1),
            (EmitSource.CACHE_AUTH, 32, 10),
        )
    header_base = 10 + len(emit_sources)
    auth_base = header_base + len(header_sources)
    records[51] = _emit_descriptor(
        segment_base=header_base, segment_count=len(header_sources),
        output_bytes=sign_bytes)
    records[52] = _emit_descriptor(
        segment_base=auth_base, segment_count=len(auth_sources),
        output_bytes=sign_bytes)
    for index, (source, length) in enumerate(emit_sources):
        records[10 + index] = _emit_segment(
            source, length, last=index + 1 == len(emit_sources))
    for index, (source, length, repeat) in enumerate(header_sources):
        records[header_base + index] = _emit_segment(
            source, length, repeat=repeat, last=False)
    for index, (source, length, repeat) in enumerate(auth_sources):
        records[auth_base + index] = _emit_segment(
            source, length, repeat=repeat,
            last=index + 1 == len(auth_sources))

    records[62] = _descriptor(StatefulDescriptorKind.CONSTANT, 0x80000006)
    records[63] = _descriptor(StatefulDescriptorKind.CONSTANT, 0x80000003)

    return StatefulMacroImage(
        name=("xmss-shake256-h10-w4" if family == StatefulFamily.XMSS
              else "lms-shake256-h10-w4-research"),
        family=family,
        tokens=tuple(token.encode() for token in token_objects),
        templates=templates,
        descriptors=tuple(records),
        keygen_entry=keygen_entry,
        sign_entry=sign_entry,
        keygen_output_bytes=keygen_bytes,
        sign_output_bytes=sign_bytes,
        expanded_keygen=tuple(expand(templates, keygen_tokens)),
        expanded_sign=tuple(expand(templates, sign_tokens)),
    )


def compile_xmss_image() -> StatefulMacroImage:
    recipes = (
        _recipe_descriptor(RecipeShape.KEYED_INDEX, stages=1, max_blocks=1),
        _recipe_descriptor(RecipeShape.ROOT_MESSAGE, stages=1, max_blocks=2),
        _recipe_descriptor(RecipeShape.SEED_ADDRESS, stages=1, max_blocks=1),
        _recipe_descriptor(RecipeShape.MASKED_CHAIN, stages=3, max_blocks=1),
        _recipe_descriptor(RecipeShape.MASKED_PARENT, stages=4, max_blocks=1),
    )
    return _compile(
        StatefulFamily.XMSS,
        keygen_bytes=196,
        sign_bytes=2500,
        recipe_words=recipes,
    )


def compile_lms_shake_image() -> StatefulMacroImage:
    recipes = (
        _recipe_descriptor(RecipeShape.PREFIX_MESSAGE, stages=1, max_blocks=2),
        _recipe_descriptor(RecipeShape.PREFIX_PRIVATE, stages=1, max_blocks=1),
        _recipe_descriptor(RecipeShape.PREFIX_CHAIN, stages=1, max_blocks=1),
        _recipe_descriptor(RecipeShape.PREFIX_LIST, stages=1, max_blocks=16),
        _recipe_descriptor(RecipeShape.PREFIX_VALUE, stages=1, max_blocks=1),
        _recipe_descriptor(RecipeShape.PREFIX_PARENT, stages=1, max_blocks=1),
    )
    return _compile(
        StatefulFamily.LMS_SHAKE_RESEARCH,
        keygen_bytes=140,
        sign_bytes=2508,
        recipe_words=recipes,
    )


def validate_stateful_image(image: StatefulMacroImage) -> None:
    if image.keygen_entry != 0 or image.sign_entry <= image.keygen_entry:
        raise ValueError("invalid operation entry table")
    if len(image.tokens) > 384 or len(image.templates) > 64:
        raise ValueError("stateful macro image exceeds ROM bounds")
    if len(image.descriptors) > 512:
        raise ValueError("stateful descriptor image exceeds ROM bounds")
    if image.expanded_keygen[-1] >> 124 != 0xF:
        raise ValueError("Keygen does not terminate")
    if image.expanded_sign[-1] >> 124 != 0xF:
        raise ValueError("Sign does not terminate")
    for word in image.expanded_keygen[:-1] + image.expanded_sign[:-1]:
        macro = (word >> 96) & 0xF
        if macro not in {int(item) for item in Macro}:
            raise ValueError("image contains a non-public macro")
    header = image.descriptors[0]
    if header >> 60 != StatefulDescriptorKind.IMAGE_V2:
        raise ValueError("missing descriptor ABI v2 header")
    profile = image.descriptors[1]
    if profile >> 60 != StatefulDescriptorKind.PROFILE:
        raise ValueError("missing stateful profile descriptor")
    if ((profile >> 48) & 0xFF) != 32 or ((profile >> 43) & 0x1F) != 10:
        raise ValueError("unsupported stateful n/tree-height profile")
    if ((profile >> 31) & 0xFF) != 67:
        raise ValueError("stateful chain count must be 67")

    descriptor_for_macro = {
        int(Macro.HASH): StatefulDescriptorKind.RECIPE,
        int(Macro.CHAIN): StatefulDescriptorKind.CHAIN,
        int(Macro.TREE_PUSH): StatefulDescriptorKind.TREE_PUSH,
        int(Macro.TRANSFORM): StatefulDescriptorKind.TRANSFORM,
        int(Macro.EMIT): StatefulDescriptorKind.EMIT,
    }
    for word in image.expanded_keygen[:-1] + image.expanded_sign[:-1]:
        if (word >> 124) & 0xF != 1:
            raise ValueError("non-issue word before HALT")
        if (word >> 106) & 1:
            raise ValueError("exclusive stateful macro illegally uses slot 1")
        macro = (word >> 96) & 0xF
        descriptor_id = (word >> 88) & 0xFF
        if descriptor_id >= len(image.descriptors):
            raise ValueError("macro descriptor reference out of range")
        expected_kind = descriptor_for_macro.get(macro)
        if expected_kind is None or image.descriptors[descriptor_id] >> 60 \
                != expected_kind:
            raise ValueError("macro/descriptor kind mismatch")

    keygen_macros = [
        ((word >> 96) & 0xF, (word >> 88) & 0xFF,
         (word >> 52) & 0xFFFFFF)
        for word in image.expanded_keygen[:-1]
    ]
    chain_coordinates = [coord for macro, _descriptor_id, coord
                         in keygen_macros if macro == Macro.CHAIN]
    outer_coordinates = [coord for macro, descriptor_id, coord
                         in keygen_macros
                         if macro == Macro.TREE_PUSH
                         and descriptor_id == 35]
    if chain_coordinates != list(range(1024)) \
            or outer_coordinates != list(range(1024)):
        raise ValueError("Keygen leaf schedule is not a complete affine range")
    inner_coordinates = [coord for macro, descriptor_id, coord
                         in keygen_macros
                         if macro == Macro.TREE_PUSH
                         and descriptor_id == 34]
    if image.family == StatefulFamily.XMSS:
        expected_inner = [leaf | (item << 10)
                          for leaf in range(1024)
                          for item in range(67)]
        if inner_coordinates != expected_inner:
            raise ValueError("XMSS L-tree pushes are not microcode complete")
    elif inner_coordinates:
        raise ValueError("LMS image unexpectedly contains L-tree pushes")

    for record in image.descriptors:
        if record >> 60 == StatefulDescriptorKind.RECIPE:
            stages = (record >> 49) & 0x7
            blocks = ((record >> 44) & 0x1F) + 1
            if not 1 <= stages <= 4 or not 1 <= blocks <= 16:
                raise ValueError("illegal recipe stage/block bound")


def all_stateful_images() -> tuple[StatefulMacroImage, ...]:
    images = (compile_xmss_image(), compile_lms_shake_image())
    for image in images:
        validate_stateful_image(image)
    return images
