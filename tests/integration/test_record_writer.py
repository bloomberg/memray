import inspect
import itertools
import os
import re
import subprocess
import sys
import sysconfig
import textwrap
from unittest.mock import ANY

from memray import AllocatorType
from memray import FileFormat
from memray import FileReader
from memray._memray import RecordWriterTestHarness


def get_sample_line_number_tables():
    callers = []

    def save_caller():
        stack = inspect.stack()
        caller = stack[1].frame
        linetable = RecordWriterTestHarness.get_linetable(caller.f_code)

        callers.append(
            {
                "lasti": RecordWriterTestHarness.get_lasti(caller),
                "linetable": linetable,
            }
        )

    def foo():
        x = 10
        y = 20
        _ = x + y
        save_caller()
        return

    def bar():
        x = []
        for _ in range(100):
            x.append(x)

        save_caller()

        return None

    def baz():
        yield
        save_caller()
        return "foo"

    foo()
    bar()
    list(baz())
    return callers


def parse_capture_file(output_file):
    output = subprocess.check_output(
        [sys.executable, "-m", "memray", "parse", output_file],
        encoding="utf-8",
    )
    parsed = output.splitlines()
    header, *rest = parsed

    assert header.startswith("HEADER ")
    header_fields = list(re.findall(r"(\S+)=(.*?)\s*(?=\S+=|$)", header))
    return header_fields, rest


def sort_runs_of_same_record_type(records):
    sorted_records = []
    for _, group in itertools.groupby(records, lambda line: line.split(" ", 1)[0]):
        sorted_records.extend(sorted(group))
    return sorted_records


