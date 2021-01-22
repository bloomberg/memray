import mmap
import threading
from pathlib import Path

import pytest

from bloomberg.pensieve import AllocatorType
from bloomberg.pensieve import Tracker
from bloomberg.pensieve import start_thread_trace


def allocating_function():
    with mmap.mmap(-1, length=2048, access=mmap.ACCESS_WRITE) as mmap_obj:
        mmap_obj[0:100] = b"a" * 100


@pytest.mark.valgrind
def test_smoke(tmpdir):
    # GIVEN / WHEN
    output = Path(tmpdir) / "test.bin"
    with Tracker(output) as tracker:
        allocating_function()

    # THEN
    records = list(tracker.get_allocation_records())

    assert len(records) >= 2

    mmap_record = next(
        (record for record in records if AllocatorType.MMAP == record.allocator), None
    )
    assert mmap_record is not None
    assert "allocating_function" in {
        element[0] for element in mmap_record.stack_trace()
    }

    mmunmap_record = next(
        (record for record in records if AllocatorType.MUNMAP == record.allocator), None
    )
    assert mmunmap_record is not None
    assert "allocating_function" in {
        element[0] for element in mmunmap_record.stack_trace()
    }


@pytest.mark.valgrind
def test_smoke_in_a_thread(tmpdir):
    # GIVEN / WHEN
    output = Path(tmpdir) / "test.bin"
    old_profile = threading._profile_hook
    threading.setprofile(start_thread_trace)
    try:
        t = threading.Thread(target=allocating_function)
        with Tracker(output) as tracker:
            t.start()
            t.join()
    finally:
        threading.setprofile(old_profile)

    # THEN
    records = list(tracker.get_allocation_records())

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
        (record for record in records if AllocatorType.MUNMAP == record.allocator), None
    )
    assert mmunmap_record is not None
    assert "allocating_function" in {
        element[0] for element in mmunmap_record.stack_trace()
    }
