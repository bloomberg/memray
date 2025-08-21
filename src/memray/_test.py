from typing import Callable

from ._test_utils import MemoryAllocator as _MemoryAllocator
from ._test_utils import MmapAllocator
from ._test_utils import PrimeCaches
from ._test_utils import PymallocDomain
from ._test_utils import PymallocMemoryAllocator
from ._test_utils import _cython_allocate_in_two_places
from ._test_utils import _cython_nested_allocation
from ._test_utils import allocate_cpp_vector
from ._test_utils import allocate_without_gil_held
from ._test_utils import exit
from ._test_utils import fill_cpp_vector
from ._test_utils import function_caller
from ._test_utils import set_thread_name


class MemoryAllocator:
    def __init__(self) -> None:
        self.allocator = _MemoryAllocator()

    def free(self) -> None:
        return self.allocator.free()

    def malloc(self, size: int) -> bool:
        return self.allocator.malloc(size)

    def calloc(self, size: int) -> bool:
        return self.allocator.calloc(size)

    def realloc(self, size: int) -> bool:
        return self.allocator.realloc(size)

    def posix_memalign(self, size: int) -> bool:
        return self.allocator.posix_memalign(size)

    def aligned_alloc(self, size: int) -> bool:
        return self.allocator.aligned_alloc(size)

    def memalign(self, size: int) -> bool:
        return self.allocator.memalign(size)

    def valloc(self, size: int) -> bool:
        return self.allocator.valloc(size)

    def pvalloc(self, size: int) -> bool:
        return self.allocator.pvalloc(size)

    def run_in_pthread(self, callback: Callable[[], None]) -> None:
        return self.allocator.run_in_pthread(callback)


__all__ = [
    "allocate_cpp_vector",
    "MemoryAllocator",
    "MmapAllocator",
    "PymallocDomain",
    "PymallocMemoryAllocator",
    "_cython_allocate_in_two_places",
    "_cython_nested_allocation",
    "allocate_without_gil_held",
    "function_caller",
    "set_thread_name",
    "fill_cpp_vector",
    "exit",
    "PrimeCaches",
]
