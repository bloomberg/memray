from dataclasses import dataclass

from memray import AllocatorType
from memray._memray import HighWaterMarkAggregatorTestHarness
from memray._memray import Interval

CALLOC = AllocatorType.CALLOC
MALLOC = AllocatorType.MALLOC
VALLOC = AllocatorType.VALLOC
FREE = AllocatorType.FREE
MMAP = AllocatorType.MMAP
MUNMAP = AllocatorType.MUNMAP


@dataclass(frozen=True)
class Contribution:
    n_allocations_in_high_water_mark: int
    bytes_in_high_water_mark: int
    n_allocations_leaked: int
    bytes_leaked: int


@dataclass(frozen=True)
class Location:
    tid: int
    native_frame_id: int
    frame_index: int
    native_segment_generation: int


def contribution_by_location_and_allocator(allocations):
    ret = {}
    for alloc in allocations:
        loc = Location(**{k: alloc[k] for k in Location.__dataclass_fields__.keys()})
        contribution = Contribution(
            **{k: alloc[k] for k in Contribution.__dataclass_fields__.keys()}
        )
        key = loc, alloc["allocator"]
        assert key not in ret
        ret[key] = contribution
    return ret


def test_no_allocations_at_start():
    # GIVEN
    tester = HighWaterMarkAggregatorTestHarness()

    # WHEN
    # THEN
    assert 0 == tester.get_current_heap_size()
    assert [] == tester.get_allocations()
    assert [0] == list(tester.high_water_mark_bytes_by_snapshot())
    assert [] == list(tester.get_temporal_allocations())


def test_one_allocation_is_both_high_water_mark_and_leaked():
    # GIVEN
    tester = HighWaterMarkAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )
    allocator = AllocatorType.CALLOC

    # WHEN
    tester.add_allocation(**loc.__dict__, allocator=allocator, address=4096, size=1234)

    # THEN
    assert 1234 == tester.get_current_heap_size()
    contributions = contribution_by_location_and_allocator(tester.get_allocations())
    assert contributions[(loc, allocator)] == Contribution(1, 1234, 1, 1234)
    assert len(contributions) == 1


def test_one_freed_allocation_is_high_water_mark_but_not_leaked():
    # GIVEN
    tester = HighWaterMarkAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )
    allocator = AllocatorType.CALLOC

    # WHEN
    tester.add_allocation(**loc.__dict__, allocator=allocator, address=4096, size=1234)
    tester.add_allocation(
        **loc.__dict__, allocator=AllocatorType.FREE, address=4096, size=0
    )

    # THEN
    assert 0 == tester.get_current_heap_size()
    contributions = contribution_by_location_and_allocator(tester.get_allocations())
    assert contributions[(loc, allocator)] == Contribution(1, 1234, 0, 0)
    assert len(contributions) == 1


def test_zero_byte_allocation():
    # GIVEN
    tester = HighWaterMarkAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )
    allocator = AllocatorType.CALLOC

    # WHEN
    tester.add_allocation(**loc.__dict__, allocator=allocator, address=4096, size=1234)
    tester.add_allocation(**loc.__dict__, allocator=allocator, address=8192, size=0)

    # THEN
    assert 1234 == tester.get_current_heap_size()
    contributions = contribution_by_location_and_allocator(tester.get_allocations())
    assert contributions[(loc, allocator)] == Contribution(2, 1234, 2, 1234)
    assert len(contributions) == 1


def test_freeing_one_of_two_high_water_mark_allocations_at_the_same_location():
    # GIVEN
    tester = HighWaterMarkAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )
    allocator = AllocatorType.CALLOC

    # WHEN
    tester.add_allocation(**loc.__dict__, allocator=allocator, address=4096, size=1234)
    tester.add_allocation(**loc.__dict__, allocator=allocator, address=8192, size=4321)
    tester.add_allocation(
        **loc.__dict__, allocator=AllocatorType.FREE, address=4096, size=0
    )

    # THEN
    assert 4321 == tester.get_current_heap_size()
    contributions = contribution_by_location_and_allocator(tester.get_allocations())
    assert contributions[(loc, allocator)] == Contribution(2, 1234 + 4321, 1, 4321)
    assert len(contributions) == 1


