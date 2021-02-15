import sys
from pathlib import Path
from unittest.mock import ANY

from bloomberg.pensieve import AllocatorType
from bloomberg.pensieve import Tracker
from bloomberg.pensieve._test import MemoryAllocator
from bloomberg.pensieve._test import _cython_nested_allocation


def alloc_func3(allocator):
    x = 1
    allocator.valloc(1234)
    x = 2
    allocator.free()
    x = 3
    return x


def alloc_func2(allocator):
    y = 1
    alloc_func3(allocator)
    y = 2
    return y


def alloc_func1(allocator):
    z = 1
    alloc_func2(allocator)
    z = 2
    return z


def test_traceback(tmpdir):
    # GIVEN
    allocator = MemoryAllocator()
    output = Path(tmpdir) / "test.bin"

    # WHEN

    with Tracker(output) as tracker:
        alloc_func1(allocator)
    records = list(tracker.get_allocation_records())

    # THEN

    allocs = [record for record in records if record.allocator == AllocatorType.VALLOC]
    assert len(allocs) == 1
    (alloc,) = allocs
    traceback = list(alloc.stack_trace())
    assert traceback[-3:] == [
        ("alloc_func3", __file__, 13),
        ("alloc_func2", __file__, 22),
        ("alloc_func1", __file__, 29),
    ]
    frees = [
        record
        for record in records
        if record.allocator == AllocatorType.FREE and record.address == alloc.address
    ]
    assert len(frees) == 1
    (free,) = frees
    traceback = list(free.stack_trace())
    assert traceback[-3:] == [
        ("alloc_func3", __file__, 15),
        ("alloc_func2", __file__, 22),
        ("alloc_func1", __file__, 29),
    ]


def test_traceback_for_high_watermark(tmpdir):
    # GIVEN
    allocator = MemoryAllocator()
    output = Path(tmpdir) / "test.bin"

    # WHEN

    with Tracker(output) as tracker:
        alloc_func1(allocator)
    records = list(tracker.get_high_watermark_allocation_records())

    # THEN

    allocs = [record for record in records if record.allocator == AllocatorType.VALLOC]
    assert len(allocs) == 1
    (alloc,) = allocs
    traceback = list(alloc.stack_trace())
    assert traceback[-3:] == [
        ("alloc_func3", __file__, 13),
        ("alloc_func2", __file__, 22),
        ("alloc_func1", __file__, 29),
    ]


def test_traceback_iteration_does_not_depend_on_the_order_of_elements(tmpdir):
    # GIVEN
    allocator = MemoryAllocator()
    output = Path(tmpdir) / "test.bin"

    # WHEN

    with Tracker(output) as tracker:
        alloc_func1(allocator)
        alloc_func1(allocator)

    # THEN

    records = list(tracker.get_allocation_records())
    allocs = [record for record in records if record.allocator == AllocatorType.VALLOC]
    alloc1, alloc2 = allocs
    traceback1 = list(alloc1.stack_trace())
    traceback2 = list(alloc2.stack_trace())

    records = list(tracker.get_allocation_records())
    allocs = [record for record in records if record.allocator == AllocatorType.VALLOC]
    alloc1, alloc2 = allocs
    assert traceback2 == list(alloc2.stack_trace())
    assert traceback1 == list(alloc1.stack_trace())


def test_cython_traceback(tmpdir):
    # GIVEN
    allocator = MemoryAllocator()
    output = Path(tmpdir) / "test.bin"

    # WHEN

    with Tracker(output) as tracker:
        _cython_nested_allocation(allocator.valloc, 1234)
    allocator.free()
    records = list(tracker.get_allocation_records())

    # THEN

    allocs = [record for record in records if record.allocator == AllocatorType.VALLOC]
    assert len(allocs) == 2
    alloc1, alloc2 = allocs

    traceback = list(alloc1.stack_trace())
    assert traceback[-3:] == [
        ("valloc", ANY, 243),
        ("_cython_nested_allocation", ANY, 258),
    ]

    traceback = list(alloc2.stack_trace())
    assert traceback[-3:] == [
        ("_cython_nested_allocation", ANY, 258),
    ]

    frees = [
        record
        for record in records
        if record.allocator == AllocatorType.FREE and record.address == alloc2.address
    ]
    assert len(frees) == 1
    (free,) = frees
    traceback = list(free.stack_trace())
    assert traceback[-3:] == [
        ("_cython_nested_allocation", ANY, 258),
    ]


