"""Utilities / Helpers for writing tests."""


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