def test_freeing_one_of_two_high_water_mark_allocations_at_different_locations():
    # GIVEN
    tester = HighWaterMarkAggregatorTestHarness()
    loc1 = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )
    loc2 = Location(
        tid=2,
        native_frame_id=8,
        frame_index=10,
        native_segment_generation=12,
    )
    allocator = AllocatorType.CALLOC

    # WHEN
    tester.add_allocation(**loc1.__dict__, allocator=allocator, address=4096, size=1234)
    tester.add_allocation(**loc2.__dict__, allocator=allocator, address=8192, size=4321)
    tester.add_allocation(
        **loc1.__dict__, allocator=AllocatorType.FREE, address=4096, size=0
    )

    # THEN
    assert 4321 == tester.get_current_heap_size()
    contributions = contribution_by_location_and_allocator(tester.get_allocations())
    assert contributions[(loc1, allocator)] == Contribution(1, 1234, 0, 0)
    assert contributions[(loc2, allocator)] == Contribution(1, 4321, 1, 4321)
    assert len(contributions) == 2


def test_allocation_freed_before_high_water_mark():
    # GIVEN
    tester = HighWaterMarkAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )
    allocator = AllocatorType.CALLOC

    # WHEN
    tester.add_allocation(**loc.__dict__, allocator=allocator, address=4096, size=1234)
    tester.add_allocation(
        **loc.__dict__, allocator=AllocatorType.FREE, address=4096, size=0
    )
    tester.add_allocation(**loc.__dict__, allocator=allocator, address=8192, size=4321)

    # THEN
    assert 4321 == tester.get_current_heap_size()
    contributions = contribution_by_location_and_allocator(tester.get_allocations())
    assert contributions[(loc, allocator)] == Contribution(1, 4321, 1, 4321)
    assert len(contributions) == 1


def test_allocation_made_and_leaked_after_high_water_mark():
    # GIVEN
    tester = HighWaterMarkAggregatorTestHarness()
    loc1 = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )
    loc2 = Location(
        tid=2,
        native_frame_id=8,
        frame_index=10,
        native_segment_generation=12,
    )
    allocator = AllocatorType.CALLOC

    # WHEN
    tester.add_allocation(**loc1.__dict__, allocator=allocator, address=8192, size=4321)
    tester.add_allocation(
        **loc1.__dict__, allocator=AllocatorType.FREE, address=8192, size=0
    )
    tester.add_allocation(**loc2.__dict__, allocator=allocator, address=4096, size=1234)

    # THEN
    assert 1234 == tester.get_current_heap_size()
    contributions = contribution_by_location_and_allocator(tester.get_allocations())
    assert contributions[(loc1, allocator)] == Contribution(1, 4321, 0, 0)
    assert contributions[(loc2, allocator)] == Contribution(0, 0, 1, 1234)
    assert len(contributions) == 2


def test_allocation_made_and_freed_after_high_water_mark():
    # GIVEN
    tester = HighWaterMarkAggregatorTestHarness()
    loc1 = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )
    loc2 = Location(
        tid=2,
        native_frame_id=8,
        frame_index=10,
        native_segment_generation=12,
    )
    allocator = AllocatorType.CALLOC

    # WHEN
    tester.add_allocation(**loc1.__dict__, allocator=allocator, address=8192, size=4321)
    tester.add_allocation(
        **loc1.__dict__, allocator=AllocatorType.FREE, address=8192, size=0
    )
    tester.add_allocation(**loc2.__dict__, allocator=allocator, address=4096, size=1234)
    tester.add_allocation(
        **loc2.__dict__, allocator=AllocatorType.FREE, address=4096, size=0
    )

    # THEN
    assert 0 == tester.get_current_heap_size()
    contributions = contribution_by_location_and_allocator(tester.get_allocations())
    assert contributions[(loc1, allocator)] == Contribution(1, 4321, 0, 0)
    assert len(contributions) == 1


