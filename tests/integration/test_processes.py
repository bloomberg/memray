from multiprocessing import Pool
from pathlib import Path

from bloomberg.pensieve import AllocatorType
from bloomberg.pensieve import Tracker
from bloomberg.pensieve._test import MemoryAllocator
from tests.utils import filter_relevant_allocations


def multiproc_func(repetitions):
    allocator = MemoryAllocator()
    for _ in range(repetitions):
        allocator.valloc(1234)
        allocator.free()


def test_allocations_with_multiprocessing(tmpdir):
    # GIVEN
    output = Path(tmpdir) / "test.bin"
    allocator = MemoryAllocator()

    # WHEN
    allocator = MemoryAllocator()
    with Tracker(output) as tracker:
        with Pool(3) as p:
            p.map(multiproc_func, [1, 10, 100, 1000, 2000, 3000, 4000, 5000])

        allocator.valloc(1234)
        allocator.free()

    relevant_records = list(
        filter_relevant_allocations(tracker.reader.get_allocation_records())
    )
    assert len(relevant_records) == 2

    vallocs = [
        record
        for record in relevant_records
        if record.allocator == AllocatorType.VALLOC
    ]
    assert len(vallocs) == 1
    (valloc,) = vallocs
    assert valloc.size == 1234

    frees = [
        record for record in relevant_records if record.allocator == AllocatorType.FREE
    ]
    assert len(frees) == 1
