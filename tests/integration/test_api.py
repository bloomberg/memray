"""Tests for exercising the public API."""

import pytest

from memray import FileDestination
from memray import FileFormat
from memray import FileReader
from memray import SocketDestination
from memray import Tracker
from memray._test import MemoryAllocator
from tests.utils import filter_relevant_allocations


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


def test_file_destination(tmp_path):
    # GIVEN
    allocator = MemoryAllocator()
    result_file = tmp_path / "test.bin"
    # WHEN
    with Tracker(destination=FileDestination(result_file)):
        allocator.valloc(1234)
        allocator.free()

    # THEN
    with FileReader(result_file) as reader:
        all_allocations = reader.get_allocation_records()
        vallocs_and_their_frees = list(filter_relevant_allocations(all_allocations))
        assert len(vallocs_and_their_frees) == 2


def test_file_destination_str_path(tmp_path):
    # GIVEN
    allocator = MemoryAllocator()
    result_file = str(tmp_path / "test.bin")
    # WHEN
    with Tracker(destination=FileDestination(result_file)):
        allocator.valloc(1234)
        allocator.free()

    # THEN
    with FileReader(result_file) as reader:
        all_allocations = reader.get_allocation_records()
        vallocs_and_their_frees = list(filter_relevant_allocations(all_allocations))
        assert len(vallocs_and_their_frees) == 2


def test_combine_destination_args():
    """Combining `writer` and `file_name` arguments in the `Tracker` should
    raise an exception."""

    # GIVEN/WHEN/THEN
    with pytest.raises(
        TypeError,
        match="Exactly one of 'file_name' or 'destination' argument must be specified",
    ):
        with Tracker(destination=SocketDestination(server_port=1234), file_name="foo"):
            pass


def test_no_destination_arg():
    """Not passing either `writer` or `file_name` argument in the `Tracker` should
    raise an exception."""

    # GIVEN/WHEN/THEN
    with pytest.raises(
        TypeError,
        match="Exactly one of 'file_name' or 'destination' argument must be specified",
    ):
        with Tracker():  # pragma: no cover
            pass


def test_follow_fork_with_socket_destination():
    # GIVEN
    with pytest.raises(RuntimeError, match="follow_fork requires an output file"):
        with Tracker(
            destination=SocketDestination(server_port=1234), follow_fork=True
        ):  # pragma: no cover
            pass


def test_aggregated_capture_with_socket_destination():
    # GIVEN
    with pytest.raises(
        RuntimeError, match="AGGREGATED_ALLOCATIONS requires an output file"
    ):
        with Tracker(
            destination=SocketDestination(server_port=1234),
            file_format=FileFormat.AGGREGATED_ALLOCATIONS,
        ):  # pragma: no cover
            pass
