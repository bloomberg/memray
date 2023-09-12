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


def compare_allocations(allocations1, allocations2):
    assert len(allocations1) == len(allocations2)
    for i in range(0, len(allocations1)):
        assert allocations1[i].allocator == allocations2[i].allocator
        assert allocations1[i].n_allocations == allocations2[i].n_allocations
        assert allocations1[i].size == allocations2[i].size
        assert allocations1[i].stack_id == allocations2[i].stack_id
        assert allocations1[i].tid == allocations2[i].tid
        assert allocations1[i].native_stack_id == allocations2[i].native_stack_id
        assert (
            allocations1[i].native_segment_generation
            == allocations2[i].native_segment_generation
        )
        assert allocations1[i].thread_name == allocations2[i].thread_name


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


def get_functions(allocations):
    (valloc,) = allocations
    return [f[0] for f in valloc.stack_trace()]


def get_relevant_allocations(records):
    return [
        record
        for record in filter_relevant_allocations(records)
        if record.allocator == AllocatorType.VALLOC
    ]


@pytest.mark.parametrize("method", ["lldb", "gdb"])
@pytest.mark.parametrize("aggregate", [True, False])
def test_basic_attach(tmp_path, method, aggregate):
    if not debugger_available(method):
        pytest.skip(f"a supported {method} debugger isn't installed")

    # GIVEN
    output = tmp_path / "test.bin"

    attach_cmd = generate_command(method, output, aggregate)

    run_process(attach_cmd)

    reader = FileReader(output)

    # WHEN
    try:
        hwa_allocation_records = list(reader.get_high_watermark_allocation_records())
        assert hwa_allocation_records is not None
        allocation_records = list(reader.get_allocation_records())
    except NotImplementedError as exc:
        if aggregate:
            assert (
                "Can't get all allocations from a pre-aggregated capture file."
                in str(exc)
            )

    hwa_relevant_allocations_records = get_relevant_allocations(hwa_allocation_records)
    relevant_allocations_records = (
        get_relevant_allocations(allocation_records) if not aggregate else []
    )

    if not aggregate:
        assert get_functions(hwa_relevant_allocations_records) == get_functions(
            relevant_allocations_records
        )
    else:
        output_no_aggregate = tmp_path / "test.bin"
        attach_cmd = generate_command(method, output_no_aggregate, False)
        run_process(attach_cmd)

        reader = FileReader(output_no_aggregate)
        allocation_records = list(reader.get_high_watermark_allocation_records())
        relevant_allocations_records = get_relevant_allocations(allocation_records)

        compare_allocations(
            relevant_allocations_records, hwa_relevant_allocations_records
        )
