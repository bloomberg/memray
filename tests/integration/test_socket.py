"""Tests to exercise socket-based read and write operations in the Tracker."""

import os
import subprocess
import sys
import textwrap
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from typing import Set
from typing import Tuple

import pytest

from memray import AllocatorType
from memray import SocketReader
from tests.utils import filter_relevant_allocations

TIMEOUT = 5
ALLOCATION_SIZE = 1234
MULTI_ALLOCATION_COUNT = 10

#
# Test helpers
#
_SCRIPT_TEMPLATE = """
import sys
from memray._test import MemoryAllocator
from memray._memray import SocketDestination
from memray._memray import Tracker

# Sanity checks
port = int(sys.argv[1])
assert sys.argv[2].endswith("allocations_made.event")
assert sys.argv[3].endswith("snapshot_taken.event")


def get_tracker():
    return Tracker(destination=SocketDestination(server_port=port))


def snapshot_point():
    print("[child] Notifying allocations made")
    with open(sys.argv[2], "w") as allocations_made:
        allocations_made.write("done")
    print("[child] Waiting on snapshot taken")
    with open(sys.argv[3], "r") as snapshot_taken:
        response = snapshot_taken.read()
    assert response == "done"
    print("[child] Continuing execution")

{body}
"""

ALLOCATE_THEN_FREE_THEN_SNAPSHOT = textwrap.dedent(
    f"""
        allocator = MemoryAllocator()

        with get_tracker():
            allocator.valloc({ALLOCATION_SIZE})
            allocator.free()
            snapshot_point()
    """
)
ALLOCATE_THEN_SNAPSHOT_THEN_FREE = textwrap.dedent(
    f"""
        allocator = MemoryAllocator()
        with get_tracker():
            allocator.valloc({ALLOCATION_SIZE})
            snapshot_point()
            allocator.free()
    """
)
ALLOCATE_MANY_THEN_SNAPSHOT_THEN_FREE_MANY = textwrap.dedent(
    f"""
        allocators = [MemoryAllocator() for _ in range({MULTI_ALLOCATION_COUNT})]
        with get_tracker():
            for allocator in allocators:
                allocator.valloc({ALLOCATION_SIZE})
            snapshot_point()
            for allocator in allocators:
                allocator.free()
    """
)


@contextmanager
def run_till_snapshot_point(
    program: str,
    *,
    reader: SocketReader,
    tmp_path: Path,
    free_port: int,
) -> Iterator[None]:
    allocations_made = tmp_path / "allocations_made.event"
    snapshot_taken = tmp_path / "snapshot_taken.event"
    os.mkfifo(allocations_made)
    os.mkfifo(snapshot_taken)

    script = _SCRIPT_TEMPLATE.format(body=program)

    env = os.environ.copy()
    env.pop("PYTHONMALLOC", None)
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            script,
            str(free_port),
            allocations_made,
            snapshot_taken,
        ],
        env=env,
    )

    try:
        with reader:
            print("[parent] Waiting on allocations made")
            with open(allocations_made, "r") as f1:
                assert f1.read() == "done"

            print("[parent] Deferring to caller")
            # Wait a bit of time, for background thread to receive + process the records.
            time.sleep(0.1)
            yield

            print("[parent] Notifying program to continue")
            with open(snapshot_taken, "w") as f2:
                f2.write("done")
            print("[parent] Will close socket reader now.")
    finally:
        print("[parent] Waiting on child to exit.")
        try:
            assert proc.wait(timeout=TIMEOUT) == 0
        except subprocess.TimeoutExpired:
            print("[parent] Killing child, after timeout.")
            proc.kill()
            raise


