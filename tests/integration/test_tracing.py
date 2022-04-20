import mmap
import sys
import threading
from pathlib import Path
from unittest.mock import ANY

import pytest

from memray import AllocatorType
from memray import FileReader
from memray import Tracker
from memray._memray import _cython_nested_allocation
from memray._test import MemoryAllocator


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

    with Tracker(output):
        alloc_func1(allocator)
    records = list(FileReader(output).get_allocation_records())

    # THEN

    allocs = [record for record in records if record.allocator == AllocatorType.VALLOC]
    assert len(allocs) == 1
    (alloc,) = allocs
    traceback = list(alloc.stack_trace())
    assert traceback[-4:] == [
        ("alloc_func3", __file__, 18),
        ("alloc_func2", __file__, 27),
        ("alloc_func1", __file__, 34),
        ("test_traceback", __file__, 47),
    ]
    frees = [
        record
        for record in records
        if record.allocator == AllocatorType.FREE and record.address == alloc.address
    ]
    assert len(frees) == 1
    (free,) = frees
    traceback = list(free.stack_trace())
    assert traceback[-4:] == [
        ("alloc_func3", __file__, 20),
        ("alloc_func2", __file__, 27),
        ("alloc_func1", __file__, 34),
        ("test_traceback", __file__, 47),
    ]


def test_traceback_for_high_watermark(tmpdir):
    # GIVEN
    allocator = MemoryAllocator()
    output = Path(tmpdir) / "test.bin"

    # WHEN

    with Tracker(output):
        alloc_func1(allocator)
    records = list(FileReader(output).get_high_watermark_allocation_records())

    # THEN

    allocs = [record for record in records if record.allocator == AllocatorType.VALLOC]
    assert len(allocs) == 1
    (alloc,) = allocs
    traceback = list(alloc.stack_trace())
    assert traceback[-4:] == [
        ("alloc_func3", __file__, 18),
        ("alloc_func2", __file__, 27),
        ("alloc_func1", __file__, 34),
        ("test_traceback_for_high_watermark", __file__, 86),
    ]


def test_traceback_iteration_does_not_depend_on_the_order_of_elements(tmpdir):
    # GIVEN
    allocator = MemoryAllocator()
    output = Path(tmpdir) / "test.bin"

    # WHEN

    with Tracker(output):
        alloc_func1(allocator)
        alloc_func1(allocator)

    # THEN

    records = list(FileReader(output).get_allocation_records())
    allocs = [record for record in records if record.allocator == AllocatorType.VALLOC]
    alloc1, alloc2 = allocs
    traceback1 = list(alloc1.stack_trace())
    traceback2 = list(alloc2.stack_trace())

    records = list(FileReader(output).get_allocation_records())
    allocs = [record for record in records if record.allocator == AllocatorType.VALLOC]
    alloc1, alloc2 = allocs
    assert traceback2 == list(alloc2.stack_trace())
    assert traceback1 == list(alloc1.stack_trace())


def test_cython_traceback(tmpdir):
    # GIVEN
    allocator = MemoryAllocator()
    output = Path(tmpdir) / "test.bin"

    # WHEN

    with Tracker(output):
        _cython_nested_allocation(allocator.valloc, 1234)
    allocator.free()
    records = list(FileReader(output).get_allocation_records())

    # THEN

    allocs = [record for record in records if record.allocator == AllocatorType.VALLOC]
    assert len(allocs) == 2
    alloc1, alloc2 = allocs

    traceback = list(alloc1.stack_trace())
    assert traceback[-3:] == [
        ("valloc", ANY, 74),
        ("_cython_nested_allocation", ANY, 92),
        ("test_cython_traceback", ANY, 137),
    ]

    traceback = list(alloc2.stack_trace())
    assert traceback[-3:] == [
        ("_cython_nested_allocation", ANY, 92),
        ("test_cython_traceback", ANY, 137),
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
        ("_cython_nested_allocation", ANY, 92),
        ("test_cython_traceback", ANY, 137),
    ]