def test_allocation_made_and_freed_between_high_water_marks():
    # GIVEN
    tester = HighWaterMarkAggregatorTestHarness()
    loc1 = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )
    loc2 = Location(
        tid=2,
        native_frame_id=8,
        frame_index=10,
        native_segment_generation=12,
    )
    allocator = AllocatorType.CALLOC

    # WHEN
    tester.add_allocation(**loc1.__dict__, allocator=allocator, address=8192, size=4321)
    tester.add_allocation(
        **loc1.__dict__, allocator=AllocatorType.FREE, address=8192, size=0
    )
    tester.add_allocation(**loc2.__dict__, allocator=allocator, address=4096, size=1234)
    tester.add_allocation(
        **loc2.__dict__, allocator=AllocatorType.FREE, address=4096, size=0
    )
    tester.add_allocation(**loc1.__dict__, allocator=allocator, address=8192, size=4321)
    tester.add_allocation(
        **loc1.__dict__, allocator=AllocatorType.FREE, address=8192, size=0
    )

    # THEN
    assert 0 == tester.get_current_heap_size()
    contributions = contribution_by_location_and_allocator(tester.get_allocations())
    assert contributions[(loc1, allocator)] == Contribution(1, 4321, 0, 0)
    assert len(contributions) == 1


def test_allocation_made_between_high_water_marks_and_freed_after_high_water_mark():
    # GIVEN
    tester = HighWaterMarkAggregatorTestHarness()
    loc1 = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )
    loc2 = Location(
        tid=2,
        native_frame_id=8,
        frame_index=10,
        native_segment_generation=12,
    )
    allocator = AllocatorType.CALLOC

    # WHEN
    tester.add_allocation(**loc1.__dict__, allocator=allocator, address=8192, size=4321)
    tester.add_allocation(
        **loc1.__dict__, allocator=AllocatorType.FREE, address=8192, size=0
    )
    tester.add_allocation(**loc2.__dict__, allocator=allocator, address=4096, size=1234)
    tester.add_allocation(**loc1.__dict__, allocator=allocator, address=8192, size=4321)
    tester.add_allocation(
        **loc1.__dict__, allocator=AllocatorType.FREE, address=8192, size=0
    )
    tester.add_allocation(
        **loc2.__dict__, allocator=AllocatorType.FREE, address=4096, size=0
    )

    # THEN
    assert 0 == tester.get_current_heap_size()
    contributions = contribution_by_location_and_allocator(tester.get_allocations())
    assert contributions[(loc1, allocator)] == Contribution(1, 4321, 0, 0)
    assert contributions[(loc2, allocator)] == Contribution(1, 1234, 0, 0)
    assert len(contributions) == 2


def test_allocation_made_between_high_water_marks_and_leaked():
    # GIVEN
    tester = HighWaterMarkAggregatorTestHarness()
    loc1 = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )
    loc2 = Location(
        tid=2,
        native_frame_id=8,
        frame_index=10,
        native_segment_generation=12,
    )
    allocator = AllocatorType.CALLOC

    # WHEN
    tester.add_allocation(**loc1.__dict__, allocator=allocator, address=8192, size=4321)
    tester.add_allocation(
        **loc1.__dict__, allocator=AllocatorType.FREE, address=8192, size=0
    )
    tester.add_allocation(**loc2.__dict__, allocator=allocator, address=4096, size=1234)
    tester.add_allocation(**loc1.__dict__, allocator=allocator, address=8192, size=4321)

    # THEN
    assert 1234 + 4321 == tester.get_current_heap_size()
    contributions = contribution_by_location_and_allocator(tester.get_allocations())
    assert contributions[(loc1, allocator)] == Contribution(1, 4321, 1, 4321)
    assert contributions[(loc2, allocator)] == Contribution(1, 1234, 1, 1234)
    assert len(contributions) == 2


