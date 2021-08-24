from bloomberg.pensieve import AllocatorType
from bloomberg.pensieve.reporters.live import MAX_TABLE_SIZE
from bloomberg.pensieve.reporters.live import LiveAllocationsReporter
from tests.utils import MockAllocationRecord


def test_initializes_with_empty_table():
    # GIVEN
    reporter = LiveAllocationsReporter()

    # WHEN / THEN
    table = reporter.get_current_table()
    assert table.row_count == 0


def test_shows_initial_allocations():
    # GIVEN
    reporter = LiveAllocationsReporter()
    record = MockAllocationRecord(
        tid=1,
        address=0x1000000,
        size=1024,
        allocator=AllocatorType.MALLOC,
        stack_id=1,
        n_allocations=1,
        _stack=[],
    )

    # WHEN
    reporter.update(record)

    # THEN
    table = reporter.get_current_table()
    assert table.row_count == 1


def test_shows_largest_n_allocations():
    # GIVEN
    reporter = LiveAllocationsReporter()

    def record_generator():
        for i in range(MAX_TABLE_SIZE + 1):
            yield MockAllocationRecord(
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

    # WHEN
    for record in record_generator():
        reporter.update(record)

    # THEN
    table = reporter.get_current_table()
    assert table.row_count == MAX_TABLE_SIZE
    # assert "function0" not in something_to_get_rows(table)
