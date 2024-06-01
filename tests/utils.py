"""Utilities / Helpers for writing tests."""
import asyncio
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from typing import List
from typing import Optional
from typing import Tuple

import pytest

from memray import AllocatorType


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


def filter_relevant_pymalloc_allocations(records, size):
    addresses = set()
    filter_allocations = [
        AllocatorType.PYMALLOC_MALLOC,
        AllocatorType.PYMALLOC_REALLOC,
        AllocatorType.PYMALLOC_CALLOC,
    ]
    filter_deallocations = [AllocatorType.PYMALLOC_FREE]
    for record in records:
        if record.allocator in filter_allocations and record.size == size:
            yield record
            addresses.add(record.address)
        elif record.allocator in filter_deallocations:
            if record.address in addresses:
                yield record
            addresses.discard(record.address)


skip_if_macos = pytest.mark.skipif(
    sys.platform == "darwin", reason="does not run on macOS"
)


@dataclass
class MockAllocationRecord:
    """Mimics :py:class:`memray._memray.AllocationRecord`."""

    tid: int
    address: int
    size: int
    allocator: AllocatorType
    stack_id: int
    n_allocations: int
    _stack: Optional[List[Tuple[str, str, int]]] = None
    _hybrid_stack: Optional[List[Tuple[str, str, int]]] = None
    thread_name: str = ""

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


@contextmanager
def run_without_tracer():
    """Fixture to run a test without custom tracer or profiling."""
    prev_trace = sys.gettrace()
    prev_profile = sys.getprofile()
    sys.settrace(None)
    sys.setprofile(None)
    try:
        yield
    finally:
        sys.settrace(prev_trace)
        sys.setprofile(prev_profile)


def async_run(coro):
    # This technique shamelessly cribbed from Textual itself...
    # `asyncio.get_event_loop()` is deprecated since Python 3.10:
    asyncio_get_event_loop_is_deprecated = sys.version_info >= (3, 10, 0)

    if asyncio_get_event_loop_is_deprecated:
        # N.B. This doesn't work with Python<3.10, as we end up with 2 event loops:
        return asyncio.run(coro)
    else:
        # pragma: no cover
        # However, this works with Python<3.10:
        event_loop = asyncio.get_event_loop()
        return event_loop.run_until_complete(coro)