def test_write_basic_records(tmp_path):
    """Test writing basic records to a file."""
    # GIVEN
    output_file = tmp_path / "test.memray"

    # WHEN
    writer = RecordWriterTestHarness(
        str(output_file),
        native_traces=True,
        trace_python_allocators=True,
        file_format=FileFormat.ALL_ALLOCATIONS,
        main_tid=10,
        skipped_frames=15,
    )

    assert writer.write_memory_record(1757101101880, 1024)
    assert writer.write_memory_record(1757101102880, 2048)

    assert writer.write_thread_record(1, "MainThread")
    assert writer.write_thread_record(2, "Other Thread")

    assert writer.write_code_object(1, "a", "a.py", b"", 1)
    assert writer.write_code_object(2, "b", "b.py", b"", 11)
    assert writer.write_code_object(3, "c", "c.py", b"", 21)

    assert writer.write_frame_push(1, 1, 12, True)
    assert writer.write_frame_push(1, 2, 34, True)
    assert writer.write_frame_push(1, 3, 56, True)

    assert writer.write_frame_pop(1, 0)
    assert writer.write_frame_pop(1, 1)
    assert writer.write_frame_pop(1, 16)
    assert writer.write_frame_pop(1, 17)

    assert writer.write_unresolved_native_frame(0xDEADBEEF, 1)
    assert writer.write_unresolved_native_frame(0xFEEDCAFE, 2)

    assert writer.write_allocation_record(1, 0x1000, 1024, AllocatorType.MALLOC, 1)
    assert writer.write_allocation_record(1, 0x2000, 2048, AllocatorType.PYMALLOC_FREE)
    assert writer.write_allocation_record(1, 0x3000, 4096, AllocatorType.POSIX_MEMALIGN)

    assert writer.write_allocation_record(2, 0x4000, 4096, AllocatorType.MALLOC, 2)

    assert writer.write_mappings(
        [
            {
                "filename": "/usr/lib/libc.so.6",
                "addr": 0xF1234567,
                "segments": [
                    {"vaddr": 0x12345678, "memsz": 0x1000},
                    {"vaddr": 0xF2345678, "memsz": 0x2000},
                ],
            }
        ]
    )

    assert writer.write_trailer()

    # THEN
    header_fields, records = parse_capture_file(output_file)
    allocator = (
        "mimalloc" if sysconfig.get_config_var("Py_GIL_DISABLED") else "pymalloc"
    )

    assert header_fields == [
        ("magic", "memray"),
        ("version", "12"),
        ("python_version", f"{sys.hexversion:08x}"),
        ("native_traces", "true"),
        ("file_format", "ALL_ALLOCATIONS"),
        ("n_allocations", "0"),
        ("n_frames", "0"),
        ("start_time", ANY),
        ("end_time", ANY),
        ("pid", f"{os.getpid()}"),
        ("main_tid", "10"),
        ("skipped_frames_on_main_tid", "15"),
        ("command_line", "memray test harness"),
        ("python_allocator", allocator),
        ("trace_python_allocators", "true"),
    ]

    expected_parse_output = """
        MEMORY_RECORD time=1757101101880 memory=1024
        MEMORY_RECORD time=1757101102880 memory=2048
        CONTEXT_SWITCH tid=1
        THREAD MainThread
        CONTEXT_SWITCH tid=2
        THREAD Other Thread
        CODE_OBJECT code_id=1 function_name=a filename=a.py firstlineno=1 linetable_size=0
        CODE_OBJECT code_id=2 function_name=b filename=b.py firstlineno=11 linetable_size=0
        CODE_OBJECT code_id=3 function_name=c filename=c.py firstlineno=21 linetable_size=0
        CONTEXT_SWITCH tid=1
        FRAME_PUSH code_object_id=1 instruction_offset=12 is_entry_frame=1
        FRAME_PUSH code_object_id=2 instruction_offset=34 is_entry_frame=1
        FRAME_PUSH code_object_id=3 instruction_offset=56 is_entry_frame=1
        FRAME_POP count=1
        FRAME_POP count=16
        FRAME_POP count=16
        FRAME_POP count=1
        NATIVE_FRAME_ID ip=0xdeadbeef index=1
        NATIVE_FRAME_ID ip=0xfeedcafe index=2
        ALLOCATION address=0x1000 size=1024 allocator=malloc native_frame_id=1
        ALLOCATION address=0x2000 size=0 allocator=pymalloc_free native_frame_id=0
        ALLOCATION address=0x3000 size=4096 allocator=posix_memalign native_frame_id=0
        CONTEXT_SWITCH tid=2
        ALLOCATION address=0x4000 size=4096 allocator=malloc native_frame_id=2
        MEMORY_MAP_START
        SEGMENT_HEADER filename=/usr/lib/libc.so.6 num_segments=2 addr=0xf1234567
        SEGMENT 0x12345678 1000
        SEGMENT 0xf2345678 2000
        TRAILER
    """

    expected_records = textwrap.dedent(expected_parse_output).strip().splitlines()
    assert records == expected_records


