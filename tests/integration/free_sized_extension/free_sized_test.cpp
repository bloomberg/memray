#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <cassert>
#include <cstdlib>

#ifdef __linux__
#include <malloc.h>
#endif

namespace {  // unnamed

extern "C" void
test_free_sized()
{
    void* ptr = malloc(1024);
    assert(ptr != nullptr);
    
    #ifdef __GLIBC__
    extern void free_sized(void* ptr, size_t size);
    free_sized(ptr, 1024);
    #else
    free(ptr);
    #endif
}

extern "C" void
test_free_aligned_sized()
{
    void* ptr = aligned_alloc(64, 1024);
    assert(ptr != nullptr);
    
    #ifdef __GLIBC__
    extern void free_aligned_sized(void* ptr, size_t alignment, size_t size);
    free_aligned_sized(ptr, 64, 1024);
    #else
    free(ptr);
    #endif
}

extern "C" void
test_both_free_functions()
{
    void* ptr1 = malloc(512);
    assert(ptr1 != nullptr);
    #ifdef __GLIBC__
    extern void free_sized(void* ptr, size_t size);
    free_sized(ptr1, 512);
    #else
    free(ptr1);
    #endif
    
    void* ptr2 = aligned_alloc(32, 256);
    assert(ptr2 != nullptr);
    #ifdef __GLIBC__
    extern void free_aligned_sized(void* ptr, size_t alignment, size_t size);
    free_aligned_sized(ptr2, 32, 256);
    #else
    free(ptr2);
    #endif
}

PyObject*
run_free_sized_test(PyObject*, PyObject*)
{
    test_free_sized();
    Py_RETURN_NONE;
}

PyObject*
run_free_aligned_sized_test(PyObject*, PyObject*)
{
    test_free_aligned_sized();
    Py_RETURN_NONE;
}

PyObject*
run_both_tests(PyObject*, PyObject*)
{
    test_both_free_functions();
    Py_RETURN_NONE;
}

}  // unnamed namespace

static PyMethodDef
free_sized_methods[] = {
    {"run_free_sized_test", run_free_sized_test, METH_NOARGS, "Test free_sized function"},
    {"run_free_aligned_sized_test", run_free_aligned_sized_test, METH_NOARGS, "Test free_aligned_sized function"},
    {"run_both_tests", run_both_tests, METH_NOARGS, "Test both free functions"},
    {nullptr, nullptr, 0, nullptr}
};

static PyModuleDef
free_sized_module = {
    PyModuleDef_HEAD_INIT,
    "free_sized_test",
    "Test module for free_sized and free_aligned_sized functions",
    -1,
    free_sized_methods,
    nullptr,
    nullptr,
    nullptr,
    nullptr
};

PyMODINIT_FUNC
PyInit_free_sized_test()
{
    return PyModule_Create(&free_sized_module);
}
