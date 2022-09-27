from _memray.records cimport Allocation
from _memray.records cimport optional_frame_id_t
from libc.stdint cimport uint64_t
from libcpp cimport bool
from libcpp.unordered_map cimport unordered_map
from libcpp.utility cimport pair
from libcpp.vector cimport vector


cdef extern from "snapshot.h" namespace "memray::api":
    cdef struct HighWatermark:
        size_t index
        size_t peak_memory

    cdef cppclass HighWatermarkFinder:
        void processAllocation(const Allocation&) except+
        HighWatermark getHighWatermark()
        size_t getCurrentWatermark()

    cdef cppclass reduced_snapshot_map_t:
        pass

    cdef cppclass AbstractAggregator:
        void addAllocation(const Allocation&) except+
        reduced_snapshot_map_t getSnapshotAllocations(bool merge_threads) except+

    cdef cppclass TemporaryAllocationsAggregator(AbstractAggregator):
        TemporaryAllocationsAggregator(size_t max_items)

    cdef cppclass SnapshotAllocationAggregator(AbstractAggregator):
        pass

    cdef cppclass LocationKey:
        size_t python_frame_id
        size_t native_frame_id
        unsigned long thread_id

    cdef cppclass index_thread_pair_hash:
        pass

    cdef cppclass AllocationStatsAggregator:
        void addAllocation(const Allocation&, optional_frame_id_t python_frame_id) except+
        uint64_t totalAllocations()
        uint64_t totalBytesAllocated()
        uint64_t peakBytesAllocated()
        const unordered_map[size_t, uint64_t]& allocationCountBySize()
        const unordered_map[int, uint64_t]& allocationCountByAllocator()
        vector[pair[uint64_t, optional_frame_id_t]] topLocationsBySize(size_t num_largest) except+
        vector[pair[uint64_t, optional_frame_id_t]] topLocationsByCount(size_t num_largest) except+

    object Py_ListFromSnapshotAllocationRecords(const reduced_snapshot_map_t&) except+
    object Py_GetSnapshotAllocationRecords(const vector[Allocation]& all_records, size_t record_index, bool merge_threads) except+
