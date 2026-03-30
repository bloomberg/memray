from memray import AllocatorType
from memray.reporters.table import TableReporter
from tests.utils import MockAllocationRecord


class TestTableReporter:
    def test_empty_report(self):
        # GIVEN / WHEN
        table = TableReporter.from_snapshot([], memory_records=[], native_traces=False)

        # THEN
        assert table.data == []

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

        # WHEN
        table = TableReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False
        )

        # THEN
        assert table.data == [
            {
                "tid": "0x1",
                "size": 1024,
                "allocator": "malloc",
                "n_allocations": 1,
                "stack_trace": "me at fun.py:12",
            }
        ]

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

        # WHEN
        table = TableReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=True
        )

        # THEN
        assert table.data == [
            {
                "tid": "0x1",
                "size": 1024,
                "allocator": "malloc",
                "n_allocations": 1,
                "stack_trace": "me at fun.c:12",
            }
        ]

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

        # WHEN
        table = TableReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False
        )

        # THEN
        assert table.data == [
            {
                "tid": "0x1",
                "size": 1024,
                "allocator": "malloc",
                "n_allocations": 1,
                "stack_trace": "me at foo.py:12",
            },
            {
                "tid": "0x1",
                "size": 2048,
                "allocator": "valloc",
                "n_allocations": 10,
                "stack_trace": "you at bar.py:21",
            },
        ]

    def test_aggregates_records_with_same_top_frame(self):
        """Records with different full stacks but same top frame should be aggregated."""
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
                    ("caller_a", "a.py", 1),
                ],
            ),
            MockAllocationRecord(
                tid=1,
                address=0x1100000,
                size=2048,
                allocator=AllocatorType.MALLOC,
                stack_id=2,
                n_allocations=3,
                _stack=[
                    ("me", "fun.py", 12),
                    ("caller_b", "b.py", 5),
                ],
            ),
        ]

        # WHEN
        table = TableReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False
        )

        # THEN
        assert table.data == [
            {
                "tid": "0x1",
                "size": 1024 + 2048,
                "allocator": "malloc",
                "n_allocations": 4,
                "stack_trace": "me at fun.py:12",
            }
        ]

    def test_does_not_aggregate_different_allocators(self):
        """Records with the same top frame but different allocators stay separate."""
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
            MockAllocationRecord(
                tid=1,
                address=0x1100000,
                size=2048,
                allocator=AllocatorType.CALLOC,
                stack_id=2,
                n_allocations=1,
                _stack=[
                    ("me", "fun.py", 12),
                ],
            ),
        ]

        # WHEN
        table = TableReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False
        )

        # THEN
        assert len(table.data) == 2
        assert table.data[0]["allocator"] == "malloc"
        assert table.data[1]["allocator"] == "calloc"

    def test_does_not_aggregate_different_threads(self):
        """Records from different threads with same top frame stay separate."""
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
            MockAllocationRecord(
                tid=2,
                address=0x1100000,
                size=2048,
                allocator=AllocatorType.MALLOC,
                stack_id=2,
                n_allocations=1,
                _stack=[
                    ("me", "fun.py", 12),
                ],
            ),
        ]

        # WHEN
        table = TableReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False
        )

        # THEN
        assert len(table.data) == 2
        assert table.data[0]["tid"] == "0x1"
        assert table.data[1]["tid"] == "0x2"

    def test_aggregates_native_records_with_same_top_frame(self):
        """Native trace records with same top frame should also be aggregated."""
        # GIVEN
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=512,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=2,
                _hybrid_stack=[
                    ("alloc", "mem.c", 42),
                    ("caller_a", "a.c", 10),
                ],
            ),
            MockAllocationRecord(
                tid=1,
                address=0x1100000,
                size=256,
                allocator=AllocatorType.MALLOC,
                stack_id=2,
                n_allocations=5,
                _hybrid_stack=[
                    ("alloc", "mem.c", 42),
                    ("caller_b", "b.c", 20),
                ],
            ),
        ]

        # WHEN
        table = TableReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=True
        )

        # THEN
        assert table.data == [
            {
                "tid": "0x1",
                "size": 768,
                "allocator": "malloc",
                "n_allocations": 7,
                "stack_trace": "alloc at mem.c:42",
            }
        ]

    def test_aggregates_merged_thread_records(self):
        """When merge_threads=True, records arrive with tid=-1 and aggregate."""
        # GIVEN
        peak_allocations = [
            MockAllocationRecord(
                tid=-1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("me", "fun.py", 12),
                    ("caller_a", "a.py", 1),
                ],
            ),
            MockAllocationRecord(
                tid=-1,
                address=0x1100000,
                size=2048,
                allocator=AllocatorType.MALLOC,
                stack_id=2,
                n_allocations=3,
                _stack=[
                    ("me", "fun.py", 12),
                    ("caller_b", "b.py", 5),
                ],
            ),
        ]

        # WHEN
        table = TableReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False
        )

        # THEN
        assert table.data == [
            {
                "tid": "merged thread",
                "size": 1024 + 2048,
                "allocator": "malloc",
                "n_allocations": 4,
                "stack_trace": "me at fun.py:12",
            }
        ]

    def test_html_special_chars_in_stack_trace(self):
        """Stack traces with HTML special chars are escaped in output."""
        # GIVEN
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=512,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _hybrid_stack=[
                    ("std::vector<int>::push_back", "vector.h", 100),
                ],
            ),
        ]

        # WHEN
        table = TableReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=True
        )

        # THEN
        assert len(table.data) == 1
        assert "&lt;" in table.data[0]["stack_trace"]
        assert "&gt;" in table.data[0]["stack_trace"]
        assert "<int>" not in table.data[0]["stack_trace"]

    def test_html_special_chars_do_not_break_aggregation(self):
        """Records with HTML chars in function names still aggregate correctly."""
        # GIVEN
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=512,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _hybrid_stack=[
                    ("std::vector<int>::push_back", "vector.h", 100),
                    ("caller_a", "a.cpp", 10),
                ],
            ),
            MockAllocationRecord(
                tid=1,
                address=0x1100000,
                size=256,
                allocator=AllocatorType.MALLOC,
                stack_id=2,
                n_allocations=2,
                _hybrid_stack=[
                    ("std::vector<int>::push_back", "vector.h", 100),
                    ("caller_b", "b.cpp", 20),
                ],
            ),
        ]

        # WHEN
        table = TableReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=True
        )

        # THEN
        assert len(table.data) == 1
        assert table.data[0]["size"] == 768
        assert table.data[0]["n_allocations"] == 3

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

        # WHEN
        table = TableReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False
        )

        # THEN
        assert table.data == [
            {
                "tid": "0x1",
                "size": 1024,
                "allocator": "malloc",
                "n_allocations": 1,
                "stack_trace": "???",
            }
        ]
