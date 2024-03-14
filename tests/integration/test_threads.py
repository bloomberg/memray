import threading
from pathlib import Path

from memray import AllocatorType
from memray import FileReader
from memray import Tracker
from memray._test import MemoryAllocator
from memray._test import set_thread_name
from tests.utils import filter_relevant_allocations
from tests.utils import skip_if_macos

HERE = Path(__file__).parent
TEST_MULTITHREADED_EXTENSION = HERE / "multithreaded_extension"


def allocating_function(allocator, flag_event, wait_event):
    allocator.valloc(1234)
    allocator.free()
    flag_event.set()
    wait_event.wait()
    allocator.valloc(1234)
    allocator.free()


def test_thread_allocations_after_tracker_is_deactivated(tmpdir):
    # GIVEN
    output = Path(tmpdir) / "test.bin"
    wait_event = threading.Event()
    flag_event = threading.Event()
    allocator = MemoryAllocator()

    # WHEN
    with Tracker(output):
        t = threading.Thread(
            target=allocating_function, args=(allocator, flag_event, wait_event)
        )
        t.start()
        flag_event.wait()

    # Keep allocating in the same thread while the tracker is not active
    wait_event.set()
    t.join()

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


@skip_if_macos
def test_thread_name(tmpdir):
    # GIVEN
    output = Path(tmpdir) / "test.bin"
    allocator = MemoryAllocator()

    def allocating_function():
        set_thread_name("my thread name")
        allocator.valloc(1234)
        allocator.free()

    # WHEN
    with Tracker(output):
        t = threading.Thread(target=allocating_function)
        t.start()
        t.join()

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
    assert "my thread name" == valloc.thread_name


def test_setting_python_thread_name(tmpdir):
    # GIVEN
    output = Path(tmpdir) / "test.bin"
    allocator = MemoryAllocator()
    name_set_inside_thread = threading.Event()
    name_set_outside_thread = threading.Event()
    prctl_rc = -1

    def allocating_function():
        allocator.valloc(1234)
        allocator.free()

        threading.current_thread().name = "set inside thread"
        allocator.valloc(1234)
        allocator.free()

        name_set_inside_thread.set()
        name_set_outside_thread.wait()
        allocator.valloc(1234)
        allocator.free()

        nonlocal prctl_rc
        prctl_rc = set_thread_name("set by prctl")
        allocator.valloc(1234)
        allocator.free()

    # WHEN
    with Tracker(output):
        t = threading.Thread(target=allocating_function, name="set before start")
        t.start()
        name_set_inside_thread.wait()
        t.name = "set outside running thread"
        name_set_outside_thread.set()
        t.join()

    # THEN
    expected_names = [
        "set before start",
        "set inside thread",
        "set outside running thread",
        "set by prctl" if prctl_rc == 0 else "set outside running thread",
    ]
    names = [
        rec.thread_name
        for rec in FileReader(output).get_allocation_records()
        if rec.allocator == AllocatorType.VALLOC
    ]
    assert names == expected_names
