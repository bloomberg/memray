import multiprocessing
import socket

import pytest

from bloomberg.pensieve import AllocatorType
from bloomberg.pensieve import FileReader
from bloomberg.pensieve import FileWriter
from bloomberg.pensieve import SocketReader
from bloomberg.pensieve import SocketWriter
from bloomberg.pensieve import Tracker
from bloomberg.pensieve._test import MemoryAllocator


@pytest.fixture
def free_port():
    s = socket.socket()
    s.bind(("", 0))
    port_number = s.getsockname()[1]
    s.close()
    return port_number


def test_file_reader_as_context_manager(tmp_path):
    # GIVEN
    allocator = MemoryAllocator()
    result_file = tmp_path / "test.bin"
    # WHEN
    with Tracker(result_file):
        allocator.valloc(1234)
        allocator.free()

    # THEN
    with FileReader(result_file) as reader:
        pass

    with pytest.raises(ValueError, match="Operation on a closed FileReader"):
        list(reader.get_high_watermark_allocation_records())


def test_file_writer(tmp_path):
    # GIVEN
    allocator = MemoryAllocator()
    result_file = tmp_path / "test.bin"
    file_writer = FileWriter(result_file)
    # WHEN
    with Tracker(writer=file_writer):
        allocator.valloc(1234)
        allocator.free()

    # THEN
    with FileReader(result_file) as reader:
        pass

    with pytest.raises(ValueError, match="Operation on a closed FileReader"):
        list(reader.get_high_watermark_allocation_records())


def test_socket_writer(free_port):
    # GIVEN
    def tracker_process():
        allocator = MemoryAllocator()
        socket_writer = SocketWriter(port=free_port)
        with Tracker(writer=socket_writer):
            allocator.valloc(1234)
            allocator.free()

    proc = multiprocessing.Process(target=tracker_process)
    proc.start()

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
