import os
import time

import pytest

from memray import AllocatorType
from memray import FileFormat
from memray import FileReader
from memray._memray import RecordWriterTestHarness


def test_write_basic_records(tmp_path):
    """Test writing basic records to a file."""
    output_file = tmp_path / "test.memray"

    # Create a writer
    writer = RecordWriterTestHarness(
        str(output_file),
        native_traces=True,
        trace_python_allocators=True,
        file_format=FileFormat.ALL_ALLOCATIONS,
    )

    # Set main thread info
    writer.set_main_tid_and_skipped_frames(1, 0)

    # Write some memory records
    current_time = int(time.time() * 1000)
    assert writer.write_memory_record(current_time, 1024)
    assert writer.write_memory_record(current_time + 1000, 2048)

    # Write thread info
    assert writer.write_thread_record(1, "MainThread")

    # Write some frame records
    assert writer.write_frame_push(1, 1)  # Push frame 1
    assert writer.write_frame_push(1, 2)  # Push frame 2
    assert writer.write_frame_pop(1, 1)  # Pop frame 2
    assert writer.write_frame_push(1, 3)  # Push frame 3

    # Write some allocation records
    assert writer.write_allocation_record(
        1, 0x1000, 1024, AllocatorType.MALLOC
    )  # malloc
    assert writer.write_allocation_record(1, 0x2000, 2048, AllocatorType.FREE)  # free

    # Write some native allocation records
    assert writer.write_allocation_record(1, 0x3000, 4096, AllocatorType.MALLOC, 1)

    # Write memory mappings
    assert writer.write_mappings(
        [
            {
                "filename": "/usr/lib/libc.so.6",
                "addr": 0x7F1234567890,
                "segments": [
                    {"vaddr": 0x7F1234567890, "memsz": 0x1000},
                    {"vaddr": 0x7F1234568890, "memsz": 0x2000},
                ],
            }
        ]
    )

    # Write trailer
    assert writer.write_trailer()

    # Verify file exists and has content
    assert output_file.exists()
    assert output_file.stat().st_size > 0

    # Read and verify the records
    with FileReader(output_file) as reader:
        # Verify metadata
        assert reader.metadata.pid == os.getpid()
        assert reader.metadata.has_native_traces is True
        assert reader.metadata.trace_python_allocators is True
        assert reader.metadata.file_format == FileFormat.ALL_ALLOCATIONS

        # Get all allocation records
        allocations = list(reader.get_allocation_records())
        assert len(allocations) == 3  # malloc, free, native malloc

        # Verify malloc record
        malloc_record = allocations[0]
        assert malloc_record.address == 0x1000
        assert malloc_record.size == 1024
        assert malloc_record.allocator == AllocatorType.MALLOC

        # Verify free record
        free_record = allocations[1]
        assert free_record.address == 0x2000
        assert free_record.size == 0
        assert free_record.allocator == AllocatorType.FREE

        # Verify native malloc record
        native_record = allocations[2]
        assert native_record.address == 0x3000
        assert native_record.size == 4096
        assert native_record.allocator == AllocatorType.MALLOC
        assert native_record.native_stack_id == 1

        # Get memory snapshots
        snapshots = list(reader.get_memory_snapshots())
        assert len(snapshots) == 2
        assert snapshots[0].time == current_time
        assert snapshots[0].rss == 1024
        assert snapshots[1].time == current_time + 1000
        assert snapshots[1].rss == 2048


