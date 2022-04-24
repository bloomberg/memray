from _memray.records cimport Allocation
from libcpp cimport bool
from libcpp.vector cimport vector


cdef extern from "snapshot.h" namespace "memray::api":
    cdef struct HighWatermark:
        size_t index
        size_t peak_memory

    cdef cppclass HighWatermarkFinder:
        void processAllocation(const Allocation&) except+
        HighWatermark getHighWatermark()

    object Py_GetSnapshotAllocationRecords(const vector[Allocation]& all_records, size_t record_index, bool merge_threads) except+