def test_records_can_be_retrieved_twice(tmpdir):
    # GIVEN
    allocator = MemoryAllocator()
    output = Path(tmpdir) / "test.bin"

    # WHEN

    with Tracker(output):
        alloc_func1(allocator)

    # THEN

    reader = FileReader(output)
    records1 = list(reader.get_allocation_records())
    records2 = list(reader.get_allocation_records())

    assert records1 == records2


def test_high_watermark_records_can_be_retrieved_twice(tmpdir):
    # GIVEN
    allocator = MemoryAllocator()
    output = Path(tmpdir) / "test.bin"

    # WHEN

    with Tracker(output):
        alloc_func1(allocator)

    # THEN

    reader = FileReader(output)
    records1 = list(reader.get_high_watermark_allocation_records())
    records2 = list(reader.get_high_watermark_allocation_records())

    assert records1 == records2


def test_traceback_can_be_retrieved_twice(tmpdir):
    # GIVEN
    allocator = MemoryAllocator()
    output = Path(tmpdir) / "test.bin"

    # WHEN

    with Tracker(output):
        alloc_func1(allocator)

    # THEN

    records = list(FileReader(output).get_allocation_records())
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

    with Tracker(output):
        alloc_func1(allocator)

    # THEN

    reader = FileReader(output)
    records = list(reader.get_high_watermark_allocation_records())
    (alloc,) = records
    traceback1 = list(alloc.stack_trace())
    records = list(reader.get_high_watermark_allocation_records())
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

    with Tracker(output):
        foo()
    records = list(FileReader(output).get_allocation_records())

    # THEN

    allocs = [record for record in records if record.allocator == AllocatorType.VALLOC]
    assert len(allocs) == 1
    (alloc,) = allocs
    traceback = [frame[0] for frame in alloc.stack_trace()]
    assert traceback[-4:] == [
        "valloc",
        "foo",
        "test_initial_tracking_frames_are_correctly_populated",
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
    with Tracker(output):
        bar()
    records = list(FileReader(output).get_allocation_records())

    # THEN

    allocs = [record for record in records if record.allocator == AllocatorType.VALLOC]
    assert len(allocs) == 1
    (alloc,) = allocs
    traceback = [frame[0] for frame in alloc.stack_trace()]
    assert traceback[-5:] == [
        "valloc",
        "foo",
        "bar",
        "test_restart_tracing_function_gets_correctly_the_frames",
    ]


def test_num_records(tmpdir):
    # GIVEN
    allocator = MemoryAllocator()
    output = Path(tmpdir) / "test.bin"

    # WHEN

    with Tracker(output):
        alloc_func1(allocator)
        alloc_func1(allocator)

    # THEN
    reader = FileReader(output)
    n_records = len(list(reader.get_allocation_records()))
    assert n_records == reader.metadata.total_allocations


def test_equal_stack_traces_compare_equal(tmpdir):
    # GIVEN
    allocator = MemoryAllocator()
    output = Path(tmpdir) / "test.bin"

    # WHEN

    with Tracker(output):
        for _ in range(2):
            alloc_func1(allocator)
            alloc_func2(allocator)

    # THEN

    records = list(FileReader(output).get_allocation_records())
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

    with Tracker(output):
        alloc_func1(allocator)
        alloc_func2(allocator)
        alloc_func1(allocator)
        alloc_func2(allocator)

    # THEN

    records = list(FileReader(output).get_allocation_records())
    allocs = [record for record in records if record.allocator == AllocatorType.VALLOC]

    assert len(allocs) == 4
    first_alloc1, first_alloc2, second_alloc1, second_alloc2 = allocs

    assert first_alloc1.stack_id != second_alloc1.stack_id
    assert first_alloc1.stack_trace()[:-1] == second_alloc1.stack_trace()[:-1]
    assert first_alloc1.stack_trace()[-1] != second_alloc1.stack_trace()[-1]
    assert first_alloc2.stack_id != second_alloc2.stack_id
    assert first_alloc2.stack_trace()[:-1] == second_alloc2.stack_trace()[:-1]
    assert first_alloc2.stack_trace()[-1] != second_alloc2.stack_trace()[-1]

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

    with Tracker(output):
        foo()

    # THEN

    records = list(FileReader(output).get_allocation_records())
    allocs = [record for record in records if record.allocator == AllocatorType.VALLOC]

    assert len(allocs) == 4
    first_alloc1, first_alloc2, second_alloc1, second_alloc2 = allocs

    assert first_alloc1.stack_id != second_alloc1.stack_id
    assert first_alloc1.stack_trace() != second_alloc1.stack_trace()
    assert first_alloc2.stack_id != second_alloc2.stack_id
    assert first_alloc2.stack_trace() != second_alloc2.stack_trace()

    assert first_alloc1.stack_id != first_alloc2.stack_id
    assert second_alloc1.stack_id != second_alloc2.stack_id


def test_thread_surviving_multiple_trackers(tmp_path):
    # GIVEN
    orig_tracker_used = threading.Event()
    new_tracker_installed = threading.Event()
    allocator = MemoryAllocator()
    output1 = tmp_path / "test.bin.1"
    output2 = tmp_path / "test.bin.2"

    def deeper_function():
        allocator.valloc(1234)
        allocator.free()
        orig_tracker_used.set()
        new_tracker_installed.wait()
        allocator.valloc(1234)
        allocator.free()

    def tracking_function():
        deeper_function()

    # WHEN
    with Tracker(output1):
        bg_thread = threading.Thread(target=tracking_function)
        bg_thread.start()
        orig_tracker_used.wait()

    with Tracker(output2):
        new_tracker_installed.set()
        bg_thread.join()

    # THEN
    tracker1_allocations = list(FileReader(output1).get_allocation_records())
    tracker2_allocations = list(FileReader(output2).get_allocation_records())

    tracker1_vallocs = [
        event
        for event in tracker1_allocations
        if event.size == 1234 and event.allocator == AllocatorType.VALLOC
    ]
    tracker2_vallocs = [
        event
        for event in tracker2_allocations
        if event.size == 1234 and event.allocator == AllocatorType.VALLOC
    ]
    assert len(tracker1_vallocs) == len(tracker2_vallocs) == 1
    assert tracker1_vallocs[0].stack_trace() != tracker2_vallocs[0].stack_trace()


class TestMmap:
    @classmethod
    def allocating_function(cls):
        with mmap.mmap(-1, length=2048, access=mmap.ACCESS_WRITE) as mmap_obj:
            mmap_obj[0:100] = b"a" * 100

    @pytest.mark.valgrind
    def test_mmap(self, tmpdir):
        # GIVEN / WHEN
        output = Path(tmpdir) / "test.bin"
        with Tracker(output):
            TestMmap.allocating_function()

        # THEN
        records = list(FileReader(output).get_allocation_records())

        assert len(records) >= 2

        mmap_record = next(
            (record for record in records if AllocatorType.MMAP == record.allocator),
            None,
        )
        assert mmap_record is not None
        assert "allocating_function" in {
            element[0] for element in mmap_record.stack_trace()
        }

        mmunmap_record = next(
            (record for record in records if AllocatorType.MUNMAP == record.allocator),
            None,
        )
        assert mmunmap_record is not None
        assert "allocating_function" in {
            element[0] for element in mmunmap_record.stack_trace()
        }

    @pytest.mark.valgrind
    def test_mmap_in_thread(self, tmpdir):
        # GIVEN / WHEN
        output = Path(tmpdir) / "test.bin"

        def custom_trace_fn():
            pass

        threading.setprofile(custom_trace_fn)
        t = threading.Thread(target=TestMmap.allocating_function)
        with Tracker(output):
            t.start()
            t.join()

        # THEN
        assert threading._profile_hook == custom_trace_fn
        records = list(FileReader(output).get_allocation_records())

        assert len(records) >= 2

        mmap_record = next(
            (
                record
                for record in records
                if AllocatorType.MMAP == record.allocator and record.size == 2048
            ),
            None,
        )
        assert mmap_record is not None
        assert "allocating_function" in {
            element[0] for element in mmap_record.stack_trace()
        }

        mmunmap_record = next(
            (record for record in records if AllocatorType.MUNMAP == record.allocator),
            None,
        )
        assert mmunmap_record is not None
        assert "allocating_function" in {
            element[0] for element in mmunmap_record.stack_trace()
        }
