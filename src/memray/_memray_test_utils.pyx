"""Utilities used only by memray's test suite.

If you make changes to this file that move functions around, you will need to
change line numbers in test files as well.
"""
import sys

from posix.mman cimport MAP_ANONYMOUS
from posix.mman cimport MAP_FAILED
from posix.mman cimport MAP_SHARED
from posix.mman cimport PROT_WRITE
from posix.mman cimport mmap
from posix.mman cimport munmap
from posix.unistd cimport read
from posix.unistd cimport write

from _memray.alloc cimport PyMem_Calloc
from _memray.alloc cimport PyMem_Free
from _memray.alloc cimport PyMem_Malloc
from _memray.alloc cimport PyMem_RawCalloc
from _memray.alloc cimport PyMem_RawFree
from _memray.alloc cimport PyMem_RawMalloc
from _memray.alloc cimport PyMem_RawRealloc
from _memray.alloc cimport PyMem_Realloc
from _memray.alloc cimport PyObject_Calloc
from _memray.alloc cimport PyObject_Free
from _memray.alloc cimport PyObject_Malloc
from _memray.alloc cimport PyObject_Realloc
from _memray.alloc cimport aligned_alloc
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
from cpython.pylifecycle cimport Py_FinalizeEx
from libc.errno cimport errno
from libc.stdint cimport uintptr_t
from libc.stdlib cimport exit as _exit
from libcpp.vector cimport vector

from ._destination import Destination

IF UNAME_SYSNAME == "Linux":
    cdef extern from "sys/prctl.h":
        int prctl(int, char*, char*, char*, char*)


def set_thread_name(new_name):
    cdef int PR_SET_NAME = 15
    IF UNAME_SYSNAME == "Linux":
        return prctl(PR_SET_NAME, new_name, NULL, NULL, NULL)
    ELSE:
        return None


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
        return self.ptr != NULL

    def calloc(self, size_t size):
        self.ptr = calloc(1, size)
        return self.ptr != NULL

    def realloc(self, size_t size):
        self.ptr = malloc(1)
        self.ptr = realloc(self.ptr, size)
        return self.ptr != NULL

    def posix_memalign(self, size_t size):
        rc = posix_memalign(&self.ptr, sizeof(void*), size)
        return rc == 0 and self.ptr != NULL

    def aligned_alloc(self, size_t size):
        self.ptr = aligned_alloc(sizeof(void*), size)
        return self.ptr != NULL

    def memalign(self, size_t size):
        self.ptr = memalign(sizeof(void*), size)
        return self.ptr != NULL

    def valloc(self, size_t size):
        self.ptr = valloc(size)
        return self.ptr != NULL

    def pvalloc(self, size_t size):
        self.ptr = pvalloc(size)
        return self.ptr != NULL

    def run_in_pthread(self, callback):
        cdef pthread_t thread
        cdef int ret = pthread_create(&thread, NULL, &_pthread_worker, <void*>callback)
        if ret != 0:
            raise RuntimeError("Failed to create thread")
        with nogil:
            pthread_join(thread, NULL)


cpdef enum PymallocDomain:
    PYMALLOC_RAW = 1
    PYMALLOC_MEM = 2
    PYMALLOC_OBJECT = 3


