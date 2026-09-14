import csv
import json
from io import StringIO

import pytest

from memray import AllocatorType
from memray._version import __version__
from memray.reporters.transform import TransformReporter
from tests.utils import MockAllocationRecord


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

    def test_stacks_preserve_allocation_order(self):
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
        reporter = TransformReporter(
            peak_allocations,
            format="speedscope",
            memory_records=[],
            native_traces=False,
        )
        output = StringIO()

        reporter.render_as_speedscope(output)
        output.seek(0)

        output_data = json.loads(output.read())
        assert output_data["shared"]["frames"] == [
            {"file": "late.py", "line": 30, "name": "late"},
            {"file": "early.py", "line": 10, "name": "early"},
        ]
        assert output_data["profiles"][0]["samples"] == [[0], [1]]
        assert output_data["profiles"][0]["weights"] == [1024, 2048]
        assert output_data["profiles"][1]["samples"] == [[0], [1]]
        assert output_data["profiles"][1]["weights"] == [1, 2]


class TestCSVTransformReporterThreadHandling:
    HEADER = TestCSVTransformReporter.HEADER

    @staticmethod
    def _records_on_two_threads():
        return [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                thread_name="thread-1",
                _stack=[("me", "fun.py", 12)],
            ),
            MockAllocationRecord(
                tid=2,
                address=0x1100000,
                size=2048,
                allocator=AllocatorType.MALLOC,
                stack_id=2,
                n_allocations=1,
                thread_name="thread-2",
                _stack=[("me", "fun.py", 12)],
            ),
        ]

    def test_render_preserves_per_thread_identity(self):
        # GIVEN
        reporter = TransformReporter(
            self._records_on_two_threads(),
            format="csv",
            memory_records=[],
            native_traces=False,
        )
        output = StringIO()

        # WHEN
        reporter.render(
            output,
            metadata=None,
            show_memory_leaks=False,
            merge_threads=False,
            inverted=False,
        )
        output.seek(0)

        # THEN
        header, *rows = tuple(csv.reader(output))
        assert header == self.HEADER
        assert rows == [
            ["MALLOC", "1", "1024", "1", "0x1 (thread-1)", "me;fun.py;12"],
            ["MALLOC", "1", "2048", "2", "0x2 (thread-2)", "me;fun.py;12"],
        ]

    def test_render_formats_merged_thread_sentinel(self):
        # GIVEN a record that the reader merged across threads (tid == -1)
        merged_record = MockAllocationRecord(
            tid=-1,
            address=0x1000000,
            size=3072,
            allocator=AllocatorType.MALLOC,
            stack_id=1,
            n_allocations=2,
            _stack=[("me", "fun.py", 12)],
        )
        reporter = TransformReporter(
            [merged_record], format="csv", memory_records=[], native_traces=False
        )
        output = StringIO()

        # WHEN
        reporter.render(
            output,
            metadata=None,
            show_memory_leaks=False,
            merge_threads=True,
            inverted=False,
        )
        output.seek(0)

        # THEN
        header, *rows = tuple(csv.reader(output))
        assert header == self.HEADER
        assert rows == [["MALLOC", "2", "3072", "-1", "merged thread", "me;fun.py;12"]]

    @pytest.mark.parametrize("fmt", ["gprof2dot", "speedscope"])
    def test_render_rejects_split_threads_for_other_formats(self, fmt):
        # GIVEN
        reporter = TransformReporter(
            [], format=fmt, memory_records=[], native_traces=False
        )

        # WHEN / THEN
        with pytest.raises(NotImplementedError, match="split threads"):
            reporter.render(
                StringIO(),
                metadata=None,
                show_memory_leaks=False,
                merge_threads=False,
                inverted=False,
            )
