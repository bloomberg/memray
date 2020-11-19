from libcpp.memory cimport unique_ptr

from _pensieve.record_writer cimport Serializer


cdef extern from "tracking_api.h" namespace "pensieve::tracking_api":
    void install_trace_function() except*

    cdef cppclass Tracker:
        Tracker(unique_ptr[Serializer])

        @staticmethod
        Tracker* getTracker()
        void flush()
        void deactivate()
