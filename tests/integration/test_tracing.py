import mmap
import os
import sys
import threading
from pathlib import Path

import pytest

from memray import AllocatorType
from memray import FileReader
from memray import Tracker
from memray._test import MemoryAllocator
from memray._test import _cython_nested_allocation
from memray._test import allocate_without_gil_held
from memray._test import function_caller


def alloc_func3(allocator):
    x = 1
    allocator.valloc(123456)
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
        ("alloc_func3", __file__, 20),
        ("alloc_func2", __file__, 29),
        ("alloc_func1", __file__, 36),
        ("test_traceback", __file__, 49),
    ]
    frees = [
        record
        for record in records
        if record.allocator == AllocatorType.FREE and record.address == alloc.address
    ]
    assert len(frees) == 1
    (free,) = frees
    with pytest.raises(NotImplementedError):
        free.stack_trace()


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
        ("alloc_func3", __file__, 20),
        ("alloc_func2", __file__, 29),
        ("alloc_func1", __file__, 36),
        ("test_traceback_for_high_watermark", __file__, 83),
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
    assert traceback == [
        ("valloc", sys.modules["memray._test"].__file__, 44),
        ("test_cython_traceback", __file__, 134),
    ]

    traceback = list(alloc2.stack_trace())
    assert traceback == [
        ("test_cython_traceback", __file__, 134),
    ]

    frees = [
        record
        for record in records
        if record.allocator == AllocatorType.FREE and record.address == alloc2.address
    ]
    assert len(frees) == 1
    (free,) = frees
    with pytest.raises(NotImplementedError):
        free.stack_trace()


def test_large_number_of_frame_pops_between_subsequent_allocations(tmpdir):
    # GIVEN
    output = Path(tmpdir) / "test.bin"

    def allocate_deep(depth):
        if depth <= 1:
            return mmap.mmap(-1, 1234)
        return allocate_deep(depth - 1)

    # WHEN
    # Note: we don't actually care about the native stacks, but we use
    # native_traces=True to ensure that the allocation we care about inside
    # of `mmap.mmap` has a different stack than any allocation that the
    # interpreter itself performs. Otherwise, our high water mark aggregator
    # could combine the mmap we care about with other allocations performed
    # inside the interpreter that happen to share the same Python stack.
    with Tracker(output, native_traces=True):
        with allocate_deep(20):
            with mmap.mmap(-1, 12345):
                pass
    records = list(FileReader(output).get_high_watermark_allocation_records())

    # THEN
    allocs = [
        record
        for record in records
        if record.allocator == AllocatorType.MMAP and record.size == 1234
    ]
    assert len(allocs) == 1
    (alloc,) = allocs
    traceback = list(alloc.stack_trace())
    assert len(traceback) == 21

    allocs = [
        record
        for record in records
        if record.allocator == AllocatorType.MMAP and record.size == 12345
    ]
    assert len(allocs) == 1
    (alloc,) = allocs
    traceback = list(alloc.stack_trace())
    assert len(traceback) == 1


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


def test_allocations_in_root_frame_have_correct_line_number(tmpdir):
    # GIVEN
    output = Path(tmpdir) / "test.bin"
    first = second = None

    # WHEN
    with Tracker(output):
        first = mmap.mmap(-1, 1)
        second = mmap.mmap(-1, 1)
        del first
        del second

    # THEN
    records = list(FileReader(output).get_allocation_records())
    print(records)
    allocs = [
        record
        for record in records
        if record.allocator == AllocatorType.MMAP and record.size == 1
    ]

    assert len(allocs) == 2
    alloc1, alloc2 = allocs
    func1, file1, line1 = alloc1.stack_trace()[0]
    func2, file2, line2 = alloc2.stack_trace()[0]
    assert func1 == "test_allocations_in_root_frame_have_correct_line_number"
    assert func2 == "test_allocations_in_root_frame_have_correct_line_number"
    assert file1 == __file__
    assert file2 == __file__
    assert abs(line1 - line2) == 1


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


def test_allocation_in_thread_started_before_tracking_starts(tmp_path):
    """Test capturing the stack of a thread started before tracking started.

    The intended execution flow is:
    Main Thread          Background Thread
    -----------          -----------------
    Start thread
                         Call thread_body
    Install tracker
                         Call func1
                         Perform an allocation
                         Exit
    Join thread
    Uninstall tracker
    """
    # GIVEN
    thread_body_entered = threading.Event()
    tracker_installed = threading.Event()
    allocator = MemoryAllocator()
    output = tmp_path / "test.bin"

    def thread_body():
        thread_body_entered.set()
        tracker_installed.wait()
        func1()

    def func1():
        allocator.valloc(1234)
        allocator.free()

    # WHEN
    bg_thread = threading.Thread(target=thread_body)
    bg_thread.start()

    thread_body_entered.wait()
    with Tracker(output):
        tracker_installed.set()
        bg_thread.join()

    # THEN
    allocations = list(FileReader(output).get_allocation_records())

    vallocs = [
        event
        for event in allocations
        if event.size == 1234 and event.allocator == AllocatorType.VALLOC
    ]
    assert len(vallocs) == 1

    funcs = [frame[0] for frame in vallocs[0].stack_trace()]
    assert funcs == [
        "valloc",
        "func1",
        "thread_body",
        "run",
        "_bootstrap_inner",
        "_bootstrap",
    ]


