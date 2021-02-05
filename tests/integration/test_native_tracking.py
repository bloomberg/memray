import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from bloomberg.pensieve import AllocatorType
from bloomberg.pensieve import Tracker
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
        from testext import run

        with Tracker(output, native_traces=True) as tracker:
            run()

    # THEN
    records = list(tracker.get_allocation_records())
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
        from native_ext import run_simple

        with Tracker(output, native_traces=True) as tracker:
            run_simple()

    # THEN
    records = list(tracker.get_allocation_records())
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
    records = list(tracker.get_allocation_records())
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
