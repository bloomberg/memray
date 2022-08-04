from _memray.record_writer cimport RecordWriter
from libcpp cimport bool
from libcpp.memory cimport unique_ptr
from libcpp.string cimport string


cdef extern from "tracking_api.h" namespace "memray::tracking_api":
    void forget_python_stack() except*
    void install_trace_function() except*
    void begin_tracking_greenlets() except+
    void handle_greenlet_switch(object, object) except+

    cdef cppclass Tracker:
        @staticmethod
        object createTracker(
            unique_ptr[RecordWriter] record_writer,
            bool native_traces,
            unsigned int memory_interval,
            bool follow_fork,
            bool trace_pymalloc,
        ) except+

        @staticmethod
        object destroyTracker() except +

        @staticmethod
        Tracker* getTracker()
