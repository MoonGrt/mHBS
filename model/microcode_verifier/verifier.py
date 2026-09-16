"""Conservative static verifier for μHBS images."""

from __future__ import annotations

from collections import deque
from typing import Any

from model.microcode_assembler.isa import Instruction, Opcode


class VerificationError(ValueError):
    pass


def _loop_pairs(code: list[Instruction]) -> tuple[dict[int, int], dict[int, int]]:
    stack: list[int] = []
    starts: dict[int, int] = {}
    ends: dict[int, int] = {}
    for pc, inst in enumerate(code):
        if inst.opcode == Opcode.LOOP_SETUP:
            stack.append(pc)
            if len(stack) > 6:
                raise VerificationError("loop nesting exceeds six")
        elif inst.opcode == Opcode.LOOP_END:
            if not stack:
                raise VerificationError(f"LOOP_END underflow at pc {pc}")
            start = stack.pop()
            starts[start] = pc
            ends[pc] = start
    if stack:
        raise VerificationError(f"unclosed LOOP_SETUP at pc {stack[-1]}")
    return starts, ends


def verify_image(image: dict[str, Any]) -> dict[str, Any]:
    code = image.get("instructions")
    if not isinstance(code, list) or not code:
        raise VerificationError("empty image")
    if len(code) > 512:
        raise VerificationError("program exceeds 512-word Phase-1 limit")
    if not 0 <= image.get("entry", -1) < len(code):
        raise VerificationError("entry outside program")
    starts, ends = _loop_pairs(code)
    layouts = image.get("layouts", {})
    moves = image.get("moves", {})
    loads = image.get("loads", {})
    xors = image.get("xors", {})
    max_loop_bound = int(image.get("bounds", {}).get("max_loop_bound", 1 << 20))

    flag_sets = {
        Opcode.HASH_LAYOUT: {0x01, 0x02, 0x03},
        Opcode.LOOP_SETUP: {0x00, 0x01},
        Opcode.TREE_PUSH: {0x00, 0x01},
        Opcode.EMIT: {0x00, 0x01},
    }

    for pc, inst in enumerate(code):
        allowed_flags = flag_sets.get(inst.opcode, {0x00})
        if inst.flags not in allowed_flags:
            if inst.opcode == Opcode.HASH_LAYOUT and inst.flags == 0:
                raise VerificationError(
                    f"HASH_LAYOUT lane mask must be nonzero at pc {pc}"
                )
            raise VerificationError(
                f"invalid flags 0x{inst.flags:02x} for "
                f"{inst.opcode.name} at pc {pc}"
            )
        if inst.opcode not in (Opcode.EMIT, Opcode.TREE_PUSH) and inst.rd >= 8:
            raise VerificationError(f"rd register index outside R0..R7 at pc {pc}")
        if inst.rs >= 8:
            raise VerificationError(f"rs register index outside R0..R7 at pc {pc}")
        if inst.opcode == Opcode.LOOP_SETUP:
            if not inst.flags & 0x01 and (inst.imm == 0 or inst.imm > max_loop_bound):
                raise VerificationError(f"invalid loop bound at pc {pc}")
            if inst.flags & 0x01 and inst.imm >= len(code):
                raise VerificationError(f"dynamic-loop exit outside program at pc {pc}")
        if inst.opcode in (Opcode.CALL, Opcode.JUMP) and inst.imm >= len(code):
            raise VerificationError(f"branch target outside program at pc {pc}")
        if inst.opcode in (Opcode.HASH_LAYOUT, Opcode.TREE_PUSH) and str(inst.imm) not in layouts:
            raise VerificationError(f"undefined layout {inst.imm} at pc {pc}")
        if inst.opcode == Opcode.STORE and str(inst.imm) not in moves:
            raise VerificationError(f"undefined move descriptor {inst.imm} at pc {pc}")
        if inst.opcode == Opcode.LOAD and str(inst.imm) not in loads:
            raise VerificationError(f"undefined load descriptor {inst.imm} at pc {pc}")
        if inst.opcode == Opcode.XOR and str(inst.imm) not in xors:
            raise VerificationError(f"undefined XOR descriptor {inst.imm} at pc {pc}")

    # Bounded reachability over pc/call-stack. Loops are represented by both
    # body and exit edges; register values are deliberately not interpreted.
    work = deque([(int(image["entry"]), tuple())])
    seen: set[tuple[int, tuple[int, ...]]] = set()
    terminal = False
    max_call_depth = 0
    while work:
        pc, calls = work.popleft()
        state = (pc, calls)
        if state in seen:
            continue
        seen.add(state)
        if not 0 <= pc < len(code):
            raise VerificationError(f"reachable pc outside program: {pc}")
        inst = code[pc]
        if inst.opcode in (Opcode.HALT, Opcode.FAIL):
            terminal = True
            continue
        if inst.opcode == Opcode.CALL:
            if len(calls) >= 4:
                raise VerificationError("call depth may exceed four")
            new_calls = calls + (pc + 1,)
            max_call_depth = max(max_call_depth, len(new_calls))
            work.append((inst.imm, new_calls))
        elif inst.opcode == Opcode.RET:
            if not calls:
                raise VerificationError(f"reachable RET underflow at pc {pc}")
            work.append((calls[-1], calls[:-1]))
        elif inst.opcode == Opcode.JUMP:
            work.append((inst.imm, calls))
        elif inst.opcode == Opcode.LOOP_SETUP:
            work.append((pc + 1, calls))
            work.append((starts[pc] + 1, calls))
        elif inst.opcode == Opcode.LOOP_END:
            work.append((ends[pc] + 1, calls))
            work.append((pc + 1, calls))
        else:
            work.append((pc + 1, calls))
    if not terminal:
        raise VerificationError("no reachable HALT/FAIL")
    return {
        "verified": True,
        "word_count": len(code),
        "image_bytes": len(code) * 8,
        "max_loop_depth": max(
            (sum(1 for start, end in starts.items() if start < pc <= end) for pc in range(len(code))),
            default=0,
        ),
        "max_call_depth": max_call_depth,
        "reachable_states": len(seen),
    }