def test_write_aggregated_records(tmp_path):
    """Test writing aggregated records to a file."""
    output_file = tmp_path / "test_aggregated.memray"

    # Create a writer with aggregated format
    writer = RecordWriterTestHarness(
        str(output_file),
        native_traces=True,
        trace_python_allocators=True,
        file_format=FileFormat.AGGREGATED_ALLOCATIONS,
    )

    # Set main thread info
    writer.set_main_tid_and_skipped_frames(1, 0)

    # Write thread info
    assert writer.write_thread_record(1, "MainThread")

    # Write some frame records
    assert writer.write_frame_push(1, 1)  # Push frame 1
    assert writer.write_frame_push(1, 2)  # Push frame 2

    # Write some allocation records
    assert writer.write_allocation_record(
        1, 0x1000, 1024, AllocatorType.MALLOC
    )  # malloc
    assert writer.write_allocation_record(
        1, 0x2000, 2048, AllocatorType.MALLOC
    )  # malloc

    # Write memory records
    current_time = int(time.time() * 1000)
    assert writer.write_memory_record(current_time, 1024)
    assert writer.write_memory_record(current_time + 1000, 2048)

    # Write trailer
    assert writer.write_trailer()

    # Verify file exists and has content
    assert output_file.exists()
    assert output_file.stat().st_size > 0

    # Read and verify the records
    with FileReader(output_file) as reader:
        # Verify metadata
        assert reader.metadata.pid == os.getpid()
        assert reader.metadata.has_native_traces is True
        assert reader.metadata.trace_python_allocators is True
        assert reader.metadata.file_format == FileFormat.AGGREGATED_ALLOCATIONS

        # Get all allocation records
        with pytest.raises(
            NotImplementedError,
            match="Can't get all allocations from a pre-aggregated capture file",
        ):
            allocations = list(reader.get_allocation_records())

        allocations = list(reader.get_high_watermark_allocation_records())
        assert len(allocations) == 1
        assert allocations[0].tid == 1
        assert allocations[0].address == 0x0
        assert allocations[0].size == 3072
        assert allocations[0].allocator == AllocatorType.MALLOC
        assert allocations[0].n_allocations == 2


def test_write_records_with_multiple_threads(tmp_path):
    """Test writing records with multiple threads."""
    output_file = tmp_path / "test_multiple_threads.memray"

    # Create a writer
    writer = RecordWriterTestHarness(str(output_file))

    # Set main thread info
    writer.set_main_tid_and_skipped_frames(1, 0)

    # Write thread info for multiple threads
    assert writer.write_thread_record(1, "MainThread")
    assert writer.write_thread_record(2, "WorkerThread1")
    assert writer.write_thread_record(3, "WorkerThread2")

    # Write frame records for different threads
    assert writer.write_frame_push(1, 1)  # Main thread
    assert writer.write_frame_push(2, 2)  # Worker 1
    assert writer.write_frame_push(3, 3)  # Worker 2

    # Write allocation records for different threads
    assert writer.write_allocation_record(
        1, 0x1000, 1024, AllocatorType.MALLOC
    )  # Main thread
    assert writer.write_allocation_record(
        2, 0x2000, 2048, AllocatorType.MALLOC
    )  # Worker 1
    assert writer.write_allocation_record(
        3, 0x3000, 4096, AllocatorType.MALLOC
    )  # Worker 2

    # Write trailer
    assert writer.write_trailer()

    # Verify file exists and has content
    assert output_file.exists()
    assert output_file.stat().st_size > 0

    # Read and verify the records
    with FileReader(output_file) as reader:
        # Get all allocation records
        allocations = list(reader.get_allocation_records())
        assert len(allocations) == 3  # One allocation per thread

        # Verify main thread allocation
        main_thread_alloc = allocations[0]
        assert main_thread_alloc.address == 0x1000
        assert main_thread_alloc.size == 1024
        assert main_thread_alloc.allocator == AllocatorType.MALLOC
        assert main_thread_alloc.tid == 1

        # Verify worker 1 allocation
        worker1_alloc = allocations[1]
        assert worker1_alloc.address == 0x2000
        assert worker1_alloc.size == 2048
        assert worker1_alloc.allocator == AllocatorType.MALLOC
        assert worker1_alloc.tid == 2

        # Verify worker 2 allocation
        worker2_alloc = allocations[2]
        assert worker2_alloc.address == 0x3000
        assert worker2_alloc.size == 4096
        assert worker2_alloc.allocator == AllocatorType.MALLOC
        assert worker2_alloc.tid == 3
