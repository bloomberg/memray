import mmap

import pytest

from bloomberg.pensieve import AllocatorType
from bloomberg.pensieve import Tracker
from bloomberg.pensieve._test import MemoryAllocator

ALLOCATORS = [
    ("malloc", AllocatorType.MALLOC),
    ("valloc", AllocatorType.VALLOC),
    ("pvalloc", AllocatorType.PVALLOC),
    ("calloc", AllocatorType.CALLOC),
    ("memalign", AllocatorType.MEMALIGN),
    ("posix_memalign", AllocatorType.POSIX_MEMALIGN),
    ("realloc", AllocatorType.REALLOC),
]


def filter_relevant_allocations(records):
    relevant_records = [
        record
        for record in records
        if record.allocator in {AllocatorType.VALLOC, AllocatorType.FREE}
    ]
    alloc_addresses = {
        record.address
        for record in relevant_records
        if record.allocator == AllocatorType.VALLOC
    }
    return [record for record in relevant_records if record.address in alloc_addresses]


def test_no_allocations_while_tracking(tmp_path):
    with Tracker(tmp_path / "test.bin") as tracker:
        pass

    assert list(tracker.get_allocation_records()) == []


@pytest.mark.parametrize(["allocator_func", "allocator_type"], ALLOCATORS)
def test_simple_allocation_tracking(allocator_func, allocator_type, tmp_path):
    # GIVEN
    allocator = MemoryAllocator()

    # WHEN
    with Tracker(tmp_path / "test.bin") as tracker:
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


def test_mmap_tracking(tmp_path):
    # GIVEN / WHEN
    with Tracker(tmp_path / "test.bin") as tracker:
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


def test_pthread_tracking(tmp_path):
    # GIVEN
    allocator = MemoryAllocator()

    def tracking_function():
        allocator.valloc(1234)
        allocator.free()

    # WHEN
    with Tracker(tmp_path / "test.bin") as tracker:
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


