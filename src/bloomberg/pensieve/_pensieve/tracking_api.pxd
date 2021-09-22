from _pensieve.record_writer cimport RecordWriter
from libcpp cimport bool
from libcpp.memory cimport unique_ptr
from libcpp.string cimport string


cdef extern from "tracking_api.h" namespace "pensieve::tracking_api":
    void install_trace_function() except*

    cdef cppclass Tracker:
        Tracker(unique_ptr[RecordWriter] record_writer, bool native_traces) except+

        @staticmethod
        Tracker* getTracker()
        void flush()
        void deactivate()