def test_records_can_be_retrieved_twice(tmpdir):
    # GIVEN
    allocator = MemoryAllocator()
    output = Path(tmpdir) / "test.bin"

    # WHEN

    with Tracker(output) as tracker:
        alloc_func1(allocator)

    # THEN

    records1 = list(tracker.get_allocation_records())
    records2 = list(tracker.get_allocation_records())

    assert records1 == records2


def test_high_watermark_records_can_be_retrieved_twice(tmpdir):
    # GIVEN
    allocator = MemoryAllocator()
    output = Path(tmpdir) / "test.bin"

    # WHEN

    with Tracker(output) as tracker:
        alloc_func1(allocator)

    # THEN

    records1 = list(tracker.get_high_watermark_allocation_records())
    records2 = list(tracker.get_high_watermark_allocation_records())

    assert records1 == records2


def test_traceback_can_be_retrieved_twice(tmpdir):
    # GIVEN
    allocator = MemoryAllocator()
    output = Path(tmpdir) / "test.bin"

    # WHEN

    with Tracker(output) as tracker:
        alloc_func1(allocator)

    # THEN

    records = list(tracker.get_allocation_records())
    allocs = [record for record in records if record.allocator == AllocatorType.VALLOC]
    (alloc,) = allocs
    traceback1 = list(alloc.stack_trace())
    traceback2 = list(alloc.stack_trace())
    assert traceback1 == traceback2


def test_traceback_for_high_watermark_records_can_be_retrieved_twice(tmpdir):
    # GIVEN
    allocator = MemoryAllocator()
    output = Path(tmpdir) / "test.bin"

    # WHEN

    with Tracker(output) as tracker:
        alloc_func1(allocator)

    # THEN

    records = list(tracker.get_high_watermark_allocation_records())
    (alloc,) = records
    traceback1 = list(alloc.stack_trace())
    records = list(tracker.get_high_watermark_allocation_records())
    (alloc,) = records
    traceback2 = list(alloc.stack_trace())

    assert traceback1 == traceback2


def test_profile_function_is_restored_after_tracking(tmpdir):
    # GIVEN
    def profilefunc(*args):
        pass

    output = Path(tmpdir) / "test.bin"

    # WHEN

    sys.setprofile(profilefunc)

    with Tracker(output):
        assert sys.getprofile() != profilefunc

    # THEN
    assert sys.getprofile() == profilefunc


def test_initial_tracking_frames_are_correctly_populated(tmpdir):
    # GIVEN
    allocator = MemoryAllocator()
    output = Path(tmpdir) / "test.bin"

    def foo():
        allocator.valloc(1234)
        allocator.free()

    # WHEN

    with Tracker(output) as tracker:
        foo()
    records = list(tracker.get_allocation_records())

    # THEN

    allocs = [record for record in records if record.allocator == AllocatorType.VALLOC]
    assert len(allocs) == 1
    (alloc,) = allocs
    traceback = [frame[0] for frame in alloc.stack_trace()]
    assert traceback[-3:] == [
        "valloc",
        "foo",
    ]


def test_restart_tracing_function_gets_correctly_the_frames(tmpdir):
    # GIVEN
    allocator = MemoryAllocator()
    output = Path(tmpdir) / "test.bin"

    def foo():
        allocator.valloc(1234)
        allocator.free()

    # WHEN

    # Do some prelininary tracing to populate the initial frames
    with Tracker(output):
        foo()

    output.unlink()

    def bar():
        foo()

    # Do another *independent* round of tracking. The previous frames
    # should not interfere with this tracing.
    with Tracker(output) as tracker:
        bar()
    records = list(tracker.get_allocation_records())

    # THEN

    allocs = [record for record in records if record.allocator == AllocatorType.VALLOC]
    assert len(allocs) == 1
    (alloc,) = allocs
    traceback = [frame[0] for frame in alloc.stack_trace()]
    assert traceback[-4:] == [
        "valloc",
        "foo",
        "bar",
    ]


