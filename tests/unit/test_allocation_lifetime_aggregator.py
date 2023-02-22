from dataclasses import dataclass

from memray import AllocatorType
from memray._memray import AllocationLifetimeAggregatorTestHarness
from memray._memray import Interval

CALLOC = AllocatorType.CALLOC
FREE = AllocatorType.FREE
MMAP = AllocatorType.MMAP
MUNMAP = AllocatorType.MUNMAP


@dataclass(frozen=True)
class Location:
    tid: int
    native_frame_id: int
    frame_index: int
    native_segment_generation: int


def test_no_allocations_at_start():
    # GIVEN
    tester = AllocationLifetimeAggregatorTestHarness()

    # WHEN
    # THEN
    assert [] == list(tester.get_allocations())


def test_allocation_not_reported_when_freed_within_same_snapshot():
    # GIVEN
    tester = AllocationLifetimeAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )

    # WHEN
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=4096, size=1234)
    tester.add_allocation(**loc.__dict__, allocator=FREE, address=4096, size=0)

    # THEN
    assert [] == list(tester.get_allocations())


def test_allocation_reported_when_freed_within_different_snapshot():
    # GIVEN
    tester = AllocationLifetimeAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )

    # WHEN
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=4096, size=1234)
    tester.capture_snapshot()
    tester.add_allocation(**loc.__dict__, allocator=FREE, address=4096, size=0)

    # THEN
    (alloc,) = tester.get_allocations()
    assert alloc.allocator == CALLOC
    assert alloc.native_stack_id == 4
    assert alloc.stack_id == 5
    assert alloc.native_segment_generation == 6
    assert alloc.tid == 1
    assert alloc.intervals == [Interval(0, 1, 1, 1234)]


def test_allocation_reported_when_leaked():
    # GIVEN
    tester = AllocationLifetimeAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )

    # WHEN
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=4096, size=1234)

    # THEN
    (alloc,) = tester.get_allocations()
    assert alloc.allocator == CALLOC
    assert alloc.native_stack_id == 4
    assert alloc.stack_id == 5
    assert alloc.native_segment_generation == 6
    assert alloc.tid == 1
    assert alloc.intervals == [Interval(0, None, 1, 1234)]


def test_multiple_snapshots_between_allocation_and_deallocation():
    # GIVEN
    tester = AllocationLifetimeAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )

    # WHEN
    tester.capture_snapshot()
    tester.capture_snapshot()
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=4096, size=1234)
    tester.capture_snapshot()
    tester.capture_snapshot()
    tester.capture_snapshot()
    tester.add_allocation(**loc.__dict__, allocator=FREE, address=4096, size=0)
    tester.capture_snapshot()

    # THEN
    (alloc,) = tester.get_allocations()
    assert alloc.allocator == CALLOC
    assert alloc.native_stack_id == 4
    assert alloc.stack_id == 5
    assert alloc.native_segment_generation == 6
    assert alloc.tid == 1
    assert alloc.intervals == [Interval(2, 5, 1, 1234)]


def test_allocations_from_same_location_and_snapshot_freed_in_different_snapshots():
    # GIVEN
    tester = AllocationLifetimeAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )

    # WHEN
    tester.capture_snapshot()
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=4096, size=1234)
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=8192, size=4321)
    tester.capture_snapshot()
    tester.add_allocation(**loc.__dict__, allocator=FREE, address=8192, size=0)
    tester.capture_snapshot()
    tester.add_allocation(**loc.__dict__, allocator=FREE, address=4096, size=0)

    # THEN
    (alloc,) = tester.get_allocations()
    assert alloc.allocator == CALLOC
    assert alloc.native_stack_id == 4
    assert alloc.stack_id == 5
    assert alloc.native_segment_generation == 6
    assert alloc.tid == 1
    assert alloc.intervals == [Interval(1, 2, 1, 4321), Interval(1, 3, 1, 1234)]


def test_allocations_from_same_location_and_different_snapshots_freed_in_one_snapshot():
    # GIVEN
    tester = AllocationLifetimeAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )

    # WHEN
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=4096, size=1234)
    tester.capture_snapshot()
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=8192, size=4321)
    tester.capture_snapshot()
    tester.add_allocation(**loc.__dict__, allocator=FREE, address=8192, size=0)
    tester.add_allocation(**loc.__dict__, allocator=FREE, address=4096, size=0)

    # THEN
    (alloc,) = tester.get_allocations()
    assert alloc.allocator == CALLOC
    assert alloc.native_stack_id == 4
    assert alloc.stack_id == 5
    assert alloc.native_segment_generation == 6
    assert alloc.tid == 1
    assert alloc.intervals == [Interval(0, 2, 1, 1234), Interval(1, 2, 1, 4321)]


