import collections
import datetime
import mmap
import signal
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from memray import AllocatorType
from memray import FileFormat
from memray import FileReader
from memray import Tracker
from memray._memray import compute_statistics
from memray._test import MemoryAllocator
from memray._test import MmapAllocator
from memray._test import PrimeCaches
from memray._test import PymallocDomain
from memray._test import PymallocMemoryAllocator
from memray._test import _cython_allocate_in_two_places
from memray._test import allocate_cpp_vector
from memray._test import fill_cpp_vector
from tests.utils import filter_relevant_allocations
from tests.utils import run_without_tracer

ALLOCATORS = [
    ("malloc", AllocatorType.MALLOC),
    ("valloc", AllocatorType.VALLOC),
    ("pvalloc", AllocatorType.PVALLOC),
    ("calloc", AllocatorType.CALLOC),
    ("memalign", AllocatorType.MEMALIGN),
    ("posix_memalign", AllocatorType.POSIX_MEMALIGN),
    ("aligned_alloc", AllocatorType.ALIGNED_ALLOC),
    ("realloc", AllocatorType.REALLOC),
]

PYMALLOC_ALLOCATORS = [
    ("malloc", AllocatorType.PYMALLOC_MALLOC),
    ("calloc", AllocatorType.PYMALLOC_CALLOC),
    ("realloc", AllocatorType.PYMALLOC_REALLOC),
]

PYMALLOC_DOMAINS = [
    PymallocDomain.PYMALLOC_RAW,
    PymallocDomain.PYMALLOC_MEM,
    PymallocDomain.PYMALLOC_OBJECT,
]


PAGE_SIZE = mmap.PAGESIZE
ALLOC_SIZE = 123 * 8


@pytest.mark.skipif(
    sys.platform == "darwin", reason="Test triggers some extra allocations in macOS"
)
def test_no_allocations_while_tracking(tmp_path):
    output = tmp_path / "test.bin"
    with Tracker(output):
        pass

    records = list(FileReader(output).get_allocation_records())
    assert not records


@pytest.mark.parametrize(["allocator_func", "allocator_type"], ALLOCATORS)
def test_simple_allocation_tracking(allocator_func, allocator_type, tmp_path):
    # GIVEN
    allocator = MemoryAllocator()
    output = tmp_path / "test.bin"

    # WHEN
    with Tracker(output):
        res = getattr(allocator, allocator_func)(ALLOC_SIZE)
        if res:
            allocator.free()

    if not res:
        pytest.skip(f"Allocator {allocator_func} not supported in this platform")

    # THEN
    allocations = list(FileReader(output).get_allocation_records())
    allocs = [
        event
        for event in allocations
        if event.size == ALLOC_SIZE and event.allocator == allocator_type
    ]
    assert len(allocs) == 1
    (alloc,) = allocs

    frees = [
        event
        for event in allocations
        if event.address == alloc.address and event.allocator == AllocatorType.FREE
    ]
    assert len(frees) >= 1


def test_simple_cpp_allocation_tracking(tmp_path):
    # GIVEN
    output = tmp_path / "test.bin"

    # WHEN
    with Tracker(output):
        allocate_cpp_vector(ALLOC_SIZE)

    # THEN
    allocations = list(FileReader(output).get_allocation_records())
    allocs = [event for event in allocations if event.size == ALLOC_SIZE]
    assert len(allocs) == 1
    (alloc,) = allocs

    frees = [
        event
        for event in allocations
        if event.address == alloc.address and event.allocator == AllocatorType.FREE
    ]
    assert len(frees) >= 1


@pytest.mark.parametrize("domain", PYMALLOC_DOMAINS)
@pytest.mark.parametrize(["allocator_func", "allocator_type"], PYMALLOC_ALLOCATORS)
def test_simple_pymalloc_allocation_tracking(
    allocator_func, allocator_type, domain, tmp_path
):
    # GIVEN
    allocator = PymallocMemoryAllocator(domain)
    output = tmp_path / "test.bin"

    # WHEN
    the_allocator = getattr(allocator, allocator_func)
    with Tracker(output, trace_python_allocators=True):
        res = the_allocator(ALLOC_SIZE)
        if res:
            allocator.free()

    if not res:
        pytest.skip(f"Allocator {allocator_func} not supported in this platform")

    # THEN
    allocations = list(FileReader(output).get_allocation_records())
    allocs = [
        event
        for event in allocations
        if event.size == ALLOC_SIZE and event.allocator == allocator_type
    ]
    assert len(allocs) == 1
    (alloc,) = allocs

    frees = [
        event
        for event in allocations
        if event.address == alloc.address
        and event.allocator == AllocatorType.PYMALLOC_FREE
    ]
    assert len(frees) >= 1


@pytest.mark.parametrize("domain", PYMALLOC_DOMAINS)
@pytest.mark.parametrize(["allocator_func", "allocator_type"], PYMALLOC_ALLOCATORS)
def test_pymalloc_allocation_tracking_deactivated(
    allocator_func, allocator_type, domain, tmp_path
):
    # GIVEN
    allocator = PymallocMemoryAllocator(domain)
    output = tmp_path / "test.bin"

    # WHEN
    the_allocator = getattr(allocator, allocator_func)
    with Tracker(output, trace_python_allocators=False):
        res = the_allocator(ALLOC_SIZE)
        if res:
            allocator.free()

    if not res:
        pytest.skip(f"Allocator {allocator_func} not supported in this platform")

    # THEN
    allocations = list(FileReader(output).get_allocation_records())
    allocs = [event for event in allocations if event.allocator == allocator_type]
    assert not allocs
    frees = [
        event for event in allocations if event.allocator == AllocatorType.PYMALLOC_FREE
    ]
    assert not frees


def test_mmap_tracking(tmp_path):
    # GIVEN / WHEN
    output = tmp_path / "test.bin"
    with Tracker(output):
        with mmap.mmap(-1, length=2048, access=mmap.ACCESS_WRITE) as mmap_obj:
            mmap_obj[0:100] = b"a" * 100

    # THEN
    records = list(FileReader(output).get_allocation_records())
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


