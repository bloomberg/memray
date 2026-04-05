import csv
import json
from datetime import datetime
from io import StringIO

from memray import AllocatorType
from memray import MemorySnapshot
from memray import Metadata
from memray import __version__
from memray._memray import FileFormat
from memray.reporters.transform import TransformReporter
from tests.utils import MockAllocationRecord
from tests.utils import MockInterval
from tests.utils import MockTemporalAllocationRecord


class TestGprof2DotTransformReporter:
    def test_empty_report(self):
        # GIVEN
        reporter = TransformReporter(
            [], format="gprof2dot", memory_records=[], native_traces=False
        )
        output = StringIO()

        # WHEN
        reporter.render_as_gprof2dot(output)
        output.seek(0)

        # THEN
        output_data = json.loads(output.read())
        assert output_data == {
            "costs": [{"description": "Memory", "unit": "bytes"}],
            "events": [],
            "functions": [],
            "version": 0,
        }

    def test_single_allocation(self):
        # GIVEN
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("me", "fun.py", 12),
                ],
            ),
        ]
        output = StringIO()

        reporter = TransformReporter(
            peak_allocations, format="gprof2dot", memory_records=[], native_traces=False
        )

        # WHEN
        reporter.render_as_gprof2dot(output)
        output.seek(0)

        # THEN
        output_data = json.loads(output.read())
        assert output_data == {
            "costs": [{"description": "Memory", "unit": "bytes"}],
            "events": [{"callchain": [0], "cost": [1024]}],
            "functions": [{"module": "fun.py", "name": "me"}],
            "version": 0,
        }

    def test_single_native_allocation(self):
        # GIVEN
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _hybrid_stack=[
                    ("me", "fun.c", 12),
                ],
            ),
        ]
        output = StringIO()

        reporter = TransformReporter(
            peak_allocations, format="gprof2dot", memory_records=[], native_traces=True
        )

        # WHEN
        reporter.render_as_gprof2dot(output)
        output.seek(0)

        # THEN
        output_data = json.loads(output.read())
        assert output_data == {
            "costs": [{"description": "Memory", "unit": "bytes"}],
            "events": [{"callchain": [0], "cost": [1024]}],
            "functions": [{"module": "fun.c", "name": "me"}],
            "version": 0,
        }

    def test_multiple_allocations(self):
        # GIVEN
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("me", "foo.py", 12),
                ],
            ),
            MockAllocationRecord(
                tid=1,
                address=0x1100000,
                size=2048,
                allocator=AllocatorType.VALLOC,
                stack_id=2,
                n_allocations=10,
                _stack=[
                    ("you", "bar.py", 21),
                ],
            ),
        ]

        output = StringIO()

        reporter = TransformReporter(
            peak_allocations, format="gprof2dot", memory_records=[], native_traces=False
        )

        # WHEN
        reporter.render_as_gprof2dot(output)
        output.seek(0)

        # THEN
        output_data = json.loads(output.read())
        assert output_data == {
            "costs": [{"description": "Memory", "unit": "bytes"}],
            "events": [
                {"callchain": [0], "cost": [1024]},
                {"callchain": [1], "cost": [2048]},
            ],
            "functions": [
                {"module": "foo.py", "name": "me"},
                {"module": "bar.py", "name": "you"},
            ],
            "version": 0,
        }

    def test_empty_stack_trace(self):
        # GIVEN
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[],
            ),
        ]
        output = StringIO()

        reporter = TransformReporter(
            peak_allocations, format="gprof2dot", memory_records=[], native_traces=False
        )

        # WHEN
        reporter.render_as_gprof2dot(output)
        output.seek(0)

        # THEN
        output_data = json.loads(output.read())
        assert output_data == {
            "costs": [{"description": "Memory", "unit": "bytes"}],
            "events": [],
            "functions": [],
            "version": 0,
        }


