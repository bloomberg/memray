import logging
from contextlib import contextmanager

from libcpp.string cimport string as cppstring

from _pensieve.tracking_api cimport attach_init, attach_fini
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