def test_different_allocators_at_one_location():
    # GIVEN
    tester = HighWaterMarkAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )

    # WHEN
    tester.add_allocation(
        **loc.__dict__, allocator=AllocatorType.MALLOC, address=4096, size=1234
    )
    tester.add_allocation(
        **loc.__dict__, allocator=AllocatorType.VALLOC, address=8192, size=4321
    )

    # THEN
    assert 1234 + 4321 == tester.get_current_heap_size()
    contributions = contribution_by_location_and_allocator(tester.get_allocations())
    assert contributions[(loc, AllocatorType.MALLOC)] == Contribution(1, 1234, 1, 1234)
    assert contributions[(loc, AllocatorType.VALLOC)] == Contribution(1, 4321, 1, 4321)
    assert len(contributions) == 2


def test_same_stack_in_different_threads():
    # GIVEN
    tester = HighWaterMarkAggregatorTestHarness()
    loc1 = Location(
        tid=1,
        native_frame_id=40,
        frame_index=50,
        native_segment_generation=60,
    )
    loc2 = Location(
        tid=2,
        native_frame_id=40,
        frame_index=50,
        native_segment_generation=60,
    )

    # WHEN
    tester.add_allocation(
        **loc1.__dict__, allocator=AllocatorType.MALLOC, address=4096, size=1234
    )
    tester.add_allocation(
        **loc2.__dict__, allocator=AllocatorType.MALLOC, address=8192, size=2468
    )

    # THEN
    assert 1234 + 2468 == tester.get_current_heap_size()
    contributions = contribution_by_location_and_allocator(tester.get_allocations())
    assert contributions[(loc1, AllocatorType.MALLOC)] == Contribution(1, 1234, 1, 1234)
    assert contributions[(loc2, AllocatorType.MALLOC)] == Contribution(1, 2468, 1, 2468)
    assert len(contributions) == 2


def test_completely_freed_range():
    # GIVEN
    tester = HighWaterMarkAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )
    allocator = AllocatorType.MMAP

    # WHEN
    tester.add_allocation(**loc.__dict__, allocator=allocator, address=4096, size=1234)
    tester.add_allocation(
        **loc.__dict__, allocator=AllocatorType.MUNMAP, address=4096, size=1234
    )

    # THEN
    assert 0 == tester.get_current_heap_size()
    contributions = contribution_by_location_and_allocator(tester.get_allocations())
    assert contributions[(loc, allocator)] == Contribution(1, 1234, 0, 0)
    assert len(contributions) == 1


def test_shrunk_range():
    # GIVEN
    tester = HighWaterMarkAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )
    allocator = AllocatorType.MMAP

    # WHEN
    tester.add_allocation(**loc.__dict__, allocator=allocator, address=4096, size=1234)
    tester.add_allocation(
        **loc.__dict__, allocator=AllocatorType.MUNMAP, address=4096, size=1000
    )

    # THEN
    assert 234 == tester.get_current_heap_size()
    contributions = contribution_by_location_and_allocator(tester.get_allocations())
    assert contributions[(loc, allocator)] == Contribution(1, 1234, 1, 234)
    assert len(contributions) == 1


def test_shrunk_then_freed_range():
    # GIVEN
    tester = HighWaterMarkAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )
    allocator = AllocatorType.MMAP

    # WHEN
    tester.add_allocation(**loc.__dict__, allocator=allocator, address=4096, size=1234)
    tester.add_allocation(
        **loc.__dict__, allocator=AllocatorType.MUNMAP, address=4096 + 1000, size=234
    )
    tester.add_allocation(
        **loc.__dict__, allocator=AllocatorType.MUNMAP, address=4096, size=1000
    )

    # THEN
    assert 0 == tester.get_current_heap_size()
    contributions = contribution_by_location_and_allocator(tester.get_allocations())
    assert contributions[(loc, allocator)] == Contribution(1, 1234, 0, 0)
    assert len(contributions) == 1


def test_split_range():
    # GIVEN
    tester = HighWaterMarkAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )
    allocator = AllocatorType.MMAP

    # WHEN
    tester.add_allocation(**loc.__dict__, allocator=allocator, address=4096, size=1234)
    tester.add_allocation(
        **loc.__dict__, allocator=AllocatorType.MUNMAP, address=4096 + 100, size=100
    )

    # THEN
    assert 1234 - 100 == tester.get_current_heap_size()
    contributions = contribution_by_location_and_allocator(tester.get_allocations())
    assert contributions[(loc, allocator)] == Contribution(1, 1234, 2, 1134)
    assert len(contributions) == 1


