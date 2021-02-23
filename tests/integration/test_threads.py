import threading
from pathlib import Path

from bloomberg.pensieve import AllocatorType
from bloomberg.pensieve import Tracker
from bloomberg.pensieve._test import MemoryAllocator
from tests.utils import filter_relevant_allocations


def allocating_function(allocator, event):
    allocator.valloc(1234)
    allocator.free()
    event.wait()
    allocator.valloc(1234)
    allocator.free()


def test_thread_allocations_after_tracker_is_deactivated(tmpdir):
    # GIVEN / WHEN
    output = Path(tmpdir) / "test.bin"
    event = threading.Event()
    allocator = MemoryAllocator()

    with Tracker(output) as tracker:
        t = threading.Thread(target=allocating_function, args=(allocator, event))
        t.start()

    # Keep allocating in the same thread while the tracker is not active
    event.set()
    t.join()

    # THEN
    relevant_records = list(
        filter_relevant_allocations(tracker.get_allocation_records())
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
