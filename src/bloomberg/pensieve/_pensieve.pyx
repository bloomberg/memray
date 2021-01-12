import pathlib
import sys
import logging

cimport cython

from libcpp.string cimport string as cppstring
from libcpp.memory cimport shared_ptr, make_shared

from _pensieve.tracking_api cimport install_trace_function
from _pensieve.tracking_api cimport Tracker as NativeTracker
from _pensieve.logging cimport initializePythonLoggerInterface
from _pensieve.alloc cimport calloc, free, malloc, realloc, posix_memalign, memalign, valloc, pvalloc
from _pensieve.pthread cimport pthread_create, pthread_join, pthread_t
from _pensieve.record_reader cimport RecordReader

initializePythonLoggerInterface()

LOGGER = logging.getLogger(__file__)

cdef api void log_with_python(cppstring message, int level):
    LOGGER.log(level, message)


cpdef enum AllocatorType:
    MALLOC = 1
    FREE = 2
    CALLOC = 3
    REALLOC = 4
    POSIX_MEMALIGN = 5
    MEMALIGN = 6
    VALLOC = 7
    PVALLOC = 8
    MMAP = 9
    MUNMAP = 10


def size_fmt(num, suffix='B'):
    for unit in ['','K','M','G','T','P','E','Z']:
        if abs(num) < 1024.0:
            return f"{num:5.3f}{unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f}Y{suffix}"


@cython.freelist(1024)
cdef class AllocationRecord:
    cdef object _tuple
    cdef object _stack_trace
    cdef shared_ptr[RecordReader] _reader

    def __init__(self, record):
        self._tuple = record
        self._stack_trace = None

    def __eq__(self, other):
        cdef AllocationRecord _other
        if isinstance(other, AllocationRecord):
            _other = other
            return self._tuple == _other._tuple
        return NotImplemented

    def __hash__(self):
        return hash(self._tuple)

    @property
    def tid(self):
        return self._tuple[0]

    @property
    def address(self):
        return self._tuple[1]

    @property
    def size(self):
        return self._tuple[2]

    @property
    def allocator(self):
        return self._tuple[3]

    @property
    def stack_id(self):
        return self._tuple[4]

    def stack_trace(self, size_t max_stacks=0):
        if self._stack_trace is None:
            self._stack_trace = self._reader.get().get_stack_frame(self._tuple[4], max_stacks)
        return self._stack_trace

    def __repr__(self):
        return (f"AllocationRecord<tid={hex(self.tid)}, address={hex(self.address)}, "
                f"size={'N/A' if not self.size else size_fmt(self.size)}, allocator={self.allocator!r}>")


cdef class Tracker:
    cdef NativeTracker* _tracker
    cdef object _previous_profile_func
    cdef cppstring _output_path
    cdef shared_ptr[RecordReader] _reader

    def __cinit__(self, object file_name):
        self._output_path = str(file_name)

    def __enter__(self):
        if pathlib.Path(self._output_path).exists():
            raise OSError(f"Output file {self._output_path} already exists")
        self._previous_profile_func = sys.getprofile()
        self._tracker = new NativeTracker(self._output_path)

        return self

    def __del__(self):
        self._reader.reset()

    def __exit__(self, exc_type, exc_value, exc_traceback):
        del self._tracker
        sys.setprofile(self._previous_profile_func)

    def get_allocation_records(self):
        self._reader = make_shared[RecordReader](self._output_path)
        cdef RecordReader* reader = self._reader.get()
        while True:
            alloc = AllocationRecord(reader.nextAllocation())
            (<AllocationRecord>alloc)._reader = self._reader
            yield alloc

    @property
    def total_allocations(self):
        if self._reader == NULL:
            self._reader = make_shared[RecordReader](self._output_path)
        cdef RecordReader* reader = self._reader.get()
        return reader.totalAllocations();

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