def test_split_then_freed_range():
    # GIVEN
    tester = HighWaterMarkAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )
    allocator = AllocatorType.MMAP

    # WHEN
    tester.add_allocation(**loc.__dict__, allocator=allocator, address=4096, size=1234)
    tester.add_allocation(
        **loc.__dict__, allocator=AllocatorType.MUNMAP, address=4096 + 100, size=100
    )
    tester.add_allocation(
        **loc.__dict__, allocator=AllocatorType.MUNMAP, address=4096, size=1234
    )

    # THEN
    assert 0 == tester.get_current_heap_size()
    contributions = contribution_by_location_and_allocator(tester.get_allocations())
    assert contributions[(loc, allocator)] == Contribution(1, 1234, 0, 0)
    assert len(contributions) == 1


def test_reporting_on_true_high_water_mark_that_was_in_a_past_snapshot():
    # GIVEN
    tester = HighWaterMarkAggregatorTestHarness()
    loc1 = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )
    loc2 = Location(
        tid=2,
        native_frame_id=8,
        frame_index=10,
        native_segment_generation=12,
    )
    allocator = AllocatorType.CALLOC

    # WHEN
    tester.capture_snapshot()
    tester.add_allocation(**loc1.__dict__, allocator=allocator, address=8192, size=4321)
    tester.capture_snapshot()
    tester.add_allocation(**loc2.__dict__, allocator=allocator, address=4096, size=100)
    tester.capture_snapshot()
    tester.add_allocation(
        **loc1.__dict__, allocator=AllocatorType.FREE, address=8192, size=0
    )
    tester.add_allocation(
        **loc2.__dict__, allocator=AllocatorType.FREE, address=4096, size=0
    )
    tester.capture_snapshot()
    tester.add_allocation(**loc2.__dict__, allocator=allocator, address=4096, size=2000)
    tester.add_allocation(
        **loc2.__dict__, allocator=AllocatorType.FREE, address=4096, size=0
    )
    tester.add_allocation(**loc1.__dict__, allocator=allocator, address=8192, size=1000)

    # THEN
    assert 1000 == tester.get_current_heap_size()
    contributions = contribution_by_location_and_allocator(tester.get_allocations())
    assert contributions[(loc1, allocator)] == Contribution(1, 4321, 1, 1000)
    assert contributions[(loc2, allocator)] == Contribution(1, 100, 0, 0)
    assert len(contributions) == 2


def test_one_allocation_before_first_snapshot():
    # GIVEN
    tester = HighWaterMarkAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )

    # WHEN
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=4096, size=1234)

    # THEN
    (alloc,) = tester.get_temporal_allocations()
    assert alloc.allocator == CALLOC
    assert alloc.stack_id == 5
    assert alloc.tid == 1
    assert alloc.intervals == [
        Interval(0, None, 1, 1234),
    ]


def test_one_allocation_after_first_snapshot():
    # GIVEN
    tester = HighWaterMarkAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )

    # WHEN
    tester.capture_snapshot()
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=4096, size=1234)

    # THEN
    (alloc,) = tester.get_temporal_allocations()
    assert alloc.allocator == CALLOC
    assert alloc.stack_id == 5
    assert alloc.tid == 1
    assert alloc.intervals == [
        Interval(1, None, 1, 1234),
    ]


def test_one_allocation_freed_at_high_water_mark_in_second_snapshot():
    # GIVEN
    tester = HighWaterMarkAggregatorTestHarness()
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
    (alloc,) = tester.get_temporal_allocations()
    assert alloc.allocator == CALLOC
    assert alloc.stack_id == 5
    assert alloc.tid == 1
    assert alloc.intervals == [
        Interval(0, 2, 1, 1234),
        Interval(2, None, 0, 0),
    ]