def test_num_records(tmpdir):
    # GIVEN
    allocator = MemoryAllocator()
    output = Path(tmpdir) / "test.bin"

    # WHEN

    with Tracker(output) as tracker:
        alloc_func1(allocator)
        alloc_func1(allocator)
    n_records = len(list(tracker.get_allocation_records()))

    # THEN

    assert n_records == tracker.total_allocations


def test_equal_stack_traces_compare_equal(tmpdir):
    # GIVEN
    allocator = MemoryAllocator()
    output = Path(tmpdir) / "test.bin"

    # WHEN

    with Tracker(output) as tracker:
        for _ in range(2):
            alloc_func1(allocator)
            alloc_func2(allocator)

    # THEN

    records = list(tracker.get_allocation_records())
    allocs = [record for record in records if record.allocator == AllocatorType.VALLOC]

    assert len(allocs) == 4
    first_alloc1, first_alloc2, second_alloc1, second_alloc2 = allocs

    assert first_alloc1.stack_id == second_alloc1.stack_id
    assert first_alloc1.stack_trace() == second_alloc1.stack_trace()
    assert first_alloc2.stack_id == second_alloc2.stack_id
    assert first_alloc2.stack_trace() == second_alloc2.stack_trace()

    assert first_alloc1.stack_id != first_alloc2.stack_id
    assert second_alloc1.stack_id != second_alloc2.stack_id


def test_identical_stack_traces_started_in_different_lines_in_the_root_do_not_compare_equal(
    tmpdir,
):  # GIVEN
    allocator = MemoryAllocator()
    output = Path(tmpdir) / "test.bin"

    # WHEN

    with Tracker(output) as tracker:
        alloc_func1(allocator)
        alloc_func2(allocator)
        alloc_func1(allocator)
        alloc_func2(allocator)

    # THEN

    records = list(tracker.get_allocation_records())
    allocs = [record for record in records if record.allocator == AllocatorType.VALLOC]

    assert len(allocs) == 4
    first_alloc1, first_alloc2, second_alloc1, second_alloc2 = allocs

    assert first_alloc1.stack_id != second_alloc1.stack_id
    assert first_alloc1.stack_trace() == second_alloc1.stack_trace()
    assert first_alloc2.stack_id != second_alloc2.stack_id
    assert first_alloc2.stack_trace() == second_alloc2.stack_trace()

    assert first_alloc1.stack_id != first_alloc2.stack_id
    assert second_alloc1.stack_id != second_alloc2.stack_id


def test_identical_stack_traces_started_in_different_lines_in_a_function_do_not_compare_equal(
    tmpdir,
):
    # GIVEN
    allocator = MemoryAllocator()
    output = Path(tmpdir) / "test.bin"

    # WHEN

    def foo():
        alloc_func1(allocator)
        alloc_func2(allocator)
        alloc_func1(allocator)
        alloc_func2(allocator)

    with Tracker(output) as tracker:
        foo()

    # THEN

    records = list(tracker.get_allocation_records())
    allocs = [record for record in records if record.allocator == AllocatorType.VALLOC]

    assert len(allocs) == 4
    first_alloc1, first_alloc2, second_alloc1, second_alloc2 = allocs

    assert first_alloc1.stack_id != second_alloc1.stack_id
    assert first_alloc1.stack_trace() != second_alloc1.stack_trace()
    assert first_alloc2.stack_id != second_alloc2.stack_id
    assert first_alloc2.stack_trace() != second_alloc2.stack_trace()

    assert first_alloc1.stack_id != first_alloc2.stack_id
    assert second_alloc1.stack_id != second_alloc2.stack_id
