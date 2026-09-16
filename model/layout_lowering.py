"""Lower JSON HASH_LAYOUT components into the native RTL component image.

This is an offline image builder, not a runtime.  It turns the existing JSON
layout language into the algorithm-independent descriptor formats consumed by
``micro_hbs_descriptor_shake_composer``.  The capability covers 16-byte
SLH-DSA and 32-byte XMSS logical slots: literals, Job bytes placed in immutable
Scratchpad slots, 32-bit register words, affine memory references, and
equal-length memory XOR, and bounded affine 32-bit expressions.  Long immutable Job fields are split offline into
aligned bounded components; no execution-time task stream is introduced.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Iterable, Mapping


FORMAT_VERSION = 1
CAP_SHAKE256 = 1
INPUT_COMPONENT_PROGRAM = 2
OUTPUT_LOGICAL_SLOT = 1

COMP_LITERAL_BE = 1
COMP_ZERO = 2
COMP_REGISTER_BE32 = 3
COMP_SCRATCH = 4
COMP_SCRATCH_XOR = 5
COMP_AFFINE_BE32 = 6
COMP_SHIFTED_AFFINE_BE32 = 7
COMP_SELECT_SCRATCH = 8


class LayoutLoweringError(ValueError):
    """A JSON layout cannot be represented by the bounded RTL capability."""


@dataclass(frozen=True)
class AffineSlot:
    base: int = 0
    reg0: int = 0
    scale0: int = 0
    use_reg0: bool = False
    reg1: int = 0
    scale1: int = 0
    use_reg1: bool = False


@dataclass(frozen=True)
class LoweredLayout:
    layout_id: int
    name: str
    descriptor: int
    component_pc: int
    component_count: int
    message_bytes: int
    output_bytes: int


@dataclass(frozen=True)
class LayoutLoweringResult:
    layouts: tuple[LoweredLayout, ...]
    components: tuple[int, ...]
    sha256: str

    def layout_hex(self) -> str:
        return "".join(f"{item.descriptor:032x}\n" for item in self.layouts)

    def component_hex(self) -> str:
        return "".join(f"{word:048x}\n" for word in self.components)


def _bounded(value: int, bits: int, name: str) -> int:
    value = int(value)
    if not 0 <= value < (1 << bits):
        raise LayoutLoweringError(f"{name} does not fit {bits} bits: {value}")
    return value


def _affine(value: Mapping[str, Any]) -> AffineSlot:
    allowed = {"kind", "base", "base_reg", "index_reg", "stride", "length"}
    unknown = set(value) - allowed
    if unknown:
        raise LayoutLoweringError(f"unsupported address keys: {sorted(unknown)}")
    terms: list[tuple[int, int]] = []
    if "base_reg" in value:
        terms.append((_bounded(value["base_reg"], 3, "base_reg"), 1))
    if "index_reg" in value:
        stride = int(value.get("stride", 1))
        if stride <= 0:
            raise LayoutLoweringError("index stride must be positive")
        terms.append((_bounded(value["index_reg"], 3, "index_reg"),
                      _bounded(stride, 16, "index stride")))
    if len(terms) > 2:
        raise LayoutLoweringError("at most two affine register terms are supported")
    padded = terms + [(0, 0)] * (2 - len(terms))
    return AffineSlot(
        base=_bounded(value.get("base", 0), 16, "slot base"),
        reg0=padded[0][0], scale0=padded[0][1], use_reg0=len(terms) >= 1,
        reg1=padded[1][0], scale1=padded[1][1], use_reg1=len(terms) >= 2,
    )


def _component_word(
    kind: int,
    byte_count: int,
    *,
    source_a: AffineSlot = AffineSlot(),
    source_b: AffineSlot = AffineSlot(),
    immediate: int = 0,
) -> int:
    byte_count = _bounded(byte_count, 8, "component byte count")
    if byte_count == 0:
        raise LayoutLoweringError("zero-length components are not representable")
    flags = (
        int(source_a.use_reg0)
        | (int(source_a.use_reg1) << 1)
        | (int(source_b.use_reg0) << 2)
        | (int(source_b.use_reg1) << 3)
    )
    word = 0
    word |= FORMAT_VERSION << 184
    word |= _bounded(kind, 8, "component kind") << 176
    word |= byte_count << 168
    word |= flags << 160
    word |= _bounded(source_a.base, 16, "source A base") << 144
    word |= _bounded(source_a.reg0, 3, "source A reg0") << 140
    word |= _bounded(source_a.scale0, 16, "source A scale0") << 124
    word |= _bounded(source_a.reg1, 3, "source A reg1") << 120
    word |= _bounded(source_a.scale1, 16, "source A scale1") << 104
    word |= _bounded(source_b.base, 16, "source B base") << 88
    word |= _bounded(source_b.reg0, 3, "source B reg0") << 84
    word |= _bounded(source_b.scale0, 16, "source B scale0") << 68
    word |= _bounded(source_b.reg1, 3, "source B reg1") << 64
    word |= _bounded(source_b.scale1, 16, "source B scale1") << 48
    word |= _bounded(immediate, 32, "component immediate") << 16
    return word


def decode_component_word(word: int) -> dict[str, int]:
    _bounded(word, 192, "component word")
    return {
        "format_version": (word >> 184) & 0xFF,
        "kind": (word >> 176) & 0xFF,
        "byte_count": (word >> 168) & 0xFF,
        "flags": (word >> 160) & 0xFF,
        "a_base": (word >> 144) & 0xFFFF,
        "a_reg0": (word >> 140) & 0x7,
        "a_scale0": (word >> 124) & 0xFFFF,
        "a_reg1": (word >> 120) & 0x7,
        "a_scale1": (word >> 104) & 0xFFFF,
        "b_base": (word >> 88) & 0xFFFF,
        "b_reg0": (word >> 84) & 0x7,
        "b_scale0": (word >> 68) & 0xFFFF,
        "b_reg1": (word >> 64) & 0x7,
        "b_scale1": (word >> 48) & 0xFFFF,
        "immediate": (word >> 16) & 0xFFFFFFFF,
        "reserved": word & 0xFFFF,
    }


def decode_layout_descriptor(word: int) -> dict[str, int]:
    _bounded(word, 128, "layout descriptor")
    return {
        "format_version": (word >> 120) & 0xFF,
        "capability": (word >> 112) & 0xFF,
        "input_mode": (word >> 104) & 0xFF,
        "output_mode": (word >> 96) & 0xFF,
        "flags": (word >> 80) & 0xFFFF,
        "message_bytes": (word >> 64) & 0xFFFF,
        "component_pc": (word >> 48) & 0xFFFF,
        "component_count": (word >> 40) & 0xFF,
        "source_count": (word >> 32) & 0xFF,
        "destination": word & 0xFFFFFFFF,
    }


def _literal_words(value: bytes) -> list[int]:
    result: list[int] = []
    offset = 0
    while offset < len(value):
        if value[offset] == 0:
            end = offset
            while end < len(value) and value[end] == 0 and end-offset < 255:
                end += 1
            result.append(_component_word(COMP_ZERO, end-offset))
            offset = end
        else:
            end = offset
            while end < len(value) and value[end] != 0 and end-offset < 4:
                end += 1
            chunk = value[offset:end]
            result.append(_component_word(
                COMP_LITERAL_BE, len(chunk),
                immediate=int.from_bytes(chunk, "big"),
            ))
            offset = end
    return result


def _affine_expression(node: Mapping[str, Any]) -> tuple[int, dict[int, int]]:
    """Return ``constant + sum(register * scale)`` for a bounded expression."""

    kind = node.get("kind")
    if kind == "literal_int":
        return int(node["value"]), {}
    if kind == "reg":
        return 0, {_bounded(node["reg"], 3, "expression register"): 1}
    op = node.get("op")
    if op == "add":
        constant = 0
        terms: dict[int, int] = {}
        for arg in node.get("args", []):
            child_constant, child_terms = _affine_expression(arg)
            constant += child_constant
            for reg, scale in child_terms.items():
                terms[reg] = terms.get(reg, 0) + scale
        return constant, terms
    if op == "mul":
        args = list(node.get("args", []))
        if len(args) != 2:
            raise LayoutLoweringError("affine multiplication must be binary")
        literal_index = next((i for i, item in enumerate(args)
                              if isinstance(item, Mapping)
                              and item.get("kind") == "literal_int"), None)
        if literal_index is None:
            raise LayoutLoweringError("affine multiplication requires a literal")
        multiplier = int(args[literal_index]["value"])
        constant, terms = _affine_expression(args[1-literal_index])
        return constant * multiplier, {
            reg: scale * multiplier for reg, scale in terms.items()
        }
    raise LayoutLoweringError("expression is not a bounded affine form")


def _affine_component(node: Mapping[str, Any]) -> int:
    constant, terms = _affine_expression(node)
    if constant < 0 or len(terms) > 2 or any(scale <= 0 for scale in terms.values()):
        raise LayoutLoweringError("affine expression is outside RTL bounds")
    ordered = sorted(terms.items())
    padded = ordered + [(0, 0)] * (2-len(ordered))
    source = AffineSlot(
        base=_bounded(constant, 16, "affine constant"),
        reg0=padded[0][0], scale0=_bounded(padded[0][1], 16, "affine scale"),
        use_reg0=len(ordered) >= 1,
        reg1=padded[1][0], scale1=_bounded(padded[1][1], 16, "affine scale"),
        use_reg1=len(ordered) >= 2,
    )
    return _component_word(COMP_AFFINE_BE32, 4, source_a=source)


def _affine_slot(node: Mapping[str, Any]) -> AffineSlot:
    constant, terms = _affine_expression(node)
    if constant < 0 or len(terms) > 2 or any(scale <= 0 for scale in terms.values()):
        raise LayoutLoweringError("affine expression is outside RTL bounds")
    ordered = sorted(terms.items())
    padded = ordered + [(0, 0)] * (2-len(ordered))
    return AffineSlot(
        base=_bounded(constant, 16, "affine constant"),
        reg0=padded[0][0], scale0=_bounded(padded[0][1], 16, "affine scale"),
        use_reg0=len(ordered) >= 1,
        reg1=padded[1][0], scale1=_bounded(padded[1][1], 16, "affine scale"),
        use_reg1=len(ordered) >= 2,
    )


def _shift_register(node: Mapping[str, Any]) -> tuple[int, int]:
    constant, terms = _affine_expression(node)
    if constant < 0 or constant > 31 or len(terms) != 1:
        raise LayoutLoweringError("shift amount must be one register plus 0..31")
    reg, scale = next(iter(terms.items()))
    if scale != 1:
        raise LayoutLoweringError("shift-register coefficient must be one")
    return reg, constant


def _shifted_affine_component(node: Mapping[str, Any]) -> int:
    if node.get("op") != "shr":
        raise LayoutLoweringError("expression is not shifted affine")
    source = _affine_slot(node["value"])
    shift_reg, shift_add = _shift_register(node["shift"])
    immediate = shift_reg | (shift_add << 3)
    return _component_word(
        COMP_SHIFTED_AFFINE_BE32, 4,
        source_a=source, immediate=immediate,
    )


def _bit_condition(node: Mapping[str, Any]) -> tuple[int, int, int]:
    if node.get("op") != "and":
        raise LayoutLoweringError("ordered-pair condition must select one bit")
    args = list(node.get("args", []))
    if len(args) != 2:
        raise LayoutLoweringError("ordered-pair condition must be binary")
    one = next((item for item in args if isinstance(item, Mapping)
                and item.get("kind") == "literal_int"
                and int(item.get("value", -1)) == 1), None)
    shifted = next((item for item in args if isinstance(item, Mapping)
                    and item.get("op") == "shr"), None)
    if one is None or shifted is None:
        raise LayoutLoweringError("ordered-pair condition must be (reg >> shift) & 1")
    value = shifted.get("value")
    if not isinstance(value, Mapping) or value.get("kind") != "reg":
        raise LayoutLoweringError("ordered-pair value must be a register")
    value_reg = _bounded(value["reg"], 3, "condition value register")
    shift_reg, shift_add = _shift_register(shifted["shift"])
    return value_reg, shift_reg, shift_add


def _job_source(
    component: Mapping[str, Any],
    job_field_slots: Mapping[str, int],
    job_field_lengths: Mapping[str, int],
) -> tuple[AffineSlot, int]:
    field = str(component["field"])
    if field not in job_field_slots:
        raise LayoutLoweringError(f"missing Scratchpad slot for Job field {field}")
    explicit = component.get("length", component.get("bytes"))
    if explicit is None:
        if field not in job_field_lengths:
            raise LayoutLoweringError(f"missing byte length for Job field {field}")
        explicit = job_field_lengths[field]
    length = int(explicit)
    if length <= 0:
        raise LayoutLoweringError(f"Job field {field} length must be positive")
    return AffineSlot(base=_bounded(job_field_slots[field], 16, "Job slot")), length


def _addressable(
    component: Mapping[str, Any],
    *,
    slot_bytes: int,
    job_field_slots: Mapping[str, int],
    job_field_lengths: Mapping[str, int],
    temp_slots: Mapping[str, int],
    memory_lengths: Mapping[int, int],
    memory_slot_map: Mapping[int, int],
) -> tuple[AffineSlot, int]:
    kind = component.get("kind")
    if kind == "memory":
        base = int(component.get("base", 0))
        physical = dict(component)
        physical["base"] = memory_slot_map.get(base, base)
        return _affine(physical), int(
            component.get("length", memory_lengths.get(base, slot_bytes))
        )
    if kind in {"job_bytes", "job_int"}:
        return _job_source(component, job_field_slots, job_field_lengths)
    if kind == "temp":
        name = str(component["name"])
        if name not in temp_slots:
            raise LayoutLoweringError(f"missing slot for temp {name}")
        return AffineSlot(base=temp_slots[name]), int(component.get("length", slot_bytes))
    raise LayoutLoweringError(f"{kind!r} is not an addressable RTL source")


def _lower_component(
    component: Mapping[str, Any],
    *,
    slot_bytes: int,
    job_field_slots: Mapping[str, int],
    job_field_lengths: Mapping[str, int],
    temp_slots: Mapping[str, int],
    memory_lengths: Mapping[int, int],
    memory_slot_map: Mapping[int, int],
) -> tuple[list[int], int]:
    kind = component.get("kind")
    if kind == "literal":
        value = bytes.fromhex(str(component.get("hex", "")))
        if not value:
            raise LayoutLoweringError("empty literal component")
        return _literal_words(value), len(value)
    if kind in {"job_bytes", "job_int", "memory", "temp"}:
        source, length = _addressable(
            component, slot_bytes=slot_bytes,
            job_field_slots=job_field_slots,
            job_field_lengths=job_field_lengths,
            temp_slots=temp_slots,
            memory_lengths=memory_lengths,
            memory_slot_map=memory_slot_map,
        )
        if length <= 0:
            raise LayoutLoweringError("Scratchpad component length must be positive")
        maximum_aligned = (255 // slot_bytes) * slot_bytes
        if maximum_aligned == 0:
            raise LayoutLoweringError("logical slot is wider than a component")
        words: list[int] = []
        offset = 0
        while length - offset > 255:
            chunk = maximum_aligned
            chunk_source = AffineSlot(
                base=_bounded(source.base + offset // slot_bytes, 16,
                              "split Scratchpad source"),
                reg0=source.reg0, scale0=source.scale0,
                use_reg0=source.use_reg0,
                reg1=source.reg1, scale1=source.scale1,
                use_reg1=source.use_reg1,
            )
            words.append(_component_word(
                COMP_SCRATCH, chunk, source_a=chunk_source
            ))
            offset += chunk
        chunk_source = AffineSlot(
            base=_bounded(source.base + offset // slot_bytes, 16,
                          "split Scratchpad source"),
            reg0=source.reg0, scale0=source.scale0,
            use_reg0=source.use_reg0,
            reg1=source.reg1, scale1=source.scale1,
            use_reg1=source.use_reg1,
        )
        words.append(_component_word(
            COMP_SCRATCH, length - offset, source_a=chunk_source
        ))
        return words, length
    if kind == "memory_range":
        count = int(component.get("count", 0))
        if count <= 0:
            raise LayoutLoweringError("memory range count must be positive")
        return _lower_component(
            {"kind": "memory", "base": int(component.get("base", 0)),
             "length": count * slot_bytes},
            slot_bytes=slot_bytes, job_field_slots=job_field_slots,
            job_field_lengths=job_field_lengths, temp_slots=temp_slots,
            memory_lengths=memory_lengths, memory_slot_map=memory_slot_map,
        )
    if kind == "reg":
        if int(component.get("bytes", 4)) != 4 or component.get("endian", "big") != "big":
            raise LayoutLoweringError("RTL register components require big-endian 32-bit words")
        if int(component.get("add", 0)) != 0:
            raise LayoutLoweringError("register add requires expression lowering")
        reg = _bounded(component["reg"], 3, "register")
        return [_component_word(COMP_REGISTER_BE32, 4, immediate=reg)], 4
    if kind == "word_array":
        width = int(component.get("word_bytes", 4))
        if width != 4 or component.get("endian", "big") != "big":
            raise LayoutLoweringError("RTL word arrays require big-endian 32-bit words")
        words: list[int] = []
        for item in component.get("words", []):
            if isinstance(item, int):
                value = _bounded(item, 32, "word-array literal")
                words.extend(_literal_words(value.to_bytes(4, "big")))
            elif isinstance(item, Mapping) and item.get("kind") == "reg":
                if int(item.get("add", 0)) != 0:
                    raise LayoutLoweringError("word-array register add requires expression lowering")
                reg = _bounded(item["reg"], 3, "word-array register")
                words.append(_component_word(COMP_REGISTER_BE32, 4, immediate=reg))
            elif isinstance(item, Mapping) and item.get("kind") == "literal_int":
                value = _bounded(item["value"], 32, "word-array literal")
                words.extend(_literal_words(value.to_bytes(4, "big")))
            elif isinstance(item, Mapping) and item.get("kind") == "expr":
                expression = item.get("expression")
                if not isinstance(expression, Mapping):
                    raise LayoutLoweringError("word-array expression is malformed")
                try:
                    words.append(_affine_component(expression))
                except LayoutLoweringError:
                    words.append(_shifted_affine_component(expression))
            else:
                raise LayoutLoweringError("word-array expression/context is not yet lowered")
        if not words:
            raise LayoutLoweringError("empty word array")
        return words, 4 * len(component.get("words", []))
    if kind == "xor":
        source_a, length_a = _addressable(
            component["left"], slot_bytes=slot_bytes,
            job_field_slots=job_field_slots,
            job_field_lengths=job_field_lengths, temp_slots=temp_slots,
            memory_lengths=memory_lengths,
            memory_slot_map=memory_slot_map,
        )
        source_b, length_b = _addressable(
            component["right"], slot_bytes=slot_bytes,
            job_field_slots=job_field_slots,
            job_field_lengths=job_field_lengths, temp_slots=temp_slots,
            memory_lengths=memory_lengths,
            memory_slot_map=memory_slot_map,
        )
        if length_a != length_b or not 0 < length_a <= 255:
            raise LayoutLoweringError("XOR sources must have equal length 1..255")
        return [_component_word(
            COMP_SCRATCH_XOR, length_a,
            source_a=source_a, source_b=source_b,
        )], length_a
    if kind == "ordered_pair":
        when_zero = list(component.get("when_zero", []))
        when_nonzero = list(component.get("when_nonzero", []))
        if len(when_zero) != 2 or len(when_nonzero) != 2:
            raise LayoutLoweringError("ordered pair needs two sources per branch")
        value_reg, shift_reg, shift_add = _bit_condition(component["condition"])
        immediate = value_reg | (shift_reg << 3) | (shift_add << 6)
        words: list[int] = []
        total = 0
        for zero_source, nonzero_source in zip(when_zero, when_nonzero, strict=True):
            source_a, length_a = _addressable(
                zero_source, slot_bytes=slot_bytes,
                job_field_slots=job_field_slots,
                job_field_lengths=job_field_lengths, temp_slots=temp_slots,
                memory_lengths=memory_lengths, memory_slot_map=memory_slot_map,
            )
            source_b, length_b = _addressable(
                nonzero_source, slot_bytes=slot_bytes,
                job_field_slots=job_field_slots,
                job_field_lengths=job_field_lengths, temp_slots=temp_slots,
                memory_lengths=memory_lengths, memory_slot_map=memory_slot_map,
            )
            if length_a != length_b or not 0 < length_a <= 255:
                raise LayoutLoweringError(
                    "ordered-pair alternatives must have equal length 1..255"
                )
            words.append(_component_word(
                COMP_SELECT_SCRATCH, length_a,
                source_a=source_a, source_b=source_b,
                immediate=immediate,
            ))
            total += length_a
        return words, total
    raise LayoutLoweringError(f"unsupported layout component kind {kind!r}")


def _destination_word(
    destination: Mapping[str, Any], memory_slot_map: Mapping[int, int]
) -> int:
    logical_base = int(destination.get("base", 0))
    base = _bounded(memory_slot_map.get(logical_base, logical_base), 8,
                    "destination base")
    use_base = "base_reg" in destination
    base_reg = _bounded(destination.get("base_reg", 0), 3, "destination base_reg")
    use_index = "index_reg" in destination
    index_reg = _bounded(destination.get("index_reg", 0), 3, "destination index_reg")
    stride = int(destination.get("stride", 1 if use_index else 0))
    if use_index and stride <= 0:
        raise LayoutLoweringError("destination index stride must be positive")
    stride = _bounded(stride, 8, "destination stride")
    return (
        (base << 24) | (base_reg << 21) | (int(use_base) << 20)
        | (index_reg << 17) | (int(use_index) << 16) | (stride << 8)
    )


def lower_layouts(
    document: Mapping[str, Any],
    layout_ids: Iterable[int],
    *,
    job_field_slots: Mapping[str, int],
    job_field_lengths: Mapping[str, int] | None = None,
    temp_slots: Mapping[str, int] | None = None,
    memory_lengths: Mapping[int, int] | None = None,
    memory_slot_map: Mapping[int, int] | None = None,
    slot_bytes: int = 32,
) -> LayoutLoweringResult:
    """Compile selected JSON layouts into one immutable RTL image."""

    if slot_bytes not in {16, 32}:
        raise LayoutLoweringError("RTL component mode requires 16- or 32-byte slots")
    job_field_lengths = job_field_lengths or {}
    temp_slots = temp_slots or {}
    memory_lengths = memory_lengths or {}
    memory_slot_map = memory_slot_map or {}
    components: list[int] = []
    layouts: list[LoweredLayout] = []
    for layout_id in layout_ids:
        try:
            layout = document["layouts"][str(int(layout_id))]
        except (KeyError, TypeError) as exc:
            raise LayoutLoweringError(f"unknown layout {layout_id}") from exc
        if layout.get("hash") != "shake256":
            raise LayoutLoweringError("component mode currently supports SHAKE256")
        component_pc = len(components)
        message_bytes = 0
        for source in layout.get("components", []):
            lowered, byte_count = _lower_component(
                source, slot_bytes=slot_bytes,
                job_field_slots=job_field_slots,
                job_field_lengths=job_field_lengths,
                temp_slots=temp_slots,
                memory_lengths=memory_lengths,
                memory_slot_map=memory_slot_map,
            )
            components.extend(lowered)
            message_bytes += byte_count
        component_count = len(components) - component_pc
        if not 0 < component_count <= 255:
            raise LayoutLoweringError("layout component count must be 1..255")
        if component_pc > 0xFFFF or message_bytes > 0xFFFF:
            raise LayoutLoweringError("layout image exceeds RTL field width")
        maximum = int(layout.get("max_input_bytes", message_bytes))
        if message_bytes > maximum:
            raise LayoutLoweringError("composed message exceeds max_input_bytes")
        output_bytes = int(layout.get("output_bytes", 32))
        if not 0 < output_bytes <= 136:
            raise LayoutLoweringError("SHAKE output length must be 1..136")
        destination = layout.get("destination")
        if not isinstance(destination, Mapping):
            raise LayoutLoweringError("layout destination must be explicit")
        descriptor = (
            (FORMAT_VERSION << 120) | (CAP_SHAKE256 << 112)
            | (INPUT_COMPONENT_PROGRAM << 104) | (OUTPUT_LOGICAL_SLOT << 96)
            | (output_bytes << 80) | (message_bytes << 64)
            | (component_pc << 48) | (component_count << 40)
            | (component_count << 32)
            | _destination_word(destination, memory_slot_map)
        )
        layouts.append(LoweredLayout(
            layout_id=int(layout_id), name=str(layout.get("name", layout_id)),
            descriptor=descriptor, component_pc=component_pc,
            component_count=component_count, message_bytes=message_bytes,
            output_bytes=output_bytes,
        ))
    payload = b"".join(item.descriptor.to_bytes(16, "big") for item in layouts)
    payload += b"".join(word.to_bytes(24, "big") for word in components)
    return LayoutLoweringResult(
        layouts=tuple(layouts), components=tuple(components),
        sha256=hashlib.sha256(payload).hexdigest(),
    )
