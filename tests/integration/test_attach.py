import functools
import subprocess
import sys

import pytest

from memray import AllocatorType
from memray import FileReader
from memray.commands.attach import debugger_available
from tests.utils import filter_relevant_allocations

PROGRAM = """
import sys
import threading
import time

from memray._test import MemoryAllocator

stop_looping = threading.Event()


def io_thread_body():
    print("ready")
    for line in sys.stdin:
        stop_looping.set()


def alloc_thread_body():
    while not stop_looping.is_set():
        allocator = MemoryAllocator()
        allocator.malloc(1024)
        allocator.free()


def foo():
    bar()


def bar():
    baz()


def baz():
    allocator = MemoryAllocator()
    allocator.valloc(50 * 1024 * 1024)
    allocator.free()


# Debugger attaches wait for allocator or deallocator calls, so we can't just
# block waiting for a signal. Allocate and free in a loop in the background.
# Additionally, there must be a Python loop in the main thread, because that's
# the thread `sys.remote_exec` attaches to and it needs the eval breaker. Spawn
# another background thread to let us know when to stop looping.
io_thread = threading.Thread(target=io_thread_body)
io_thread.start()

alloc_thread = threading.Thread(target=alloc_thread_body)
alloc_thread.start()

while not stop_looping.is_set():
    time.sleep(0.1)

alloc_thread.join()
io_thread.join()

foo()
"""


def generate_attach_command(method, output, *args):
    cmd = [
        sys.executable,
        "-m",
        "memray",
        "attach",
        "--verbose",
        "--force",
        "--method",
        method,
        "-o",
        str(output),
    ]

    if args:
        cmd.extend(args)

    return cmd


def generate_detach_command(method, *args):
    cmd = [
        sys.executable,
        "-m",
        "memray",
        "detach",
        "--verbose",
        "--method",
        method,
    ]

    if args:
        cmd.extend(args)

    return cmd


def run_process(cmd, wait_for_stderr=False):
    process_stderr = ""
    tracked_process = subprocess.Popen(
        [sys.executable, "-uc", PROGRAM],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Help the type checker out...
    assert tracked_process.stdin is not None
    assert tracked_process.stdout is not None

    assert tracked_process.stdout.readline() == "ready\n"

    cmd.append(str(tracked_process.pid))

    # WHEN
    try:
        subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
    except subprocess.CalledProcessError as exc:
        # The test has failed; we'd just wait forever.
        wait_for_stderr = False

        if "Couldn't write extended state status" in exc.output:
            # https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=898048
            pytest.xfail("gdb < 8 does not support this CPU")
        else:
            print(exc.output)
            raise
    finally:
        print("1", file=tracked_process.stdin, flush=True)
        if wait_for_stderr:
            process_stderr = tracked_process.stderr.readline()
            while "WARNING" in process_stderr:
                process_stderr = tracked_process.stderr.readline()
        tracked_process.stdin.close()
        tracked_process.wait()

    # THEN
    assert "" == tracked_process.stdout.read()
    assert tracked_process.returncode == 0
    return process_stderr


def get_call_stack(allocation):
    return [f[0] for f in allocation.stack_trace()]


def get_relevant_vallocs(records):
    return [
        record
        for record in filter_relevant_allocations(records)
        if record.allocator == AllocatorType.VALLOC
    ]


@functools.lru_cache(maxsize=None)
def debugging_method_works(method):
    proc = subprocess.Popen(
        [sys.executable, "-uc", r'input("ready\n")'],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout.readline() == "ready\n"
    try:
        if method == "sys.remote_exec":
            cmd = [
                sys.executable,
                "-uc",
                f"import sys; sys.remote_exec({proc.pid}, '/dev/null')",
            ]
        elif method == "gdb":
            cmd = ["gdb", "-batch", "-p", str(proc.pid)]
        elif method == "lldb":
            cmd = ["lldb", "--batch", "-p", str(proc.pid)]
        else:
            raise ValueError(f"Unknown method: {method}")

        try:
            subprocess.check_call(cmd)
            return True
        except Exception:
            return False
    finally:
        proc.terminate()
        proc.wait()


def skip_if_not_supported(method):
    if not debugger_available(method):
        pytest.skip(f"{method} isn't available")

    if not debugging_method_works(method):
        pytest.skip(f"{method} cannot attach to remote processes on this system")


@pytest.mark.parametrize("method", ["sys.remote_exec", "lldb", "gdb"])
def test_basic_attach(tmp_path, method):
    skip_if_not_supported(method)

    # GIVEN
    output = tmp_path / "test.bin"
    attach_cmd = generate_attach_command(method, output)

    # WHEN
    run_process(attach_cmd)

    # THEN
    reader = FileReader(output)
    (valloc,) = get_relevant_vallocs(reader.get_allocation_records())
    assert get_call_stack(valloc) == ["valloc", "baz", "bar", "foo", "<module>"]


@pytest.mark.parametrize("method", ["sys.remote_exec", "lldb", "gdb"])
def test_aggregated_attach(tmp_path, method):
    skip_if_not_supported(method)

    # GIVEN
    output = tmp_path / "test.bin"
    attach_cmd = generate_attach_command(method, output, "--aggregate")

    # WHEN
    run_process(attach_cmd)

    # THEN
    reader = FileReader(output)
    with pytest.raises(
        NotImplementedError,
        match="Can't get all allocations from a pre-aggregated capture file.",
    ):
        list(reader.get_allocation_records())

    (valloc,) = get_relevant_vallocs(reader.get_high_watermark_allocation_records())
    assert get_call_stack(valloc) == ["valloc", "baz", "bar", "foo", "<module>"]


@pytest.mark.parametrize("method", ["sys.remote_exec", "lldb", "gdb"])
def test_attach_time(tmp_path, method):
    skip_if_not_supported(method)

    # GIVEN
    output = tmp_path / "test.bin"
    attach_cmd = generate_attach_command(method, output, "--duration", "1")

    # WHEN
    process_stderr = run_process(attach_cmd, wait_for_stderr=True)

    # THEN
    assert "memray: Deactivating tracking: 1 seconds have elapsed" in process_stderr


@pytest.mark.parametrize("method", ["sys.remote_exec", "lldb", "gdb"])
def test_detach_without_attach(method):
    skip_if_not_supported(method)

    # GIVEN
    detach_cmd = generate_detach_command(method)

    # WHEN
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        run_process(detach_cmd)

    # THEN
    assert (
        "Failed to stop tracking in remote process:"
        " no previous `memray attach` call detected"
    ) in exc_info.value.stdout
