import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 13, 3),
    reason="Python object reference tracking requires Python 3.13.3 or later",
)

INTERRUPTED_MESSAGE = (
    "Object lifetime tracking was interrupted because the reference tracer "
    "was replaced or removed"
)


def _exercise_reference_tracer(directory, replacement, delete_object, native_traces):
    import ctypes
    import faulthandler
    import gc
    import resource
    import threading
    import tracemalloc
    import weakref

    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    faulthandler.enable()
    faulthandler.dump_traceback_later(20, exit=True)

    from memray import FileReader
    from memray import Tracker

    # Use CPython's C API directly, never a Python callback entered by the
    # reference tracer while the interpreter is allocating or freeing objects.
    set_tracer = ctypes.pythonapi.PyRefTracer_SetTracer
    set_tracer.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    set_tracer.restype = ctypes.c_int
    get_tracer = ctypes.pythonapi.PyRefTracer_GetTracer
    get_tracer.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
    get_tracer.restype = ctypes.c_void_p

    def tracer_state():
        context = ctypes.c_void_p()
        callback = get_tracer(ctypes.byref(context))
        return callback, context.value

    class TrackedObject:
        pass

    # Keep each subprocess independent of PYTHONTRACEMALLOC settings.
    tracemalloc.stop()
    assert tracer_state() == (None, None)
    original_profile = sys.getprofile()
    original_thread_profile = threading.getprofile()
    output = directory / "interrupted.bin"
    interrupted = replacement != "unchanged"

    try:
        try:
            with Tracker(
                output,
                track_object_lifetimes=True,
                native_traces=native_traces,
            ) as tracker:
                survivor = TrackedObject()
                survivor_address = id(survivor)
                victim = TrackedObject()
                victim_ref = weakref.ref(victim)
                memray_tracer = tracer_state()
                assert memray_tracer[0] is not None

                if replacement in ("remove", "remove_and_restore"):
                    assert set_tracer(None, None) == 0
                    successor = tracer_state()
                    assert successor == (None, None)
                elif replacement == "tracemalloc":
                    tracemalloc.start()
                    successor = tracer_state()
                    assert successor[0] is not None
                    assert successor[0] != memray_tracer[0]

                if delete_object:
                    # The original tracker has retained the raw address. Once
                    # its callback is removed, it cannot observe this death.
                    del victim
                    gc.collect()
                    assert victim_ref() is None

                if replacement == "remove_and_restore":
                    # Ownership at exit looks unchanged, but the destruction
                    # above was missed while the original callback was absent.
                    assert set_tracer(*memray_tracer) == 0
                    assert tracer_state() == memray_tracer
        except RuntimeError as error:
            assert interrupted, f"Normal tracker cleanup raised: {error}"
            assert str(error) == INTERRUPTED_MESSAGE
        else:
            assert not interrupted, (
                "Tracker exit did not report the lost reference tracer"
            )

        # A failing __exit__ must still destroy the native tracker and restore
        # the Python hooks and thread descriptors it installed on entry.
        assert sys.getprofile() is original_profile
        assert threading.getprofile() is original_thread_profile
        assert not hasattr(threading.Thread, "_name")
        assert not hasattr(threading.Thread, "_ident")

        if interrupted:
            assert tracer_state() == successor
            with pytest.raises(RuntimeError):
                tracker.get_surviving_objects()
        else:
            assert tracer_state() == (None, None)
            assert any(obj is survivor for obj in tracker.get_surviving_objects())

        if replacement == "tracemalloc":
            assert tracemalloc.is_tracing()
            allocated_after_exit = bytearray(4096)
            assert tracemalloc.get_object_traceback(allocated_after_exit) is not None

        with FileReader(output) as reader:
            events = list(reader.get_object_lifetime_events())
        assert any(
            event.is_created and event.address == survivor_address for event in events
        )
        assert all(event.address != 0 for event in events)
    finally:
        tracemalloc.stop()

    # Prove cleanup released the process-wide tracker slot and left subsequent
    # lifetime tracking usable, including after stopping a native successor.
    assert tracer_state() == (None, None)
    with Tracker(
        directory / "subsequent.bin",
        track_object_lifetimes=True,
        native_traces=native_traces,
    ) as subsequent_tracker:
        subsequent_survivor = TrackedObject()
    assert any(
        obj is subsequent_survivor for obj in subsequent_tracker.get_surviving_objects()
    )
    assert tracer_state() == (None, None)
    faulthandler.cancel_dump_traceback_later()


def _run_scenario(tmp_path, replacement, delete_object, native_traces):
    completed = subprocess.run(
        [
            sys.executable,
            "-X",
            "faulthandler",
            str(Path(__file__).resolve()),
            str(tmp_path),
            replacement,
            str(int(delete_object)),
            str(int(native_traces)),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, (
        f"Reference-tracer subprocess exited with {completed.returncode}\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )


@pytest.mark.parametrize("native_traces", [False, True])
@pytest.mark.parametrize("delete_object", [False, True], ids=["alive", "deleted"])
@pytest.mark.parametrize(
    "replacement",
    [
        "remove",
        pytest.param(
            "tracemalloc",
            marks=pytest.mark.skipif(
                sys.version_info < (3, 15),
                reason="tracemalloc uses the reference tracer starting in Python 3.15",
            ),
        ),
    ],
)
def test_replacing_reference_tracer_reports_interruption(
    tmp_path, replacement, delete_object, native_traces
):
    _run_scenario(tmp_path, replacement, delete_object, native_traces)


@pytest.mark.skipif(
    sys.version_info < (3, 15),
    reason="Reference tracer removal notifications require Python 3.15",
)
def test_restoring_removed_reference_tracer_still_reports_interruption(tmp_path):
    _run_scenario(tmp_path, "remove_and_restore", True, False)


@pytest.mark.parametrize("native_traces", [False, True])
def test_reference_tracer_normal_cleanup_does_not_report_interruption(
    tmp_path, native_traces
):
    _run_scenario(tmp_path, "unchanged", True, native_traces)


if __name__ == "__main__":
    _exercise_reference_tracer(
        Path(sys.argv[1]), sys.argv[2], bool(int(sys.argv[3])), bool(int(sys.argv[4]))
    )