def test_two_allocations_in_different_snapshots():
    # GIVEN
    tester = HighWaterMarkAggregatorTestHarness()
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
    tester.capture_snapshot()
    tester.add_allocation(**loc2.__dict__, allocator=CALLOC, address=8192, size=2468)

    # THEN
    (alloc1, alloc2) = tester.get_temporal_allocations()
    assert alloc1.allocator == CALLOC
    assert alloc1.stack_id == 5
    assert alloc1.tid == 1
    assert alloc1.intervals == [
        Interval(0, None, 1, 1234),
    ]

    assert alloc2.allocator == CALLOC
    assert alloc2.stack_id == 8
    assert alloc2.tid == 1
    assert alloc2.intervals == [
        Interval(1, None, 1, 2468),
    ]


def test_one_allocation_freed_before_high_water_mark_in_second_snapshot():
    # GIVEN
    tester = HighWaterMarkAggregatorTestHarness()
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
    tester.capture_snapshot()
    tester.add_allocation(**loc1.__dict__, allocator=FREE, address=4096, size=0)
    tester.add_allocation(**loc2.__dict__, allocator=CALLOC, address=4096, size=2468)

    # THEN
    (alloc1, alloc2) = tester.get_temporal_allocations()
    assert alloc1.allocator == CALLOC
    assert alloc1.stack_id == 5
    assert alloc1.tid == 1
    assert alloc1.intervals == [
        Interval(0, 1, 1, 1234),
        Interval(1, None, 0, 0),
    ]

    assert alloc2.allocator == CALLOC
    assert alloc2.stack_id == 8
    assert alloc2.tid == 1
    assert alloc2.intervals == [
        Interval(1, None, 1, 2468),
    ]


def test_allocations_freed_over_two_snapshots():
    # GIVEN
    tester = HighWaterMarkAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )

    # WHEN
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=4096, size=1234)
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=8192, size=2468)
    tester.capture_snapshot()
    tester.add_allocation(**loc.__dict__, allocator=FREE, address=4096, size=0)
    tester.capture_snapshot()
    tester.add_allocation(**loc.__dict__, allocator=FREE, address=8192, size=0)
    tester.capture_snapshot()

    # THEN
    (alloc,) = tester.get_temporal_allocations()

    assert alloc.allocator == CALLOC
    assert alloc.stack_id == 5
    assert alloc.tid == 1
    assert alloc.intervals == [
        Interval(0, 2, 2, 1234 + 2468),
        Interval(2, 3, 1, 2468),
        Interval(3, None, 0, 0),
    ]


def test_allocations_freed_over_two_non_adjacent_snapshots():
    # GIVEN
    tester = HighWaterMarkAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )

    # WHEN
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=4096, size=1234)
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=8192, size=2468)
    tester.capture_snapshot()
    tester.capture_snapshot()
    tester.add_allocation(**loc.__dict__, allocator=FREE, address=4096, size=0)
    tester.capture_snapshot()
    tester.capture_snapshot()
    tester.add_allocation(**loc.__dict__, allocator=FREE, address=8192, size=0)
    tester.capture_snapshot()

    # THEN
    (alloc,) = tester.get_temporal_allocations()

    assert alloc.allocator == CALLOC
    assert alloc.stack_id == 5
    assert alloc.tid == 1
    assert alloc.intervals == [
        Interval(0, 3, 2, 1234 + 2468),
        Interval(3, 5, 1, 2468),
        Interval(5, None, 0, 0),
    ]


def test_allocation_after_high_water_mark_in_current_snapshot():
    # GIVEN
    tester = HighWaterMarkAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )

    # WHEN
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=8192, size=2468)
    tester.add_allocation(**loc.__dict__, allocator=FREE, address=8192, size=0)
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=8192, size=1234)

    # THEN
    (alloc,) = tester.get_temporal_allocations()

    assert alloc.allocator == CALLOC
    assert alloc.stack_id == 5
    assert alloc.tid == 1
    assert alloc.intervals == [
        Interval(0, 1, 1, 2468),
        Interval(1, None, 1, 1234),
    ]


