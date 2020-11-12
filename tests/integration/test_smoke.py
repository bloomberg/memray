import mmap
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from bloomberg.pensieve import Tracker
from bloomberg.pensieve import start_thread_trace

HERE = Path(__file__).parent
TEST_MULTITHREADED_EXTENSION = HERE / "multithreaded_extension"


def allocating_function():
    with mmap.mmap(-1, length=2048, access=mmap.ACCESS_WRITE) as mmap_obj:
        mmap_obj[0:100] = b"a" * 100


def test_smoke():
    # GIVEN / WHEN
    with Tracker() as tracker:
        allocating_function()

    # THEN
    records = tracker.get_allocation_records()

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
    tracker = Tracker()
    records = tracker.get_allocation_records()

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


def test_multithreaded_extension(tmpdir, monkeypatch):
    """Test tracking allocations in a native extension which spawns multiple threads,
    each thread allocating and freeing memory."""
    # GIVEN
    extension_name = "multithreaded_extension"
    extension_path = tmpdir / extension_name
    shutil.copytree(TEST_MULTITHREADED_EXTENSION, extension_path)
    subprocess.run(
        [sys.executable, str(extension_path / "setup.py"), "build_ext", "--inplace"],
        check=True,
        cwd=extension_path,
        capture_output=True,
    )

    # WHEN
    with monkeypatch.context() as ctx:
        ctx.setattr(sys, "path", [*sys.path, str(extension_path)])
        from testext import run

        with Tracker() as tracker:
            run()

    # THEN
    records = tracker.get_allocation_records()
    assert records

    vallocs = [record for record in records if record["allocator"] == "valloc"]
    assert len(vallocs) == 100 * 100  # 100 threads allocate 100 times in testext
    vallocs_addr = {record["address"] for record in vallocs}
    valloc_frees = [
        record
        for record in records
        if record["address"] in vallocs_addr and record["allocator"] == "free"
    ]

    assert len(valloc_frees) == 100 * 100
