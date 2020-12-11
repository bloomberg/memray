import sys
from pathlib import Path

from bloomberg.pensieve import Tracker
from bloomberg.pensieve._test import MemoryAllocator


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
        with Tracker(output) as tracker:
            allocator.valloc(1234)
            allocator.free()
        return tracker.get_allocation_records()

    # WHEN

    records = foo()

    # THEN

    allocs = [record for record in records if record["allocator"] == "valloc"]
    assert len(allocs) == 1
    (alloc,) = allocs
    traceback = [frame["function_name"] for frame in alloc["stack_trace"]]
    assert traceback[-3:] == [
        "test_initial_tracking_frames_are_correctly_populated",
        "foo",
        "valloc",
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
        with Tracker(output) as tracker:
            foo()
        return tracker.get_allocation_records()

    # Do another *independent* round of tracking. The previous frames
    # should not interfere with this tracing.
    records = bar()

    # THEN

    allocs = [record for record in records if record["allocator"] == "valloc"]
    assert len(allocs) == 1
    (alloc,) = allocs
    traceback = [frame["function_name"] for frame in alloc["stack_trace"]]
    assert traceback[-4:] == [
        "test_restart_tracing_function_gets_correctly_the_frames",
        "bar",
        "foo",
        "valloc",
    ]
