"""Deterministic offline lowering from logical objects to RTL data images.

The Python interpreter addresses variable-length objects by logical slot.  The
RTL Scratchpad addresses 64-bit physical words.  This module freezes the
mapping as::

    physical_word = logical_slot * ceil(logical_slot_bytes / 8)

Every logical slot reserves the same physical stride.  This intentionally
trades compactness for an affine mapping: existing ``base + R[b] +
R[i]*stride`` address expressions remain lowerable without runtime software.

Descriptor v1 is the 128-bit format consumed by the current data descriptor
store.  If every dynamic operand uses one shared register with physical stride
one, v1 is emitted.  Otherwise the complete descriptor table is promoted to
backward-compatible v2: all common v1 fields retain their bit positions and
the low 32 reserved bits point into a 64-bit address-binding side table.

V2 descriptor ``reserved[31:16]`` is the binding-table base,
``reserved[15:12]`` is the binding count, and ``reserved[11:0]`` is zero.  A
binding word is::

    [63:62] operand (0 source_a, 1 source_b, 2 destination)
    [61]    use_base_reg       [60:58] base_reg
    [57]    use_index_reg      [56:54] index_reg
    [53:38] base register scale in physical words
    [37:22] index stride in physical words
    [21:0]  reserved zero
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Iterable, Mapping


WORD_BYTES = 8
FORMAT_V1 = 1
FORMAT_V2 = 2

OPERATION_FLAGS = {"LOAD": 0x0001, "STORE": 0x0002,
                   "XOR": 0x0004, "EMIT": 0x0008}
OPERAND_CODES = {"source_a": 0, "source_b": 1, "destination": 2}


class DataLoweringError(ValueError):
    """Raised when a logical image cannot be represented without ambiguity."""


@dataclass(frozen=True)
class LogicalObject:
    name: str
    slot: int
    data: bytes


@dataclass(frozen=True)
class AddressExpression:
    base: int = 0
    base_reg: int | None = None
    index_reg: int | None = None
    stride: int = 1

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AddressExpression":
        if not isinstance(value, Mapping):
            raise DataLoweringError("address expression must be a mapping")
        allowed = {"base", "base_reg", "index_reg", "stride"}
        unknown = set(value) - allowed
        if unknown:
            raise DataLoweringError(
                f"unsupported address keys: {sorted(unknown)}"
            )
        result = cls(
            base=int(value.get("base", 0)),
            base_reg=(int(value["base_reg"])
                      if "base_reg" in value else None),
            index_reg=(int(value["index_reg"])
                       if "index_reg" in value else None),
            stride=int(value.get("stride", 1)),
        )
        if result.base < 0 or result.stride < 0:
            raise DataLoweringError("address base/stride must be nonnegative")
        for register in (result.base_reg, result.index_reg):
            if register is not None and not 0 <= register < 8:
                raise DataLoweringError("register must be in R0..R7")
        return result

    @property
    def dynamic(self) -> bool:
        return self.base_reg is not None or self.index_reg is not None


@dataclass(frozen=True)
class LogicalDescriptor:
    descriptor_id: int
    operation: str
    byte_count: int
    source_a: AddressExpression | None = None
    source_b: AddressExpression | None = None
    destination: AddressExpression | None = None


@dataclass(frozen=True)
class ObjectPlacement:
    name: str
    logical_slot: int
    base_word: int
    allocated_words: int
    data_words: int
    last_bytes: int


@dataclass(frozen=True)
class BindingEntry:
    operand: str
    use_base_reg: bool
    base_reg: int
    use_index_reg: bool
    index_reg: int
    base_scale_words: int
    index_stride_words: int
    word: int


@dataclass(frozen=True)
class LoweredDescriptor:
    descriptor_id: int
    operation: str
    format_version: int
    word: int
    binding_base: int
    binding_count: int
    shared_index_reg: int | None


@dataclass(frozen=True)
class LoweringResult:
    logical_slot_count: int
    logical_slot_bytes: int
    slot_stride_words: int
    scratch_capacity_words: int
    scratch_words: tuple[int, ...]
    initialized_words: tuple[bool, ...]
    placements: tuple[ObjectPlacement, ...]
    descriptor_format_version: int
    descriptors: tuple[LoweredDescriptor, ...]
    bindings: tuple[BindingEntry, ...]
    sha256: str

    def descriptor_hex(self) -> str:
        return "".join(f"{item.word:032x}\n" for item in self.descriptors)

    def binding_hex(self) -> str:
        return "".join(f"{item.word:016x}\n" for item in self.bindings)

    def scratch_hex(self) -> str:
        return "".join(f"{word:016x}\n" for word in self.scratch_words)


def descriptor_from_program_move(
    document: Mapping[str, Any],
    move_id: int,
    *,
    descriptor_id: int | None = None,
    byte_count: int,
) -> LogicalDescriptor:
    """Translate one existing interpreter ``moves`` entry to a STORE input."""

    try:
        move = document["moves"][str(move_id)]
        source = AddressExpression.from_mapping(move["source"])
        destination = AddressExpression.from_mapping(move["destination"])
    except (KeyError, TypeError) as exc:
        raise DataLoweringError(f"invalid move descriptor {move_id}") from exc
    return LogicalDescriptor(
        descriptor_id=move_id if descriptor_id is None else descriptor_id,
        operation="STORE",
        byte_count=byte_count,
        source_a=source,
        destination=destination,
    )


def _ceil_words(byte_count: int) -> int:
    return (byte_count + WORD_BYTES - 1) // WORD_BYTES


def _last_bytes(byte_count: int) -> int:
    return ((byte_count - 1) % WORD_BYTES) + 1


def _register_range(
    register: int, register_bounds: Mapping[int, tuple[int, int]]
) -> tuple[int, int]:
    if register not in register_bounds:
        raise DataLoweringError(f"missing bounds for R{register}")
    low, high = map(int, register_bounds[register])
    if low < 0 or high < low or high >= (1 << 32):
        raise DataLoweringError(f"invalid bounds for R{register}: {(low, high)}")
    return low, high


def _logical_range(
    address: AddressExpression,
    register_bounds: Mapping[int, tuple[int, int]],
) -> tuple[int, int]:
    low = high = address.base
    if address.base_reg is not None:
        reg_low, reg_high = _register_range(address.base_reg, register_bounds)
        low += reg_low
        high += reg_high
    if address.index_reg is not None:
        reg_low, reg_high = _register_range(address.index_reg, register_bounds)
        low += reg_low * address.stride
        high += reg_high * address.stride
    return low, high


def _required_operands(descriptor: LogicalDescriptor) -> tuple[str, ...]:
    operation = descriptor.operation.upper()
    if operation == "LOAD":
        required = ("source_a",)
    elif operation == "STORE":
        required = ("source_a", "destination")
    elif operation == "XOR":
        required = ("source_a", "source_b", "destination")
    elif operation == "EMIT":
        required = ("source_a",)
    else:
        raise DataLoweringError(f"unsupported operation {descriptor.operation!r}")
    for operand in required:
        if getattr(descriptor, operand) is None:
            raise DataLoweringError(
                f"{operation} descriptor {descriptor.descriptor_id} "
                f"requires {operand}"
            )
    return required


def _v1_shared_index(
    descriptor: LogicalDescriptor,
    required: tuple[str, ...],
    slot_stride_words: int,
) -> tuple[bool, int | None]:
    registers: set[int] = set()
    for operand in required:
        address = getattr(descriptor, operand)
        assert address is not None
        if address.base_reg is not None:
            return False, None
        if address.index_reg is not None:
            if address.stride * slot_stride_words != 1:
                return False, None
            registers.add(address.index_reg)
    if len(registers) > 1:
        return False, None
    return True, next(iter(registers), None)


def _encode_binding(
    operand: str, address: AddressExpression, slot_stride_words: int
) -> BindingEntry:
    use_base = address.base_reg is not None
    use_index = address.index_reg is not None
    base_scale = slot_stride_words if use_base else 0
    index_stride = (
        address.stride * slot_stride_words if use_index else 0
    )
    if base_scale > 0xFFFF or index_stride > 0xFFFF:
        raise DataLoweringError("address-binding coefficient exceeds 16 bits")
    base_reg = address.base_reg or 0
    index_reg = address.index_reg or 0
    word = (
        (OPERAND_CODES[operand] << 62)
        | (int(use_base) << 61)
        | (base_reg << 58)
        | (int(use_index) << 57)
        | (index_reg << 54)
        | (base_scale << 38)
        | (index_stride << 22)
    )
    return BindingEntry(
        operand=operand,
        use_base_reg=use_base,
        base_reg=base_reg,
        use_index_reg=use_index,
        index_reg=index_reg,
        base_scale_words=base_scale,
        index_stride_words=index_stride,
        word=word,
    )


def decode_descriptor_word(word: int) -> dict[str, int]:
    if not 0 <= word < (1 << 128):
        raise DataLoweringError("descriptor word does not fit 128 bits")
    return {
        "format_version": (word >> 120) & 0xFF,
        "flags": (word >> 104) & 0xFFFF,
        "source_a": (word >> 88) & 0xFFFF,
        "source_b": (word >> 72) & 0xFFFF,
        "destination": (word >> 56) & 0xFFFF,
        "word_count": (word >> 40) & 0xFFFF,
        "last_bytes": (word >> 36) & 0xF,
        "address_mode": (word >> 32) & 0xF,
        "reserved": word & 0xFFFFFFFF,
    }


def decode_binding_word(word: int) -> dict[str, int]:
    if not 0 <= word < (1 << 64):
        raise DataLoweringError("binding word does not fit 64 bits")
    operand_code = (word >> 62) & 0x3
    operand_names = {value: key for key, value in OPERAND_CODES.items()}
    if operand_code not in operand_names:
        raise DataLoweringError("reserved binding operand code")
    return {
        "operand": operand_names[operand_code],
        "use_base_reg": (word >> 61) & 1,
        "base_reg": (word >> 58) & 0x7,
        "use_index_reg": (word >> 57) & 1,
        "index_reg": (word >> 54) & 0x7,
        "base_scale_words": (word >> 38) & 0xFFFF,
        "index_stride_words": (word >> 22) & 0xFFFF,
        "reserved": word & ((1 << 22) - 1),
    }


def evaluate_physical_address(
    descriptor_word: int,
    binding_words: Iterable[int],
    operand: str,
    registers: Mapping[int, int],
) -> int:
    """Reference evaluation of a lowered v1/v2 operand address."""

    fields = decode_descriptor_word(descriptor_word)
    base = fields[operand]
    if fields["format_version"] == FORMAT_V1:
        raise DataLoweringError(
            "v1 dynamic address needs the instruction R[rs] value"
        )
    words = tuple(binding_words)
    binding_base = fields["reserved"] >> 16
    binding_count = (fields["reserved"] >> 12) & 0xF
    if binding_base + binding_count > len(words):
        raise DataLoweringError("descriptor binding range exceeds side table")
    for word in words[binding_base:binding_base + binding_count]:
        binding = decode_binding_word(word)
        if binding["operand"] != operand:
            continue
        if binding["use_base_reg"]:
            base += int(registers[binding["base_reg"]]) * binding["base_scale_words"]
        if binding["use_index_reg"]:
            base += int(registers[binding["index_reg"]]) * binding["index_stride_words"]
        return base
    return base


def lower_logical_data(
    objects: Iterable[LogicalObject],
    descriptors: Iterable[LogicalDescriptor],
    *,
    logical_slot_count: int,
    logical_slot_bytes: int,
    scratch_capacity_words: int,
    register_bounds: Mapping[int, tuple[int, int]] | None = None,
) -> LoweringResult:
    """Lower a complete immutable logical-data image and descriptor table."""

    if logical_slot_count < 1 or logical_slot_bytes < 1:
        raise DataLoweringError("logical slot dimensions must be positive")
    slot_stride_words = _ceil_words(logical_slot_bytes)
    required_words = logical_slot_count * slot_stride_words
    if required_words > scratch_capacity_words:
        raise DataLoweringError(
            f"logical image needs {required_words} words, exceeds "
            f"Scratchpad capacity {scratch_capacity_words}"
        )
    if scratch_capacity_words > 65536:
        raise DataLoweringError("Scratchpad exceeds 16-bit descriptor address space")

    physical_words = [0] * scratch_capacity_words
    initialized = [False] * scratch_capacity_words
    placements: list[ObjectPlacement] = []
    seen_slots: set[int] = set()
    object_list = sorted(objects, key=lambda item: (item.slot, item.name))
    for item in object_list:
        if not item.name:
            raise DataLoweringError("logical object name must be nonempty")
        if item.slot in seen_slots:
            raise DataLoweringError(f"overlapping logical slot {item.slot}")
        seen_slots.add(item.slot)
        if not 0 <= item.slot < logical_slot_count:
            raise DataLoweringError(f"logical object {item.name} is out of bounds")
        if not 1 <= len(item.data) <= logical_slot_bytes:
            raise DataLoweringError(
                f"logical object {item.name} length must be in "
                f"1..{logical_slot_bytes} bytes"
            )
        base_word = item.slot * slot_stride_words
        data_words = _ceil_words(len(item.data))
        for offset in range(data_words):
            chunk = item.data[offset * WORD_BYTES:(offset + 1) * WORD_BYTES]
            word_address = base_word + offset
            if initialized[word_address]:
                raise DataLoweringError(
                    f"physical word overlap at {word_address}"
                )
            # Byte zero occupies out_data[7:0], matching AXI-stream keep[0].
            physical_words[word_address] = int.from_bytes(chunk, "little")
            initialized[word_address] = True
        placements.append(ObjectPlacement(
            name=item.name,
            logical_slot=item.slot,
            base_word=base_word,
            allocated_words=slot_stride_words,
            data_words=data_words,
            last_bytes=_last_bytes(len(item.data)),
        ))

    register_bounds = register_bounds or {}
    descriptor_list = sorted(
        descriptors, key=lambda item: (item.descriptor_id, item.operation)
    )
    seen_descriptor_ids: set[int] = set()
    required_by_descriptor: list[tuple[LogicalDescriptor, tuple[str, ...]]]
    required_by_descriptor = []
    table_needs_v2 = False
    shared_registers: dict[int, int | None] = {}
    for item in descriptor_list:
        if item.descriptor_id in seen_descriptor_ids:
            raise DataLoweringError(
                f"duplicate descriptor id {item.descriptor_id}"
            )
        seen_descriptor_ids.add(item.descriptor_id)
        if not 0 <= item.descriptor_id <= 0xFFFF:
            raise DataLoweringError("descriptor id does not fit 16 bits")
        if not 1 <= item.byte_count <= logical_slot_bytes:
            raise DataLoweringError(
                f"descriptor {item.descriptor_id} byte_count must be in "
                f"1..{logical_slot_bytes}"
            )
        operation = item.operation.upper()
        if operation == "LOAD" and item.byte_count > WORD_BYTES:
            raise DataLoweringError("RTL LOAD descriptor must select one word")
        required = _required_operands(item)
        required_by_descriptor.append((item, required))
        for operand in required:
            address = getattr(item, operand)
            assert address is not None
            low, high = _logical_range(address, register_bounds)
            if low < 0 or high >= logical_slot_count:
                raise DataLoweringError(
                    f"descriptor {item.descriptor_id} {operand} logical "
                    f"range [{low}, {high}] is out of bounds"
                )
            physical_base = address.base * slot_stride_words
            if physical_base > 0xFFFF:
                raise DataLoweringError("descriptor base does not fit 16 bits")
            physical_last = high * slot_stride_words + _ceil_words(item.byte_count) - 1
            if physical_last >= scratch_capacity_words:
                raise DataLoweringError(
                    f"descriptor {item.descriptor_id} {operand} physical "
                    "range exceeds Scratchpad"
                )
        can_v1, shared_index = _v1_shared_index(
            item, required, slot_stride_words
        )
        shared_registers[item.descriptor_id] = shared_index
        table_needs_v2 |= not can_v1

    format_version = FORMAT_V2 if table_needs_v2 else FORMAT_V1
    bindings: list[BindingEntry] = []
    lowered_descriptors: list[LoweredDescriptor] = []
    for item, required in required_by_descriptor:
        operation = item.operation.upper()
        word_count = _ceil_words(item.byte_count)
        base_fields = {"source_a": 0, "source_b": 0, "destination": 0}
        address_mode = 0
        binding_base = len(bindings)
        for operand in required:
            address = getattr(item, operand)
            assert address is not None
            base_fields[operand] = address.base * slot_stride_words
            if format_version == FORMAT_V1:
                if address.index_reg is not None:
                    address_mode |= 1 << OPERAND_CODES[operand]
            elif address.dynamic:
                address_mode |= 1 << OPERAND_CODES[operand]
                bindings.append(
                    _encode_binding(operand, address, slot_stride_words)
                )
        binding_count = len(bindings) - binding_base
        if binding_base > 0xFFFF or binding_count > 0xF:
            raise DataLoweringError("address-binding table cannot be encoded")
        reserved = 0
        if format_version == FORMAT_V2:
            reserved = (binding_base << 16) | (binding_count << 12)
        descriptor_word = (
            (format_version << 120)
            | (OPERATION_FLAGS[operation] << 104)
            | (base_fields["source_a"] << 88)
            | (base_fields["source_b"] << 72)
            | (base_fields["destination"] << 56)
            | (word_count << 40)
            | (_last_bytes(item.byte_count) << 36)
            | (address_mode << 32)
            | reserved
        )
        lowered_descriptors.append(LoweredDescriptor(
            descriptor_id=item.descriptor_id,
            operation=operation,
            format_version=format_version,
            word=descriptor_word,
            binding_base=binding_base,
            binding_count=binding_count,
            shared_index_reg=(shared_registers[item.descriptor_id]
                              if format_version == FORMAT_V1 else None),
        ))

    canonical = {
        "logical_slot_count": logical_slot_count,
        "logical_slot_bytes": logical_slot_bytes,
        "slot_stride_words": slot_stride_words,
        "scratch_capacity_words": scratch_capacity_words,
        "scratch_words": [f"{word:016x}" for word in physical_words],
        "initialized_words": initialized,
        "placements": [item.__dict__ for item in placements],
        "descriptor_format_version": format_version,
        "descriptors": [
            {
                **item.__dict__,
                "word": f"{item.word:032x}",
            }
            for item in lowered_descriptors
        ],
        "bindings": [
            {**item.__dict__, "word": f"{item.word:016x}"}
            for item in bindings
        ],
    }
    digest_input = json.dumps(
        canonical, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    return LoweringResult(
        logical_slot_count=logical_slot_count,
        logical_slot_bytes=logical_slot_bytes,
        slot_stride_words=slot_stride_words,
        scratch_capacity_words=scratch_capacity_words,
        scratch_words=tuple(physical_words),
        initialized_words=tuple(initialized),
        placements=tuple(placements),
        descriptor_format_version=format_version,
        descriptors=tuple(lowered_descriptors),
        bindings=tuple(bindings),
        sha256=hashlib.sha256(digest_input).hexdigest(),
    )
