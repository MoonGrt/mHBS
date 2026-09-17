"""μHBS 64-bit instruction encoding."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Opcode(IntEnum):
    SET_REG = 0x01
    ADD_IMM = 0x02
    HASH = 0x03
    LOOP_BEGIN = 0x04
    LOOP_END = 0x05
    CALL = 0x06
    RETURN = 0x07
    DATA_LOAD = 0x08
    DATA_MOVE = 0x09
    TREE_PUSH = 0x0B
    OUTPUT = 0x0C
    HALT = 0x0D


@dataclass(frozen=True)
class Instruction:
    opcode: Opcode
    flags: int = 0
    rd: int = 0
    rs: int = 0
    imm: int = 0

    def encode(self) -> int:
        for name, value, bits in (
            ("flags", self.flags, 8),
            ("rd", self.rd, 8),
            ("rs", self.rs, 8),
            ("imm", self.imm, 32),
        ):
            if not 0 <= value < (1 << bits):
                raise ValueError(f"{name} does not fit {bits} bits: {value}")
        return (
            int(self.opcode) << 56
            | self.flags << 48
            | self.rd << 40
            | self.rs << 32
            | self.imm
        )

    @classmethod
    def decode(cls, word: int) -> "Instruction":
        if not 0 <= word < (1 << 64):
            raise ValueError("instruction word does not fit 64 bits")
        try:
            opcode = Opcode((word >> 56) & 0xFF)
        except ValueError as exc:
            raise ValueError(f"illegal opcode 0x{(word >> 56) & 0xff:02x}") from exc
        return cls(
            opcode=opcode,
            flags=(word >> 48) & 0xFF,
            rd=(word >> 40) & 0xFF,
            rs=(word >> 32) & 0xFF,
            imm=word & 0xFFFFFFFF,
        )