#
# Actual tests
#
class TestSocketReaderErrorHandling:
    @pytest.mark.valgrind
    def test_get_current_snapshot_raises_before_context(self, free_port: int) -> None:
        # GIVEN
        reader = SocketReader(port=free_port)

        # WHEN / THEN
        with pytest.raises(StopIteration):
            next(reader.get_current_snapshot(merge_threads=False))

    def test_get_is_active_after_context(self, free_port: int, tmp_path: Path) -> None:
        # GIVEN
        reader = SocketReader(port=free_port)
        program = ALLOCATE_THEN_SNAPSHOT_THEN_FREE

        # WHEN
        with run_till_snapshot_point(
            program,
            reader=reader,
            tmp_path=tmp_path,
            free_port=free_port,
        ):
            pass

        # THEN
        assert reader.is_active is False

    @pytest.mark.valgrind
    def test_get_current_snapshot_raises_after_context(
        self, free_port: int, tmp_path: Path
    ) -> None:
        # GIVEN
        reader = SocketReader(port=free_port)
        program = ALLOCATE_THEN_SNAPSHOT_THEN_FREE

        # WHEN
        with run_till_snapshot_point(
            program,
            reader=reader,
            tmp_path=tmp_path,
            free_port=free_port,
        ):
            pass

        # THEN
        with pytest.raises(StopIteration):
            next(reader.get_current_snapshot(merge_threads=False))

    @pytest.mark.valgrind
    def test_get_current_snapshot_first_yield_after_context_raises(
        self, free_port: int, tmp_path: Path
    ) -> None:
        # GIVEN
        reader = SocketReader(port=free_port)
        program = ALLOCATE_THEN_SNAPSHOT_THEN_FREE

        # WHEN
        with run_till_snapshot_point(
            program,
            reader=reader,
            tmp_path=tmp_path,
            free_port=free_port,
        ):
            snapshot = reader.get_current_snapshot(merge_threads=False)

        # THEN
        with pytest.raises(StopIteration):
            next(snapshot)

    @pytest.mark.valgrind
    def test_nested_context_is_diallowed(self, free_port: int, tmp_path: Path) -> None:
        # GIVEN
        reader = SocketReader(port=free_port)
        program = ALLOCATE_THEN_FREE_THEN_SNAPSHOT

        # WHEN
        with run_till_snapshot_point(
            program,
            reader=reader,
            tmp_path=tmp_path,
            free_port=free_port,
        ):
            # THEN
            with pytest.raises(
                ValueError, match="Can not enter (.*)context (.*)more than once"
            ):
                with reader:
                    pass


