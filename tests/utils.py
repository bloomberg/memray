"""Utilities / Helpers for writing tests."""

from dataclasses import dataclass
from typing import List
from typing import Tuple

from bloomberg.pensieve import AllocatorType


def filter_relevant_allocations(records):
    addresses = set()
    for record in records:
        if record.allocator in (AllocatorType.VALLOC, AllocatorType.MMAP):
            yield record
            addresses.add(record.address)
        elif record.allocator in (AllocatorType.FREE, AllocatorType.MUNMAP):
            if record.address in addresses:
                yield record
            addresses.discard(record.address)


@dataclass
class MockAllocationRecord:
    """Mimics :py:class:`bloomberg.pensieve._pensieve.AllocationRecord`."""

    tid: int
    address: int
    size: int
    allocator: AllocatorType
    stack_id: int
    n_allocations: int
    _stack: List[Tuple[str, str, int]]

    def stack_trace(self, max_stacks=0):
        if max_stacks == 0:
            return self._stack
        else:
            return self._stack[:max_stacks]
