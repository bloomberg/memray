from _pensieve.records cimport Allocation
from _pensieve.records cimport HeaderRecord
from _pensieve.records cimport MemoryRecord
from _pensieve.source cimport Source
from libcpp cimport bool
from libcpp.memory cimport unique_ptr
from libcpp.string cimport string
from libcpp.vector cimport vector


cdef extern from "record_reader.h" namespace "pensieve::api":
    cdef enum RecordResult 'pensieve::api::RecordReader::RecordResult':
        RecordResultAllocationRecord 'pensieve::api::RecordReader::RecordResult::ALLOCATION_RECORD'
        RecordResultMemoryRecord 'pensieve::api::RecordReader::RecordResult::MEMORY_RECORD'
        RecordResultError 'pensieve::api::RecordReader::RecordResult::ERROR'
        RecordResultEndOfFile 'pensieve::api::RecordReader::RecordResult::END_OF_FILE'

    cdef cppclass RecordReader:
        RecordReader(unique_ptr[Source]) except+
        void close()
        bool isOpen() const
        RecordResult nextRecord() except+
        object Py_GetStackFrame(int frame_id) except+
        object Py_GetStackFrame(int frame_id, size_t max_stacks) except+
        object Py_GetNativeStackFrame(int frame_id, size_t generation) except+
        object Py_GetNativeStackFrame(int frame_id, size_t generation, size_t max_stacks) except+
        size_t totalAllocations()
        HeaderRecord getHeader()
        object dumpAllRecords() except+
        string getThreadName(long int tid) except+
        vector[Allocation]& allocationRecords() except+
        vector[MemoryRecord]& memoryRecords() except+
