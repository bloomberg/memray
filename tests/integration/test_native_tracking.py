import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from bloomberg.pensieve import AllocatorType
from bloomberg.pensieve import Tracker
from bloomberg.pensieve._test import MemoryAllocator
from tests.utils import filter_relevant_allocations

HERE = Path(__file__).parent
TEST_MULTITHREADED_EXTENSION = HERE / "multithreaded_extension"
TEST_NATIVE_EXTENSION = HERE / "native_extension"


def test_multithreaded_extension_with_native_tracking(tmpdir, monkeypatch):
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

        with Tracker(output, native_traces=True) as tracker:
            run()

    # THEN
    records = list(tracker.reader.get_allocation_records())
    memaligns = [
        record for record in records if record.allocator == AllocatorType.MEMALIGN
    ]

    assert len(memaligns) == 100 * 100  # 100 threads allocate 100 times in testext
    assert all(len(memalign.stack_trace()) == 0 for memalign in memaligns)
    expected_symbols = ["worker(void*)", "start_thread"]
    assert all(
        expected_symbols == [stack[0] for stack in record.native_stack_trace()][:2]
        for record in memaligns
    )

    memaligns_addr = {record.address for record in memaligns}
    memalign_frees = [
        record
        for record in records
        if record.address in memaligns_addr and record.allocator == AllocatorType.FREE
    ]

    assert len(memalign_frees) >= 100 * 100
    assert all(len(memalign.stack_trace()) == 0 for memalign in memalign_frees)
    assert all(len(record.native_stack_trace()) == 0 for record in memalign_frees)


@pytest.mark.valgrind
def test_simple_call_chain_with_native_tracking(tmpdir, monkeypatch):
    # GIVEN
    output = Path(tmpdir) / "test.bin"
    extension_name = "multithreaded_extension"
    extension_path = tmpdir / extension_name
    shutil.copytree(TEST_NATIVE_EXTENSION, extension_path)
    subprocess.run(
        [sys.executable, str(extension_path / "setup.py"), "build_ext", "--inplace"],
        check=True,
        cwd=extension_path,
        capture_output=True,
    )

    # WHEN
    with monkeypatch.context() as ctx:
        ctx.setattr(sys, "path", [*sys.path, str(extension_path)])
        from native_ext import run_simple  # type: ignore

        with Tracker(output, native_traces=True) as tracker:
            run_simple()

    # THEN
    records = list(tracker.reader.get_allocation_records())
    vallocs = [
        record
        for record in filter_relevant_allocations(records)
        if record.allocator == AllocatorType.VALLOC
    ]

    assert len(vallocs) == 1
    (valloc,) = vallocs

    assert len(valloc.stack_trace()) == 0
    expected_symbols = ["baz", "bar", "foo"]
    assert expected_symbols == [stack[0] for stack in valloc.native_stack_trace()[:3]]


def test_inlined_call_chain_with_native_tracking(tmpdir, monkeypatch):
    # GIVEN
    output = Path(tmpdir) / "test.bin"
    extension_name = "multithreaded_extension"
    extension_path = tmpdir / extension_name
    shutil.copytree(TEST_NATIVE_EXTENSION, extension_path)
    subprocess.run(
        [sys.executable, str(extension_path / "setup.py"), "build_ext", "--inplace"],
        check=True,
        cwd=extension_path,
        capture_output=True,
    )

    # WHEN
    with monkeypatch.context() as ctx:
        ctx.setattr(sys, "path", [*sys.path, str(extension_path)])
        from native_ext import run_inline

        with Tracker(output, native_traces=True) as tracker:
            run_inline()

    # THEN
    records = list(tracker.reader.get_allocation_records())
    vallocs = [
        record
        for record in filter_relevant_allocations(records)
        if record.allocator == AllocatorType.VALLOC
    ]

    assert len(vallocs) == 1
    (valloc,) = vallocs

    assert len(valloc.stack_trace()) == 0
    expected_symbols = ["baz_inline", "bar_inline", "foo_inline"]
    assert expected_symbols == [stack[0] for stack in valloc.native_stack_trace()[:3]]


@pytest.mark.valgrind
def test_deep_call_chain_with_native_tracking(tmpdir, monkeypatch):
    # GIVEN
    output = Path(tmpdir) / "test.bin"
    extension_name = "multithreaded_extension"
    extension_path = tmpdir / extension_name
    shutil.copytree(TEST_NATIVE_EXTENSION, extension_path)
    subprocess.run(
        [sys.executable, str(extension_path / "setup.py"), "build_ext", "--inplace"],
        check=True,
        cwd=extension_path,
        capture_output=True,
    )

    # WHEN
    with monkeypatch.context() as ctx:
        ctx.setattr(sys, "path", [*sys.path, str(extension_path)])
        from native_ext import run_deep

        with Tracker(output, native_traces=True) as tracker:
            run_deep(2048)

    # THEN
    records = list(tracker.reader.get_allocation_records())
    vallocs = [
        record
        for record in filter_relevant_allocations(records)
        if record.allocator == AllocatorType.VALLOC
    ]

    assert len(vallocs) == 1
    (valloc,) = vallocs

    assert len(valloc.stack_trace()) == 0
    expected_symbols = ["baz", "bar", "foo"]
    native_stack = tuple(valloc.native_stack_trace())
    assert len(native_stack) > 2048
    assert expected_symbols == [stack[0] for stack in native_stack[:3]]
    assert all("deep_call" in stack[0] for stack in native_stack[3 : 3 + 2048])


