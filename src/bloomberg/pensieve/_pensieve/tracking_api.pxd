from libcpp cimport bool
from libcpp.string cimport string


cdef extern from "tracking_api.h" namespace "pensieve::tracking_api":
    void install_trace_function() except*

    cdef cppclass Tracker:
        Tracker(const string& file_name, bool native_traces)

        @staticmethod
        Tracker* getTracker()
        void flush()
        void deactivate()
