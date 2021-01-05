from libcpp.string cimport string
from libcpp.vector cimport vector

from _pensieve.records cimport AllocationRecord

cdef extern from "record_reader.h" namespace "pensieve::api":
    cdef cppclass RecordReader:
        RecordReader(const string& file_name) except+
        unsigned long allocations()
        object nextAllocation() except+
        object get_stack_frame(int frame_id, size_t max_stacks)