def test_pthread_tracking(tmp_path):
    # GIVEN
    allocator = MemoryAllocator()

    def tracking_function():  # pragma: no cover
        allocator.valloc(ALLOC_SIZE)
        allocator.free()

    # WHEN
    output = tmp_path / "test.bin"
    with Tracker(output):
        allocator.run_in_pthread(tracking_function)

    # THEN
    allocations = list(FileReader(output).get_allocation_records())
    allocs = [
        event
        for event in allocations
        if event.size == ALLOC_SIZE and event.allocator == AllocatorType.VALLOC
    ]
    assert len(allocs) == 1
    (alloc,) = allocs

    frees = [
        event
        for event in allocations
        if event.address == alloc.address and event.allocator == AllocatorType.FREE
    ]
    assert len(frees) >= 1


def test_tracking_with_SIGKILL(tmpdir):
    """Verify that we can successfully retrieve the allocations after SIGKILL."""
    # GIVEN
    output = Path(tmpdir) / "test.bin"
    subprocess_code = textwrap.dedent(
        f"""
        import os
        import signal
        from memray import Tracker
        from memray._test import MemoryAllocator

        allocator = MemoryAllocator()
        output = "{output}"

        with Tracker(output) as tracker:
            num_flushes = 0
            last_size = os.stat(output).st_size

            # Loop until two flushes occur, since the first flush might include
            # a frame record but not an allocation record.
            while num_flushes < 2:
                allocator.valloc(1024)
                new_size = os.stat(output).st_size
                if new_size != last_size:
                    last_size = new_size
                    num_flushes += 1

            # Kill ourselves without letting the tracker clean itself up.
            os.kill(os.getpid(), signal.SIGKILL)
    """
    )

    # WHEN
    process = subprocess.run([sys.executable, "-c", subprocess_code], timeout=5)

    # THEN
    assert process.returncode == -signal.SIGKILL

    records = list(FileReader(output).get_allocation_records())
    vallocs = [
        record
        for record in filter_relevant_allocations(records)
        if record.allocator == AllocatorType.VALLOC
    ]
    (allocation, *rest) = vallocs
    assert allocation.size == 1024


def test_no_allocations(tmpdir):
    """Verify that we can successfully read a file that has no allocations."""
    # GIVEN
    output = Path(tmpdir) / "test.bin"
    subprocess_code = textwrap.dedent(
        f"""
        import os
        from memray import Tracker
        output = "{output}"
        tracker = Tracker(output)
        with tracker:
            os._exit(0)
    """
    )

    # WHEN
    process = subprocess.run([sys.executable, "-c", subprocess_code], timeout=5)

    # THEN
    assert process.returncode == 0

    records = list(FileReader(output).get_allocation_records())
    assert not records


def test_unsupported_operations_on_aggregated_capture(tmpdir):
    """Verify that we can successfully read a file that has no allocations."""
    # GIVEN
    output = Path(tmpdir) / "test.bin"
    subprocess_code = textwrap.dedent(
        f"""
        import os
        from memray import Tracker, FileFormat
        output = "{output}"
        tracker = Tracker(output, file_format=FileFormat.AGGREGATED_ALLOCATIONS)
        with tracker:
            pass
        """
    )
    process = subprocess.run([sys.executable, "-c", subprocess_code], timeout=5)
    assert process.returncode == 0
    reader = FileReader(output)

    # WHEN / THEN
    with pytest.raises(
        NotImplementedError,
        match="Can't find temporary allocations using a pre-aggregated capture file",
    ):
        list(reader.get_temporary_allocation_records())

    with pytest.raises(
        NotImplementedError,
        match="Can't get all allocations from a pre-aggregated capture file",
    ):
        list(reader.get_allocation_records())

    with pytest.raises(
        NotImplementedError,
        match="Can't compute statistics using a pre-aggregated capture file",
    ):
        compute_statistics(str(output))


