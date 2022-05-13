cdef extern from "alloc.h" nogil:
    void *calloc (size_t count, size_t eltsize)
    void free (void *ptr)
    void *malloc (size_t size)
    int posix_memalign(void** memptr, size_t alignment, size_t size)
    void* aligned_alloc(size_t alignment, size_t size)
    void *realloc (void *ptr, size_t newsize)
    void* valloc(size_t size)
    void* memalign(size_t alignment, size_t size)
    void* pvalloc(size_t size)

cdef extern from "Python.h":
    void* PyMem_RawMalloc(size_t n) nogil
    void* PyMem_RawCalloc(size_t nelem, size_t elsize) nogil
    void* PyMem_RawRealloc(void *p, size_t n) nogil
    void PyMem_RawFree(void *p) nogil

    void* PyMem_Malloc(size_t n)
    void* PyMem_Calloc(size_t nelem, size_t elsize)
    void* PyMem_Realloc(void *p, size_t n)
    void PyMem_Free(void *p)

    void* PyObject_Malloc(size_t size)
    void* PyObject_Calloc(size_t nelem, size_t elsize)
    void* PyObject_Realloc(void *ptr, size_t new_size)
    void PyObject_Free(void *ptr)