def test_two_leaked_allocations_from_one_location():
    # GIVEN
    tester = AllocationLifetimeAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )

    # WHEN
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=4096, size=1234)
    tester.capture_snapshot()
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=8192, size=4321)
    tester.capture_snapshot()

    # THEN
    (alloc,) = tester.get_allocations()
    assert alloc.allocator == CALLOC
    assert alloc.native_stack_id == 4
    assert alloc.stack_id == 5
    assert alloc.native_segment_generation == 6
    assert alloc.tid == 1
    assert alloc.intervals == [Interval(0, None, 1, 1234), Interval(1, None, 1, 4321)]


def test_allocations_made_and_freed_together_are_aggregated():
    # GIVEN
    tester = AllocationLifetimeAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )

    # WHEN
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=4096, size=1234)
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=8192, size=4321)
    tester.capture_snapshot()
    tester.add_allocation(**loc.__dict__, allocator=FREE, address=8192, size=0)
    tester.add_allocation(**loc.__dict__, allocator=FREE, address=4096, size=0)

    # THEN
    (alloc,) = tester.get_allocations()
    assert alloc.allocator == CALLOC
    assert alloc.native_stack_id == 4
    assert alloc.stack_id == 5
    assert alloc.native_segment_generation == 6
    assert alloc.tid == 1
    assert alloc.intervals == [Interval(0, 1, 2, 1234 + 4321)]


def test_leaked_allocations_within_one_snapshot_are_aggregated():
    # GIVEN
    tester = AllocationLifetimeAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )

    # WHEN
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=4096, size=1234)
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=8192, size=4321)
    tester.capture_snapshot()

    # THEN
    (alloc,) = tester.get_allocations()
    assert alloc.allocator == CALLOC
    assert alloc.native_stack_id == 4
    assert alloc.stack_id == 5
    assert alloc.native_segment_generation == 6
    assert alloc.tid == 1
    assert alloc.intervals == [Interval(0, None, 2, 1234 + 4321)]


def test_freed_allocations_from_different_locations_are_not_aggregated():
    # GIVEN
    tester = AllocationLifetimeAggregatorTestHarness()
    loc1 = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )
    loc2 = Location(
        tid=1,
        native_frame_id=7,
        frame_index=8,
        native_segment_generation=9,
    )
    free = Location(
        tid=0,
        native_frame_id=0,
        frame_index=0,
        native_segment_generation=0,
    )

    # WHEN
    tester.add_allocation(**loc1.__dict__, allocator=CALLOC, address=4096, size=1234)
    tester.add_allocation(**loc2.__dict__, allocator=CALLOC, address=8192, size=4321)
    tester.capture_snapshot()
    tester.add_allocation(**free.__dict__, allocator=FREE, address=8192, size=0)
    tester.add_allocation(**free.__dict__, allocator=FREE, address=4096, size=0)

    # THEN
    alloc1, alloc2 = tester.get_allocations()
    assert alloc1.allocator == CALLOC
    assert alloc1.native_stack_id == 4
    assert alloc1.stack_id == 5
    assert alloc1.native_segment_generation == 6
    assert alloc1.tid == 1
    assert alloc1.intervals == [Interval(0, 1, 1, 1234)]

    assert alloc2.allocator == CALLOC
    assert alloc2.native_stack_id == 7
    assert alloc2.stack_id == 8
    assert alloc2.native_segment_generation == 9
    assert alloc2.tid == 1
    assert alloc2.intervals == [Interval(0, 1, 1, 4321)]


def test_leaked_allocations_from_different_locations_are_not_aggregated():
    # GIVEN
    tester = AllocationLifetimeAggregatorTestHarness()
    loc1 = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )
    loc2 = Location(
        tid=1,
        native_frame_id=7,
        frame_index=8,
        native_segment_generation=9,
    )

    # WHEN
    tester.add_allocation(**loc1.__dict__, allocator=CALLOC, address=4096, size=1234)
    tester.add_allocation(**loc2.__dict__, allocator=CALLOC, address=8192, size=4321)

    # THEN
    alloc1, alloc2 = tester.get_allocations()
    assert alloc1.allocator == CALLOC
    assert alloc1.native_stack_id == 4
    assert alloc1.stack_id == 5
    assert alloc1.native_segment_generation == 6
    assert alloc1.tid == 1
    assert alloc1.intervals == [Interval(0, None, 1, 1234)]

    assert alloc2.allocator == CALLOC
    assert alloc2.native_stack_id == 7
    assert alloc2.stack_id == 8
    assert alloc2.native_segment_generation == 9
    assert alloc2.tid == 1
    assert alloc2.intervals == [Interval(0, None, 1, 4321)]


