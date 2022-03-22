from multiprocessing import Pool
from pathlib import Path

from bloomberg.pensieve import AllocatorType
from bloomberg.pensieve import FileReader
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
    with Tracker(output):
        with Pool(3) as p:
            p.map(multiproc_func, [1, 10, 100, 1000, 2000, 3000, 4000, 5000])

        allocator.valloc(1234)
        allocator.free()

    relevant_records = list(
        filter_relevant_allocations(FileReader(output).get_allocation_records())
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

    # No files created by child processes
    child_files = Path(tmpdir).glob("test.bin.*")
    assert list(child_files) == []


def test_allocations_with_multiprocessing_following_fork(tmpdir):
    # GIVEN
    output = Path(tmpdir) / "test.bin"
    allocator = MemoryAllocator()

    # WHEN
    with Tracker(output, follow_fork=True):
        with Pool(3) as p:
            p.map(multiproc_func, [1, 10, 100, 1000, 2000, 3000, 4000, 5000])

        allocator.valloc(1234)
        allocator.free()

    # THEN
    relevant_records = list(
        filter_relevant_allocations(FileReader(output).get_allocation_records())
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

    child_files = Path(tmpdir).glob("test.bin.*")
    child_records = []
    for child_file in child_files:
        child_records.extend(
            filter_relevant_allocations(FileReader(child_file).get_allocation_records())
        )

    child_vallocs = [
        record for record in child_records if record.allocator == AllocatorType.VALLOC
    ]

    child_frees = [
        record for record in child_records if record.allocator == AllocatorType.FREE
    ]

    num_expected = 5000 + 4000 + 3000 + 2000 + 1000 + 100 + 10 + 1
    assert len(child_vallocs) == num_expected
    assert len(child_frees) == num_expected
    for valloc in child_vallocs:
        assert valloc.size == 1234
