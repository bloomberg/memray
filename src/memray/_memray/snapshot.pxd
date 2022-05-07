from _memray.records cimport Allocation
from libcpp cimport bool
from libcpp.vector cimport vector


cdef extern from "snapshot.h" namespace "memray::api":
    cdef struct HighWaterMark:
        size_t index
        size_t peak_memory

    cdef cppclass reduced_snapshot_map_t:
        pass

    cdef cppclass SnapshotAllocationAggregator:
        void addAllocation(const Allocation&) except+
        reduced_snapshot_map_t getSnapshotAllocations(bool merge_threads) except+

    cdef cppclass StreamingAllocationAggregator:
        void addAllocation(const Allocation&) except+
        reduced_snapshot_map_t getHighWaterMarkAllocations(bool merge_threads) except+
        reduced_snapshot_map_t getLeakedAllocations(bool merge_threads) except+
        HighWaterMark getHighWaterMark() except+

    object Py_ListFromSnapshotAllocationRecords(const reduced_snapshot_map_t&) except+
    object Py_GetSnapshotAllocationRecords(const vector[Allocation]& all_records, size_t record_index, bool merge_threads) except+
