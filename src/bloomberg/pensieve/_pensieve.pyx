import logging

from libcpp.string cimport string as cppstring

from _pensieve.tracking_api cimport attach_init, attach_fini, install_trace_function
from _pensieve.tracking_api cimport Tracker as NativeTracker
from _pensieve.logging cimport initializePythonLoggerInterface
from _pensieve.alloc cimport calloc, free, malloc, realloc, posix_memalign, memalign, valloc, pvalloc
from _pensieve.pthread cimport pthread_create, pthread_join, pthread_t

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
    cdef object _allocation_records

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
        self._allocation_records = self._tracker.getAllocationRecords()
        self._tracker.clearAllocationRecords()

    def get_allocation_records(self):
        return self._allocation_records


def start_thread_trace(frame, event, arg):
    if event in {"call", "c_call"}:
        install_trace_function()
    return start_thread_trace


cdef class MemoryAllocator:
    cdef void* ptr

    def __cinit__(self):
        self.ptr = NULL

    def free(self):
        if self.ptr == NULL:
            raise RuntimeError("Pointer cannot be NULL")
        free(self.ptr)
        self.ptr = NULL

    def malloc(self, size_t size):
        self.ptr = malloc(size)

    def calloc(self, size_t size):
        self.ptr = calloc(1, size)

    def realloc(self, size_t size):
        self.ptr = malloc(1)
        self.ptr = realloc(self.ptr, size)

    def posix_memalign(self, size_t size):
        posix_memalign(&self.ptr, sizeof(void*), size)

    def memalign(self, size_t size):
        self.ptr = memalign(sizeof(void*), size)

    def valloc(self, size_t size):
        self.ptr = valloc(size)

    def pvalloc(self, size_t size):
        self.ptr = pvalloc(size)

    def run_in_pthread(self, callback):
        cdef pthread_t thread
        cdef int ret = pthread_create(&thread, NULL, &_pthread_worker, <void*>callback)
        if ret != 0:
            raise RuntimeError("Failed to create thread")
        with nogil:
            pthread_join(thread, NULL)


cdef void* _pthread_worker(void* arg) with gil:
    (<object> arg)()