class TestCSVTransformReporter:
    HEADER = [
        "allocator",
        "num_allocations",
        "size",
        "tid",
        "thread_name",
        "stack_trace",
    ]

    def test_empty_report(self):
        # GIVEN
        reporter = TransformReporter(
            [], format="csv", memory_records=[], native_traces=False
        )
        output = StringIO()

        # WHEN
        reporter.render_as_csv(output)
        output.seek(0)

        # THEN
        header, *output_data = tuple(csv.reader(output))
        assert header == self.HEADER
        assert output_data == []

    def test_single_allocation(self):
        # GIVEN
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("me", "fun.py", 12),
                ],
            ),
        ]
        output = StringIO()

        reporter = TransformReporter(
            peak_allocations, format="csv", memory_records=[], native_traces=False
        )

        # WHEN
        reporter.render_as_csv(output)
        output.seek(0)

        # THEN
        header, *output_data = tuple(csv.reader(output))
        assert header == self.HEADER
        assert output_data == [["MALLOC", "1", "1024", "1", "0x1", "me;fun.py;12"]]

    def test_single_native_allocation(self):
        # GIVEN
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _hybrid_stack=[
                    ("me", "fun.c", 12),
                ],
            ),
        ]
        output = StringIO()

        reporter = TransformReporter(
            peak_allocations, format="csv", memory_records=[], native_traces=True
        )

        # WHEN
        reporter.render_as_csv(output)
        output.seek(0)

        # THEN
        header, *output_data = tuple(csv.reader(output))
        assert header == self.HEADER
        assert output_data == [["MALLOC", "1", "1024", "1", "0x1", "me;fun.c;12"]]

    def test_multiple_allocations(self):
        # GIVEN
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("me", "foo.py", 12),
                ],
            ),
            MockAllocationRecord(
                tid=1,
                address=0x1100000,
                size=2048,
                allocator=AllocatorType.VALLOC,
                stack_id=2,
                n_allocations=10,
                _stack=[
                    ("you", "bar.py", 21),
                ],
            ),
        ]

        output = StringIO()

        reporter = TransformReporter(
            peak_allocations, format="csv", memory_records=[], native_traces=False
        )

        # WHEN
        reporter.render_as_csv(output)
        output.seek(0)

        # THEN
        header, *output_data = tuple(csv.reader(output))
        assert header == self.HEADER
        assert output_data == [
            ["MALLOC", "1", "1024", "1", "0x1", "me;foo.py;12"],
            ["VALLOC", "10", "2048", "1", "0x1", "you;bar.py;21"],
        ]

    def test_empty_stack_trace(self):
        # GIVEN
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[],
            ),
        ]
        output = StringIO()

        reporter = TransformReporter(
            peak_allocations, format="csv", memory_records=[], native_traces=False
        )

        # WHEN
        reporter.render_as_csv(output)
        output.seek(0)

        # THEN
        header, *output_data = tuple(csv.reader(output))
        assert header == self.HEADER
        assert output_data == [["MALLOC", "1", "1024", "1", "0x1", ""]]

    def test_multiple_stack_frames(self):
        # GIVEN
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("me", "foo.py", 12),
                    ("you", "bar.py", 21),
                ],
            ),
        ]
        output = StringIO()

        reporter = TransformReporter(
            peak_allocations, format="csv", memory_records=[], native_traces=False
        )

        # WHEN
        reporter.render_as_csv(output)
        output.seek(0)

        # THEN
        header, *output_data = tuple(csv.reader(output))
        assert header == self.HEADER

        assert output_data == [
            ["MALLOC", "1", "1024", "1", "0x1", "me;foo.py;12|you;bar.py;21"]
        ]


