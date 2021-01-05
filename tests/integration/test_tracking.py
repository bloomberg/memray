import mmap
from pathlib import Path

import pytest

from bloomberg.pensieve import AllocatorType
from bloomberg.pensieve import Tracker
from bloomberg.pensieve._test import MemoryAllocator


@pytest.mark.parametrize(
    "allocator_func, allocator_type",
    [
        ("malloc", AllocatorType.MALLOC),
        ("valloc", AllocatorType.VALLOC),
        ("pvalloc", AllocatorType.PVALLOC),
        ("calloc", AllocatorType.CALLOC),
        ("memalign", AllocatorType.MEMALIGN),
        ("posix_memalign", AllocatorType.POSIX_MEMALIGN),
        ("realloc", AllocatorType.REALLOC),
    ],
)
def test_simple_allocation_tracking(allocator_func, allocator_type, tmpdir):
    # GIVEN
    allocator = MemoryAllocator()
    output = Path(tmpdir) / "test.bin"

    # WHEM
    with Tracker(output) as tracker:
        getattr(allocator, allocator_func)(1234)
        allocator.free()

    allocations = list(tracker.get_allocation_records())
    allocs = [
        event
        for event in allocations
        if event.size == 1234 and event.allocator == allocator_type
    ]
    assert len(allocs) == 1
    (alloc,) = allocs

    frees = [
        event
        for event in allocations
        if event.address == alloc.address and event.allocator == AllocatorType.FREE
    ]
    assert len(frees) >= 1


def test_mmap_tracking(tmpdir):
    # GIVEN / WHEM
    output = Path(tmpdir) / "test.bin"
    with Tracker(output) as tracker:
        with mmap.mmap(-1, length=2048, access=mmap.ACCESS_WRITE) as mmap_obj:
            mmap_obj[0:100] = b"a" * 100

    # THEN
    records = list(tracker.get_allocation_records())
    assert len(records) >= 2

    mmap_records = [
        record
        for record in records
        if AllocatorType.MMAP == record.allocator and record.size == 2048
    ]
    assert len(mmap_records) == 1
    mmunmap_record = [
        record for record in records if AllocatorType.MUNMAP == record.allocator
    ]
    assert len(mmunmap_record) == 1


def test_pthread_tracking(tmpdir):
    # GIVEN
    allocator = MemoryAllocator()
    output = Path(tmpdir) / "test.bin"

    def tracking_function():
        allocator.valloc(1234)
        allocator.free()

    # WHEM
    with Tracker(output) as tracker:
        allocator.run_in_pthread(tracking_function)

    allocations = list(tracker.get_allocation_records())
    allocs = [
        event
        for event in allocations
        if event.size == 1234 and event.allocator == AllocatorType.VALLOC
    ]
    assert len(allocs) == 1
    (alloc,) = allocs

    frees = [
        event
        for event in allocations
        if event.address == alloc.address and event.allocator == AllocatorType.FREE
    ]
    assert len(frees) >= 1