def test_write_aggregated_records(tmp_path):
    """Test writing aggregated records to a file."""
    # GIVEN
    output_file = tmp_path / "test_aggregated.memray"

    # WHEN
    writer = RecordWriterTestHarness(
        str(output_file),
        native_traces=False,
        trace_python_allocators=False,
        file_format=FileFormat.AGGREGATED_ALLOCATIONS,
    )

    assert writer.write_memory_record(1757105244685, 10000)

    assert writer.write_code_object(10, "a", "a.py", b"", 1)
    assert writer.write_code_object(20, "b", "b.py", b"", 11)
    assert writer.write_code_object(30, "c", "c.py", b"", 21)

    assert writer.write_frame_push(1, 1, 12, True)
    assert writer.write_frame_push(1, 2, 34, True)
    assert writer.write_allocation_record(1, 0x1000, 1024, AllocatorType.MALLOC)

    assert writer.write_frame_push(2, 3, 56, True)
    assert writer.write_allocation_record(2, 0x2000, 2048, AllocatorType.MALLOC)

    assert writer.write_memory_record(1757105245685, 20000)

    assert writer.write_trailer()

    # THEN
    header_fields, records = parse_capture_file(output_file)
    allocator = (
        "mimalloc" if sysconfig.get_config_var("Py_GIL_DISABLED") else "pymalloc"
    )

    assert header_fields == [
        ("magic", "memray"),
        ("version", "12"),
        ("python_version", f"{sys.hexversion:08x}"),
        ("native_traces", "false"),
        ("file_format", "AGGREGATED_ALLOCATIONS"),
        ("n_allocations", "0"),
        ("n_frames", "0"),
        ("start_time", ANY),
        ("end_time", ANY),
        ("pid", f"{os.getpid()}"),
        ("main_tid", "1"),
        ("skipped_frames_on_main_tid", "0"),
        ("command_line", "memray test harness"),
        ("python_allocator", allocator),
        ("trace_python_allocators", "false"),
    ]

    records = sort_runs_of_same_record_type(records)
    expected_parse_output = """
        MEMORY_SNAPSHOT time=1757105244685 rss=10000 heap=0
        MEMORY_SNAPSHOT time=1757105245685 rss=20000 heap=3072
        CODE_OBJECT code_id=10 function_name=a filename=a.py firstlineno=1 linetable_size=0
        CODE_OBJECT code_id=20 function_name=b filename=b.py firstlineno=11 linetable_size=0
        CODE_OBJECT code_id=30 function_name=c filename=c.py firstlineno=21 linetable_size=0
        PYTHON_FRAME_INDEX frame_id=0 code_object_id=1 instruction_offset=12 is_entry_frame=1
        PYTHON_FRAME_INDEX frame_id=1 code_object_id=2 instruction_offset=34 is_entry_frame=1
        PYTHON_FRAME_INDEX frame_id=2 code_object_id=3 instruction_offset=56 is_entry_frame=1
        PYTHON_TRACE_INDEX frame_id=0 parent_index=0
        PYTHON_TRACE_INDEX frame_id=1 parent_index=1
        PYTHON_TRACE_INDEX frame_id=2 parent_index=0
        AGGREGATED_ALLOCATION tid=1 allocator=malloc native_frame_id=0 python_frame_id=2 native_segment_generation=0 n_allocations_in_high_water_mark=1 n_allocations_leaked=1 bytes_in_high_water_mark=1024 bytes_leaked=1024
        AGGREGATED_ALLOCATION tid=2 allocator=malloc native_frame_id=0 python_frame_id=3 native_segment_generation=0 n_allocations_in_high_water_mark=1 n_allocations_leaked=1 bytes_in_high_water_mark=2048 bytes_leaked=2048
        AGGREGATED_TRAILER
    """  # noqa: E501
    expected_records = sort_runs_of_same_record_type(
        textwrap.dedent(expected_parse_output).strip().splitlines()
    )

    assert records == expected_records


def test_decoding_line_numbers(tmp_path):
    # GIVEN
    funcs = get_sample_line_number_tables()
    output_file = tmp_path / "test.memray"

    # WHEN
    writer = RecordWriterTestHarness(str(output_file))

    assert writer.write_code_object(1, "foo", "foo a.py", funcs[0]["linetable"], 1)
    assert writer.write_code_object(2, "bar", "bar b.py", funcs[1]["linetable"], 11)
    assert writer.write_code_object(3, "baz", "baz c.py", funcs[2]["linetable"], 21)

    assert writer.write_frame_push(1, 1, funcs[0]["lasti"], True)
    assert writer.write_frame_push(1, 2, funcs[1]["lasti"], True)
    assert writer.write_frame_push(1, 3, funcs[2]["lasti"], True)

    assert writer.write_allocation_record(1, 0x1000, 1024, AllocatorType.MALLOC)

    # THEN
    with FileReader(output_file) as reader:
        allocations = list(reader.get_allocation_records())
        assert len(allocations) == 1
        assert allocations[0].stack_trace() == [
            ("baz", "baz c.py", 23),
            ("bar", "bar b.py", 16),
            ("foo", "foo a.py", 5),
        ]
