"""Utilities / Helpers for writing tests."""

from bloomberg.pensieve import AllocatorType


def filter_relevant_allocations(records):
    relevant_records = [
        record
        for record in records
        if record.allocator in {AllocatorType.VALLOC, AllocatorType.FREE}
    ]
    alloc_addresses = {
        record.address
        for record in relevant_records
        if record.allocator == AllocatorType.VALLOC
    }
    return [record for record in relevant_records if record.address in alloc_addresses]


class MockAllocationRecord:
    """Mimics :py:class:`bloomberg.pensieve._pensieve.AllocationRecord`."""

    def __init__(self, tid, address, size, allocator, stack_id, n_allocations, stack):
        super().__init__()
        self.tid = tid
        self.address = address
        self.size = size
        self.allocator = allocator
        self.stack_id = stack_id
        self.n_allocations = n_allocations

        self._stack = stack

    def stack_trace(self, max_stacks=0):
        if max_stacks == 0:
            return self._stack
        else:
            return self._stack[:max_stacks]

    def __eq__(self, other):
        if not isinstance(other, MockAllocationRecord):
            return NotImplemented

        return (
            self.tid == other.tid
            and self.address == other.address
            and self.size == other.size
            and self.allocator == other.allocator
            and self.stack_id == other.stack_id
            and self.n_allocations == other.n_allocations
        )
