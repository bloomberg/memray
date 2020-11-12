import logging
import threading
from contextlib import contextmanager

from libcpp.string cimport string as cppstring

from _pensieve.tracking_api cimport attach_init, attach_fini, install_trace_function
from _pensieve.tracking_api cimport Tracker as NativeTracker
from _pensieve.logging cimport initializePythonLoggerInterface

initializePythonLoggerInterface()

LOGGER = logging.getLogger(__file__)
logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s(%(funcName)s): %(message)s",
)

cdef api void log_with_python(cppstring message, int level):
    LOGGER.log(level, message)


cdef class Tracker:
    cdef NativeTracker* _tracker

    def __cinit__(self):
        self._tracker = NativeTracker.getTracker()
        if self._tracker is NULL:
            attach_init()
            self._tracker = NativeTracker.getTracker()
        assert(self._tracker != NULL)

    def __enter__(self):
        attach_init()
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        attach_fini()

    def get_allocation_records(self):
        if self._tracker == NULL:
            raise RuntimeError("Tracker is not active")
        return self._tracker.getAllocationRecords()


def start_thread_trace(frame, event, arg):
    if event in {"call", "c_call"}:
        install_trace_function()
    return start_thread_trace