@pytest.mark.parametrize(
    "file_format",
    [
        pytest.param(FileFormat.ALL_ALLOCATIONS, id="ALL_ALLOCATIONS"),
        pytest.param(FileFormat.AGGREGATED_ALLOCATIONS, id="AGGREGATED_ALLOCATIONS"),
    ],
)
class TestHighWatermark:
    def test_no_allocations_while_tracking(self, tmp_path, file_format):
        # GIVEN
        output = tmp_path / "test.bin"

        def tracking_function():
            pass

        with PrimeCaches():
            tracking_function()

        # WHEN
        with Tracker(output, native_traces=True, file_format=file_format):
            tracking_function()

        # THEN
        assert list(FileReader(output).get_high_watermark_allocation_records()) == []

    @pytest.mark.parametrize(["allocator_func", "allocator_type"], ALLOCATORS)
    def test_simple_allocation_tracking(
        self, tmp_path, allocator_func, allocator_type, file_format
    ):
        # GIVEN
        allocator = MemoryAllocator()
        output = tmp_path / "test.bin"

        # WHEN
        with Tracker(output, file_format=file_format):
            res = getattr(allocator, allocator_func)(ALLOC_SIZE)
            if res:
                allocator.free()

        if not res:
            pytest.skip(f"Allocator {allocator_func} not supported in this platform")

        # THEN
        peak_allocations_unfiltered = FileReader(
            output
        ).get_high_watermark_allocation_records()
        peak_allocations = [
            record
            for record in peak_allocations_unfiltered
            if record.size == ALLOC_SIZE
        ]
        assert len(peak_allocations) == 1, peak_allocations

        record = peak_allocations[0]
        assert record.allocator == allocator_type
        assert record.n_allocations == 1

    def test_multiple_high_watermark(self, tmp_path, file_format):
        # GIVEN
        allocator = MemoryAllocator()
        output = tmp_path / "test.bin"

        def test_function():
            for _ in range(2):
                allocator.valloc(1024)
                allocator.free()

        with PrimeCaches():
            test_function()

        # WHEN
        with Tracker(output, file_format=file_format):
            test_function()

        # THEN
        reader = FileReader(output)

        if file_format == FileFormat.ALL_ALLOCATIONS:
            all_allocations = list(
                filter_relevant_allocations(reader.get_allocation_records())
            )
            assert len(all_allocations) == 4

        peak_allocations = list(
            filter_relevant_allocations(reader.get_high_watermark_allocation_records())
        )
        assert len(peak_allocations) == 1
        record = peak_allocations[0]

        assert record.allocator == AllocatorType.VALLOC
        assert record.size == 1024
        assert record.n_allocations == 1

    def test_freed_before_high_watermark_do_not_appear(self, tmp_path, file_format):
        # GIVEN
        allocator1 = MemoryAllocator()
        allocator2 = MemoryAllocator()
        output = tmp_path / "test.bin"

        def test_function():
            allocator1.valloc(1024)
            allocator1.free()
            allocator2.valloc(2048)
            allocator2.free()

        with PrimeCaches():
            test_function()

        # WHEN
        with Tracker(output, file_format=file_format):
            test_function()

        # THEN
        reader = FileReader(output)

        if file_format == FileFormat.ALL_ALLOCATIONS:
            all_allocations = list(
                filter_relevant_allocations(reader.get_allocation_records())
            )
            assert len(all_allocations) == 4

        peak_allocations = list(
            filter_relevant_allocations(reader.get_high_watermark_allocation_records())
        )
        assert len(peak_allocations) == 1

        record = peak_allocations[0]
        assert record.allocator == AllocatorType.VALLOC
        assert record.size == 2048
        assert record.n_allocations == 1

    def test_freed_after_high_watermark_do_not_appear(self, tmp_path, file_format):
        # GIVEN
        allocator1 = MemoryAllocator()
        allocator2 = MemoryAllocator()
        output = tmp_path / "test.bin"

        def test_function():
            allocator2.valloc(2048)
            allocator2.free()
            allocator1.valloc(1024)
            allocator1.free()

        with PrimeCaches():
            test_function()

        # WHEN
        with Tracker(output, file_format=file_format):
            test_function()

        # THEN
        reader = FileReader(output)

        if file_format == FileFormat.ALL_ALLOCATIONS:
            all_allocations = list(
                filter_relevant_allocations(reader.get_allocation_records())
            )
            assert len(all_allocations) == 4

        peak_allocations = list(
            filter_relevant_allocations(reader.get_high_watermark_allocation_records())
        )
        assert len(peak_allocations) == 1

        record = peak_allocations[0]
        assert record.allocator == AllocatorType.VALLOC
        assert record.size == 2048
        assert record.n_allocations == 1

    def test_allocations_aggregation_on_same_line(self, tmp_path, file_format):
        # GIVEN
        allocators = []
        output = tmp_path / "test.bin"

        # WHEN
        with Tracker(output, file_format=file_format):
            for _ in range(2):
                allocator = MemoryAllocator()
                allocators.append(allocator)

                allocator.valloc(1024)

            for allocator in allocators:
                allocator.free()

        # THEN
        reader = FileReader(output)

        if file_format == FileFormat.ALL_ALLOCATIONS:
            all_allocations = list(
                filter_relevant_allocations(reader.get_allocation_records())
            )
            assert len(all_allocations) == 4

        peak_allocations = list(
            filter_relevant_allocations(reader.get_high_watermark_allocation_records())
        )
        assert len(peak_allocations) == 1

        record = peak_allocations[0]
        assert record.allocator == AllocatorType.VALLOC
        assert record.size == 2048
        assert record.n_allocations == 2

    def test_aggregation_same_python_stack_and_same_native_stack(
        self, tmp_path, file_format
    ):
        # GIVEN
        allocators = []
        output = tmp_path / "test.bin"

        # WHEN
        with Tracker(output, native_traces=True, file_format=file_format):
            for _ in range(2):
                allocator = MemoryAllocator()
                allocators.append(allocator)

                allocator.valloc(1024)

            for allocator in allocators:
                allocator.free()

        # THEN
        reader = FileReader(output)

        if file_format == FileFormat.ALL_ALLOCATIONS:
            all_allocations = list(
                filter_relevant_allocations(reader.get_allocation_records())
            )
            assert len(all_allocations) == 4

        peak_allocations = list(
            filter_relevant_allocations(reader.get_high_watermark_allocation_records())
        )
        assert len(peak_allocations) == 1

        record = peak_allocations[0]
        assert record.allocator == AllocatorType.VALLOC
        assert record.size == 2048
        assert record.n_allocations == 2

    def test_allocations_aggregation_on_different_lines(self, tmp_path, file_format):
        # GIVEN
        allocator1 = MemoryAllocator()
        allocator2 = MemoryAllocator()
        output = tmp_path / "test.bin"

        # WHEN
        with Tracker(output, file_format=file_format):
            allocator1.valloc(1024)
            allocator2.valloc(2048)
            allocator1.free()
            allocator2.free()

        # THEN
        reader = FileReader(output)

        if file_format == FileFormat.ALL_ALLOCATIONS:
            all_allocations = list(
                filter_relevant_allocations(reader.get_allocation_records())
            )
            assert len(all_allocations) == 4

        peak_allocations = list(
            filter_relevant_allocations(reader.get_high_watermark_allocation_records())
        )
        assert len(peak_allocations) == 2
        assert sum(record.size for record in peak_allocations) == 1024 + 2048
        assert all(record.n_allocations == 1 for record in peak_allocations)

    def test_aggregation_same_python_stack_but_different_native_stack(
        self, tmp_path, file_format
    ):
        # GIVEN
        output = tmp_path / "test.bin"

        # WHEN
        with Tracker(output, native_traces=True, file_format=file_format):
            _cython_allocate_in_two_places(ALLOC_SIZE)

        # THEN
        reader = FileReader(output)

        if file_format == FileFormat.ALL_ALLOCATIONS:
            all_allocations = list(
                filter_relevant_allocations(reader.get_allocation_records())
            )
            assert len(all_allocations) == 4

        peak_allocations = list(
            filter_relevant_allocations(reader.get_high_watermark_allocation_records())
        )
        assert len(peak_allocations) == 2
        assert (
            sum(record.size for record in peak_allocations) == ALLOC_SIZE + ALLOC_SIZE
        )
        assert all(record.n_allocations == 1 for record in peak_allocations)

    def test_non_freed_allocations_are_accounted_for(self, tmp_path, file_format):
        # GIVEN
        allocator1 = MemoryAllocator()
        allocator2 = MemoryAllocator()
        output = tmp_path / "test.bin"

        # WHEN
        with Tracker(output, file_format=file_format):
            allocator1.valloc(1024)
            allocator2.valloc(2048)
            allocator1.free()
            allocator2.free()

        # THEN
        reader = FileReader(output)

        if file_format == FileFormat.ALL_ALLOCATIONS:
            all_allocations = list(
                filter_relevant_allocations(reader.get_allocation_records())
            )
            assert len(all_allocations) == 4

        peak_allocations = list(
            filter_relevant_allocations(reader.get_high_watermark_allocation_records())
        )
        assert len(peak_allocations) == 2
        assert sum(record.size for record in peak_allocations) == 1024 + 2048
        assert all(record.n_allocations == 1 for record in peak_allocations)

    def test_final_allocation_is_peak(self, tmp_path, file_format):
        # GIVEN
        allocator1 = MemoryAllocator()
        allocator2 = MemoryAllocator()
        output = tmp_path / "test.bin"

        # WHEN
        with Tracker(output, file_format=file_format):
            allocator1.valloc(1024)
            allocator1.free()
            allocator2.valloc(2048)
        allocator2.free()

        # THEN
        reader = FileReader(output)

        if file_format == FileFormat.ALL_ALLOCATIONS:
            all_allocations = list(
                filter_relevant_allocations(reader.get_allocation_records())
            )
            assert len(all_allocations) == 3

        peak_allocations = list(
            filter_relevant_allocations(reader.get_high_watermark_allocation_records())
        )
        assert len(peak_allocations) == 1

        record = peak_allocations[0]
        assert record.n_allocations == 1
        assert record.allocator == AllocatorType.VALLOC
        assert record.size == 2048

    def test_spiky_generally_increasing_to_final_peak(self, tmp_path, file_format):
        """Checks multiple aspects with an interesting toy function."""

        # GIVEN
        def recursive(n, chunk_size):
            """Mimics generally-increasing but spiky usage"""
            if not n:
                return

            allocator = MemoryAllocator()
            print(f"+{n:>2} kB")
            allocator.valloc(n * chunk_size)

            # Don't keep allocated memory when recursing, ~50% of the calls.
            if n % 2:
                allocator.free()
                print(f"-{n:>2} kB")
                recursive(n - 1, chunk_size)
            else:
                recursive(n - 1, chunk_size)
                allocator.free()
                print(f"-{n:>2} kB")

        # WHEN
        output = tmp_path / "test.bin"
        with Tracker(output, file_format=file_format):
            recursive(10, 1024)

        # THEN
        reader = FileReader(output)

        if file_format == FileFormat.ALL_ALLOCATIONS:
            all_allocations = list(
                filter_relevant_allocations(reader.get_allocation_records())
            )
            assert len(all_allocations) == 20
            assert sum(record.size for record in all_allocations) == 56320

        peak_allocations = list(
            filter_relevant_allocations(reader.get_high_watermark_allocation_records())
        )
        assert all(record.n_allocations == 1 for record in peak_allocations)

        expected = {10, 8, 6, 4, 2, 1}
        assert len(peak_allocations) == len(expected)
        assert {record.size / 1024 for record in peak_allocations} == expected

    def test_allocations_after_high_watermark_is_freed_do_not_appear(
        self, tmp_path, file_format
    ):
        # GIVEN
        allocator = MemoryAllocator()
        output = tmp_path / "test.bin"

        def test_function():
            allocator.valloc(2048)
            allocator.free()
            allocator.valloc(1024)

        with PrimeCaches():
            test_function()
            allocator.free()

        # WHEN
        with Tracker(output, file_format=file_format):
            test_function()
        allocator.free()

        # THEN
        reader = FileReader(output)

        if file_format == FileFormat.ALL_ALLOCATIONS:
            all_allocations = list(
                filter_relevant_allocations(reader.get_allocation_records())
            )
            assert len(all_allocations) == 3

        peak_allocations = list(
            filter_relevant_allocations(reader.get_high_watermark_allocation_records())
        )
        assert len(peak_allocations) == 1

        record = peak_allocations[0]
        assert record.n_allocations == 1
        assert record.allocator == AllocatorType.VALLOC
        assert record.size == 2048

    def test_partial_munmap(self, tmp_path, file_format):
        """Partial munmap operations should be accurately tracked: we should
        only account for the removal of the actually munmap'd chunk and not
        the entire mmap'd region when a partial munmap is performed."""

        # GIVEN
        output = tmp_path / "test.bin"

        def test_function():
            # Mmap some memory and free just the first page. This should not register
            # the deallocation of the entire mmap'd region, only one page.
            alloc = MmapAllocator(2 * PAGE_SIZE)
            alloc.munmap(PAGE_SIZE)

            # Now perform the peak allocation. This should be detected as the peak index.
            MmapAllocator(10 * PAGE_SIZE)
            # At this point we should have 11 * PAGE_SIZE allocated

        with PrimeCaches():
            test_function()

        # WHEN
        with Tracker(output, file_format=file_format):
            test_function()

        # THEN
        reader = FileReader(output)
        peak_allocations = list(reader.get_high_watermark_allocation_records())
        assert len(peak_allocations) == 2
        peak_memory = sum(x.size for x in peak_allocations)
        assert peak_memory == 11 * PAGE_SIZE

    def test_partial_munmap_gap(self, tmp_path, file_format):
        """Validate that removing chunks from a mmap'd region correctly accounts
        for the parts removed. This test allocates 4 pages and removes the first
        and last pages of the mmap'd region."""

        # GIVEN
        output = tmp_path / "test.bin"

        def test_function():
            # Mmap some memory and free two pages: one at the beginning and one at the
            # end of the region.
            alloc = MmapAllocator(4 * PAGE_SIZE)
            alloc.munmap(PAGE_SIZE)
            alloc.munmap(PAGE_SIZE, 3 * PAGE_SIZE)

            # Now perform the peak allocation. This should be detected as the peak index.
            MmapAllocator(10 * PAGE_SIZE)
            # At this point we should have 12 * PAGE_SIZE allocated

        with PrimeCaches():
            test_function()

        # WHEN
        with Tracker(output, file_format=file_format):
            test_function()

        # THEN
        reader = FileReader(output)
        peak_allocations = list(reader.get_high_watermark_allocation_records())
        assert len(peak_allocations) == 2
        peak_memory = sum(x.size for x in peak_allocations)
        assert peak_memory == 12 * PAGE_SIZE

    def test_munmap_multiple_mmaps(self, tmp_path, file_format):
        """Allocate multiple contiguous mmap'd regions and then deallocate all of them
        with munmap in one go."""

        # GIVEN
        output = tmp_path / "test.bin"
        with Tracker(output, file_format=file_format):
            # Ensure we have a long enough free buffer for the contiguous
            # mmap's. We also need to make sure the allocation addresses are
            # page-aligned later, and mmap does that for us. We can then use
            # the pointer from this allocation for the actual test.
            buf = MmapAllocator(8 * PAGE_SIZE)
            buf.munmap(8 * PAGE_SIZE)

            # WHEN
            # Allocate 2 contiguous chunks of 4 pages (8 pages in total) and free them
            # with a single munmap
            alloc1 = MmapAllocator(4 * PAGE_SIZE, buf.address)
            MmapAllocator(4 * PAGE_SIZE, alloc1.address + (4 * PAGE_SIZE))
            alloc1.munmap(8 * PAGE_SIZE)

            # Now perform the peak allocation. This should be detected as the peak index.
            MmapAllocator(10 * PAGE_SIZE)

        # THEN
        reader = FileReader(output)
        peak_allocations = list(
            filter_relevant_allocations(
                reader.get_high_watermark_allocation_records(), ranged=True
            )
        )
        peak_memory = sum(x.size for x in peak_allocations)
        assert peak_memory == 10 * PAGE_SIZE

    def test_munmap_multiple_mmaps_multiple_munmaps(self, tmp_path, file_format):
        """Allocate multiple contiguous mmap'd regions and then with multiple munmap's, each
        deallocating several mmap'd areas in one go."""
        # GIVEN
        output = tmp_path / "test.bin"
        with Tracker(output, file_format=file_format):
            # Ensure we have a long enough free buffer for the contiguous
            # mmap's. We also need to make sure the allocation addresses are
            # page-aligned later, and mmap does that for us. We can then use
            # the pointer from this allocation for the actual test.
            buf = MmapAllocator(8 * PAGE_SIZE)
            buf.munmap(8 * PAGE_SIZE)

            # WHEN
            alloc1 = MmapAllocator(2 * PAGE_SIZE, buf.address)
            MmapAllocator(2 * PAGE_SIZE, buf.address + (2 * PAGE_SIZE))
            MmapAllocator(2 * PAGE_SIZE, buf.address + (4 * PAGE_SIZE))
            MmapAllocator(2 * PAGE_SIZE, buf.address + (6 * PAGE_SIZE))
            alloc1.munmap(4 * PAGE_SIZE)
            alloc1.munmap(4 * PAGE_SIZE, 4 * PAGE_SIZE)

            # Now perform the peak allocation. This should be detected as the peak index.
            MmapAllocator(10 * PAGE_SIZE)

        # THEN
        reader = FileReader(output)
        peak_allocations = list(
            filter_relevant_allocations(
                reader.get_high_watermark_allocation_records(), ranged=True
            )
        )
        peak_memory = sum(x.size for x in peak_allocations)
        assert peak_memory == 10 * PAGE_SIZE

    def test_partial_munmap_multiple_split_in_middle(self, tmp_path, file_format):
        """Deallocate pages in of a larger mmap'd area, splitting it into 3 areas."""
        # GIVEN
        output = tmp_path / "test.bin"

        def test_function():
            alloc = MmapAllocator(5 * PAGE_SIZE)
            alloc.munmap(PAGE_SIZE, 1 * PAGE_SIZE)
            alloc.munmap(PAGE_SIZE, 3 * PAGE_SIZE)
            MmapAllocator(10 * PAGE_SIZE)

        with PrimeCaches():
            test_function()

        # WHEN
        with Tracker(output, file_format=file_format):
            test_function()

        # THEN
        reader = FileReader(output)
        peak_allocations = list(reader.get_high_watermark_allocation_records())
        assert len(peak_allocations) == 2
        peak_memory = sum(x.size for x in peak_allocations)
        assert peak_memory == 13 * PAGE_SIZE

    def test_partial_munmap_split_in_middle(self, tmp_path, file_format):
        """Deallocate a single page in the middle of a larger mmap'd area."""
        # GIVEN
        output = tmp_path / "test.bin"

        def test_function():
            alloc = MmapAllocator(8 * PAGE_SIZE)
            alloc.munmap(PAGE_SIZE, 4 * PAGE_SIZE)

            MmapAllocator(10 * PAGE_SIZE)

        with PrimeCaches():
            test_function()

        # WHEN
        with Tracker(output, file_format=file_format):
            test_function()

        # THEN
        reader = FileReader(output)
        peak_allocations = list(reader.get_high_watermark_allocation_records())
        assert len(peak_allocations) == 2
        peak_memory = sum(x.size for x in peak_allocations)
        assert peak_memory == 17 * PAGE_SIZE


