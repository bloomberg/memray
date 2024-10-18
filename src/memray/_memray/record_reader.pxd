from _memray.records cimport AggregatedAllocation
from _memray.records cimport Allocation
from _memray.records cimport HeaderRecord
from _memray.records cimport MemoryRecord
from _memray.records cimport MemorySnapshot
from _memray.records cimport TrackedObject
from _memray.records cimport optional_location_id_t
from _memray.source cimport Source
from libcpp cimport bool
from libcpp.memory cimport unique_ptr
from libcpp.string cimport string
from libcpp.vector cimport vector


cdef extern from "record_reader.h" namespace "memray::api":
    cdef enum RecordResult 'memray::api::RecordReader::RecordResult':
        RecordResultAllocationRecord 'memray::api::RecordReader::RecordResult::ALLOCATION_RECORD'
        RecordResultAggregatedAllocationRecord 'memray::api::RecordReader::RecordResult::AGGREGATED_ALLOCATION_RECORD'
        RecordResultMemoryRecord 'memray::api::RecordReader::RecordResult::MEMORY_RECORD'
        RecordResultMemorySnapshot 'memray::api::RecordReader::RecordResult::MEMORY_SNAPSHOT'
        RecordResultError 'memray::api::RecordReader::RecordResult::ERROR'
        RecordResultEndOfFile 'memray::api::RecordReader::RecordResult::END_OF_FILE'
        RecordResultObjectRecord 'memray::api::RecordReader::RecordResult::OBJECT_RECORD'

    cdef cppclass RecordReader:
        RecordReader(unique_ptr[Source]) except+
        RecordReader(unique_ptr[Source], bool track_stacks) except+
        RecordReader(unique_ptr[Source], bool track_stacks, bool track_object_lifetimes) except+
        void close()
        bool isOpen() const
        RecordResult nextRecord() except+
        object Py_GetStackFrame(size_t frame_id) except+
        object Py_GetStackFrame(size_t frame_id, size_t max_stacks) except+
        object Py_GetStackFrameAndEntryInfo(
            size_t frame_id, vector[unsigned char]* is_entry_frame
        ) except+
        object Py_GetStackFrameAndEntryInfo(
            size_t frame_id, vector[unsigned char]* is_entry_frame, size_t max_stacks
        ) except+
        object Py_GetNativeStackFrame(int frame_id, size_t generation) except+
        object Py_GetNativeStackFrame(int frame_id, size_t generation, size_t max_stacks) except+
        optional_location_id_t getLatestPythonLocationId(const Allocation&) except+
        object Py_GetLocation(optional_location_id_t frame) except+
        HeaderRecord getHeader()
        size_t getMainThreadTid()
        size_t getSkippedFramesOnMainThread()
        object dumpAllRecords() except+
        string getThreadName(long int tid) except+
        Allocation getLatestAllocation()
        MemoryRecord getLatestMemoryRecord()
        AggregatedAllocation getLatestAggregatedAllocation()
        MemorySnapshot getLatestMemorySnapshot()
        TrackedObject getLatestObject()