class TestSpeedscopeTransformReporter:
    def test_empty_report(self):
        reporter = TransformReporter(
            [], format="speedscope", memory_records=[], native_traces=False
        )
        output = StringIO()

        reporter.render_as_speedscope(output)
        output.seek(0)

        output_data = json.loads(output.read())
        assert output_data == {
            "$schema": "https://www.speedscope.app/file-format-schema.json",
            "activeProfileIndex": 0,
            "exporter": f"memray@{__version__}",
            "name": "memray",
            "profiles": [
                {
                    "endValue": 0,
                    "name": "Memory",
                    "samples": [],
                    "startValue": 0,
                    "type": "sampled",
                    "unit": "bytes",
                    "weights": [],
                },
                {
                    "endValue": 0,
                    "name": "Allocations",
                    "samples": [],
                    "startValue": 0,
                    "type": "sampled",
                    "unit": "none",
                    "weights": [],
                },
            ],
            "shared": {"frames": []},
        }

    def test_stacks_are_written_root_to_leaf(self):
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("leaf", "leaf.py", 30),
                    ("root", "root.py", 10),
                ],
            ),
        ]
        output = StringIO()

        reporter = TransformReporter(
            peak_allocations,
            format="speedscope",
            memory_records=[],
            native_traces=False,
        )

        reporter.render_as_speedscope(output)
        output.seek(0)

        output_data = json.loads(output.read())
        assert output_data["shared"]["frames"] == [
            {"file": "root.py", "line": 10, "name": "root"},
            {"file": "leaf.py", "line": 30, "name": "leaf"},
        ]
        assert output_data["profiles"][0]["samples"] == [[0, 1]]
        assert output_data["profiles"][0]["weights"] == [1024]
        assert output_data["profiles"][1]["samples"] == [[0, 1]]
        assert output_data["profiles"][1]["weights"] == [1]

    def test_identical_stacks_are_aggregated(self):
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("leaf", "leaf.py", 30),
                    ("root", "root.py", 10),
                ],
            ),
            MockAllocationRecord(
                tid=1,
                address=0x2000000,
                size=2048,
                allocator=AllocatorType.CALLOC,
                stack_id=2,
                n_allocations=4,
                _stack=[
                    ("leaf", "leaf.py", 30),
                    ("root", "root.py", 10),
                ],
            ),
        ]
        output = StringIO()

        reporter = TransformReporter(
            peak_allocations,
            format="speedscope",
            memory_records=[],
            native_traces=False,
        )

        reporter.render_as_speedscope(output)
        output.seek(0)

        output_data = json.loads(output.read())
        assert output_data["profiles"][0]["samples"] == [[0, 1]]
        assert output_data["profiles"][0]["weights"] == [3072]
        assert output_data["profiles"][0]["endValue"] == 3072
        assert output_data["profiles"][1]["samples"] == [[0, 1]]
        assert output_data["profiles"][1]["weights"] == [5]
        assert output_data["profiles"][1]["endValue"] == 5

    def test_stacks_with_exact_timestamps_are_ordered_by_timestamp(self):
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[("late", "late.py", 30)],
            ),
            MockAllocationRecord(
                tid=1,
                address=0x2000000,
                size=2048,
                allocator=AllocatorType.CALLOC,
                stack_id=2,
                n_allocations=2,
                _stack=[("early", "early.py", 10)],
            ),
        ]
        peak_allocations[0].timestamp_us = 50
        peak_allocations[1].timestamp_us = 10

        reporter = TransformReporter(
            peak_allocations,
            format="speedscope",
            memory_records=[],
            native_traces=False,
        )
        output = StringIO()

        reporter.render_as_speedscope(
            output,
            metadata=Metadata(
                start_time=datetime(2024, 1, 1, 0, 0, 0),
                end_time=datetime(2024, 1, 1, 0, 0, 1),
                total_allocations=2,
                total_frames=2,
                peak_memory=3072,
                command_line="memray",
                pid=1,
                main_thread_id=1,
                python_allocator="pymalloc",
                has_native_traces=False,
                trace_python_allocators=False,
                file_format=FileFormat.ALL_ALLOCATIONS,
                has_allocation_timestamps=True,
            ),
        )
        output.seek(0)

        output_data = json.loads(output.read())
        assert output_data["shared"]["frames"] == [
            {"file": "late.py", "line": 30, "name": "late"},
            {"file": "early.py", "line": 10, "name": "early"},
        ]
        assert output_data["profiles"][0]["samples"] == [[1], [0]]
        assert output_data["profiles"][0]["weights"] == [2048, 1024]
        assert output_data["profiles"][1]["samples"] == [[1], [0]]
        assert output_data["profiles"][1]["weights"] == [2, 1]

    def test_temporal_fallback_orders_by_snapshot_time(self):
        allocations = [
            MockTemporalAllocationRecord(
                tid=1,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                intervals=[MockInterval(1, None, 1, 200)],
                _stack=[("later", "later.py", 20)],
            ),
            MockTemporalAllocationRecord(
                tid=1,
                allocator=AllocatorType.CALLOC,
                stack_id=2,
                intervals=[MockInterval(0, None, 1, 100)],
                _stack=[("earlier", "earlier.py", 10)],
            ),
        ]
        reporter = TransformReporter(
            allocations,
            format="speedscope",
            memory_records=[
                MemorySnapshot(100, 0, 0),
                MemorySnapshot(110, 0, 0),
            ],
            native_traces=False,
            high_water_mark_by_snapshot=[100, 300],
        )
        output = StringIO()

        reporter.render_as_speedscope(output, show_memory_leaks=False)
        output.seek(0)

        output_data = json.loads(output.read())
        assert output_data["profiles"][0]["samples"] == [[1], [0]]
        assert output_data["profiles"][0]["weights"] == [100, 200]
        assert output_data["profiles"][1]["samples"] == [[1], [0]]
        assert output_data["profiles"][1]["weights"] == [1, 1]

    def test_temporal_leak_fallback_omits_freed_intervals(self):
        allocations = [
            MockTemporalAllocationRecord(
                tid=1,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                intervals=[MockInterval(0, None, 1, 100)],
                _stack=[("leaked", "leaked.py", 10)],
            ),
            MockTemporalAllocationRecord(
                tid=1,
                allocator=AllocatorType.CALLOC,
                stack_id=2,
                intervals=[MockInterval(0, 1, 1, 200)],
                _stack=[("freed", "freed.py", 20)],
            ),
        ]
        reporter = TransformReporter(
            allocations,
            format="speedscope",
            memory_records=[MemorySnapshot(100, 0, 0)],
            native_traces=False,
        )
        output = StringIO()

        reporter.render_as_speedscope(output, show_memory_leaks=True)
        output.seek(0)

        output_data = json.loads(output.read())
        assert output_data["profiles"][0]["samples"] == [[0]]
        assert output_data["profiles"][0]["weights"] == [100]
        assert output_data["profiles"][1]["samples"] == [[0]]
        assert output_data["profiles"][1]["weights"] == [1]
