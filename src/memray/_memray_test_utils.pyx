"""Utilities used only by memray's test suite.

If you make changes to this file that move functions around, you will need to
change line numbers in test files as well.
"""
from posix.mman cimport MAP_ANONYMOUS
from posix.mman cimport MAP_FAILED
from posix.mman cimport MAP_SHARED
from posix.mman cimport PROT_WRITE
from posix.mman cimport mmap
from posix.mman cimport munmap

from _memray.alloc cimport calloc
from _memray.alloc cimport free
from _memray.alloc cimport malloc
from _memray.alloc cimport memalign
from _memray.alloc cimport posix_memalign
from _memray.alloc cimport pvalloc
from _memray.alloc cimport realloc
from _memray.alloc cimport valloc
from _memray.pthread cimport pthread_create
from _memray.pthread cimport pthread_join
from _memray.pthread cimport pthread_t
from libc.errno cimport errno
from libc.stdint cimport uintptr_t

from ._destination import Destination


cdef extern from "sys/prctl.h":
    int prctl(int, char*, char*, char*, char*)


def set_thread_name(new_name):
    cdef int PR_SET_NAME = 15
    return prctl(PR_SET_NAME, new_name, NULL, NULL, NULL)


cdef class MemoryAllocator:
    cdef void* ptr

    def __cinit__(self):
        self.ptr = NULL

    @cython.profile(True)
    def free(self):
        if self.ptr == NULL:
            raise RuntimeError("Pointer cannot be NULL")
        free(self.ptr)
        self.ptr = NULL

    @cython.profile(True)
    def malloc(self, size_t size):
        self.ptr = malloc(size)
        return self.ptr != NULL

    @cython.profile(True)
    def calloc(self, size_t size):
        self.ptr = calloc(1, size)
        return self.ptr != NULL

    @cython.profile(True)
    def realloc(self, size_t size):
        self.ptr = malloc(1)
        self.ptr = realloc(self.ptr, size)
        return self.ptr != NULL

    @cython.profile(True)
    def posix_memalign(self, size_t size):
        posix_memalign(&self.ptr, sizeof(void*), size)
        return self.ptr != NULL

    @cython.profile(True)
    def memalign(self, size_t size):
        self.ptr = memalign(sizeof(void*), size)
        return self.ptr != NULL

    @cython.profile(True)
    def valloc(self, size_t size):
        self.ptr = valloc(size)
        return self.ptr != NULL

    @cython.profile(True)
    def pvalloc(self, size_t size):
        self.ptr = pvalloc(size)
        return self.ptr != NULL

    @cython.profile(True)
    def run_in_pthread(self, callback):
        cdef pthread_t thread
        cdef int ret = pthread_create(&thread, NULL, &_pthread_worker, <void*>callback)
        if ret != 0:
            raise RuntimeError("Failed to create thread")
        with nogil:
            pthread_join(thread, NULL)


@cython.profile(True)
def _cython_nested_allocation(allocator_fn, size):
    allocator_fn(size)
    cdef void* p = valloc(size);
    free(p)

cdef class MmapAllocator:
    cdef uintptr_t _address

    @cython.profile(True)
    def __cinit__(self, size, address=0):
        cdef uintptr_t start_address = address

        self._address = <uintptr_t>mmap(<void *>start_address, size, PROT_WRITE, MAP_SHARED | MAP_ANONYMOUS, -1, 0)
        if <void *>self._address == MAP_FAILED:
            raise MemoryError

    @property
    def address(self):
        return self._address

    @cython.profile(True)
    def munmap(self, length, offset=0):
        cdef uintptr_t addr = self._address + <uintptr_t> offset
        cdef int ret = munmap(<void *>addr, length)
        if ret != 0:
            raise MemoryError(f"munmap rcode: {ret} errno: {errno}")

@cython.profile(True)
cdef void* _pthread_worker(void* arg) with gil:
    (<object> arg)()
