import shutil
import subprocess
import sys
from pathlib import Path

from bloomberg.pensieve import AllocatorType
from bloomberg.pensieve import Tracker
from bloomberg.pensieve._test import MemoryAllocator

HERE = Path(__file__).parent
TEST_MULTITHREADED_EXTENSION = HERE / "multithreaded_extension"
TEST_MISBEHAVING_EXTENSION = HERE / "misbehaving_extension"


def test_multithreaded_extension(tmpdir, monkeypatch):
    """Test tracking allocations in a native extension which spawns multiple threads,
    each thread allocating and freeing memory."""
    # GIVEN
    output = Path(tmpdir) / "test.bin"
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

        with Tracker(output) as tracker:
            run()

    # THEN
    records = list(tracker.get_allocation_records())
    assert records

    memaligns = [
        record for record in records if record.allocator == AllocatorType.MEMALIGN
    ]
    assert len(memaligns) == 100 * 100  # 100 threads allocate 100 times in testext

    # We don't keep track of the native stacks. Make sure they are empty
    assert all(len(memalign.stack_trace()) == 0 for memalign in memaligns)

    memaligns_addr = {record.address for record in memaligns}
    memalign_frees = [
        record
        for record in records
        if record.address in memaligns_addr and record.allocator == AllocatorType.FREE
    ]

    assert len(memalign_frees) >= 100 * 100


def test_misbehaving_extension(tmpdir, monkeypatch):
    """Check that we can correctly track allocations in an extension which invokes
    Python code in a thread and does not register trace functions."""
    # GIVEN
    output = Path(tmpdir) / "test.bin"
    extension_name = "misbehaving_extension"
    extension_path = tmpdir / extension_name
    shutil.copytree(TEST_MISBEHAVING_EXTENSION, extension_path)
    subprocess.run(
        [sys.executable, str(extension_path / "setup.py"), "build_ext", "--inplace"],
        check=True,
        cwd=extension_path,
        capture_output=True,
    )

    def allocating_function():
        allocator = MemoryAllocator()
        allocator.valloc(1234)
        allocator.free()

    # WHEN
    with monkeypatch.context() as ctx:
        ctx.setattr(sys, "path", [*sys.path, str(extension_path)])
        from misbehaving import call_fn

        with Tracker(output) as tracker:
            call_fn(allocating_function)

    # THEN
    allocations = list(tracker.get_allocation_records())
    allocs = [
        event
        for event in allocations
        if event.size == 1234 and event.allocator == AllocatorType.VALLOC
    ]
    assert len(allocs) == 1
    (alloc,) = allocs

    stack_trace = alloc.stack_trace()
    assert len(stack_trace)

    *_, bottom_frame = stack_trace
    func, filename, line = bottom_frame
    assert func == "allocating_function"
    assert filename.endswith(__file__)
    assert line == 77

    frees = [
        event
        for event in allocations
        if event.address == alloc.address and event.allocator == AllocatorType.FREE
    ]
    assert len(frees) >= 1
