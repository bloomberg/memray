from libcpp.string cimport string
from libcpp.vector cimport vector
from libcpp cimport bool

from _pensieve.records cimport Allocation

cdef extern from "record_reader.h" namespace "pensieve::api":
    cdef cppclass RecordReader:
        RecordReader(const string& file_name) 
        bool nextAllocationRecord(Allocation* allocation) except+
        object Py_GetStackFrame(int frame_id) except+
        object Py_GetStackFrame(int frame_id, size_t max_stacks) except+
        object Py_GetNativeStackFrame(int frame_id, size_t generation) except+
        object Py_GetNativeStackFrame(int frame_id, size_t generation, size_t max_stacks) except+
        size_t totalAllocations()

    size_t getHighWatermarkIndex(const vector[Allocation]& records) except+
    object Py_GetSnapshotAllocationRecords(const vector[Allocation]& all_records, size_t record_index) except+