def test_hybrid_stack_in_pure_python(tmpdir):
    # GIVEN
    allocator = MemoryAllocator()
    output = Path(tmpdir) / "test.bin"
    MAX_RECURSIONS = 4

    def recursive_func(n):
        if n == 1:
            return allocator.valloc(1234)
        return recursive_func(n - 1)

    # WHEN

    with Tracker(output, native_traces=True) as tracker:
        recursive_func(MAX_RECURSIONS)

    # THEN
    records = list(tracker.reader.get_allocation_records())
    vallocs = [
        record
        for record in filter_relevant_allocations(records)
        if record.allocator == AllocatorType.VALLOC
    ]

    assert len(vallocs) == 1
    (valloc,) = vallocs

    hybrid_stack = tuple(frame[0] for frame in valloc.hybrid_stack_trace())
    assert hybrid_stack.count("recursive_func") == MAX_RECURSIONS

    # The cython frame of valloc() must not appear in the hybrid stack trace because we
    # already have it in as a native information
    assert (
        hybrid_stack.count("recursive_func")
        == len(valloc.stack_trace()) - 1
        == MAX_RECURSIONS
    )
    assert (
        len(valloc.stack_trace())
        <= len(hybrid_stack)
        <= len(valloc.native_stack_trace())
    )

    # The hybrid stack trace must run until the latest python function seen by the tracker
    assert hybrid_stack[-1] == "recursive_func"


def test_hybrid_stack_in_recursive_python_c_call(tmpdir, monkeypatch):
    # GIVEN
    output = Path(tmpdir) / "test.bin"
    extension_name = "multithreaded_extension"
    extension_path = tmpdir / extension_name
    shutil.copytree(TEST_NATIVE_EXTENSION, extension_path)
    subprocess.run(
        [sys.executable, str(extension_path / "setup.py"), "build_ext", "--inplace"],
        check=True,
        cwd=extension_path,
        capture_output=True,
    )

    MAX_RECURSIONS = 4

    # WHEN
    with monkeypatch.context() as ctx:
        ctx.setattr(sys, "path", [*sys.path, str(extension_path)])
        from native_ext import run_recursive

        def callback(n):
            return run_recursive(n, callback)

        with Tracker(output, native_traces=True) as tracker:
            run_recursive(MAX_RECURSIONS, callback)

    # THEN
    records = list(tracker.reader.get_allocation_records())
    vallocs = [
        record
        for record in filter_relevant_allocations(records)
        if record.allocator == AllocatorType.VALLOC
    ]

    assert len(vallocs) == 1
    (valloc,) = vallocs

    hybrid_stack = tuple(frame[0] for frame in valloc.hybrid_stack_trace())
    assert hybrid_stack.count("callback") == MAX_RECURSIONS
    assert (
        sum(1 if "run_recursive" in elem else 0 for elem in hybrid_stack)
        == MAX_RECURSIONS
    )

    assert hybrid_stack.count("callback") == len(valloc.stack_trace()) == MAX_RECURSIONS
    assert (
        len(valloc.stack_trace())
        <= len(hybrid_stack)
        <= len(valloc.native_stack_trace())
    )

    # The hybrid stack trace must run until the latest python function seen by the tracker
    assert hybrid_stack[-1] == "callback"


def test_hybrid_stack_in_a_thread(tmpdir, monkeypatch):
    # GIVEN
    output = Path(tmpdir) / "test.bin"
    extension_name = "multithreaded_extension"
    extension_path = tmpdir / extension_name
    shutil.copytree(TEST_NATIVE_EXTENSION, extension_path)
    subprocess.run(
        [sys.executable, str(extension_path / "setup.py"), "build_ext", "--inplace"],
        check=True,
        cwd=extension_path,
        capture_output=True,
    )

    # WHEN
    with monkeypatch.context() as ctx:
        ctx.setattr(sys, "path", [*sys.path, str(extension_path)])
        from native_ext import run_simple

        with Tracker(output, native_traces=True) as tracker:
            run_simple()

    # THEN
    records = list(tracker.reader.get_allocation_records())
    vallocs = [
        record
        for record in filter_relevant_allocations(records)
        if record.allocator == AllocatorType.VALLOC
    ]

    assert len(vallocs) == 1
    (valloc,) = vallocs

    assert len(valloc.stack_trace()) == 0
    expected_symbols = ["baz", "bar", "foo"]
    assert expected_symbols == [stack[0] for stack in valloc.hybrid_stack_trace()][:3]


@pytest.mark.parametrize("native_traces", [True, False])
def test_native_tracing_header(native_traces, tmpdir):
    # GIVEN
    allocator = MemoryAllocator()
    output = Path(tmpdir) / "test.bin"

    # WHEN

    with Tracker(output, native_traces=native_traces) as tracker:
        return allocator.valloc(1234)

    # THEN
    assert tracker.reader.has_native_traces is native_traces