def test_range_freed_in_same_snapshot():
    # GIVEN
    tester = AllocationLifetimeAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )

    # WHEN
    tester.add_allocation(**loc.__dict__, allocator=MMAP, address=4096, size=1234)
    tester.add_allocation(**loc.__dict__, allocator=MUNMAP, address=4096, size=1234)

    # THEN
    assert [] == list(tester.get_allocations())


def test_range_freed_in_different_snapshot():
    # GIVEN
    tester = AllocationLifetimeAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )

    # WHEN
    tester.add_allocation(**loc.__dict__, allocator=MMAP, address=4096, size=1234)
    tester.capture_snapshot()
    tester.add_allocation(**loc.__dict__, allocator=MUNMAP, address=4096, size=1234)

    # THEN
    (alloc,) = tester.get_allocations()
    assert alloc.allocator == MMAP
    assert alloc.native_stack_id == 4
    assert alloc.stack_id == 5
    assert alloc.native_segment_generation == 6
    assert alloc.tid == 1
    assert alloc.intervals == [Interval(0, 1, 1, 1234)]


def test_range_leaked():
    # GIVEN
    tester = AllocationLifetimeAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )

    # WHEN
    tester.add_allocation(**loc.__dict__, allocator=MMAP, address=4096, size=1234)

    # THEN
    (alloc,) = tester.get_allocations()
    assert alloc.allocator == MMAP
    assert alloc.native_stack_id == 4
    assert alloc.stack_id == 5
    assert alloc.native_segment_generation == 6
    assert alloc.tid == 1
    assert alloc.intervals == [Interval(0, None, 1, 1234)]


def test_shrunk_then_leaked_range():
    # GIVEN
    tester = AllocationLifetimeAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )

    # WHEN
    tester.add_allocation(**loc.__dict__, allocator=MMAP, address=4096, size=1234)
    tester.add_allocation(**loc.__dict__, allocator=MUNMAP, address=4096, size=1000)

    # THEN
    (alloc,) = tester.get_allocations()
    assert alloc.allocator == MMAP
    assert alloc.native_stack_id == 4
    assert alloc.stack_id == 5
    assert alloc.native_segment_generation == 6
    assert alloc.tid == 1
    assert alloc.intervals == [Interval(0, None, 1, 234)]


def test_shrunk_then_freed_range():
    # GIVEN
    tester = AllocationLifetimeAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )

    # WHEN
    tester.add_allocation(**loc.__dict__, allocator=MMAP, address=4096, size=1234)
    tester.capture_snapshot()
    tester.add_allocation(**loc.__dict__, allocator=MUNMAP, address=4096, size=1000)
    tester.capture_snapshot()
    tester.add_allocation(**loc.__dict__, allocator=MUNMAP, address=4096, size=1234)

    # THEN
    (alloc,) = tester.get_allocations()
    assert alloc.allocator == MMAP
    assert alloc.native_stack_id == 4
    assert alloc.stack_id == 5
    assert alloc.native_segment_generation == 6
    assert alloc.tid == 1
    assert alloc.intervals == [Interval(0, 1, 0, 1000), Interval(0, 2, 1, 234)]


def test_split_then_leaked_range():
    # GIVEN
    tester = AllocationLifetimeAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )

    # WHEN
    tester.add_allocation(**loc.__dict__, allocator=MMAP, address=4096, size=1234)
    tester.capture_snapshot()
    tester.add_allocation(**loc.__dict__, allocator=MUNMAP, address=5000, size=100)

    # THEN
    (alloc,) = tester.get_allocations()

    assert alloc.allocator == MMAP
    assert alloc.native_stack_id == 4
    assert alloc.stack_id == 5
    assert alloc.native_segment_generation == 6
    assert alloc.tid == 1
    assert alloc.intervals == [Interval(0, 1, 0, 100), Interval(0, None, 1, 1234 - 100)]


def test_split_then_freed_range():
    # GIVEN
    tester = AllocationLifetimeAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )

    # WHEN
    tester.add_allocation(**loc.__dict__, allocator=MMAP, address=4096, size=1234)
    tester.capture_snapshot()
    tester.add_allocation(**loc.__dict__, allocator=MUNMAP, address=5000, size=100)
    tester.capture_snapshot()
    tester.add_allocation(**loc.__dict__, allocator=MUNMAP, address=4096, size=904)
    tester.capture_snapshot()
    tester.add_allocation(**loc.__dict__, allocator=MUNMAP, address=5100, size=230)

    # THEN
    (alloc,) = tester.get_allocations()
    assert alloc.allocator == MMAP
    assert alloc.native_stack_id == 4
    assert alloc.stack_id == 5
    assert alloc.native_segment_generation == 6
    assert alloc.tid == 1
    assert alloc.intervals == [
        Interval(0, 1, 0, 100),
        Interval(0, 2, 0, 904),
        Interval(0, 3, 1, 230),
    ]
