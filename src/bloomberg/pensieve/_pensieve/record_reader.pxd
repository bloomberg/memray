from libcpp.string cimport string
from libcpp.vector cimport vector
from libcpp cimport bool

from _pensieve.records cimport Allocation

cdef extern from "record_reader.h" namespace "pensieve::api":
    cdef cppclass RecordReader:
        RecordReader(const string& file_name) 
        bool nextAllocationRecord(Allocation* allocation) except+
        object Py_GetStackFrame(int frame_id, size_t max_stacks) except+
        size_t totalAllocations()

    object Py_HighWatermarkAllocationRecords(vector[Allocation]& all_records) except+
