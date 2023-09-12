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

from memray._test import MemoryAllocator

stop_bg_thread = threading.Event()


def bg_thread_body():
    bg_allocator = MemoryAllocator()
    while not stop_bg_thread.is_set():
        bg_allocator.malloc(1024)
        bg_allocator.free()


def foo():
    bar()


def bar():
    baz()


def baz():
    allocator = MemoryAllocator()
    allocator.valloc(50 * 1024 * 1024)
    allocator.free()


# attach waits for a call to an allocator or deallocator, so we can't just
# block waiting for a signal. Allocate and free in a loop in the background.
bg_thread = threading.Thread(target=bg_thread_body)
bg_thread.start()

print("ready")
for line in sys.stdin:
    if not stop_bg_thread.is_set():
        stop_bg_thread.set()
        bg_thread.join()
    foo()
"""


def generate_command(method, output, aggregate):
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

    if aggregate:
        cmd.append("--aggregate")

    return cmd


def run_process(cmd):
    tracked_process = subprocess.Popen(
        [sys.executable, "-uc", PROGRAM],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
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
        if "Couldn't write extended state status" in exc.output:
            # https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=898048
            pytest.xfail("gdb < 8 does not support this CPU")
        else:
            print(exc.output)
            raise
    finally:
        tracked_process.stdin.write("1\n")
        tracked_process.stdin.close()
        tracked_process.wait()

    # THEN
    assert "" == tracked_process.stdout.read()
    assert tracked_process.returncode == 0


def get_call_stack(allocation):
    return [f[0] for f in allocation.stack_trace()]


def get_relevant_vallocs(records):
    return [
        record
        for record in filter_relevant_allocations(records)
        if record.allocator == AllocatorType.VALLOC
    ]


@pytest.mark.parametrize("method", ["lldb", "gdb"])
def test_basic_attach(tmp_path, method):
    if not debugger_available(method):
        pytest.skip(f"a supported {method} debugger isn't installed")

    # GIVEN
    output = tmp_path / "test.bin"
    attach_cmd = generate_command(method, output, aggregate=False)

    # WHEN
    run_process(attach_cmd)

    # THEN
    reader = FileReader(output)
    (valloc,) = get_relevant_vallocs(reader.get_allocation_records())
    assert get_call_stack(valloc) == ["valloc", "baz", "bar", "foo", "<module>"]


@pytest.mark.parametrize("method", ["lldb", "gdb"])
def test_aggregated_attach(tmp_path, method):
    if not debugger_available(method):
        pytest.skip(f"a supported {method} debugger isn't installed")

    # GIVEN
    output = tmp_path / "test.bin"
    attach_cmd = generate_command(method, output, aggregate=True)

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