class TestSocketReaderAccess:
    @pytest.mark.valgrind
    def test_empty_snapshot_after_free(self, free_port: int, tmp_path: Path) -> None:
        # GIVEN
        reader = SocketReader(port=free_port)
        program = ALLOCATE_THEN_FREE_THEN_SNAPSHOT

        # WHEN
        with run_till_snapshot_point(
            program,
            reader=reader,
            tmp_path=tmp_path,
            free_port=free_port,
        ):
            unfiltered_snapshot = list(reader.get_current_snapshot(merge_threads=False))

        # THEN
        snapshot = list(filter_relevant_allocations(unfiltered_snapshot))
        assert snapshot == []

    @pytest.mark.valgrind
    def test_single_allocation_snapshot(self, free_port: int, tmp_path: Path) -> None:
        # GIVEN
        reader = SocketReader(port=free_port)
        program = ALLOCATE_THEN_SNAPSHOT_THEN_FREE

        # WHEN
        with run_till_snapshot_point(
            program,
            reader=reader,
            tmp_path=tmp_path,
            free_port=free_port,
        ):
            unfiltered_snapshot = list(reader.get_current_snapshot(merge_threads=False))

        # THEN
        snapshot = list(filter_relevant_allocations(unfiltered_snapshot))
        assert len(snapshot) == 1

        allocation = snapshot[0]
        assert allocation.size == ALLOCATION_SIZE * 1
        assert allocation.allocator == AllocatorType.VALLOC

        symbol, filename, lineno = allocation.stack_trace()[0]
        assert symbol == "valloc"
        assert filename.endswith("/_test.py")
        assert 0 < lineno < 200

    @pytest.mark.valgrind
    def test_multi_allocation_snapshot(self, free_port: int, tmp_path: Path) -> None:
        # GIVEN
        reader = SocketReader(port=free_port)
        program = ALLOCATE_MANY_THEN_SNAPSHOT_THEN_FREE_MANY

        # WHEN
        with run_till_snapshot_point(
            program,
            reader=reader,
            tmp_path=tmp_path,
            free_port=free_port,
        ):
            unfiltered_snapshot = list(reader.get_current_snapshot(merge_threads=False))

        # THEN
        snapshot = list(filter_relevant_allocations(unfiltered_snapshot))
        assert len(snapshot) == 1

        allocation = snapshot[0]
        assert allocation.size == ALLOCATION_SIZE * 10
        assert allocation.allocator == AllocatorType.VALLOC

        symbol, filename, lineno = allocation.stack_trace()[0]
        assert symbol == "valloc"
        assert filename.endswith("/_test.py")
        assert 0 < lineno < 200

    @pytest.mark.valgrind
    def test_multiple_context_entries_does_not_crash(
        self, free_port: int, tmp_path: Path
    ) -> None:
        # GIVEN
        reader = SocketReader(port=free_port)
        program = ALLOCATE_THEN_FREE_THEN_SNAPSHOT
        tmp_path_one = tmp_path / "one"
        tmp_path_one.mkdir()
        tmp_path_two = tmp_path / "two"
        tmp_path_two.mkdir()

        # WHEN
        with run_till_snapshot_point(
            program,
            reader=reader,
            tmp_path=tmp_path_one,
            free_port=free_port,
        ):
            pass

        # THEN
        with run_till_snapshot_point(
            program,
            reader=reader,
            tmp_path=tmp_path_two,
            free_port=free_port,
        ):
            pass

    @pytest.mark.valgrind
    def test_command_line(self, free_port: int, tmp_path: Path) -> None:
        # GIVEN
        reader = SocketReader(port=free_port)
        program = ALLOCATE_THEN_FREE_THEN_SNAPSHOT

        # WHEN
        with run_till_snapshot_point(
            program,
            reader=reader,
            tmp_path=tmp_path,
            free_port=free_port,
        ):
            command_line = reader.command_line

        # THEN
        assert command_line
        assert command_line.startswith("-c")  # these samples run with `python -c`
        assert str(free_port) in command_line

    @pytest.mark.valgrind
    def test_reading_allocations_while_reading_stack_traces(
        self, free_port: int, tmp_path: Path
    ) -> None:
        """This test exist mainly to give valgrind/helgrind the opportunity to
        see races between fetching stack traces and the background thread
        fetching allocations. Therefore no interesting asserts are done in
        the test itself.

        The test will spawn a tracked process that is constantly creating new
        functions and code objects so the process is constantly sending new
        frames to the SocketReader, triggering tons of updates of the internal
        structures inside. We want to check that if we get the stack traces
        inside the allocations it won't crash/race with fetching new allocations
        """
        # GIVEN
        script = textwrap.dedent(
            f"""\
            from memray._test import MemoryAllocator
            from memray._memray import SocketDestination
            from memray._memray import Tracker
            from itertools import count
            import textwrap

            def foo(allocator, n):
                fname = f"blech_{{n}}"
                namespace = {{}}

                exec(textwrap.dedent(f'''
                def {{fname}}(allocator):
                    allocator.valloc(1024)
                    allocator.free()
                '''), namespace, namespace)

                func = namespace[fname]
                func(allocator)

            with Tracker(destination=SocketDestination(server_port={free_port})):
                allocator = MemoryAllocator()
                for n in count(0):
                    foo(allocator, n)
        """
        )
        code = [
            sys.executable,
            "-c",
            script,
        ]
        traces: Set[Tuple[str, str, int]] = set()
        MAX_TRACES = 10

        # WHEN
        with subprocess.Popen(code) as proc, SocketReader(port=free_port) as reader:
            while len(traces) < MAX_TRACES:
                for allocation in reader.get_current_snapshot(merge_threads=False):
                    traces.update(allocation.stack_trace())

            proc.terminate()

        # THEN
        assert len(traces) >= MAX_TRACES
        proc.returncode == 0