class TestHighWatermark:
    def test_no_allocations_while_tracking(self, tmp_path):
        with Tracker(tmp_path / "test.bin") as tracker:
            pass

        assert list(tracker.get_high_watermark_allocation_records()) == []

    @pytest.mark.parametrize(["allocator_func", "allocator_type"], ALLOCATORS)
    def test_simple_allocation_tracking(self, tmp_path, allocator_func, allocator_type):
        allocator = MemoryAllocator()

        with Tracker(tmp_path / "test.bin") as tracker:
            getattr(allocator, allocator_func)(1234)
            allocator.free()

        peak_allocations_unfiltered = tracker.get_high_watermark_allocation_records()
        peak_allocations = [
            record for record in peak_allocations_unfiltered if record.size == 1234
        ]
        assert len(peak_allocations) == 1, peak_allocations

        record = peak_allocations[0]
        assert record.allocator == allocator_type
        assert record.n_allocations == 1

    def test_multiple_high_watermark(self, tmp_path):
        allocator = MemoryAllocator()

        with Tracker(tmp_path / "test.bin") as tracker:
            for _ in range(2):
                allocator.valloc(1024)
                allocator.free()

        all_allocations = filter_relevant_allocations(tracker.get_allocation_records())
        assert len(all_allocations) == 4

        peak_allocations = filter_relevant_allocations(
            tracker.get_high_watermark_allocation_records()
        )
        assert len(peak_allocations) == 1
        record = peak_allocations[0]

        assert record.allocator == AllocatorType.VALLOC
        assert record.size == 1024
        assert record.n_allocations == 1

    def test_freed_before_high_watermark_do_not_appear(self, tmp_path):
        allocator1 = MemoryAllocator()
        allocator2 = MemoryAllocator()

        with Tracker(tmp_path / "test.bin") as tracker:
            allocator1.valloc(1024)
            allocator1.free()
            allocator2.valloc(2048)
            allocator2.free()

        all_allocations = filter_relevant_allocations(tracker.get_allocation_records())
        assert len(all_allocations) == 4

        peak_allocations = filter_relevant_allocations(
            tracker.get_high_watermark_allocation_records()
        )
        assert len(peak_allocations) == 1

        record = peak_allocations[0]
        assert record.allocator == AllocatorType.VALLOC
        assert record.size == 2048
        assert record.n_allocations == 1

    def test_freed_after_high_watermark_do_not_appear(self, tmp_path):
        allocator1 = MemoryAllocator()
        allocator2 = MemoryAllocator()

        with Tracker(tmp_path / "test.bin") as tracker:
            allocator2.valloc(2048)
            allocator2.free()
            allocator1.valloc(1024)
            allocator1.free()

        all_allocations = filter_relevant_allocations(tracker.get_allocation_records())
        assert len(all_allocations) == 4

        peak_allocations = filter_relevant_allocations(
            tracker.get_high_watermark_allocation_records()
        )
        assert len(peak_allocations) == 1

        record = peak_allocations[0]
        assert record.allocator == AllocatorType.VALLOC
        assert record.size == 2048
        assert record.n_allocations == 1

    def test_allocations_aggregation_on_same_line(self, tmp_path):
        allocators = []
        with Tracker(tmp_path / "test.bin") as tracker:
            for _ in range(2):
                allocator = MemoryAllocator()
                allocators.append(allocator)

                allocator.valloc(1024)

            for allocator in allocators:
                allocator.free()

        all_allocations = filter_relevant_allocations(tracker.get_allocation_records())
        assert len(all_allocations) == 4

        peak_allocations = filter_relevant_allocations(
            tracker.get_high_watermark_allocation_records()
        )
        assert len(peak_allocations) == 1

        record = peak_allocations[0]
        assert record.allocator == AllocatorType.VALLOC
        assert record.size == 2048
        assert record.n_allocations == 2

    def test_allocations_aggregation_on_different_lines(self, tmp_path):
        allocator1 = MemoryAllocator()
        allocator2 = MemoryAllocator()

        with Tracker(tmp_path / "test.bin") as tracker:
            allocator1.valloc(1024)
            allocator2.valloc(2048)
            allocator1.free()
            allocator2.free()

        all_allocations = filter_relevant_allocations(tracker.get_allocation_records())
        assert len(all_allocations) == 4

        peak_allocations = filter_relevant_allocations(
            tracker.get_high_watermark_allocation_records()
        )
        assert len(peak_allocations) == 2
        assert sum(record.size for record in peak_allocations) == 1024 + 2048
        assert all(record.n_allocations == 1 for record in peak_allocations)

    def test_non_freed_allocations_are_accounted_for(self, tmp_path):
        allocator1 = MemoryAllocator()
        allocator2 = MemoryAllocator()

        with Tracker(tmp_path / "test.bin") as tracker:
            allocator1.valloc(1024)
            allocator2.valloc(2048)
            allocator1.free()
            allocator2.free()

        all_allocations = filter_relevant_allocations(tracker.get_allocation_records())
        assert len(all_allocations) == 4

        peak_allocations = filter_relevant_allocations(
            tracker.get_high_watermark_allocation_records()
        )
        assert len(peak_allocations) == 2
        assert sum(record.size for record in peak_allocations) == 1024 + 2048
        assert all(record.n_allocations == 1 for record in peak_allocations)

    def test_final_allocation_is_peak(self, tmp_path):
        allocator1 = MemoryAllocator()
        allocator2 = MemoryAllocator()

        with Tracker(tmp_path / "test.bin") as tracker:
            allocator1.valloc(1024)
            allocator1.free()
            allocator2.valloc(2048)
        allocator2.free()

        all_allocations = filter_relevant_allocations(tracker.get_allocation_records())
        assert len(all_allocations) == 3

        peak_allocations = filter_relevant_allocations(
            tracker.get_high_watermark_allocation_records()
        )
        assert len(peak_allocations) == 1

        record = peak_allocations[0]
        assert record.n_allocations == 1
        assert record.allocator == AllocatorType.VALLOC
        assert record.size == 2048

    def test_spiky_generally_increasing_to_final_peak(self, tmp_path):
        """Checks multiple aspects with an interesting toy function."""

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

        with Tracker(tmp_path / "test.bin") as tracker:
            recursive(10, 1024)

        all_allocations = filter_relevant_allocations(tracker.get_allocation_records())
        assert len(all_allocations) == 20
        assert sum(record.size for record in all_allocations) == 56320

        peak_allocations = filter_relevant_allocations(
            tracker.get_high_watermark_allocation_records()
        )
        assert all(record.n_allocations == 1 for record in peak_allocations)

        expected = {10, 8, 6, 4, 2, 1}
        assert len(peak_allocations) == len(expected)
        assert {record.size / 1024 for record in peak_allocations} == expected

    def test_allocations_after_high_watermark_is_freed_do_not_appear(self, tmp_path):
        allocator = MemoryAllocator()

        with Tracker(tmp_path / "test.bin") as tracker:
            allocator.valloc(2048)
            allocator.free()
            allocator.valloc(1024)
        allocator.free()

        all_allocations = filter_relevant_allocations(tracker.get_allocation_records())
        assert len(all_allocations) == 3

        peak_allocations = filter_relevant_allocations(
            tracker.get_high_watermark_allocation_records()
        )
        assert len(peak_allocations) == 1

        record = peak_allocations[0]
        assert record.n_allocations == 1
        assert record.allocator == AllocatorType.VALLOC
        assert record.size == 2048
