from dataclasses import dataclass

from memray import AllocatorType
from memray._memray import HighWaterMarkAggregatorTestHarness


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
