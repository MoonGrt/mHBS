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
        | (1 << 29)
        | (chain_shape << 25)
        | (parent_shape << 21)
        | (hash_a_shape << 17)
        | (hash_b_shape << 13)
        | (list_reduce << 12)
        | (auth_prefix << 11)
        | (52 << 5)
    )
    return _descriptor(StatefulDescriptorKind.PROFILE, payload)


def _recipe_descriptor(
    recipe: RecipeShape, *, stages: int, max_blocks: int,
    output_bytes: int = 32,
) -> int:
    if not 1 <= stages <= 4:
        raise ValueError("compound recipe must contain one to four stages")
    if not 1 <= max_blocks <= 16:
        raise ValueError("stateful recipe block bound must be in 1..16")
    payload = (
        (int(recipe) << 52)
        | (stages << 49)
        | ((max_blocks - 1) << 44)
        | (output_bytes << 36)
    )
    return _descriptor(StatefulDescriptorKind.RECIPE, payload)


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
    # Descriptor IDs are an ABI shared by the two family wrappers.
    # 32=TREE build, 33=TREE auth lookup, 40=message HASH,
    # 41=OTS CHAIN, 48=base-w/checksum, 50/51=output layouts.
    templates = (
        _template(macro_command(Macro.TREE_PUSH, 31, 0), first=True),
        _template(macro_command(Macro.CHAIN, 42, 0)),
        _template(macro_command(Macro.TREE_PUSH, 32, 0)),
        _template(macro_command(Macro.EMIT, 50, 0)),
        _template(macro_command(Macro.HASH, 40, 0), first=True),
        _template(macro_command(Macro.TRANSFORM, 48, 0)),
        _template(macro_command(Macro.CHAIN, 41, 0)),
        _template(macro_command(Macro.TREE_PUSH, 33, 0)),
        _template(macro_command(Macro.EMIT, 51, 0)),
    )
    keygen_tokens = (
        StaticTaskToken(TOKEN_SINGLE, template=0),
        StaticTaskToken(TOKEN_SINGLE, template=1),
        StaticTaskToken(TOKEN_SINGLE, template=2),
        # 32 leaves per inner loop and 32 inner-loop groups.  The two affine
        # LOOP tokens encode all 1024 leaf constructions without a hardwired
        # leaf counter in the macro executor.
        StaticTaskToken(TOKEN_LOOP, back_count=2, loop_repeats=31,
                        delta0=1),
        StaticTaskToken(TOKEN_LOOP, back_count=3, loop_repeats=31,
                        delta0=32),
        StaticTaskToken(TOKEN_SINGLE, template=3),
        StaticTaskToken(TOKEN_HALT),
    )
    sign_tokens = (
        StaticTaskToken(TOKEN_SINGLE, template=4),
        StaticTaskToken(TOKEN_SINGLE, template=5),
        StaticTaskToken(TOKEN_SINGLE, template=6),
        StaticTaskToken(TOKEN_SINGLE, template=7),
        StaticTaskToken(TOKEN_SINGLE, template=8),
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
    records[40] = _descriptor(
        StatefulDescriptorKind.RECIPE, (1 << 52) | (1 << 49))
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
    output_layout = int(family)
    records[50] = _descriptor(
        StatefulDescriptorKind.EMIT,
        (output_layout << 52) | (1 << 51) | keygen_bytes)
    records[51] = _descriptor(
        StatefulDescriptorKind.EMIT,
        (output_layout << 52) | (1 << 50) | sign_bytes)
    # Generic EMIT constants.  The XMSS layout does not reference them.
    records[52] = _descriptor(
        StatefulDescriptorKind.CONSTANT,
        0x80000006 if family == StatefulFamily.LMS_SHAKE_RESEARCH else 0)
    records[53] = _descriptor(
        StatefulDescriptorKind.CONSTANT,
        0x80000003 if family == StatefulFamily.LMS_SHAKE_RESEARCH else 0)

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

    keygen_macros = [((word >> 96) & 0xF, (word >> 52) & 0xFFFFFF)
                     for word in image.expanded_keygen[:-1]]
    chain_coordinates = [coord for macro, coord in keygen_macros
                         if macro == Macro.CHAIN]
    push_coordinates = [coord for macro, coord in keygen_macros
                        if macro == Macro.TREE_PUSH][1:]
    if chain_coordinates != list(range(1024)) \
            or push_coordinates != list(range(1024)):
        raise ValueError("Keygen leaf schedule is not a complete affine range")

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
