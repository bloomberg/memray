from _memray.records cimport Allocation
from libcpp cimport bool


cdef extern from "hooks.h" namespace "memray::hooks":
    cdef cppclass Allocator:
        pass

    bool isDeallocator(const Allocator& allocator)
