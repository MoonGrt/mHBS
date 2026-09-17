"""Assembler for declarative JSON μHBS program sources."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .isa import Instruction, Opcode


class AssemblyError(ValueError):
    pass


def assemble_document(document: dict[str, Any]) -> dict[str, Any]:
    source = document.get("program")
    if not isinstance(source, list):
        raise AssemblyError("program must be a list")
    labels: dict[str, int] = {}
    pc = 0
    for item in source:
        if "label" in item:
            label = item["label"]
            if not isinstance(label, str) or label in labels:
                raise AssemblyError(f"invalid or duplicate label: {label!r}")
            labels[label] = pc
        else:
            pc += 1

    instructions: list[Instruction] = []
    for item in source:
        if "label" in item:
            continue
        try:
            opcode = Opcode[item["op"]]
        except (KeyError, TypeError) as exc:
            raise AssemblyError(f"unknown opcode in {item!r}") from exc
        imm: Any = item.get("imm", 0)
        if "target" in item:
            target = item["target"]
            if target not in labels:
                raise AssemblyError(f"undefined label: {target}")
            imm = labels[target]
        # JSON written before the RTL lane-mask contract commonly omitted the
        # HASH flags field.  Preserve that source compatibility while
        # producing a legal single-lane command.  An explicitly supplied zero
        # remains zero so the verifier can reject author intent rather than
        # silently rewriting it.
        if "flags" in item:
            flags = int(item["flags"])
        else:
            flags = 1 if opcode == Opcode.HASH else 0
        rd = int(item.get("rd", 0))
        if "repeat" in item:
            if opcode != Opcode.HASH or not isinstance(item["repeat"], dict):
                raise AssemblyError("repeat is legal only on HASH")
            repeat = item["repeat"]
            count = int(repeat.get("count", 0))
            counter_reg = int(repeat.get("counter_reg", -1))
            counter_offset = int(repeat.get("counter_offset", -1))
            if not 1 <= count <= 0xFF:
                raise AssemblyError("HASH repeat count must fit 1..255")
            if not 0 <= counter_reg < 8:
                raise AssemblyError("HASH repeat counter_reg must be R0..R7")
            if not 0 <= counter_offset <= 0xFF:
                raise AssemblyError("HASH repeat counter_offset must fit one byte")
            if not 0 <= int(imm) <= 0xFFFF:
                raise AssemblyError("HASH repeat layout id must fit 16 bits")
            flags |= 0x08
            if "capture_reg_base" in repeat:
                capture_reg_base = int(repeat["capture_reg_base"])
                if not 0 <= capture_reg_base < 8:
                    raise AssemblyError(
                        "HASH repeat capture_reg_base must be R0..R7"
                    )
                flags |= 0x10 | capture_reg_base << 5
            rd = counter_reg
            imm = counter_offset << 24 | count << 16 | int(imm)
        inst = Instruction(
            opcode,
            flags,
            rd,
            int(item.get("rs", 0)),
            int(imm),
        )
        inst.encode()
        instructions.append(inst)

    words = [inst.encode() for inst in instructions]
    raw = b"".join(word.to_bytes(8, "big") for word in words)
    return {
        "schema_version": 1,
        "micro_isa_version": document.get("micro_isa_version", "0.2"),
        "name": document.get("name", "unnamed"),
        "entry": labels.get(document.get("entry", "entry"), 0),
        "word_count": len(words),
        "image_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "words": words,
        "instructions": instructions,
        "layouts": document.get("layouts", {}),
        "moves": document.get("moves", {}),
        "loads": document.get("loads", {}),
        "bounds": document.get("bounds", {}),
    }


def load_and_assemble(path: Path | str) -> dict[str, Any]:
    path = Path(path)
    return assemble_document(json.loads(path.read_text(encoding="utf-8")))