cdef class PymallocMemoryAllocator:
    cdef void* ptr
    cdef PymallocDomain domain

    def __cinit__(self, PymallocDomain domain):
        self.ptr = NULL
        self.domain = domain

    def free(self):
        if self.ptr == NULL:
            raise RuntimeError("Pointer cannot be NULL")
        if self.domain == PYMALLOC_RAW:
            PyMem_RawFree(self.ptr)
        elif self.domain == PYMALLOC_MEM:
            PyMem_Free(self.ptr)
        elif self.domain == PYMALLOC_OBJECT:
            PyObject_Free(self.ptr)
        else:
            raise RuntimeError("Invlid pymalloc domain")
        self.ptr = NULL

    def malloc(self, size_t size):
        if self.domain == PYMALLOC_RAW:
            self.ptr = PyMem_RawMalloc(size)
        elif self.domain == PYMALLOC_MEM:
            self.ptr = PyMem_Malloc(size)
        elif self.domain == PYMALLOC_OBJECT:
            self.ptr = PyObject_Malloc(size)
        else:
            raise RuntimeError("Invlid pymalloc domain")

        return self.ptr != NULL

    def calloc(self, size_t size):
        if self.domain == PYMALLOC_RAW:
            self.ptr = PyMem_RawCalloc(1, size)
        elif self.domain == PYMALLOC_MEM:
            self.ptr = PyMem_Calloc(1, size)
        elif self.domain == PYMALLOC_OBJECT:
            self.ptr = PyObject_Calloc(1, size)
        else:
            raise RuntimeError("Invlid pymalloc domain")

        return self.ptr != NULL

    def realloc(self, size_t size):
        if self.domain == PYMALLOC_RAW:
            self.ptr = PyMem_RawRealloc(self.ptr, size)
        elif self.domain == PYMALLOC_MEM:
            self.ptr = PyMem_Realloc(self.ptr, size)
        elif self.domain == PYMALLOC_OBJECT:
            self.ptr = PyObject_Realloc(self.ptr, size)
        else:
            raise RuntimeError("Invlid pymalloc domain")

        return self.ptr != NULL

cdef do_not_optimize_ptr(void* ptr):
    return ptr == <void*>(1)

def _cython_nested_allocation(allocator_fn, size):
    allocator_fn(size)
    cdef void* p = valloc(size);
    do_not_optimize_ptr(p)
    free(p)

cdef class MmapAllocator:
    cdef uintptr_t _address

    def __cinit__(self, size, address=0):
        cdef uintptr_t start_address = address

        self._address = <uintptr_t>mmap(<void *>start_address, size, PROT_WRITE, MAP_SHARED | MAP_ANONYMOUS, -1, 0)
        if <void *>self._address == MAP_FAILED:
            raise MemoryError

    @property
    def address(self):
        return self._address

    def munmap(self, length, offset=0):
        cdef uintptr_t addr = self._address + <uintptr_t> offset
        cdef int ret = munmap(<void *>addr, length)
        if ret != 0:
            raise MemoryError(f"munmap rcode: {ret} errno: {errno}")

cdef void* _pthread_worker(void* arg) noexcept with gil:
    (<object> arg)()

def _cython_allocate_in_two_places(size_t size):
    cdef void* a = allocation_place_a(size)
    do_not_optimize_ptr(a)
    cdef void* b = allocation_place_b(size)
    do_not_optimize_ptr(b)
    free(a)
    free(b)

cdef void* allocation_place_a(size_t size):
    return valloc(size)

cdef void* allocation_place_b(size_t size):
    return valloc(size)

def function_caller(func):
    func()

def allocate_without_gil_held(int wake_up_main_fd, int wake_up_thread_fd):
    cdef char buf = 0
    cdef int write_rc = 0
    cdef int read_rc = 0
    cdef void* p = NULL
    with nogil:
        while write_rc != 1:
            write_rc = write(wake_up_main_fd, &buf, 1)
        while read_rc != 1:
            read_rc = read(wake_up_thread_fd, &buf, 1)
        p = valloc(1234)
    do_not_optimize_ptr(p)
    free(p)
    p = valloc(4321)
    do_not_optimize_ptr(p)
    free(p)

def allocate_cpp_vector(size_t size):
    cdef vector[int] v;
    cdef size_t nelems = <size_t>(size / sizeof(int))
    v.reserve(nelems)
    return v.size()


def fill_cpp_vector(size_t size):
    cdef vector[int] v
    cdef size_t nelems = <size_t>(size / sizeof(int))
    for i in range(nelems):
        v.push_back(i)
    return v.size()

def exit(bint py_finalize=False):
    if py_finalize:
        Py_FinalizeEx()
        _exit(0)
    else:
        with nogil:
            _exit(0)


cdef class PrimeCaches:
    cdef object old_profile
    def __enter__(self):
        self.old_profile = sys.getprofile()
        sys.setprofile(lambda *args: None)
        return self
    def __exit__(self, *args):
        sys.setprofile(self.old_profile)
