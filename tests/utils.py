"""Utilities / Helpers for writing tests."""

from dataclasses import dataclass
from typing import List
from typing import Optional
from typing import Tuple

from bloomberg.pensieve import AllocatorType


def filter_relevant_allocations(records, ranged=False):
    addresses = set()
    filter_allocations = [AllocatorType.VALLOC]
    filter_deallocations = [AllocatorType.FREE]
    if ranged:
        filter_allocations.append(AllocatorType.MMAP)
        filter_deallocations.append(AllocatorType.MUNMAP)
    for record in records:
        if record.allocator in filter_allocations:
            yield record
            addresses.add(record.address)
        elif record.allocator in filter_deallocations:
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
    _stack: Optional[List[Tuple[str, str, int]]] = None
    _hybrid_stack: Optional[List[Tuple[str, str, int]]] = None

    @staticmethod
    def __get_stack_trace(stack, max_stacks):
        if max_stacks == 0:
            return stack
        else:
            return stack[:max_stacks]

    def stack_trace(self, max_stacks=0):
        if self._stack is None:
            raise AssertionError("did not expect a call to `stack_trace`")
        return self.__get_stack_trace(self._stack, max_stacks)

    def hybrid_stack_trace(self, max_stacks=0):
        if self._hybrid_stack is None:
            raise AssertionError("did not expect a call to `hybrid_stack_trace`")
        return self.__get_stack_trace(self._hybrid_stack, max_stacks)
