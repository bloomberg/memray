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
