"""Tests to exercise socket-based read and write operations in the Tracker."""
import multiprocessing
import socket
import subprocess
import sys
import textwrap

import pytest

from bloomberg.pensieve._pensieve import AllocatorType
from bloomberg.pensieve._pensieve import MemoryAllocator
from bloomberg.pensieve._pensieve import SocketReader
from bloomberg.pensieve._pensieve import SocketWriter
from bloomberg.pensieve._pensieve import Tracker


@pytest.fixture
def free_port():
    s = socket.socket()
    s.bind(("", 0))
    port_number = s.getsockname()[1]
    s.close()
    return port_number


class TestSocketWriter:
    def test_socket_writer(self, free_port):
        # GIVEN
        tracked_app = textwrap.dedent(
            f"""\
            from bloomberg.pensieve._pensieve import MemoryAllocator
            from bloomberg.pensieve._pensieve import SocketWriter
            from bloomberg.pensieve._pensieve import Tracker

            allocator = MemoryAllocator()
            socket_writer = SocketWriter(port={free_port})
            with Tracker(writer=socket_writer):
                allocator.valloc(1234)
                allocator.free()
        """
        )

        proc = subprocess.Popen([sys.executable, "-c", tracked_app])

        # WHEN
        reader = SocketReader(port=free_port)

        # THEN
        records = list(reader.get_allocation_records())
        assert len(records) == 2
        alloc, free = records
        assert alloc.allocator == AllocatorType.VALLOC
        assert alloc.size == 1234
        symbol, file, line = alloc.stack_trace()[0]
        assert symbol == "valloc"
        assert file == "src/bloomberg/pensieve/_pensieve.pyx"
        assert line > 0 < 200
        assert free.allocator == AllocatorType.FREE
        assert free.size == 0
        assert proc.wait() == 0

    def test_tracker_waits_for_connection(self, free_port):
        """Check that we gracefully handle the case when a `SocketReader` disconnects before
        the tracking completes."""

        # GIVEN
        def server(q):
            allocator = MemoryAllocator()
            socket_writer = SocketWriter(port=free_port)
            tracker = Tracker(writer=socket_writer)
            with tracker:
                allocator.valloc(1234)
                q.put("valloc")
                # At this point the reader will disconnect and the Tracker should
                # get disabled
                allocator.free()

            # The Tracker should still be in disabled state, even after getting
            # a new context manager instance
            with tracker:
                allocator.valloc(1234)
                allocator.free()

        def client(q):
            reader = SocketReader(port=free_port)
            record = next(reader.get_allocation_records())
            assert record.allocator == AllocatorType.VALLOC
            assert q.get() == "valloc"
            # CLose connection before reading any further records

        queue = multiprocessing.Queue()
        server = multiprocessing.Process(target=server, args=(queue,))
        server.start()

        client = multiprocessing.Process(target=client, args=(queue,))
        client.start()