@pytest.mark.parametrize(
    "file_format",
    [
        pytest.param(FileFormat.ALL_ALLOCATIONS, id="ALL_ALLOCATIONS"),
        pytest.param(FileFormat.AGGREGATED_ALLOCATIONS, id="AGGREGATED_ALLOCATIONS"),
    ],
)
class TestLeaks:
    def test_leaks_allocations_are_detected(self, tmp_path, file_format):
        # GIVEN
        allocator = MemoryAllocator()
        output = tmp_path / "test.bin"

        # WHEN
        with Tracker(output, file_format=file_format):
            allocator.valloc(1024)
        allocator.free()

        # THEN
        reader = FileReader(output)

        if file_format == FileFormat.ALL_ALLOCATIONS:
            all_allocations = list(
                filter_relevant_allocations(reader.get_allocation_records())
            )
            assert len(all_allocations) == 1

        leaked_allocations = list(
            filter_relevant_allocations(reader.get_leaked_allocation_records())
        )
        assert len(leaked_allocations) == 1

        record = leaked_allocations[0]
        assert record.n_allocations == 1
        assert record.allocator == AllocatorType.VALLOC
        assert record.size == 1024

    def test_allocations_that_are_freed_do_not_appear_as_leaks(
        self, tmp_path, file_format
    ):
        # GIVEN
        allocator = MemoryAllocator()
        output = tmp_path / "test.bin"

        # WHEN
        with Tracker(output, file_format=file_format):
            allocator.valloc(1024)
            allocator.free()
            allocator.valloc(1024)
            allocator.free()
            allocator.valloc(1024)
            allocator.free()

        # THEN
        reader = FileReader(output)

        if file_format == FileFormat.ALL_ALLOCATIONS:
            all_allocations = list(
                filter_relevant_allocations(reader.get_allocation_records())
            )
            assert len(all_allocations) == 6

        leaked_allocations = list(
            filter_relevant_allocations(reader.get_leaked_allocation_records())
        )
        assert not leaked_allocations

    def test_leak_that_happens_in_the_middle_is_detected(self, tmp_path, file_format):
        # GIVEN
        allocator = MemoryAllocator()
        leak_allocator = MemoryAllocator()
        output = tmp_path / "test.bin"

        # WHEN
        with Tracker(output, file_format=file_format):
            allocator.valloc(1024)
            allocator.free()
            allocator.valloc(1024)
            leak_allocator.valloc(2048)
            allocator.free()
            allocator.valloc(1024)
            allocator.free()
        leak_allocator.free()

        # THEN
        reader = FileReader(output)

        if file_format == FileFormat.ALL_ALLOCATIONS:
            all_allocations = list(
                filter_relevant_allocations(reader.get_allocation_records())
            )
            assert len(all_allocations) == 7

        leaked_allocations = list(
            filter_relevant_allocations(reader.get_leaked_allocation_records())
        )

        assert len(leaked_allocations) == 1

        record = leaked_allocations[0]
        assert record.n_allocations == 1
        assert record.allocator == AllocatorType.VALLOC
        assert record.size == 2048

    def test_leaks_that_happen_in_different_lines(self, tmp_path, file_format):
        # GIVEN
        allocator1 = MemoryAllocator()
        allocator2 = MemoryAllocator()
        output = tmp_path / "test.bin"

        # WHEN
        with Tracker(output, file_format=file_format):
            allocator1.valloc(1024)
            allocator2.valloc(2048)

        allocator1.free()
        allocator2.free()

        # THEN
        leaked_allocations = list(
            filter_relevant_allocations(
                FileReader(output).get_leaked_allocation_records()
            )
        )
        assert len(leaked_allocations) == 2
        assert sum(record.size for record in leaked_allocations) == 1024 + 2048
        assert all(record.n_allocations == 1 for record in leaked_allocations)

    def test_leaks_that_happen_in_the_same_function_are_aggregated(
        self, tmp_path, file_format
    ):
        # GIVEN
        allocators = []
        output = tmp_path / "test.bin"

        def foo():
            allocator = MemoryAllocator()
            allocator.valloc(1024)
            allocators.append(allocator)

        # WHEN
        with Tracker(output, file_format=file_format):
            for _ in range(10):
                foo()

        for allocator in allocators:
            allocator.free()

        # THEN
        reader = FileReader(output)

        if file_format == FileFormat.ALL_ALLOCATIONS:
            all_allocations = list(
                filter_relevant_allocations(reader.get_allocation_records())
            )
            assert len(all_allocations) == 10

        leaked_allocations = list(
            filter_relevant_allocations(reader.get_leaked_allocation_records())
        )
        assert len(leaked_allocations) == 1
        (allocation,) = leaked_allocations
        assert allocation.size == 1024 * 10
        assert allocation.n_allocations == 10

    def test_unmatched_deallocations_are_not_reported(self, tmp_path, file_format):
        # GIVEN
        allocator = MemoryAllocator()
        output = tmp_path / "test.bin"

        # WHEN
        allocator.valloc(ALLOC_SIZE)
        with Tracker(output, file_format=file_format):
            allocator.free()

        # THEN
        reader = FileReader(output)

        if file_format == FileFormat.ALL_ALLOCATIONS:
            all_allocations = list(reader.get_allocation_records())
            assert len(all_allocations) >= 1

        assert not list(
            filter_relevant_allocations(reader.get_leaked_allocation_records())
        )

    def test_thread_allocations_multiple_threads(self, tmpdir, file_format):
        # GIVEN
        def allocating_function(allocator, amount, stop_flag):
            allocator.posix_memalign(amount)
            allocator.posix_memalign(amount)
            # We need a barrier as pthread might reuse the same thread ID if the first thread
            # finishes before the other one starts
            stop_flag.wait()

        # WHEN
        alloc1 = MemoryAllocator()
        stop_flag1 = threading.Event()
        alloc2 = MemoryAllocator()
        stop_flag2 = threading.Event()
        output = Path(tmpdir) / "test.bin"
        with Tracker(output, file_format=file_format):
            t1 = threading.Thread(
                target=allocating_function, args=(alloc1, 2048, stop_flag1)
            )
            t1.start()
            t2 = threading.Thread(
                target=allocating_function, args=(alloc2, 2048, stop_flag2)
            )
            t2.start()

            stop_flag1.set()
            t1.join()
            stop_flag2.set()
            t2.join()

        # THEN
        reader = FileReader(output)

        if file_format == FileFormat.ALL_ALLOCATIONS:
            all_allocations = [
                record
                for record in reader.get_allocation_records()
                if record.allocator == AllocatorType.POSIX_MEMALIGN
            ]
            assert len(all_allocations) == 4

        high_watermark_records = (
            record
            for record in reader.get_high_watermark_allocation_records(
                merge_threads=False
            )
            if record.allocator == AllocatorType.POSIX_MEMALIGN
        )
        # Group the allocations per thread
        records = collections.defaultdict(list)
        for record in high_watermark_records:
            records[record.tid].append(record)
        assert len(records.keys()) == 2
        # Each thread should have 4096 bytes total allocations
        for tid, allocations in records.items():
            assert sum(allocation.size for allocation in allocations) == 4096


