import inspect
import shutil
import subprocess
import sys
from pathlib import Path

from bloomberg.pensieve import AllocatorType
from bloomberg.pensieve import Tracker
from bloomberg.pensieve._test import MemoryAllocator

HERE = Path(__file__).parent
TEST_MULTITHREADED_EXTENSION = HERE / "multithreaded_extension"


def alloc_func3(allocator):
    x = 1
    allocator.valloc(1234)
    x = 2
    allocator.free()
    x = 3
    return x


def alloc_func2(allocator):
    y = 1
    alloc_func3(allocator)
    y = 2
    return y


def alloc_func1(allocator):
    z = 1
    alloc_func2(allocator)
    z = 2
    return z


def test_traceback(tmpdir):
    # GIVEN
    allocator = MemoryAllocator()
    output = Path(tmpdir) / "test.bin"

    def _get_source_line(function):
        _, lineno = inspect.getsourcelines(function)
        return lineno

    # WHEN

    with Tracker(output) as tracker:
        alloc_func1(allocator)
    records = list(tracker.get_allocation_records())

    # THEN

    allocs = [record for record in records if record.allocator == AllocatorType.VALLOC]
    assert len(allocs) == 1
    (alloc,) = allocs
    traceback = list(alloc.stack_trace())
    assert traceback[-3:] == [
        ("alloc_func3", __file__, _get_source_line(alloc_func3) + 2),
        ("alloc_func2", __file__, _get_source_line(alloc_func2) + 2),
        ("alloc_func1", __file__, _get_source_line(alloc_func1) + 2),
    ]
    frees = [
        record
        for record in records
        if record.allocator == AllocatorType.FREE and record.address == alloc.address
    ]
    assert len(frees) == 1
    (free,) = frees
    traceback = list(free.stack_trace())
    assert traceback[-3:] == [
        ("alloc_func3", __file__, _get_source_line(alloc_func3) + 4),
        ("alloc_func2", __file__, _get_source_line(alloc_func2) + 2),
        ("alloc_func1", __file__, _get_source_line(alloc_func1) + 2),
    ]


def test_traceback_iteration_does_not_depend_on_the_order_of_elements(tmpdir):
    # GIVEN
    allocator = MemoryAllocator()
    output = Path(tmpdir) / "test.bin"

    # WHEN

    with Tracker(output) as tracker:
        alloc_func1(allocator)
        alloc_func1(allocator)

    # THEN

    records = list(tracker.get_allocation_records())
    allocs = [record for record in records if record.allocator == AllocatorType.VALLOC]
    alloc1, alloc2 = allocs
    traceback1 = list(alloc1.stack_trace())
    traceback2 = list(alloc2.stack_trace())

    records = list(tracker.get_allocation_records())
    allocs = [record for record in records if record.allocator == AllocatorType.VALLOC]
    alloc1, alloc2 = allocs
    assert traceback2 == list(alloc2.stack_trace())
    assert traceback1 == list(alloc1.stack_trace())


def test_records_can_be_retrieved_twice(tmpdir):
    # GIVEN
    allocator = MemoryAllocator()
    output = Path(tmpdir) / "test.bin"

    # WHEN

    with Tracker(output) as tracker:
        alloc_func1(allocator)

    # THEN

    records1 = list(tracker.get_allocation_records())
    records2 = list(tracker.get_allocation_records())

    assert records1 == records2


def test_traceback_can_be_retrieved_twice(tmpdir):
    # GIVEN
    allocator = MemoryAllocator()
    output = Path(tmpdir) / "test.bin"

    # WHEN

    with Tracker(output) as tracker:
        alloc_func1(allocator)

    # THEN

    records = list(tracker.get_allocation_records())
    allocs = [record for record in records if record.allocator == AllocatorType.VALLOC]
    (alloc,) = allocs
    traceback1 = list(alloc.stack_trace())
    traceback2 = list(alloc.stack_trace())
    assert traceback1 == traceback2


def test_profile_function_is_restored_after_tracking(tmpdir):
    # GIVEN
    def profilefunc(*args):
        pass

    output = Path(tmpdir) / "test.bin"

    # WHEN

    sys.setprofile(profilefunc)

    with Tracker(output):
        assert sys.getprofile() != profilefunc

    # THEN
    assert sys.getprofile() == profilefunc


def test_initial_tracking_frames_are_correctly_populated(tmpdir):
    # GIVEN
    allocator = MemoryAllocator()
    output = Path(tmpdir) / "test.bin"

    def foo():
        allocator.valloc(1234)
        allocator.free()

    # WHEN

    with Tracker(output) as tracker:
        foo()
    records = list(tracker.get_allocation_records())

    # THEN

    allocs = [record for record in records if record.allocator == AllocatorType.VALLOC]
    assert len(allocs) == 1
    (alloc,) = allocs
    traceback = [frame[0] for frame in alloc.stack_trace()]
    assert traceback[-3:] == [
        "valloc",
        "foo",
    ]


def test_restart_tracing_function_gets_correctly_the_frames(tmpdir):
    # GIVEN
    allocator = MemoryAllocator()
    output = Path(tmpdir) / "test.bin"

    def foo():
        allocator.valloc(1234)
        allocator.free()

    # WHEN

    # Do some prelininary tracing to populate the initial frames
    with Tracker(output):
        foo()

    output.unlink()

    def bar():
        foo()

    # Do another *independent* round of tracking. The previous frames
    # should not interfere with this tracing.
    with Tracker(output) as tracker:
        bar()
    records = list(tracker.get_allocation_records())

    # THEN

    allocs = [record for record in records if record.allocator == AllocatorType.VALLOC]
    assert len(allocs) == 1
    (alloc,) = allocs
    traceback = [frame[0] for frame in alloc.stack_trace()]
    assert traceback[-4:] == [
        "valloc",
        "foo",
        "bar",
    ]


def test_traceback_of_allocations_outside_the_python_vm(tmpdir, monkeypatch):
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
    assert all(not list(record.stack_trace()) for record in memaligns)
