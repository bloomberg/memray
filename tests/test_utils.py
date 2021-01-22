"""Tests for our testing utilities."""

from bloomberg.pensieve import AllocatorType
from bloomberg.pensieve._pensieve import AllocationRecord
from tests.utils import MockAllocationRecord


class TestMockAllocationRecord:
    def test_holds_values_at_correct_names(self):
        tid = 0
        address = 0x1140000
        size = 1024
        allocator = AllocatorType.MALLOC
        stack_id = 1
        n_allocations = 1
        stack = ["stack 0", "stack 1"]

        mock_record = MockAllocationRecord(
            tid, address, size, allocator, stack_id, n_allocations, stack
        )
        assert mock_record.tid == tid
        assert mock_record.address == address
        assert mock_record.size == size
        assert mock_record.allocator == allocator
        assert mock_record.stack_id == stack_id
        assert mock_record.n_allocations == n_allocations
        assert mock_record.stack_trace() == stack
        assert mock_record.stack_trace(max_stacks=1) == ["stack 0"]

    def test_looks_like_AllocationRecord(self):
        tid = 0
        address = 0x1140000
        size = 1024
        allocator = AllocatorType.MALLOC
        stack_id = 1
        n_allocations = 1
        stack = ["i'm stack"]

        record = AllocationRecord(
            (tid, address, size, allocator, stack_id, n_allocations)
        )
        mock_record = MockAllocationRecord(
            tid, address, size, allocator, stack_id, n_allocations, stack
        )

        assert mock_record.tid == record.tid == tid
        assert mock_record.address == record.address == address
        assert mock_record.size == record.size == size
        assert mock_record.allocator == record.allocator == allocator
        assert mock_record.stack_id == record.stack_id == stack_id
        assert mock_record.n_allocations == record.n_allocations == n_allocations

    def test_equality(self):
        one = MockAllocationRecord(1, 0x1000000, 0, AllocatorType.FREE, 0, 0, [])
        two = MockAllocationRecord(1, 0x1000000, 0, AllocatorType.FREE, 0, 0, [])
        three = MockAllocationRecord(2, 0x1000000, 0, AllocatorType.FREE, 0, 0, [])

        assert one == one
        assert one == two
        assert one != three

        assert two == one
        assert two == two
        assert two != three

        assert three != one
        assert three != two
        assert three == three