class TestTemporaryAllocations:
    def test_temporary_allocations_are_detected(self, tmp_path):
        # GIVEN
        allocator = MemoryAllocator()
        output = tmp_path / "test.bin"

        # WHEN
        with Tracker(output):
            allocator.valloc(1024)
            allocator.free()

        # THEN
        reader = FileReader(output)
        all_allocations = list(
            filter_relevant_allocations(reader.get_allocation_records())
        )
        assert len(all_allocations) == 2

        temporary_allocations = list(
            filter_relevant_allocations(reader.get_temporary_allocation_records())
        )
        assert len(temporary_allocations) == 1

        record = temporary_allocations[0]
        assert record.n_allocations == 1
        assert record.allocator == AllocatorType.VALLOC
        assert record.size == 1024

    def test_temporary_allocations_with_two_allocators_are_detected(self, tmp_path):
        # GIVEN
        allocator1 = MemoryAllocator()
        allocator2 = MemoryAllocator()
        output = tmp_path / "test.bin"

        # WHEN
        with Tracker(output):
            allocator1.valloc(1024)
            allocator1.free()
            allocator2.valloc(1024)
            allocator2.free()
        # THEN
        reader = FileReader(output)
        all_allocations = list(
            filter_relevant_allocations(reader.get_allocation_records())
        )
        assert len(all_allocations) == 4

        temporary_allocations = list(
            filter_relevant_allocations(reader.get_temporary_allocation_records())
        )
        assert len(temporary_allocations) == 2

        for record in temporary_allocations:
            assert record.n_allocations == 1
            assert record.allocator == AllocatorType.VALLOC
            assert record.size == 1024

    @pytest.mark.parametrize(
        "buffer_size",
        [
            1,
            2,
            5,
            10,
        ],
    )
    def test_temporary_allocations_outside_buffer_are_not_detected(
        self, tmp_path, buffer_size
    ):
        # GIVEN
        allocators = [MemoryAllocator() for _ in range(buffer_size + 1)]
        output = tmp_path / "test.bin"

        # WHEN
        with Tracker(output):
            for allocator in allocators:
                allocator.valloc(1024)
            for allocator in reversed(allocators):
                allocator.free()

        # THEN
        reader = FileReader(output)
        all_allocations = list(
            filter_relevant_allocations(reader.get_allocation_records())
        )
        assert len(all_allocations) == 2 * (buffer_size + 1)

        temporary_allocations = list(
            filter_relevant_allocations(
                reader.get_temporary_allocation_records(threshold=buffer_size - 1)
            )
        )
        assert len(temporary_allocations) == 1
        (allocation,) = temporary_allocations
        assert allocation.n_allocations == buffer_size

    def test_temporary_allocations_that_happen_in_different_lines(self, tmp_path):
        # GIVEN
        allocator1 = MemoryAllocator()
        allocator2 = MemoryAllocator()
        output = tmp_path / "test.bin"

        # WHEN
        with Tracker(output):
            allocator1.valloc(1024)
            allocator1.free()
            allocator2.valloc(2048)
            allocator2.free()

        # THEN
        temporary_allocations = list(
            filter_relevant_allocations(
                FileReader(output).get_temporary_allocation_records()
            )
        )
        assert len(temporary_allocations) == 2
        assert sum(record.size for record in temporary_allocations) == 1024 + 2048
        assert all(record.n_allocations == 1 for record in temporary_allocations)

    def test_temporary_allocations_that_happen_in_the_same_function_are_aggregated(
        self, tmp_path
    ):
        # GIVEN
        output = tmp_path / "test.bin"

        def foo():
            allocator = MemoryAllocator()
            allocator.valloc(1024)
            allocator.free()

        # WHEN
        with Tracker(output):
            for _ in range(10):
                foo()

        # THEN
        reader = FileReader(output)
        all_allocations = list(
            filter_relevant_allocations(reader.get_allocation_records())
        )
        assert len(all_allocations) == 10 + 10  # 10 x valloc + 10 x free

        temporary_allocations = list(
            filter_relevant_allocations(reader.get_temporary_allocation_records())
        )
        assert len(temporary_allocations) == 1
        (allocation,) = temporary_allocations
        assert allocation.size == 1024 * 10
        assert allocation.n_allocations == 10

    def test_unmatched_allocations_are_not_reported(self, tmp_path):
        # GIVEN
        allocator = MemoryAllocator()
        output = tmp_path / "test.bin"

        # WHEN
        with Tracker(output):
            allocator.valloc(ALLOC_SIZE)
        allocator.free()

        # THEN
        reader = FileReader(output)
        all_allocations = list(reader.get_allocation_records())
        assert len(all_allocations) >= 1
        assert not list(
            filter_relevant_allocations(reader.get_temporary_allocation_records())
        )

    def test_thread_allocations_multiple_threads(self, tmpdir):
        # GIVEN
        def allocating_function(allocator, amount, stop_flag):
            allocator.posix_memalign(amount)
            allocator.free()
            allocator.posix_memalign(amount)
            allocator.free()
            # We need a barrier as pthread might reuse the same thread ID if the first thread
            # finishes before the other one starts
            stop_flag.wait()

        # WHEN
        alloc1 = MemoryAllocator()
        stop_flag1 = threading.Event()
        alloc2 = MemoryAllocator()
        stop_flag2 = threading.Event()
        output = Path(tmpdir) / "test.bin"
        with Tracker(output):
            t1 = threading.Thread(
                target=allocating_function, args=(alloc1, 2048, stop_flag1)
            )
            t1.start()
            t2 = threading.Thread(
                target=allocating_function, args=(alloc2, 2048, stop_flag2)
            )
            t2.start()

            stop_flag1.set()
            t1.join()
            stop_flag2.set()
            t2.join()

        # THEN
        reader = FileReader(output)
        all_allocations = [
            record
            for record in reader.get_allocation_records()
            if record.allocator == AllocatorType.POSIX_MEMALIGN
        ]
        assert len(all_allocations) == 4

        temporary_allocation_records = (
            record
            for record in reader.get_temporary_allocation_records(merge_threads=False)
            if record.allocator == AllocatorType.POSIX_MEMALIGN
        )
        # Group the allocations per thread
        records = collections.defaultdict(list)
        for record in temporary_allocation_records:
            records[record.tid].append(record)
        assert len(records.keys()) == 2
        # Each thread should have 4096 bytes total allocations
        for tid, allocations in records.items():
            assert sum(allocation.size for allocation in allocations) == 4096

    def test_intertwined_temporary_allocations_in_threads(self, tmpdir):
        """This test checks that temporary allocations are correctly detected
        when they happen in different threads with interleaved calls to malloc
        and free.

        Note that there is not an easy way to synchronize this test because
        using condition variables may allocate, disrupting the test as there
        will be other spurious allocations between our call to posix_memalign
        and the call to free.

        The best effort is that both threads are synchronized by spinlocking
        around a python boolean that uses the GIL as means to ensure the correct
        ordering of allocations.
        """

        # GIVEN
        thread1_allocated = False
        thread1_should_free = False

        def thread1_body(allocator):
            nonlocal thread1_allocated
            allocator.posix_memalign(1234)
            thread1_allocated = True
            while not thread1_should_free:
                pass
            allocator.free()

        def thread2_body(allocator):
            nonlocal thread1_should_free
            while not thread1_allocated:
                pass
            allocator.posix_memalign(1234)
            allocator.free()
            thread1_should_free = True

        # WHEN
        alloc1 = MemoryAllocator()
        alloc2 = MemoryAllocator()
        output = Path(tmpdir) / "test.bin"
        with Tracker(output):
            t1 = threading.Thread(target=thread1_body, args=[alloc1])
            t1.start()
            t2 = threading.Thread(
                target=thread2_body,
                args=[alloc2],
            )
            t2.start()

            t1.join()
            t2.join()

        # THEN
        reader = FileReader(output)
        all_allocations = [
            record
            for record in reader.get_allocation_records()
            if record.allocator == AllocatorType.POSIX_MEMALIGN
        ]
        assert len(all_allocations) == 2

        temporary_allocation_records = (
            record
            for record in reader.get_temporary_allocation_records(merge_threads=False)
            if record.allocator == AllocatorType.POSIX_MEMALIGN
        )
        # Group the allocations per thread
        records = collections.defaultdict(list)
        for record in temporary_allocation_records:
            records[record.tid].append(record)
        assert len(records.keys()) == 2
        # Each thread should have 1234 bytes total allocations
        for _, allocations in records.items():
            assert sum(allocation.size for allocation in allocations) == 1234


