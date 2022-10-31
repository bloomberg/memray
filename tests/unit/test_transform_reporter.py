import csv
import json
from io import StringIO

from memray import AllocatorType
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
