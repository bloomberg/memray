from unittest import mock

from bloomberg.pensieve import AllocatorType
from bloomberg.pensieve.reporters.live import LiveAllocationsReporter
from tests.utils import MockAllocationRecord


def test_initializes_with_empty_table():
    # GIVEN
    reader = mock.Mock()
    reader.get_current_snapshot.side_effect = [[]]
    reporter = LiveAllocationsReporter(reader)

    # WHEN
    table = reporter.get_current_table()

    # THEN
    assert table.row_count == 0


def test_shows_single_allocation():
    # GIVEN
    reader = mock.Mock()
    reader.get_current_snapshot.side_effect = [
        [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[],
            )
        ]
    ]
    reporter = LiveAllocationsReporter(reader)

    # WHEN
    table = reporter.get_current_table()

    # THEN
    assert table.row_count == 1


def test_shows_all_allocations():
    # GIVEN
    table_size = 10
    reader = mock.Mock()
    reader.get_current_snapshot.side_effect = [
        [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024 * (i + 1),
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    (f"function{i}", "/src/lel.py", 18),
                ],
            )
            for i in range(table_size)
        ]
    ]
    reporter = LiveAllocationsReporter(reader)

    # WHEN
    table = reporter.get_current_table()

    # THEN
    assert table.row_count == table_size
