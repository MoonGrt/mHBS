"""Crash-safe state-index protocol model for LMS/XMSS integration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class IndexState(str, Enum):
    FREE = "FREE"
    RESERVED = "RESERVED"
    PERSISTED = "PERSISTED"
    RELEASED = "RELEASED"
    CONSUMED = "CONSUMED"
    BURNED = "BURNED"


class StateFault(RuntimeError):
    pass


@dataclass
class Reservation:
    index: int
    state: IndexState


class StatefulIndexManager:
    def __init__(self, capacity: int):
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self.next_index = 0
        self.persisted_floor = 0
        self.records: dict[int, Reservation] = {}

    def reserve(self) -> int:
        if self.next_index >= self.capacity:
            raise StateFault("ERR_INDEX_EXHAUSTED")
        index = self.next_index
        self.next_index += 1  # monotonic before computation begins
        self.records[index] = Reservation(index, IndexState.RESERVED)
        return index

    def persist(self, index: int) -> None:
        record = self._expect(index, IndexState.RESERVED)
        record.state = IndexState.PERSISTED
        self.persisted_floor = max(self.persisted_floor, index + 1)

    def release_signature(self, index: int) -> None:
        record = self._expect(index, IndexState.PERSISTED)
        record.state = IndexState.RELEASED

    def consume(self, index: int) -> None:
        record = self._expect(index, IndexState.RELEASED)
        record.state = IndexState.CONSUMED

    def cancel_or_reset(self) -> None:
        for record in self.records.values():
            if record.state in (IndexState.RESERVED, IndexState.PERSISTED):
                record.state = IndexState.BURNED

    def recover(self, persisted_next_index: int) -> None:
        if persisted_next_index < self.persisted_floor or persisted_next_index < self.next_index:
            raise StateFault("ERR_STATE_ROLLBACK")
        if persisted_next_index > self.capacity:
            raise StateFault("ERR_STATE_CORRUPT")
        self.next_index = persisted_next_index
        self.persisted_floor = persisted_next_index
        self.cancel_or_reset()

    def _expect(self, index: int, expected: IndexState) -> Reservation:
        record = self.records.get(index)
        if record is None or record.state != expected:
            raise StateFault(f"ERR_STATE_TRANSITION:{index}:{expected.value}")
        return record