def test_allocation_in_thread_before_reacquiring_gil_after_tracking_starts(tmp_path):
    """
    The intended execution flow is:
    Main Thread          Background Thread
    -----------          -----------------
    Start thread
                         Call allocate_without_gil_held
                         release GIL
    Install tracker
                         Perform an allocation for 1234 bytes
                         acquire GIL
                         Perform an allocation for 4321 bytes
                         Exit
    Join thread
    Uninstall tracker
    """
    # GIVEN
    wake_up_main_r, wake_up_main_w = os.pipe()
    wake_up_thread_r, wake_up_thread_w = os.pipe()
    output = tmp_path / "test.bin"

    def thread_body():
        allocate_without_gil_held(wake_up_main_w, wake_up_thread_r)

    # WHEN
    bg_thread = threading.Thread(target=thread_body)
    bg_thread.start()

    os.read(wake_up_main_r, 1)
    with Tracker(output):
        os.write(wake_up_thread_w, b"x")
        bg_thread.join()

    # THEN
    allocations = list(FileReader(output).get_allocation_records())

    vallocs = [
        event for event in allocations if event.allocator == AllocatorType.VALLOC
    ]
    assert len(vallocs) == 2

    funcs1 = [frame[0] for frame in vallocs[0].stack_trace()]
    funcs2 = [frame[0] for frame in vallocs[1].stack_trace()]
    expected = ["thread_body", "run", "_bootstrap_inner", "_bootstrap"]
    assert funcs1 == funcs2 == expected


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


def test_thread_surviving_multiple_trackers_with_changing_callstack(tmp_path):
    """Test the call stack of a thread changing between two tracking sessions.

    The intended execution flow is:
    Main Thread          Background Thread
    -----------          -----------------
    Install tracker
    Start thread
                         Call thread_body
                         Call func1
                         Perform an allocation
    Uninstall tracker
                         Return from func1
    Install new tracker
                         Call func2
                         Perform an allocation
                         Return from func2
                         Return from thread_body
    Uninstall tracker

    We use a bunch of events to force this order.
    """
    # GIVEN
    allocation_performed_in_func1 = threading.Event()
    tracker_uninstalled = threading.Event()
    returned_from_func1 = threading.Event()
    new_tracker_installed = threading.Event()

    allocator = MemoryAllocator()
    output1 = tmp_path / "test.bin.1"
    output2 = tmp_path / "test.bin.2"

    def thread_body():
        func1()
        returned_from_func1.set()
        new_tracker_installed.wait()
        func2()

    def func1():
        allocator.valloc(1234)
        allocator.free()
        allocation_performed_in_func1.set()
        tracker_uninstalled.wait()

    def func2():
        allocator.valloc(1234)
        allocator.free()

    # WHEN
    with Tracker(output1):
        bg_thread = threading.Thread(target=thread_body)
        bg_thread.start()
        allocation_performed_in_func1.wait()

    tracker_uninstalled.set()
    returned_from_func1.wait()

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

    tracker1_funcs = [frame[0] for frame in tracker1_vallocs[0].stack_trace()]
    tracker2_funcs = [frame[0] for frame in tracker2_vallocs[0].stack_trace()]

    common_frames = ["thread_body", "run", "_bootstrap_inner", "_bootstrap"]
    assert tracker1_funcs == ["valloc", "func1"] + common_frames
    assert tracker2_funcs == ["valloc", "func2"] + common_frames


def test_cython_frame_in_pre_existing_thread_stack(tmp_path):
    """Test starting tracking when another thread's stack has Cython frames.

    The intended execution flow is:
    Main Thread          Background Thread
    -----------          -----------------
    Start thread
                         Call thread_body
                         Call function_caller (Cython frame)
                         Call func1
    Install new tracker
                         Perform an allocation
                         Return from func1
                         Return from function_caller
                         Perform an allocation
                         Return from thread_body
    Join thread
    Uninstall tracker
    """
    # GIVEN
    ready_to_install_tracker = threading.Event()
    tracker_installed = threading.Event()

    allocator = MemoryAllocator()
    output = tmp_path / "test.bin"

    def thread_body():
        function_caller(func1)
        allocator.valloc(1234)
        allocator.free()

    def func1():
        ready_to_install_tracker.set()
        tracker_installed.wait()
        allocator.valloc(1234)
        allocator.free()

    # WHEN
    thread = threading.Thread(target=thread_body)
    thread.start()
    ready_to_install_tracker.wait()

    with Tracker(output):
        tracker_installed.set()
        thread.join()

    # THEN
    allocations = list(FileReader(output).get_allocation_records())

    vallocs = [
        event
        for event in allocations
        if event.size == 1234 and event.allocator == AllocatorType.VALLOC
    ]
    assert len(vallocs) == 2

    first, second = vallocs
    alloc1_funcs = [frame[0] for frame in first.stack_trace()]
    alloc2_funcs = [frame[0] for frame in second.stack_trace()]

    # Cython frames called before tracking started aren't in the Python stack.
    assert alloc1_funcs[:3] == ["valloc", "func1", "thread_body"]
    assert alloc2_funcs[:2] == ["valloc", "thread_body"]


