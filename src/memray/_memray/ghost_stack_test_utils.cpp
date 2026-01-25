#include "ghost_stack_test_utils.h"

#include <Python.h>
#include <cstdint>

#ifdef MEMRAY_HAS_GHOST_STACK
#    include "ghost_stack.h"
#    ifdef __APPLE__
#        include <execinfo.h>
#    else
#        define UNW_LOCAL_ONLY
#        include <libunwind.h>
#    endif
#endif

extern "C" {

PyObject*
ghost_stack_test_backtrace(void)
{
#ifdef MEMRAY_HAS_GHOST_STACK
    void* frames[256];
    size_t n = ghost_stack_backtrace(frames, 256);
    PyObject* result = PyList_New(static_cast<Py_ssize_t>(n));
    if (!result) return nullptr;
    for (size_t i = 0; i < n; i++) {
        PyObject* addr = PyLong_FromUnsignedLongLong(reinterpret_cast<uintptr_t>(frames[i]));
        if (!addr) {
            Py_DECREF(result);
            return nullptr;
        }
        PyList_SET_ITEM(result, static_cast<Py_ssize_t>(i), addr);
    }
    return result;
#else
    Py_RETURN_NONE;
#endif
}

PyObject*
libunwind_test_backtrace(void)
{
#ifdef MEMRAY_HAS_GHOST_STACK
    void* frames[256];
#    ifdef __APPLE__
    int n = backtrace(frames, 256);
#    else
    int n = unw_backtrace(frames, 256);
#    endif
    if (n < 0) n = 0;
    PyObject* result = PyList_New(static_cast<Py_ssize_t>(n));
    if (!result) return nullptr;
    for (int i = 0; i < n; i++) {
        PyObject* addr = PyLong_FromUnsignedLongLong(reinterpret_cast<uintptr_t>(frames[i]));
        if (!addr) {
            Py_DECREF(result);
            return nullptr;
        }
        PyList_SET_ITEM(result, static_cast<Py_ssize_t>(i), addr);
    }
    return result;
#else
    Py_RETURN_NONE;
#endif
}

void
ghost_stack_test_reset(void)
{
#ifdef MEMRAY_HAS_GHOST_STACK
    ghost_stack_reset();
#endif
}

void
ghost_stack_test_init(void)
{
#ifdef MEMRAY_HAS_GHOST_STACK
    ghost_stack_init(nullptr);
#endif
}

int
ghost_stack_test_has_support(void)
{
#ifdef MEMRAY_HAS_GHOST_STACK
    return 1;
#else
    return 0;
#endif
}

}  // extern "C"
