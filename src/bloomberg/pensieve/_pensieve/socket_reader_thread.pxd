from _pensieve.record_reader cimport RecordReader
from libcpp cimport bool
from libcpp cimport int
from libcpp.memory cimport shared_ptr


cdef extern from "socket_reader_thread.h" namespace "pensieve::socket_thread":
    cdef cppclass BackgroundSocketReader:
        BackgroundSocketReader(shared_ptr[RecordReader]) except+

        object Py_GetSnapshotAllocationRecords(bool merge_threads)