def test_cython_frame_in_pre_existing_thread_stack_when_restarting_tracking(tmp_path):
    """Test restarting tracking when another thread's stack has Cython frames.

    The intended execution flow is:
    Main Thread          Background Thread
    -----------          -----------------
    Install tracker
    Start thread
                         Call thread_body
                         Call function_caller (Cython frame)
                         Call func1
    Uninstall tracker
    Install new tracker
                         Perform an allocation
                         Return from func1
                         Return from function_caller
                         Perform an allocation
                         Return from thread_body
    Join thread
    Uninstall tracker
    """
    # GIVEN
    ready_to_replace_tracker = threading.Event()
    tracker_replaced = threading.Event()

    allocator = MemoryAllocator()
    output1 = tmp_path / "test.bin.1"
    output2 = tmp_path / "test.bin.2"

    def thread_body():
        function_caller(func1)
        allocator.valloc(1234)
        allocator.free()

    def func1():
        ready_to_replace_tracker.set()
        tracker_replaced.wait()
        allocator.valloc(1234)
        allocator.free()

    # WHEN
    with Tracker(output1):
        thread = threading.Thread(target=thread_body)
        thread.start()
        ready_to_replace_tracker.wait()

    with Tracker(output2):
        tracker_replaced.set()
        thread.join()

    # THEN
    allocations = list(FileReader(output2).get_allocation_records())

    vallocs = [
        event
        for event in allocations
        if event.size == 1234 and event.allocator == AllocatorType.VALLOC
    ]
    assert len(vallocs) == 2

    first, second = vallocs
    alloc1_funcs = [frame[0] for frame in first.stack_trace()]
    alloc2_funcs = [frame[0] for frame in second.stack_trace()]

    # Cython frames called before tracking started aren't in the Python stack.
    assert alloc1_funcs[:3] == ["valloc", "func1", "thread_body"]

    # But we do get pop events for them if tracking was enabled when they were
    # pushed. Ensure we handle these unexpected pops.
    assert alloc2_funcs[:2] == ["valloc", "thread_body"]


def test_allocation_after_unsetting_profile_function(tmp_path):
    """After tracking starts, unset the profile function then allocate.

    Make sure that the stack for the allocation is unknown.
    """
    # GIVEN
    allocator = MemoryAllocator()
    output = tmp_path / "test.bin"

    def func():
        allocator.valloc(1234)
        allocator.free()
        sys.setprofile(None)
        allocator.valloc(1234)
        allocator.free()

    # WHEN
    with Tracker(output):
        func()

    # THEN
    allocations = list(FileReader(output).get_allocation_records())

    vallocs = [
        event
        for event in allocations
        if event.size == 1234 and event.allocator == AllocatorType.VALLOC
    ]
    assert len(vallocs) == 2

    first, second = vallocs
    alloc1_funcs = [frame[0] for frame in first.stack_trace()]
    alloc2_funcs = [frame[0] for frame in second.stack_trace()]

    assert alloc1_funcs == [
        "valloc",
        "func",
        "test_allocation_after_unsetting_profile_function",
    ]
    assert alloc2_funcs == []


def test_allocation_in_thread_after_unsetting_profile_function(tmp_path):
    """In a thread, unset the profile function then allocate.

    Make sure that the stack for the allocation is unknown.
    """
    # GIVEN
    allocator = MemoryAllocator()
    output = tmp_path / "test.bin"

    def func():
        allocator.valloc(1234)
        allocator.free()
        sys.setprofile(None)
        allocator.valloc(1234)
        allocator.free()

    # WHEN
    with Tracker(output):
        thread = threading.Thread(target=func)
        thread.start()
        thread.join()

    # THEN
    allocations = list(FileReader(output).get_allocation_records())

    vallocs = [
        event
        for event in allocations
        if event.size == 1234 and event.allocator == AllocatorType.VALLOC
    ]
    assert len(vallocs) == 2

    first, second = vallocs
    alloc1_funcs = [frame[0] for frame in first.stack_trace()]
    alloc2_funcs = [frame[0] for frame in second.stack_trace()]

    assert alloc1_funcs[:2] == ["valloc", "func"]
    assert alloc2_funcs == []


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

        munmap_record = next(
            (record for record in records if AllocatorType.MUNMAP == record.allocator),
            None,
        )
        assert munmap_record is not None
        with pytest.raises(NotImplementedError):
            munmap_record.stack_trace()

    @pytest.mark.valgrind
    def test_mmap_in_thread(self, tmpdir):
        # GIVEN / WHEN
        output = Path(tmpdir) / "test.bin"

        def custom_trace_fn():  # pragma: no cover
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

        munmap_record = next(
            (record for record in records if AllocatorType.MUNMAP == record.allocator),
            None,
        )
        assert munmap_record is not None
        with pytest.raises(NotImplementedError):
            munmap_record.stack_trace()
