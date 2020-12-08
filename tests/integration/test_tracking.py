import mmap
from pathlib import Path

import pytest

from bloomberg.pensieve import Tracker
from bloomberg.pensieve._test import MemoryAllocator


@pytest.mark.parametrize(
    "allocator_func",
    [
        "malloc",
        "valloc",
        "pvalloc",
        "calloc",
        "memalign",
        "posix_memalign",
        "realloc",
    ],
)
def test_simple_allocation_tracking(allocator_func, tmpdir):
    # GIVEN
    allocator = MemoryAllocator()
    output = Path(tmpdir) / "test.bin"

    # WHEM
    with Tracker(output) as tracker:
        getattr(allocator, allocator_func)(1234)
        allocator.free()

    allocations = tracker.get_allocation_records()
    allocs = [
        event
        for event in allocations
        if event["size"] == 1234 and event["allocator"] == allocator_func
    ]
    assert len(allocs) == 1
    (alloc,) = allocs

    frees = [
        event
        for event in allocations
        if event["address"] == alloc["address"] and event["allocator"] == "free"
    ]
    assert len(frees) >= 1


def test_mmap_tracking(tmpdir):
    # GIVEN / WHEM
    output = Path(tmpdir) / "test.bin"
    with Tracker(output) as tracker:
        with mmap.mmap(-1, length=2048, access=mmap.ACCESS_WRITE) as mmap_obj:
            mmap_obj[0:100] = b"a" * 100

    # THEN
    records = tracker.get_allocation_records()
    assert len(records) >= 2

    mmap_records = [
        record
        for record in records
        if "mmap" in record["allocator"] and record["size"] == 2048
    ]
    assert len(mmap_records) == 1
    mmunmap_record = [record for record in records if "munmap" in record["allocator"]]
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

    allocations = tracker.get_allocation_records()
    allocs = [
        event
        for event in allocations
        if event["size"] == 1234 and event["allocator"] == "valloc"
    ]
    assert len(allocs) == 1
    (alloc,) = allocs

    frees = [
        event
        for event in allocations
        if event["address"] == alloc["address"] and event["allocator"] == "free"
    ]
    assert len(frees) >= 1
