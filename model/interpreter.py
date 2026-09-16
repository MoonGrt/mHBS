"""Instruction-level μHBS model with one-Job autonomous execution."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any

from model.microcode_assembler.isa import Instruction, Opcode
from model.microcode_verifier.verifier import VerificationError, verify_image
from model.treehash import StorageMode, TreeHash


class ExecutionFault(RuntimeError):
    def __init__(self, code: str, pc: int):
        super().__init__(f"{code} at pc {pc}")
        self.code = code
        self.pc = pc


@dataclass
class ExecutionResult:
    done: bool
    error: str | None
    output: bytes
    trace: list[dict[str, Any]]
    counters: dict[str, int]
    hash_trace_sha256: str
    memory: dict[int, bytes] = field(repr=False)


class MicroInterpreter:
    def __init__(self, image: dict[str, Any], trace_mode: str = "full"):
        if trace_mode not in {"full", "hash", "none"}:
            raise ValueError("trace_mode must be full, hash, or none")
        self.image = image
        self.trace_mode = trace_mode
        self.verification = verify_image(image)
        self.code: list[Instruction] = image["instructions"]
        self.loop_end, self.loop_start = self._pair_loops(self.code)
        self.scratch_slots = int(image.get("bounds", {}).get("scratch_slots", 256))
        self.max_steps = int(image.get("bounds", {}).get("max_dynamic_instructions", 10_000_000))

    @staticmethod
    def _pair_loops(code: list[Instruction]) -> tuple[dict[int, int], dict[int, int]]:
        stack: list[int] = []
        start_to_end: dict[int, int] = {}
        end_to_start: dict[int, int] = {}
        for pc, inst in enumerate(code):
            if inst.opcode == Opcode.LOOP_SETUP:
                stack.append(pc)
            elif inst.opcode == Opcode.LOOP_END:
                start = stack.pop()
                start_to_end[start] = pc
                end_to_start[pc] = start
        return start_to_end, end_to_start

    def _address(self, component: dict[str, Any], regs: list[int]) -> int:
        address = int(component.get("base", 0))
        if "base_reg" in component:
            address += regs[int(component["base_reg"])]
        if "index_reg" in component:
            address += regs[int(component["index_reg"])] * int(component.get("stride", 1))
        if not 0 <= address < self.scratch_slots:
            raise ExecutionFault("ERR_SCRATCH_BOUNDS", self.pc)
        return address

    def _eval_int_expression(
        self,
        expression: Any,
        job: dict[str, Any],
        regs: list[int],
        memory: dict[int, bytes],
        context: dict[str, Any],
    ) -> int:
        """Evaluate the deliberately small, side-effect-free layout ALU."""
        if isinstance(expression, int):
            return expression
        if not isinstance(expression, dict):
            raise ExecutionFault("ERR_INTEGER_EXPRESSION", self.pc)
        kind = expression.get("kind")
        if kind == "literal_int":
            value = int(expression["value"])
        elif kind == "reg":
            value = regs[int(expression["reg"])]
        elif kind == "job_int":
            value = job.get(expression["field"])
            if not isinstance(value, int):
                raise ExecutionFault("ERR_JOB_FIELD", self.pc)
        elif kind == "memory_int":
            address = self._address(expression, regs)
            if address not in memory:
                raise ExecutionFault("ERR_UNINITIALIZED_READ", self.pc)
            value = int.from_bytes(memory[address], expression.get("endian", "big"))
        elif kind == "context":
            name = str(expression["name"])
            if name not in context:
                raise ExecutionFault("ERR_TREE_LAYOUT", self.pc)
            value = int(context[name])
        else:
            operation = expression.get("op")
            if operation in {"add", "mul", "xor", "and", "or"}:
                arguments = [
                    self._eval_int_expression(item, job, regs, memory, context)
                    for item in expression.get("args", [])
                ]
                if not arguments:
                    raise ExecutionFault("ERR_INTEGER_EXPRESSION", self.pc)
                value = arguments[0]
                for argument in arguments[1:]:
                    if operation == "add":
                        value += argument
                    elif operation == "mul":
                        value *= argument
                    elif operation == "xor":
                        value ^= argument
                    elif operation == "and":
                        value &= argument
                    else:
                        value |= argument
            elif operation == "sub":
                value = self._eval_int_expression(
                    expression["left"], job, regs, memory, context
                ) - self._eval_int_expression(
                    expression["right"], job, regs, memory, context
                )
            elif operation in {"shl", "shr"}:
                value = self._eval_int_expression(
                    expression["value"], job, regs, memory, context
                )
                shift = self._eval_int_expression(
                    expression["shift"], job, regs, memory, context
                )
                if shift < 0 or shift > 4096:
                    raise ExecutionFault("ERR_INTEGER_EXPRESSION", self.pc)
                value = value << shift if operation == "shl" else value >> shift
            else:
                raise ExecutionFault("ERR_INTEGER_EXPRESSION", self.pc)
        value += int(expression.get("add", 0))
        if value < 0:
            raise ExecutionFault("ERR_ARITH_OVERFLOW", self.pc)
        return value

    def _compose(
        self,
        layout: dict[str, Any],
        job: dict[str, Any],
        regs: list[int],
        memory: dict[int, bytes],
        context: dict[str, Any] | None = None,
        temps: dict[str, bytes] | None = None,
    ) -> bytes:
        context = context or {}
        temps = temps or {}
        chunks = [
            self._component(component, job, regs, memory, context, temps)
            for component in layout.get("components", [])
        ]
        result = b"".join(chunks)
        if len(result) > int(layout.get("max_input_bytes", len(result))):
            raise ExecutionFault("ERR_LAYOUT_LENGTH", self.pc)
        return result

    def _component(
        self,
        component: dict[str, Any],
        job: dict[str, Any],
        regs: list[int],
        memory: dict[int, bytes],
        context: dict[str, Any],
        temps: dict[str, bytes],
    ) -> bytes:
        kind = component.get("kind")
        if kind == "literal":
            return bytes.fromhex(component.get("hex", ""))
        if kind == "job_bytes":
            value = job.get(component["field"])
            if not isinstance(value, bytes):
                raise ExecutionFault("ERR_JOB_FIELD", self.pc)
            expected = component.get("length")
            if expected is not None and len(value) != int(expected):
                raise ExecutionFault("ERR_JOB_FIELD_LENGTH", self.pc)
            return value
        if kind == "job_int":
            value = job.get(component["field"])
            if not isinstance(value, int) or value < 0:
                raise ExecutionFault("ERR_JOB_FIELD", self.pc)
            try:
                return value.to_bytes(int(component["bytes"]), component.get("endian", "big"))
            except OverflowError as exc:
                raise ExecutionFault("ERR_JOB_FIELD_WIDTH", self.pc) from exc
        if kind == "reg":
            value = regs[int(component["reg"])] + int(component.get("add", 0))
            try:
                return value.to_bytes(int(component["bytes"]), component.get("endian", "big"))
            except OverflowError as exc:
                raise ExecutionFault("ERR_REGISTER_WIDTH", self.pc) from exc
        if kind == "memory":
            address = self._address(component, regs)
            if address not in memory:
                raise ExecutionFault("ERR_UNINITIALIZED_READ", self.pc)
            return memory[address]
        if kind == "memory_range":
            base = int(component["base"])
            count = int(component["count"])
            if base < 0 or count < 0 or base + count > self.scratch_slots:
                raise ExecutionFault("ERR_SCRATCH_BOUNDS", self.pc)
            chunks: list[bytes] = []
            for address in range(base, base + count):
                if address not in memory:
                    raise ExecutionFault("ERR_UNINITIALIZED_READ", self.pc)
                chunks.append(memory[address])
            return b"".join(chunks)
        if kind == "temp":
            name = str(component["name"])
            if name not in temps:
                raise ExecutionFault("ERR_UNINITIALIZED_TEMP", self.pc)
            return temps[name]
        if kind in {
            "tree_index",
            "tree_height",
            "tree_parent_height",
            "tree_parent_index",
            "tree_start_leaf",
        }:
            if kind not in context:
                raise ExecutionFault("ERR_TREE_LAYOUT", self.pc)
            try:
                return int(context[kind]).to_bytes(
                    int(component["bytes"]), component.get("endian", "big")
                )
            except OverflowError as exc:
                raise ExecutionFault("ERR_REGISTER_WIDTH", self.pc) from exc
        if kind == "ordered_pair":
            condition = self._eval_int_expression(
                component["condition"], job, regs, memory, context
            )
            branch = component["when_zero" if condition == 0 else "when_nonzero"]
            if not isinstance(branch, list) or len(branch) != 2:
                raise ExecutionFault("ERR_LAYOUT_COMPONENT", self.pc)
            return b"".join(
                self._component(item, job, regs, memory, context, temps)
                for item in branch
            )
        if kind in {"tree_left", "tree_right"}:
            if kind not in context:
                raise ExecutionFault("ERR_TREE_LAYOUT", self.pc)
            return context[kind]
        if kind == "xor":
            left = self._component(component["left"], job, regs, memory, context, temps)
            right = self._component(component["right"], job, regs, memory, context, temps)
            if len(left) != len(right):
                raise ExecutionFault("ERR_XOR_LENGTH", self.pc)
            return bytes(a ^ b for a, b in zip(left, right, strict=True))
        if kind == "word_array":
            width = int(component.get("word_bytes", 4))
            endian = component.get("endian", "big")
            words: list[bytes] = []
            for word in component.get("words", []):
                if isinstance(word, int):
                    value = word
                elif isinstance(word, dict):
                    word_kind = word.get("kind")
                    if word_kind == "literal_int":
                        value = int(word["value"])
                    elif word_kind == "reg":
                        value = regs[int(word["reg"])] + int(word.get("add", 0))
                    elif word_kind == "expr":
                        value = self._eval_int_expression(
                            word["expression"], job, regs, memory, context
                        )
                    elif word_kind in {
                        "tree_height",
                        "tree_parent_height",
                        "tree_parent_index",
                        "tree_start_leaf",
                    }:
                        if word_kind not in context:
                            raise ExecutionFault("ERR_TREE_LAYOUT", self.pc)
                        value = int(context[word_kind]) + int(word.get("add", 0))
                    else:
                        raise ExecutionFault("ERR_LAYOUT_COMPONENT", self.pc)
                else:
                    raise ExecutionFault("ERR_LAYOUT_COMPONENT", self.pc)
                try:
                    words.append(value.to_bytes(width, endian))
                except OverflowError as exc:
                    raise ExecutionFault("ERR_REGISTER_WIDTH", self.pc) from exc
            return b"".join(words)
        raise ExecutionFault("ERR_LAYOUT_COMPONENT", self.pc)

    def _hash(self, name: str, data: bytes, out_len: int) -> bytes:
        if name == "sha256":
            if out_len > 32:
                raise ExecutionFault("ERR_HASH_OUTPUT_LENGTH", self.pc)
            return hashlib.sha256(data).digest()[:out_len]
        if name == "shake256":
            return hashlib.shake_256(data).digest(out_len)
        raise ExecutionFault("ERR_HASH_ALGORITHM", self.pc)

    def execute(self, job: dict[str, Any]) -> ExecutionResult:
        # A call to execute is the acceptance of exactly one immutable Job.
        frozen_job = dict(job)
        regs = [0] * 8
        memory: dict[int, bytes] = {}
        output = bytearray()
        trace: list[dict[str, Any]] = []
        loops: list[dict[str, int]] = []
        calls: list[int] = []
        counters = {
            "accepted_job_commands": 1,
            "host_control_writes_during_busy": 0,
            "external_task_descriptors": 0,
            "external_hash_descriptors": 0,
            "dynamic_instructions": 0,
            "hash_calls": 0,
            "keccak_permutations": 0,
        }
        trace_digest = hashlib.sha256()
        tree: TreeHash | None = None

        def record_hash(kind: str, data: bytes, value: bytes) -> None:
            record = {
                "hash_class": kind,
                "hash_input_digest": hashlib.sha256(data).hexdigest(),
                "hash_output": value.hex(),
            }
            trace_digest.update(json.dumps(record, sort_keys=True, separators=(",", ":")).encode())

        self.pc = int(self.image["entry"])
        done = False
        error: str | None = None
        try:
            while not done:
                if counters["dynamic_instructions"] >= self.max_steps:
                    raise ExecutionFault("ERR_WATCHDOG", self.pc)
                if not 0 <= self.pc < len(self.code):
                    raise ExecutionFault("ERR_PC_BOUNDS", self.pc)
                inst = self.code[self.pc]
                counters["dynamic_instructions"] += 1
                event: dict[str, Any] = {
                    "seq": counters["dynamic_instructions"] - 1,
                    "pc": self.pc,
                    "opcode": inst.opcode.name,
                    "loop_depth": len(loops),
                    "call_depth": len(calls),
                }
                next_pc = self.pc + 1

                if inst.opcode == Opcode.NOP:
                    pass
                elif inst.opcode == Opcode.MOVI:
                    regs[inst.rd] = inst.imm
                elif inst.opcode == Opcode.ADDI:
                    signed_imm = inst.imm if inst.imm < (1 << 31) else inst.imm - (1 << 32)
                    value = regs[inst.rs] + signed_imm
                    if not 0 <= value < (1 << 32):
                        raise ExecutionFault("ERR_ARITH_OVERFLOW", self.pc)
                    regs[inst.rd] = value
                elif inst.opcode == Opcode.LOOP_SETUP:
                    if len(loops) >= 6:
                        raise ExecutionFault("ERR_LOOP_OVERFLOW", self.pc)
                    regs[inst.rs] = 0
                    if inst.flags & 0x01:
                        bound_address = regs[inst.rd]
                        if not 0 <= bound_address < self.scratch_slots:
                            raise ExecutionFault("ERR_SCRATCH_BOUNDS", self.pc)
                        if bound_address not in memory or len(memory[bound_address]) != 1:
                            raise ExecutionFault("ERR_DYNAMIC_LOOP_BOUND", self.pc)
                        bound = memory[bound_address][0]
                    else:
                        bound = inst.imm
                    if bound == 0:
                        next_pc = inst.imm
                    else:
                        loops.append({"setup": self.pc, "counter_reg": inst.rs, "bound": bound})
                elif inst.opcode == Opcode.LOOP_END:
                    if not loops or loops[-1]["setup"] != self.loop_start[self.pc]:
                        raise ExecutionFault("ERR_LOOP_UNDERFLOW", self.pc)
                    frame = loops[-1]
                    reg = frame["counter_reg"]
                    regs[reg] += 1
                    if regs[reg] < frame["bound"]:
                        next_pc = frame["setup"] + 1
                    else:
                        loops.pop()
                elif inst.opcode == Opcode.CALL:
                    if len(calls) >= 4:
                        raise ExecutionFault("ERR_CALL_OVERFLOW", self.pc)
                    calls.append(self.pc + 1)
                    next_pc = inst.imm
                elif inst.opcode == Opcode.RET:
                    if not calls:
                        raise ExecutionFault("ERR_CALL_UNDERFLOW", self.pc)
                    next_pc = calls.pop()
                elif inst.opcode == Opcode.JUMP:
                    next_pc = inst.imm
                elif inst.opcode == Opcode.HASH_LAYOUT:
                    layout = self.image["layouts"][str(inst.imm)]
                    data = self._compose(layout, frozen_job, regs, memory)
                    result = self._hash(layout["hash"], data, int(layout["output_bytes"]))
                    destination = layout.get("destination", {"base": inst.rd})
                    address = self._address(destination, regs)
                    memory[address] = result
                    counters["hash_calls"] += 1
                    if layout["hash"] == "shake256":
                        counters["keccak_permutations"] += len(data) // 136 + 1
                    record_hash(layout.get("class", "unspecified"), data, result)
                    event.update(
                        {
                            "layout_id": inst.imm,
                            "effective_address": address,
                            "hash_class": layout.get("class", "unspecified"),
                            "hash_input_length": len(data),
                            "hash_input_digest": hashlib.sha256(data).hexdigest(),
                            "hash_output": result.hex(),
                        }
                    )
                elif inst.opcode == Opcode.TREE_PUSH:
                    layout = self.image["layouts"][str(inst.imm)]
                    address = inst.rd + (regs[inst.rs] if inst.flags & 0x01 else 0)
                    if not 0 <= address < self.scratch_slots:
                        raise ExecutionFault("ERR_SCRATCH_BOUNDS", self.pc)
                    if address not in memory:
                        raise ExecutionFault("ERR_UNINITIALIZED_READ", self.pc)
                    tree_height = int(layout["tree_height"])
                    if tree is None:
                        def parent_hash(height: int, start_leaf: int, left: bytes, right: bytes) -> bytes:
                            heap_index = ((1 << tree_height) + start_leaf) >> height
                            context = {
                                "tree_left": left,
                                "tree_right": right,
                                "tree_height": height - 1,
                                "tree_parent_height": height,
                                "tree_start_leaf": start_leaf,
                                "tree_parent_index": start_leaf >> height,
                                "tree_index": heap_index,
                            }
                            if "parent_pipeline" in layout:
                                temps: dict[str, bytes] = {}
                                for step in layout["parent_pipeline"]:
                                    data = self._compose(
                                        step, frozen_job, regs, memory, context, temps
                                    )
                                    value = self._hash(
                                        step["hash"], data, int(step["output_bytes"])
                                    )
                                    counters["hash_calls"] += 1
                                    if step["hash"] == "shake256":
                                        counters["keccak_permutations"] += len(data) // 136 + 1
                                    record_hash(step.get("class", "tree_internal"), data, value)
                                    temps[str(step["name"])] = value
                                result_name = str(layout.get("pipeline_result", layout["parent_pipeline"][-1]["name"]))
                                return temps[result_name]

                            data = self._compose(
                                layout, frozen_job, regs, memory, context, {}
                            )
                            value = self._hash(layout["hash"], data, int(layout["output_bytes"]))
                            counters["hash_calls"] += 1
                            if layout["hash"] == "shake256":
                                counters["keccak_permutations"] += len(data) // 136 + 1
                            record_hash(layout.get("class", "tree_internal"), data, value)
                            return value

                        tree = TreeHash(
                            tree_height,
                            parent_hash,
                            StorageMode(layout.get("storage_mode", "TREEHASH_MIN")),
                            frozen_job.get(layout.get("target_leaf_field", "target_leaf")),
                            int(layout.get("subtree_height", 4)),
                        )
                    reductions = tree.push(memory[address])
                    event.update(
                        {
                            "layout_id": inst.imm,
                            "effective_address": address,
                            "tree_event": "push",
                            "tree_reductions": len(reductions),
                        }
                    )
                    if tree.metrics.leaf_count == (1 << tree_height):
                        root, auth, _metrics = tree.finish()
                        root_destination = layout["root_destination"]
                        root_address = (
                            self._address(root_destination, regs)
                            if isinstance(root_destination, dict)
                            else int(root_destination)
                        )
                        if not 0 <= root_address < self.scratch_slots:
                            raise ExecutionFault("ERR_SCRATCH_BOUNDS", self.pc)
                        memory[root_address] = root
                        if "auth_destination" in layout:
                            auth_destination = int(layout["auth_destination"])
                            if auth_destination < 0 or auth_destination + len(auth) > self.scratch_slots:
                                raise ExecutionFault("ERR_SCRATCH_BOUNDS", self.pc)
                            for auth_offset, auth_node in enumerate(auth):
                                memory[auth_destination + auth_offset] = auth_node
                        event["tree_event"] = "root"
                        event["auth_nodes"] = len(auth)
                        if layout.get("restart_on_complete", False):
                            tree = None
                elif inst.opcode == Opcode.LOAD:
                    descriptor = self.image["loads"][str(inst.imm)]
                    transform = descriptor.get("transform")
                    value = (
                        b""
                        if transform == "integer_expression"
                        else self._component(
                            descriptor["source"], frozen_job, regs, memory, {}, {}
                        )
                    )
                    if transform is None:
                        if "destination_reg" in descriptor:
                            regs[int(descriptor["destination_reg"])] = int.from_bytes(
                                value, descriptor.get("endian", "big")
                            )
                        else:
                            destination = self._address(descriptor["destination"], regs)
                            memory[destination] = value
                            event["effective_address"] = destination
                    elif transform == "base_w_checksum":
                        log_w = int(descriptor["log_w"])
                        w = 1 << log_w
                        len1 = int(descriptor["len1"])
                        len2 = int(descriptor["len2"])
                        digits: list[int] = []
                        for byte in value:
                            for shift in range(8 - log_w, -1, -log_w):
                                digits.append((byte >> shift) & (w - 1))
                                if len(digits) == len1:
                                    break
                            if len(digits) == len1:
                                break
                        if len(digits) != len1:
                            raise ExecutionFault("ERR_POSTPROCESS_LENGTH", self.pc)
                        checksum = sum(w - 1 - digit for digit in digits)
                        checksum_bits = len2 * log_w
                        checksum <<= 8 - (checksum_bits % 8)
                        checksum_bytes = checksum.to_bytes((checksum_bits + 7) // 8, "big")
                        checksum_digits: list[int] = []
                        for byte in checksum_bytes:
                            for shift in range(8 - log_w, -1, -log_w):
                                checksum_digits.append((byte >> shift) & (w - 1))
                                if len(checksum_digits) == len2:
                                    break
                            if len(checksum_digits) == len2:
                                break
                        destination = self._address(descriptor["destination"], regs)
                        all_digits = digits + checksum_digits
                        if destination + len(all_digits) > self.scratch_slots:
                            raise ExecutionFault("ERR_SCRATCH_BOUNDS", self.pc)
                        for offset, digit in enumerate(all_digits):
                            memory[destination + offset] = bytes([digit])
                        event.update(
                            {
                                "effective_address": destination,
                                "memory_event": "base_w_checksum",
                                "output_slots": len(all_digits),
                            }
                        )
                    elif transform == "integer_expression":
                        integer = self._eval_int_expression(
                            descriptor["expression"], frozen_job, regs, memory, {}
                        )
                        if "destination_reg" in descriptor:
                            if integer >= (1 << 32):
                                raise ExecutionFault("ERR_REGISTER_WIDTH", self.pc)
                            regs[int(descriptor["destination_reg"])] = integer
                        else:
                            width = int(descriptor["bytes"])
                            try:
                                encoded = integer.to_bytes(
                                    width, descriptor.get("endian", "big")
                                )
                            except OverflowError as exc:
                                raise ExecutionFault("ERR_POSTPROCESS_LENGTH", self.pc) from exc
                            destination = self._address(
                                descriptor["destination"], regs
                            )
                            memory[destination] = encoded
                            event.update(
                                {
                                    "effective_address": destination,
                                    "memory_event": "integer_expression",
                                    "output_slots": 1,
                                }
                            )
                    else:
                        raise ExecutionFault("ERR_LOAD_TRANSFORM", self.pc)
                elif inst.opcode == Opcode.STORE:
                    move = self.image["moves"][str(inst.imm)]
                    source = self._address(move["source"], regs)
                    destination = self._address(move["destination"], regs)
                    if source not in memory:
                        raise ExecutionFault("ERR_UNINITIALIZED_READ", self.pc)
                    memory[destination] = memory[source]
                    event.update(
                        {
                            "effective_address": destination,
                            "source_address": source,
                            "memory_event": "copy",
                        }
                    )
                elif inst.opcode == Opcode.XOR:
                    descriptor = self.image["xors"][str(inst.imm)]
                    source_a = self._address(descriptor["source_a"], regs)
                    source_b = self._address(descriptor["source_b"], regs)
                    destination = self._address(descriptor["destination"], regs)
                    if source_a not in memory or source_b not in memory:
                        raise ExecutionFault("ERR_UNINITIALIZED_READ", self.pc)
                    left = memory[source_a]
                    right = memory[source_b]
                    if len(left) != len(right):
                        raise ExecutionFault("ERR_XOR_LENGTH", self.pc)
                    memory[destination] = bytes(a ^ b for a, b in zip(left, right))
                    event.update(
                        {
                            "effective_address": destination,
                            "source_address": source_a,
                            "source_b_address": source_b,
                            "memory_event": "xor",
                            "output_bytes": len(left),
                        }
                    )
                elif inst.opcode == Opcode.EMIT:
                    address = inst.rd + (regs[inst.rs] if inst.flags & 0x01 else 0) + inst.imm
                    if not 0 <= address < self.scratch_slots:
                        raise ExecutionFault("ERR_SCRATCH_BOUNDS", self.pc)
                    if address not in memory:
                        raise ExecutionFault("ERR_UNINITIALIZED_READ", self.pc)
                    output.extend(memory[address])
                    event.update({"effective_address": address, "emit_bytes": len(memory[address])})
                elif inst.opcode == Opcode.HALT:
                    if loops or calls:
                        raise ExecutionFault("ERR_UNBALANCED_STACK", self.pc)
                    done = True
                elif inst.opcode == Opcode.FAIL:
                    raise ExecutionFault(f"PROGRAM_FAIL_{inst.imm}", self.pc)
                elif inst.opcode in (Opcode.WAIT, Opcode.BARRIER):
                    pass  # Hashes are atomic in the Phase-1 functional model.
                else:
                    raise ExecutionFault("ERR_UNIMPLEMENTED_OPCODE", self.pc)

                if self.trace_mode == "full" or (
                    self.trace_mode == "hash" and inst.opcode in (Opcode.HASH_LAYOUT, Opcode.TREE_PUSH)
                ):
                    trace.append(event)
                self.pc = next_pc
        except (ExecutionFault, VerificationError) as exc:
            error = exc.code if isinstance(exc, ExecutionFault) else "ERR_IMAGE_VERIFY"
            # Fail closed: no partial result escapes.
            output.clear()
            memory.clear()
        return ExecutionResult(
            done=done and error is None,
            error=error,
            output=bytes(output),
            trace=trace,
            counters=counters,
            hash_trace_sha256=trace_digest.hexdigest(),
            memory=memory,
        )
