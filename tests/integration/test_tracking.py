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
def test_allocation_tracking(allocator_func):
    # GIVEN
    allocator = MemoryAllocator()

    # WHEM
    with Tracker() as tracker:
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


def test_pthread_tracking():
    # GIVEN
    allocator = MemoryAllocator()

    def tracking_function():
        allocator.valloc(1234)
        allocator.free()

    # WHEM
    with Tracker() as tracker:
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
