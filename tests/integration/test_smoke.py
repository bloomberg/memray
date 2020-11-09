import mmap
import threading

from bloomberg.pensieve import get_allocation_records
from bloomberg.pensieve import start_thread_trace
from bloomberg.pensieve import tracker


def allocating_function():
    with mmap.mmap(-1, length=2048, access=mmap.ACCESS_WRITE) as mmap_obj:
        mmap_obj[0:100] = b"a" * 100


def test_smoke():
    # GIVEN / WHEN
    with tracker():
        allocating_function()

    # THEN
    records = get_allocation_records()

    assert len(records) >= 2

    mmap_record = next(
        (record for record in records if "mmap" in record["allocator"]), None
    )
    assert mmap_record is not None
    assert "allocating_function" in {
        element["function_name"] for element in mmap_record["stacktrace"]
    }

    mmunmap_record = next(
        (record for record in records if "munmap" in record["allocator"]), None
    )
    assert mmunmap_record is not None
    assert "allocating_function" in {
        element["function_name"] for element in mmunmap_record["stacktrace"]
    }


def test_smoke_in_a_thread():
    # GIVEN / WHEN
    old_profile = threading._profile_hook
    threading.setprofile(start_thread_trace)
    try:
        t = threading.Thread(target=allocating_function)
        t.start()
        t.join()
    finally:
        threading.setprofile(old_profile)

    # THEN
    records = get_allocation_records()

    assert len(records) >= 2

    mmap_record = next(
        (record for record in records if "mmap" in record["allocator"]), None
    )
    assert mmap_record is not None
    assert "allocating_function" in {
        element["function_name"] for element in mmap_record["stacktrace"]
    }

    mmunmap_record = next(
        (record for record in records if "munmap" in record["allocator"]), None
    )
    assert mmunmap_record is not None
    assert "allocating_function" in {
        element["function_name"] for element in mmunmap_record["stacktrace"]
    }
