import threading
from pathlib import Path

from memray import AllocatorType
from memray import FileReader
from memray import Tracker
from memray._test import MemoryAllocator
from memray._test import set_thread_name
from tests.utils import filter_relevant_allocations

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
    assert "my thread name" in valloc.thread_name
