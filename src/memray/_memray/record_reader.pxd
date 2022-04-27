from _memray.records cimport Allocation
from _memray.records cimport HeaderRecord
from _memray.records cimport MemoryRecord
from _memray.source cimport Source
from libcpp cimport bool
from libcpp.memory cimport unique_ptr
from libcpp.string cimport string
from libcpp.vector cimport vector


cdef extern from "record_reader.h" namespace "memray::api":
    cdef enum RecordResult 'memray::api::RecordReader::RecordResult':
        RecordResultAllocationRecord 'memray::api::RecordReader::RecordResult::ALLOCATION_RECORD'
        RecordResultMemoryRecord 'memray::api::RecordReader::RecordResult::MEMORY_RECORD'
        RecordResultError 'memray::api::RecordReader::RecordResult::ERROR'
        RecordResultEndOfFile 'memray::api::RecordReader::RecordResult::END_OF_FILE'

    cdef cppclass RecordReader:
        RecordReader(unique_ptr[Source]) except+
        RecordReader(unique_ptr[Source], bool track_stacks) except+
        void close()
        bool isOpen() const
        RecordResult nextRecord() except+
        object Py_GetStackFrame(int frame_id) except+
        object Py_GetStackFrame(int frame_id, size_t max_stacks) except+
        object Py_GetNativeStackFrame(int frame_id, size_t generation) except+
        object Py_GetNativeStackFrame(int frame_id, size_t generation, size_t max_stacks) except+
        HeaderRecord getHeader()
        object dumpAllRecords() except+
        string getThreadName(long int tid) except+
        Allocation getLatestAllocation()
        MemoryRecord getLatestMemoryRecord()
