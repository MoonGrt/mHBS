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
        self._dependency_memory_reads: set[int] | None = None
        self._dependency_register_reads: set[int] | None = None

    def _begin_dependency_capture(self) -> None:
        self._dependency_memory_reads = set()
        self._dependency_register_reads = set()

    def _track_memory_read(self, address: int) -> None:
        if self._dependency_memory_reads is not None:
            self._dependency_memory_reads.add(address)

    def _track_register_read(self, register: int) -> None:
        if self._dependency_register_reads is not None:
            self._dependency_register_reads.add(register)

    @staticmethod
    def _pair_loops(code: list[Instruction]) -> tuple[dict[int, int], dict[int, int]]:
        stack: list[int] = []
        start_to_end: dict[int, int] = {}
        end_to_start: dict[int, int] = {}
        for pc, inst in enumerate(code):
            if inst.opcode == Opcode.LOOP_BEGIN:
                stack.append(pc)
            elif inst.opcode == Opcode.LOOP_END:
                start = stack.pop()
                start_to_end[start] = pc
                end_to_start[pc] = start
        return start_to_end, end_to_start

    def _address(self, component: dict[str, Any], regs: list[int]) -> int:
        address = int(component.get("base", 0))
        if "base_reg" in component:
            register = int(component["base_reg"])
            self._track_register_read(register)
            address += regs[register]
        if "index_reg" in component:
            register = int(component["index_reg"])
            self._track_register_read(register)
            address += regs[register] * int(component.get("stride", 1))
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
            register = int(expression["reg"])
            self._track_register_read(register)
            value = regs[register]
        elif kind == "job_int":
            value = job.get(expression["field"])
            if not isinstance(value, int):
                raise ExecutionFault("ERR_JOB_FIELD", self.pc)
        elif kind == "memory_int":
            address = self._address(expression, regs)
            if address not in memory:
                raise ExecutionFault("ERR_UNINITIALIZED_READ", self.pc)
            self._track_memory_read(address)
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
        if kind == "job_slice":
            value = job.get(component["field"])
            if not isinstance(value, bytes):
                raise ExecutionFault("ERR_JOB_FIELD", self.pc)
            offset = self._eval_int_expression(
                component["offset"], job, regs, memory, context
            )
            length = int(component["length"])
            if offset < 0 or length < 0 or offset + length > len(value):
                raise ExecutionFault("ERR_JOB_FIELD_LENGTH", self.pc)
            return value[offset : offset + length]
        if kind == "job_int":
            value = job.get(component["field"])
            if not isinstance(value, int) or value < 0:
                raise ExecutionFault("ERR_JOB_FIELD", self.pc)
            try:
                return value.to_bytes(int(component["bytes"]), component.get("endian", "big"))
            except OverflowError as exc:
                raise ExecutionFault("ERR_JOB_FIELD_WIDTH", self.pc) from exc
        if kind == "reg":
            register = int(component["reg"])
            self._track_register_read(register)
            value = regs[register] + int(component.get("add", 0))
            try:
                return value.to_bytes(int(component["bytes"]), component.get("endian", "big"))
            except OverflowError as exc:
                raise ExecutionFault("ERR_REGISTER_WIDTH", self.pc) from exc
        if kind == "memory":
            address = self._address(component, regs)
            if address not in memory:
                raise ExecutionFault("ERR_UNINITIALIZED_READ", self.pc)
            self._track_memory_read(address)
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
                self._track_memory_read(address)
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
                        register = int(word["reg"])
                        self._track_register_read(register)
                        value = regs[register] + int(word.get("add", 0))
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
        memory_dependencies: dict[int, frozenset[int]] = {}
        register_dependencies: list[frozenset[int]] = [frozenset() for _ in regs]
        value_dependencies: dict[bytes, frozenset[int]] = {}
        output = bytearray()
        trace: list[dict[str, Any]] = []
        loops: list[dict[str, Any]] = []
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
        pair_trace_records: list[list[bytes]] = [[], []]
        next_hash_id = 0
        active_tree_hash_events: list[dict[str, Any]] = []

        def hash_record(kind: str, data: bytes, value: bytes) -> bytes:
            record = {
                "hash_class": kind,
                "hash_input_digest": hashlib.sha256(data).hexdigest(),
                "hash_output": value.hex(),
            }
            return json.dumps(
                record, sort_keys=True, separators=(",", ":")
            ).encode()

        def record_hash(kind: str, data: bytes, value: bytes) -> None:
            trace_digest.update(hash_record(kind, data, value))

        def control_dependencies() -> set[int]:
            dependencies: set[int] = set()
            for frame in loops:
                dependencies.update(frame.get("dependencies", ()))
            return dependencies

        def captured_dependencies(*extra: frozenset[int] | set[int]) -> frozenset[int]:
            dependencies = control_dependencies()
            for address in self._dependency_memory_reads or ():
                dependencies.update(memory_dependencies.get(address, ()))
            for register in self._dependency_register_reads or ():
                dependencies.update(register_dependencies[register])
            for values in extra:
                dependencies.update(values)
            return frozenset(dependencies)

        def allocate_hash(
            kind: str,
            data: bytes,
            value: bytes,
            dependencies: frozenset[int],
            *,
            address: int | None = None,
            lane: int | None = None,
        ) -> dict[str, Any]:
            nonlocal next_hash_id
            hash_id = next_hash_id
            next_hash_id += 1
            event = {
                "hash_id": hash_id,
                "hash_class": kind,
                "hash_input_length": len(data),
                "hash_input_digest": hashlib.sha256(data).hexdigest(),
                "hash_output": value.hex(),
                "dependency_hash_ids": sorted(dependencies),
            }
            if address is not None:
                event["effective_address"] = address
                memory_dependencies[address] = frozenset((hash_id,))
            if lane is not None:
                event["lane"] = lane
            prior = value_dependencies.get(value, frozenset())
            value_dependencies[value] = prior | frozenset((hash_id,))
            return event

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
                self._begin_dependency_capture()
                next_pc = self.pc + 1

                if inst.opcode == Opcode.SET_REG:
                    regs[inst.rd] = inst.imm
                    register_dependencies[inst.rd] = frozenset()
                elif inst.opcode == Opcode.ADD_IMM:
                    self._track_register_read(inst.rs)
                    signed_imm = inst.imm if inst.imm < (1 << 31) else inst.imm - (1 << 32)
                    value = regs[inst.rs] + signed_imm
                    if not 0 <= value < (1 << 32):
                        raise ExecutionFault("ERR_ARITH_OVERFLOW", self.pc)
                    regs[inst.rd] = value
                    register_dependencies[inst.rd] = captured_dependencies()
                elif inst.opcode == Opcode.LOOP_BEGIN:
                    if len(loops) >= 6:
                        raise ExecutionFault("ERR_LOOP_OVERFLOW", self.pc)
                    regs[inst.rs] = 0
                    register_dependencies[inst.rs] = frozenset()
                    if inst.flags & 0x01:
                        self._track_register_read(inst.rd)
                        bound_address = regs[inst.rd]
                        if not 0 <= bound_address < self.scratch_slots:
                            raise ExecutionFault("ERR_SCRATCH_BOUNDS", self.pc)
                        if bound_address not in memory or len(memory[bound_address]) != 1:
                            raise ExecutionFault("ERR_DYNAMIC_LOOP_BOUND", self.pc)
                        self._track_memory_read(bound_address)
                        bound = memory[bound_address][0]
                    else:
                        bound = inst.imm
                    if bound == 0:
                        next_pc = inst.imm
                    else:
                        loops.append(
                            {
                                "setup": self.pc,
                                "counter_reg": inst.rs,
                                "bound": bound,
                                "dependencies": tuple(captured_dependencies()),
                            }
                        )
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
                elif inst.opcode == Opcode.RETURN:
                    if not calls:
                        raise ExecutionFault("ERR_CALL_UNDERFLOW", self.pc)
                    next_pc = calls.pop()
                elif inst.opcode == Opcode.HASH:
                    repeat_mode = bool(inst.flags & 0x08)
                    capture_mode = bool(inst.flags & 0x10)
                    capture_reg_base = inst.flags >> 5
                    layout_id = inst.imm & 0xFFFF if repeat_mode else inst.imm
                    repeat_count = (inst.imm >> 16) & 0xFF if repeat_mode else 1
                    layout = self.image["layouts"][str(layout_id)]
                    repeat_prefix = layout.get("repeat_prefix")
                    prefix_mode = repeat_mode and isinstance(repeat_prefix, dict)
                    prefix_recipe = (
                        repeat_prefix.get("recipe") if prefix_mode else None
                    )
                    if prefix_mode and prefix_recipe not in {
                        "hbs_64byte_f_chain", "hbs_64byte_feedback"
                    }:
                        raise ExecutionFault("ERR_BAD_DESCRIPTOR", self.pc)
                    # flags[1:0]=2'b11 is the bounded static P2 operation:
                    # evaluate the adjacent logical indices 2*R[rs] and
                    # 2*R[rs]+1.  The hardware may defer the intermediate
                    # writes when flags[2] is set, but atomic software writes
                    # are observably equivalent at instruction boundaries.
                    pair_mode = (inst.flags & 0x03) == 0x03
                    self._track_register_read(inst.rs)
                    original_index = regs[inst.rs]
                    original_counter = regs[inst.rd] if repeat_mode else 0
                    lanes = (0, 1) if pair_mode else (None,)
                    lane_events = []
                    prefix_templates: dict[int | None, bytes] = {}
                    prefix_results: dict[int | None, bytes] = {}
                    prefix_hash_ids: dict[int | None, int] = {}
                    captured_values: dict[int | None, tuple[bytes, frozenset[int]]] = {}
                    capture_after = {
                        lane: regs[capture_reg_base + (0 if lane is None else lane)]
                        for lane in lanes
                    } if capture_mode else {}
                    if capture_mode:
                        destination = layout.get("destination", {"base": inst.rd})
                        for lane in lanes:
                            if lane is not None:
                                regs[inst.rs] = 2 * original_index + lane
                            address = self._address(destination, regs)
                            if capture_after[lane] == 0 and not prefix_mode:
                                captured_values[lane] = (
                                    memory[address],
                                    memory_dependencies.get(address, frozenset()),
                                )
                        regs[inst.rs] = original_index
                    for repeat_index in range(repeat_count):
                        if repeat_mode:
                            regs[inst.rd] = original_counter + repeat_index
                        for lane in lanes:
                            self._begin_dependency_capture()
                            self._track_register_read(inst.rs)
                            if lane is not None:
                                regs[inst.rs] = 2 * original_index + lane
                            if prefix_mode and repeat_index > 0:
                                data_image = bytearray(prefix_templates[lane])
                                data_image[32:36] = int(
                                    repeat_prefix.get("domain", 0)
                                ).to_bytes(4, "big")
                                if prefix_recipe == "hbs_64byte_f_chain":
                                    data_image[44:48] = (
                                        original_counter + repeat_index - 1
                                    ).to_bytes(4, "big")
                                data_image[48:64] = prefix_results[lane]
                                data = bytes(data_image)
                                dependencies = captured_dependencies(
                                    frozenset((prefix_hash_ids[lane],))
                                )
                                hash_class = str(repeat_prefix.get(
                                    "repeat_class", layout.get("class", "unspecified")
                                ))
                            else:
                                data = self._compose(layout, frozen_job, regs, memory)
                                pair_patch = layout.get("pair_patch")
                                if pair_mode and lane == 1 and isinstance(
                                    pair_patch, dict
                                ):
                                    data_image = bytearray(data)
                                    patch_offset = int(pair_patch["byte_offset"])
                                    patch_register = int(pair_patch["register"])
                                    data_image[patch_offset:patch_offset + 4] = (
                                        regs[patch_register] + 1
                                    ).to_bytes(4, "big")
                                    data = bytes(data_image)
                                dependencies = captured_dependencies()
                                hash_class = str(
                                    repeat_prefix.get(
                                        "initial_class",
                                        layout.get("class", "unspecified"),
                                    )
                                    if prefix_mode else layout.get(
                                        "class", "unspecified"
                                    )
                                )
                                if prefix_mode:
                                    prefix_templates[lane] = data
                            result = self._hash(
                                layout["hash"], data, int(layout["output_bytes"])
                            )
                            destination = layout.get("destination", {"base": inst.rd})
                            address = self._address(destination, regs)
                            if pair_mode and lane is not None:
                                address += lane * int(
                                    destination.get("pair_stride", 0)
                                )
                                if not 0 <= address < self.scratch_slots:
                                    raise ExecutionFault(
                                        "ERR_SCRATCH_BOUNDS", self.pc
                                    )
                            memory[address] = result
                            memory_dependencies[address] = dependencies
                            if (capture_mode
                                    and capture_after[lane]
                                    + (1 if prefix_mode else 0)
                                    == repeat_index + 1):
                                captured_values[lane] = (result, dependencies)
                            counters["hash_calls"] += 1
                            if layout["hash"] == "shake256":
                                counters["keccak_permutations"] += len(data) // 136 + 1
                            if pair_mode:
                                pair_trace_records[lane].append(
                                    hash_record(
                                        hash_class, data, result
                                    )
                                )
                            else:
                                record_hash(
                                    hash_class, data, result
                                )
                            lane_event = allocate_hash(
                                hash_class,
                                data,
                                result,
                                dependencies,
                                address=address,
                                lane=0 if lane is None else lane,
                            )
                            lane_events.append(lane_event)
                            if prefix_mode:
                                prefix_results[lane] = result
                                prefix_hash_ids[lane] = int(lane_event["hash_id"])
                        regs[inst.rs] = original_index
                    regs[inst.rs] = original_index
                    if capture_mode:
                        capture_destination = layout.get("capture_destination")
                        if not isinstance(capture_destination, dict):
                            raise ExecutionFault("ERR_BAD_DESCRIPTOR", self.pc)
                        for lane in lanes:
                            if lane not in captured_values:
                                raise ExecutionFault("ERR_BAD_DESCRIPTOR", self.pc)
                            if lane is not None:
                                regs[inst.rs] = 2 * original_index + lane
                            capture_address = self._address(capture_destination, regs)
                            capture_value, capture_dependencies = captured_values[lane]
                            memory[capture_address] = capture_value
                            memory_dependencies[capture_address] = capture_dependencies
                        regs[inst.rs] = original_index
                    if repeat_mode:
                        regs[inst.rd] = original_counter + repeat_count
                    if pair_mode and not (inst.flags & 0x04):
                        # Deferred pair feedback changes the physical service
                        # order, not the logical SLH-DSA chain order.  Flush
                        # the completed pair chain-major so the architectural
                        # trace remains comparable with the independent oracle.
                        for lane_records in pair_trace_records:
                            for record in lane_records:
                                trace_digest.update(record)
                            lane_records.clear()
                    final_event = lane_events[-1]
                    event.update(
                        {
                            "layout_id": layout_id,
                            "effective_address": final_event["effective_address"],
                            "hash_class": layout.get("class", "unspecified"),
                            "hash_input_length": final_event["hash_input_length"],
                            "hash_input_digest": final_event["hash_input_digest"],
                            "hash_output": final_event["hash_output"],
                            "hash_id": final_event["hash_id"],
                            "dependency_hash_ids": final_event[
                                "dependency_hash_ids"
                            ],
                            "hash_lanes": lane_events,
                        }
                    )
                elif inst.opcode == Opcode.TREE_PUSH:
                    layout = self.image["layouts"][str(inst.imm)]
                    self._track_register_read(inst.rs)
                    address = inst.rd + (regs[inst.rs] if inst.flags & 0x01 else 0)
                    if not 0 <= address < self.scratch_slots:
                        raise ExecutionFault("ERR_SCRATCH_BOUNDS", self.pc)
                    if address not in memory:
                        raise ExecutionFault("ERR_UNINITIALIZED_READ", self.pc)
                    tree_height = int(layout["tree_height"])
                    if tree is None:
                        def parent_hash(height: int, start_leaf: int, left: bytes, right: bytes) -> bytes:
                            child_dependencies = (
                                value_dependencies.get(left, frozenset())
                                | value_dependencies.get(right, frozenset())
                            )
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
                                temp_dependencies: dict[str, frozenset[int]] = {}
                                for step in layout["parent_pipeline"]:
                                    self._begin_dependency_capture()
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
                                    dependencies = captured_dependencies(
                                        child_dependencies,
                                        *temp_dependencies.values(),
                                    )
                                    hash_event = allocate_hash(
                                        step.get("class", "tree_internal"),
                                        data,
                                        value,
                                        dependencies,
                                        lane=1,
                                    )
                                    active_tree_hash_events.append(hash_event)
                                    name = str(step["name"])
                                    temps[name] = value
                                    temp_dependencies[name] = frozenset(
                                        (int(hash_event["hash_id"]),)
                                    )
                                result_name = str(layout.get("pipeline_result", layout["parent_pipeline"][-1]["name"]))
                                return temps[result_name]

                            self._begin_dependency_capture()
                            data = self._compose(
                                layout, frozen_job, regs, memory, context, {}
                            )
                            value = self._hash(layout["hash"], data, int(layout["output_bytes"]))
                            counters["hash_calls"] += 1
                            if layout["hash"] == "shake256":
                                counters["keccak_permutations"] += len(data) // 136 + 1
                            record_hash(layout.get("class", "tree_internal"), data, value)
                            active_tree_hash_events.append(
                                allocate_hash(
                                    layout.get("class", "tree_internal"),
                                    data,
                                    value,
                                    captured_dependencies(child_dependencies),
                                    lane=1,
                                )
                            )
                            return value

                        tree = TreeHash(
                            tree_height,
                            parent_hash,
                            StorageMode(layout.get("storage_mode", "TREEHASH_MIN")),
                            frozen_job.get(layout.get("target_leaf_field", "target_leaf")),
                            int(layout.get("subtree_height", 4)),
                        )
                    active_tree_hash_events = []
                    reductions = tree.push(memory[address])
                    event.update(
                        {
                            "layout_id": inst.imm,
                            "effective_address": address,
                            "tree_event": "push",
                            "tree_reductions": len(reductions),
                            "tree_hashes": list(active_tree_hash_events),
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
                        memory_dependencies[root_address] = value_dependencies.get(
                            root, frozenset()
                        )
                        if "auth_destination" in layout:
                            auth_destination = int(layout["auth_destination"])
                            if auth_destination < 0 or auth_destination + len(auth) > self.scratch_slots:
                                raise ExecutionFault("ERR_SCRATCH_BOUNDS", self.pc)
                            for auth_offset, auth_node in enumerate(auth):
                                auth_address = auth_destination + auth_offset
                                memory[auth_address] = auth_node
                                memory_dependencies[auth_address] = (
                                    value_dependencies.get(auth_node, frozenset())
                                )
                        event["tree_event"] = "root"
                        event["auth_nodes"] = len(auth)
                        if layout.get("restart_on_complete", False):
                            tree = None
                elif inst.opcode == Opcode.DATA_LOAD:
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
                            register_dependencies[
                                int(descriptor["destination_reg"])
                            ] = captured_dependencies()
                        else:
                            destination = self._address(descriptor["destination"], regs)
                            memory[destination] = value
                            memory_dependencies[destination] = captured_dependencies()
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
                            address = destination + offset
                            memory[address] = bytes([digit])
                            memory_dependencies[address] = captured_dependencies()
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
                            register_dependencies[
                                int(descriptor["destination_reg"])
                            ] = captured_dependencies()
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
                            memory_dependencies[destination] = captured_dependencies()
                            event.update(
                                {
                                    "effective_address": destination,
                                    "memory_event": "integer_expression",
                                    "output_slots": 1,
                                }
                            )
                    else:
                        raise ExecutionFault("ERR_LOAD_TRANSFORM", self.pc)
                elif inst.opcode == Opcode.DATA_MOVE:
                    move = self.image["moves"][str(inst.imm)]
                    source = self._address(move["source"], regs)
                    destination = self._address(move["destination"], regs)
                    if source not in memory:
                        raise ExecutionFault("ERR_UNINITIALIZED_READ", self.pc)
                    self._track_memory_read(source)
                    memory[destination] = memory[source]
                    memory_dependencies[destination] = captured_dependencies()
                    event.update(
                        {
                            "effective_address": destination,
                            "source_address": source,
                            "memory_event": "copy",
                        }
                    )
                elif inst.opcode == Opcode.OUTPUT:
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
                else:
                    raise ExecutionFault("ERR_UNIMPLEMENTED_OPCODE", self.pc)

                if self.trace_mode == "full" or (
                    self.trace_mode == "hash" and inst.opcode in (Opcode.HASH, Opcode.TREE_PUSH)
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
