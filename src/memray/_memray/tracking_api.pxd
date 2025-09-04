from _memray.record_writer cimport RecordWriter
from cpython cimport PyObject
from libc.stdint cimport uint64_t
from libcpp cimport bool
from libcpp.memory cimport unique_ptr
from libcpp.string cimport string
from libcpp.unordered_set cimport unordered_set


cdef extern from "tracking_api.h" namespace "memray::tracking_api":
    void set_up_pthread_fork_handlers() except+
    void install_trace_function() except*

    cdef cppclass RecursionGuard:
        RecursionGuard()

    cdef cppclass Tracker:
        @staticmethod
        object createTracker(
            unique_ptr[RecordWriter] record_writer,
            bool native_traces,
            unsigned int memory_interval,
            bool follow_fork,
            bool trace_pymalloc,
            bool reference_tracking,
        ) except+

        @staticmethod
        object destroyTracker() except +

        @staticmethod
        Tracker* getTracker()

        @staticmethod
        void beginTrackingGreenlets() except+

        @staticmethod
        void handleGreenletSwitch(object, object) except+

        @staticmethod
        void registerThreadNameById(uint64_t, const char*) except+

        @staticmethod
        void childFork() noexcept nogil

        @staticmethod
        unordered_set[PyObject*] getSurvivingObjects() except+
