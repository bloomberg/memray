from _pensieve.records cimport Allocation
from _pensieve.records cimport HeaderRecord
from libcpp cimport bool
from libcpp.string cimport string
from libcpp.vector cimport vector


cdef extern from "record_reader.h" namespace "pensieve::api":
    cdef struct HighWatermark:
        size_t index
        size_t peak_memory

    cdef cppclass RecordReader:
        RecordReader(const string& file_name) except+
        void close()
        bool isOpen() const
        bool nextAllocationRecord(Allocation* allocation) except+
        object Py_GetStackFrame(int frame_id) except+
        object Py_GetStackFrame(int frame_id, size_t max_stacks) except+
        object Py_GetNativeStackFrame(int frame_id, size_t generation) except+
        object Py_GetNativeStackFrame(int frame_id, size_t generation, size_t max_stacks) except+
        size_t totalAllocations()
        HeaderRecord getHeader()


    HighWatermark getHighWatermark(const vector[Allocation]& records) except+
    object Py_GetSnapshotAllocationRecords(const vector[Allocation]& all_records, size_t record_index, bool merge_threads) except+
