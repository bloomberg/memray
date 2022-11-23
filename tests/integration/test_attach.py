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
    allocator.valloc(1024)
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


@pytest.mark.parametrize("method", ["lldb", "gdb"])
def test_basic_attach(tmp_path, method):
    if not debugger_available(method):
        pytest.skip(f"a supported {method} debugger isn't installed")

    # GIVEN
    output = tmp_path / "test.bin"
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
    attach_cmd = [
        sys.executable,
        "-m",
        "memray",
        "attach",
        "--verbose",
        "--method",
        method,
        "-o",
        str(output),
        str(tracked_process.pid),
    ]

    # WHEN
    try:
        subprocess.check_output(attach_cmd, stderr=subprocess.STDOUT, text=True)
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

    reader = FileReader(output)
    records = list(reader.get_allocation_records())
    vallocs = [
        record
        for record in filter_relevant_allocations(records)
        if record.allocator == AllocatorType.VALLOC
    ]

    (valloc,) = vallocs
    functions = [f[0] for f in valloc.stack_trace()]
    assert functions == ["valloc", "baz", "bar", "foo", "<module>"]
