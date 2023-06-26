import multiprocessing
import sys
from multiprocessing import Pool
from pathlib import Path

import pytest

from memray import AllocatorType
from memray import FileReader
from memray import Tracker
from memray._test import MemoryAllocator
from memray._test import PymallocDomain
from memray._test import PymallocMemoryAllocator
from tests.utils import filter_relevant_allocations
from tests.utils import filter_relevant_pymalloc_allocations


@pytest.fixture(scope="module", autouse=True)
def set_multiprocessing_to_fork():
    current_method = multiprocessing.get_start_method()
    multiprocessing.set_start_method("fork", force=True)
    yield
    multiprocessing.set_start_method(current_method, force=True)


def multiproc_func(repetitions):  # pragma: no cover
    allocator = MemoryAllocator()
    for _ in range(repetitions):
        allocator.valloc(1234)
        allocator.free()


def pymalloc_multiproc_func():  # pragma: no cover
    allocator = PymallocMemoryAllocator(PymallocDomain.PYMALLOC_RAW)
    allocator.calloc(1234)
    allocator.free()


@pytest.mark.no_cover
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


@pytest.mark.no_cover
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


@pytest.mark.no_cover
def test_pymalloc_allocations_after_fork(tmpdir):
    # GIVEN
    output = Path(tmpdir) / "test.bin"

    # WHEN
    with Tracker(output, follow_fork=True, trace_python_allocators=True):
        with Pool(3) as p:
            p.starmap(pymalloc_multiproc_func, [()] * 10)

    # THEN
    child_files = Path(tmpdir).glob("test.bin.*")
    child_records = []
    for child_file in child_files:
        child_records.extend(
            filter_relevant_pymalloc_allocations(
                FileReader(child_file).get_allocation_records(), size=1234
            )
        )

    print(child_records)
    child_callocs = [
        record
        for record in child_records
        if record.allocator == AllocatorType.PYMALLOC_CALLOC and record.size == 1234
    ]

    num_expected = 10
    assert len(child_callocs) == num_expected


@pytest.mark.no_cover
def test_stack_cleanup_after_fork(tmpdir):
    """Test that we don't crash miserably when we try to write pending Python
    frames when the profile function is deactivated if the tracker has been
    destroyed after a fork without `follow_fork=True`"""

    # GIVEN
    output = Path(tmpdir) / "test.bin"

    def foo():
        with Pool() as pool:
            result = pool.map_async(sys.setprofile, [None])
            return result.get(timeout=1)

    # WHEN

    with Tracker(output, follow_fork=False):
        result = foo()

    # THEN

    assert result == [None]
