import logging
import threading
from contextlib import contextmanager

from libcpp.string cimport string as cppstring

from _pensieve.tracking_api cimport attach_init, attach_fini, install_trace_function
from _pensieve.tracking_api cimport get_allocation_records as _get_allocation_records
from _pensieve.logging cimport initializePythonLoggerInterface

initializePythonLoggerInterface()

LOGGER = logging.getLogger(__file__)
logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s(%(funcName)s): %(message)s",
)

cdef api void log_with_python(cppstring message, int level):
    LOGGER.log(level, message)


@contextmanager
def tracker():
    attach_init()
    yield
    attach_fini()


def start_thread_trace(frame, event, arg):
    if event in {"call", "c_call"}:
        install_trace_function()
    return start_thread_trace

def get_allocation_records():
    return _get_allocation_records()