def test_allocation_after_high_water_mark_in_historical_snapshot():
    # GIVEN
    tester = HighWaterMarkAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )

    # WHEN
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=8192, size=2468)
    tester.add_allocation(**loc.__dict__, allocator=FREE, address=8192, size=0)
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=8192, size=1234)
    tester.capture_snapshot()

    # THEN
    (alloc,) = tester.get_temporal_allocations()

    assert alloc.allocator == CALLOC
    assert alloc.stack_id == 5
    assert alloc.tid == 1
    assert alloc.intervals == [
        Interval(0, 1, 1, 2468),
        Interval(1, None, 1, 1234),
    ]


def test_allocation_and_deallocation_after_high_water_mark():
    # GIVEN
    tester = HighWaterMarkAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )

    # WHEN
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=8192, size=2468)
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=4096, size=1234)
    tester.add_allocation(**loc.__dict__, allocator=FREE, address=8192, size=0)
    tester.add_allocation(**loc.__dict__, allocator=FREE, address=4096, size=0)
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=4096, size=1230)
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=8192, size=2460)
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=0, size=1)

    # THEN
    (alloc,) = tester.get_temporal_allocations()

    assert alloc.allocator == CALLOC
    assert alloc.stack_id == 5
    assert alloc.tid == 1
    assert alloc.intervals == [
        Interval(0, 1, 2, 2468 + 1234),
        Interval(1, None, 3, 1230 + 2460 + 1),
    ]


def test_allocation_and_deallocation_across_multiple_snapshots():
    # GIVEN
    tester = HighWaterMarkAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )

    # WHEN
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=8192, size=2468)
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=4096, size=1234)
    tester.add_allocation(**loc.__dict__, allocator=FREE, address=8192, size=0)
    tester.capture_snapshot()
    tester.add_allocation(**loc.__dict__, allocator=FREE, address=4096, size=0)
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=4096, size=1230)
    tester.capture_snapshot()
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=8192, size=2460)
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=0, size=1)

    # THEN
    (alloc,) = tester.get_temporal_allocations()

    assert alloc.allocator == CALLOC
    assert alloc.stack_id == 5
    assert alloc.tid == 1
    assert alloc.intervals == [
        Interval(0, 1, 2, 2468 + 1234),
        Interval(1, 2, 1, 1234),
        Interval(2, None, 3, 1230 + 2460 + 1),
    ]


def test_allocation_and_deallocation_across_multiple_snapshots_with_other_allocators():
    # GIVEN
    tester = HighWaterMarkAggregatorTestHarness()
    loc = Location(
        tid=1,
        native_frame_id=4,
        frame_index=5,
        native_segment_generation=6,
    )

    # WHEN
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=8192, size=2468)
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=4096, size=1234)
    tester.add_allocation(**loc.__dict__, allocator=FREE, address=8192, size=0)
    tester.capture_snapshot()
    tester.add_allocation(**loc.__dict__, allocator=MALLOC, address=8192, size=1230)
    tester.capture_snapshot()
    tester.add_allocation(**loc.__dict__, allocator=VALLOC, address=0, size=1)
    tester.capture_snapshot()
    tester.add_allocation(**loc.__dict__, allocator=CALLOC, address=1000, size=42)
    tester.add_allocation(**loc.__dict__, allocator=FREE, address=8192, size=0)

    # THEN
    (alloc1, alloc2, alloc3) = tester.get_temporal_allocations()

    assert alloc1.allocator == MALLOC
    assert alloc1.stack_id == 5
    assert alloc1.tid == 1
    assert alloc1.intervals == [
        Interval(1, 4, 1, 1230),
        Interval(4, None, 0, 0),
    ]

    assert alloc2.allocator == CALLOC
    assert alloc2.stack_id == 5
    assert alloc2.tid == 1
    assert alloc2.intervals == [
        Interval(0, 1, 2, 2468 + 1234),
        Interval(1, 3, 1, 1234),
        Interval(3, None, 2, 1234 + 42),
    ]

    assert alloc3.allocator == VALLOC
    assert alloc3.stack_id == 5
    assert alloc3.tid == 1
    assert alloc3.intervals == [
        Interval(2, None, 1, 1),
    ]
