import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from memray import AllocatorType
from memray import FileReader
from memray import Tracker
from memray._test import MemoryAllocator

HERE = Path(__file__).parent
TEST_MULTITHREADED_EXTENSION = HERE / "multithreaded_extension"
TEST_MISBEHAVING_EXTENSION = HERE / "misbehaving_extension"


@pytest.mark.valgrind
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
        from testext import run  # type: ignore

        with Tracker(output):
            run()

    # THEN
    records = list(FileReader(output).get_allocation_records())
    assert records

    memaligns = [
        record for record in records if record.allocator == AllocatorType.POSIX_MEMALIGN
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
        from misbehaving import call_fn  # type: ignore

        with Tracker(output):
            call_fn(allocating_function)

    # THEN
    allocations = list(FileReader(output).get_allocation_records())
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
    assert line == 81

    frees = [
        event
        for event in allocations
        if event.address == alloc.address and event.allocator == AllocatorType.FREE
    ]
    assert len(frees) >= 1


def test_extension_that_uses_pygilstate_ensure(tmpdir, monkeypatch):
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

    def foo1():
        foo2()

    def foo2():
        call_fn_no_thread(allocating_function)

    # WHEN
    with monkeypatch.context() as ctx:
        ctx.setattr(sys, "path", [*sys.path, str(extension_path)])
        from misbehaving import call_fn_no_thread

        allocator = MemoryAllocator()
        with Tracker(output):
            foo1()
            allocator.valloc(1234)
            allocator.free()

    # THEN
    allocations = list(FileReader(output).get_allocation_records())
    allocs = [
        event
        for event in allocations
        if event.size == 1234 and event.allocator == AllocatorType.VALLOC
    ]
    assert len(allocs) == 2
    (alloc1, alloc2) = allocs

    stack_trace = alloc1.stack_trace()
    assert len(stack_trace)
    first_frame, *_, bottom_frame = stack_trace
    func, filename, line = bottom_frame
    assert func == "test_extension_that_uses_pygilstate_ensure"
    assert filename.endswith(__file__)
    assert line == 152

    # We should have 2 frames here: this function calling `allocator.valloc`,
    # and `allocator.valloc` calling the C `valloc`.
    # We should not see any call to foo1() or foo2().
    stack_trace = alloc2.stack_trace()
    assert len(stack_trace) == 2
    (callee, caller) = stack_trace
    func, filename, line = callee
    assert func == "valloc"
    assert filename.endswith(".pyx")

    func, filename, line = caller
    assert func == "test_extension_that_uses_pygilstate_ensure"
    assert filename.endswith(__file__)
    assert line == 153

    frees = [
        event
        for event in allocations
        if event.address in (alloc1.address, alloc2.address)
        and event.allocator == AllocatorType.FREE
    ]
    assert len(frees) >= 1


def test_native_dlopen(tmpdir, monkeypatch):
    """Check that we can correctly track allocations in an extension which calls
    dlopen() without the GIL held"""
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
        from misbehaving import dlopen_self  # type: ignore

        with Tracker(output):
            dlopen_self(allocating_function)

    # THEN
    allocations = list(FileReader(output).get_allocation_records())
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
    assert func == "test_native_dlopen"
    assert filename.endswith(__file__)
    assert line == 224

    frees = [
        event
        for event in allocations
        if event.address == alloc.address and event.allocator == AllocatorType.FREE
    ]
    assert len(frees) >= 1


@pytest.mark.valgrind
def test_valloc_at_thread_exit(tmpdir, monkeypatch):
    """Test tracking allocations that happen while a thread is shutting down"""
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
        from testext import run_valloc_at_exit  # type: ignore

        with Tracker(output):
            run_valloc_at_exit()

    # THEN
    records = list(FileReader(output).get_allocation_records())
    assert records

    vallocs = [record for record in records if record.allocator == AllocatorType.VALLOC]
    assert len(vallocs) == 1