class TestHeader:
    def test_get_header(self, monkeypatch, tmpdir):
        # GIVEN
        allocator = MemoryAllocator()
        output = Path(tmpdir) / "test.bin"

        with PrimeCaches():
            pass

        # WHEN

        monkeypatch.setattr(sys, "argv", ["python", "-m", "pytest"])
        with run_without_tracer():
            start_time = datetime.datetime.now()
            with Tracker(output):
                for _ in range(100):
                    allocator.valloc(1024)
            end_time = datetime.datetime.now()

        reader = FileReader(output)
        n_records = len(list(reader.get_allocation_records()))
        metadata = reader.metadata

        # THEN
        assert metadata.end_time > metadata.start_time
        assert abs(metadata.start_time - start_time).seconds < 1
        assert abs(metadata.end_time - end_time).seconds < 1
        assert metadata.total_allocations == n_records
        assert metadata.command_line == "python -m pytest"
        assert metadata.peak_memory == 1024 * 100

    def test_get_header_after_snapshot(self, monkeypatch, tmpdir):
        """Verify that we can successfully retrieve the metadata after querying
        the high watermark snapshot."""
        # GIVEN
        allocator = MemoryAllocator()
        output = Path(tmpdir) / "test.bin"

        with PrimeCaches():
            pass

        # WHEN

        monkeypatch.setattr(sys, "argv", ["python", "-m", "pytest"])
        start_time = datetime.datetime.now()
        with Tracker(output):
            for _ in range(100):
                allocator.valloc(1024)
        end_time = datetime.datetime.now()

        reader = FileReader(output)
        peak, *_ = list(reader.get_high_watermark_allocation_records())
        metadata = reader.metadata

        # THEN
        assert metadata.end_time > metadata.start_time
        assert abs(metadata.start_time - start_time).seconds < 1
        assert abs(metadata.end_time - end_time).seconds < 1
        assert metadata.total_allocations == peak.n_allocations
        assert metadata.command_line == "python -m pytest"
        assert metadata.peak_memory == 1024 * 100

    @pytest.mark.parametrize(
        "allocator, allocator_name",
        [
            ("malloc", "malloc"),
            ("pymalloc", "pymalloc"),
            ("pymalloc_debug", "pymalloc debug"),
        ],
    )
    def test_header_allocator(self, allocator, allocator_name, tmpdir):
        # GIVEN
        output = Path(tmpdir) / "test.bin"

        # WHEN

        subprocess_code = textwrap.dedent(
            f"""
        from memray import Tracker
        from memray._test import MemoryAllocator
        allocator = MemoryAllocator()

        with Tracker('{output}'):
            allocator.valloc(1024)
            allocator.free()
        """
        )

        subprocess.run(
            [sys.executable, "-c", subprocess_code],
            timeout=5,
            env={"PYTHONMALLOC": allocator},
        )

        reader = FileReader(output)
        metadata = reader.metadata

        # THEN
        assert metadata.python_allocator == allocator_name


