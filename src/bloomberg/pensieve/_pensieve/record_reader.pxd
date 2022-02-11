from _pensieve.records cimport Allocation
from _pensieve.records cimport HeaderRecord
from _pensieve.source cimport Source
from libcpp cimport bool
from libcpp.memory cimport unique_ptr
from libcpp.string cimport string
from libcpp.vector cimport vector


cdef extern from "record_reader.h" namespace "pensieve::api":
    cdef cppclass RecordReader:
        RecordReader(unique_ptr[Source]) except+
        void close()
        bool isOpen() const
        bool nextAllocationRecord(Allocation* allocation) except+
        object Py_GetStackFrame(int frame_id) except+
        object Py_GetStackFrame(int frame_id, size_t max_stacks) except+
        object Py_GetNativeStackFrame(int frame_id, size_t generation) except+
        object Py_GetNativeStackFrame(int frame_id, size_t generation, size_t max_stacks) except+
        size_t totalAllocations()
        HeaderRecord getHeader()
        object dumpAllRecords() except+
        string getThreadName(long int tid) except+
