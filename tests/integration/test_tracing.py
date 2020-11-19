import sys

from bloomberg.pensieve import Tracker
from bloomberg.pensieve._test import MemoryAllocator


def test_profile_function_is_restored_after_tracking():
    # GIVEN
    def profilefunc(*args):
        pass

    # WHEN

    sys.setprofile(profilefunc)

    with Tracker():
        assert sys.getprofile() != profilefunc

    # THEN
    assert sys.getprofile() == profilefunc


def test_initial_tracking_frames_are_correctly_populated():
    # GIVEN
    allocator = MemoryAllocator()

    def foo():
        with Tracker() as tracker:
            allocator.valloc(1234)
            allocator.free()
        return tracker.get_allocation_records()

    # WHEN

    records = foo()

    # THEN

    allocs = [record for record in records if record["allocator"] == "valloc"]
    assert len(allocs) == 1
    (alloc,) = allocs
    traceback = [frame["function_name"] for frame in alloc["stacktrace"]]
    assert traceback[-3:] == [
        "test_initial_tracking_frames_are_correctly_populated",
        "foo",
        "valloc",
    ]


def test_restart_tracing_function_gets_correctly_the_frames():
    # GIVEN
    allocator = MemoryAllocator()

    def foo():
        allocator.valloc(1234)
        allocator.free()

    # WHEN

    # Do some prelininary tracing to populate the initial frames
    with Tracker():
        foo()

    def bar():
        with Tracker() as tracker:
            foo()
        return tracker.get_allocation_records()

    # Do another *independent* round of tracking. The previous frames
    # should not interfere with this tracing.
    records = bar()

    # THEN

    allocs = [record for record in records if record["allocator"] == "valloc"]
    assert len(allocs) == 1
    (alloc,) = allocs
    traceback = [frame["function_name"] for frame in alloc["stacktrace"]]
    assert traceback[-4:] == [
        "test_restart_tracing_function_gets_correctly_the_frames",
        "bar",
        "foo",
        "valloc",
    ]