class TestMemorySnapshots:
    @pytest.mark.valgrind
    def test_memory_snapshots_are_written(self, tmp_path):
        # GIVEN
        allocator = MemoryAllocator()
        output = tmp_path / "test.bin"

        # WHEN
        with Tracker(output):
            allocator.valloc(ALLOC_SIZE)
            time.sleep(0.11)
            allocator.free()

        memory_snapshots = list(FileReader(output).get_memory_snapshots())

        assert memory_snapshots
        assert all(record.rss > 0 for record in memory_snapshots)
        assert any(record.heap >= ALLOC_SIZE for record in memory_snapshots)
        assert sorted(memory_snapshots, key=lambda r: r.time) == memory_snapshots
        assert all(
            _next.time - prev.time >= 10
            for prev, _next in zip(memory_snapshots, memory_snapshots[1:])
        )

    def test_memory_snapshots_tick_interval(self, tmp_path):
        # GIVEN
        allocator = MemoryAllocator()
        output = tmp_path / "test.bin"

        # WHEN
        with Tracker(output, memory_interval_ms=20):
            allocator.valloc(ALLOC_SIZE)
            time.sleep(1)

        memory_snapshots = list(FileReader(output).get_memory_snapshots())

        assert len(memory_snapshots)
        assert all(record.rss > 0 for record in memory_snapshots)
        assert any(record.heap >= ALLOC_SIZE for record in memory_snapshots)
        assert sorted(memory_snapshots, key=lambda r: r.time) == memory_snapshots
        assert all(
            _next.time - prev.time >= 20
            for prev, _next in zip(memory_snapshots, memory_snapshots[1:])
        )

    def test_temporary_allocations_when_filling_vector_without_preallocating(
        self, tmp_path
    ):
        # GIVEN
        output = tmp_path / "test.bin"

        # WHEN
        with Tracker(output):
            elements = fill_cpp_vector(2 << 10)

        # THEN
        reader = FileReader(output)
        temporary_allocations = [
            alloc
            for alloc in reader.get_temporary_allocation_records(threshold=1)
            if __file__ in alloc.stack_trace()[0][1]
        ]
        assert elements == 512
        assert len(temporary_allocations) == 1
        (record,) = temporary_allocations
        assert record.n_allocations == 10
        assert record.allocator == AllocatorType.MALLOC
        assert record.size >= (2 << 10)

    def test_temporary_allocations_when_filling_vector_without_preallocating_small_buffer(
        self, tmp_path
    ):
        # GIVEN
        output = tmp_path / "test.bin"

        # WHEN
        with Tracker(output):
            elements = fill_cpp_vector(2 << 10)

        # THEN
        reader = FileReader(output)
        temporary_allocations = [
            alloc
            for alloc in reader.get_temporary_allocation_records(threshold=0)
            if __file__ in alloc.stack_trace()[0][1]
        ]
        assert elements == 512
        assert len(temporary_allocations) == 1
        (record,) = temporary_allocations
        # With a buffer of 1 we only see the last allocation
        assert record.n_allocations == 1
        assert record.allocator == AllocatorType.MALLOC
        assert record.size == 2 << 10
