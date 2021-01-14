from libcpp.string cimport string
from libcpp.vector cimport vector

from _pensieve.records cimport AllocationRecord

cdef extern from "record_reader.h" namespace "pensieve::api":
    cdef cppclass RecordReader:
        RecordReader(const string& file_name) 
        object Py_NextAllocationRecord() except+
        object Py_GetStackFrame(int frame_id, size_t max_stacks) except+
        object Py_HighWatermarkAllocationRecords() except+
        size_t totalAllocations()
