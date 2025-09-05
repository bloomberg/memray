#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <assert.h>
#include <stdlib.h>
#include <dlfcn.h>

__attribute__((weak)) void free_sized(void* ptr, size_t size);
__attribute__((weak)) void free_aligned_sized(void* ptr, size_t alignment, size_t size);

// Check if C23 functions are available
static int functions_available = -1;

static void check_functions_available(void) {
    if (functions_available == -1) {
        functions_available = (free_sized != NULL && free_aligned_sized != NULL);
    }
}

// Structure to hold allocation info
void*
test_free_sized(void)
{
    void* address;

    check_functions_available();
    if (!functions_available) {
        return address;
    }

    void* ptr = malloc(1024);
    assert(ptr != NULL);

    address = ptr;

    free_sized(ptr, 1024);
    return address;
}

void*
test_free_aligned_sized(void)
{
    void* address;

    check_functions_available();
    if (!functions_available) {
        return address;
    }

    void* ptr = aligned_alloc(64, 1024);
    assert(ptr != NULL);

    address = ptr;

    free_aligned_sized(ptr, 64, 1024);
    return address;
}

void*
test_both_free_functions(void)
{
    void* address;

    check_functions_available();
    if (!functions_available) {
        return NULL;
    }

    void* ptr1 = malloc(512);
    assert(ptr1 != NULL);
    free_sized(ptr1, 512);

    void* ptr2 = aligned_alloc(32, 256);
    assert(ptr2 != NULL);
    free_aligned_sized(ptr2, 32, 256);

    address = ptr2;

    return address;
}

PyObject*
run_free_sized_test(PyObject* self, PyObject* args)
{
    check_functions_available();
    if (!functions_available) {
        Py_RETURN_NONE;
    }

    void* address = test_free_sized();

    // Return address for verification
    PyObject* result = Py_BuildValue("(KII)", address);
    return result;
}

PyObject*
run_free_aligned_sized_test(PyObject* self, PyObject* args)
{
    check_functions_available();
    if (!functions_available) {
        Py_RETURN_NONE;
    }

    void* address = test_free_aligned_sized();

    PyObject* result = Py_BuildValue("(KII)", address);
    return result;
}

PyObject*
run_both_tests(PyObject* self, PyObject* args)
{
    check_functions_available();
    if (!functions_available) {
        Py_RETURN_NONE; // Skip test if functions not available
    }

    void* address = test_both_free_functions();

    PyObject* result = Py_BuildValue("(KII)", address);
    return result;
}

static PyMethodDef
free_sized_methods[] = {
    {"run_free_sized_test", run_free_sized_test, METH_NOARGS, "Test free_sized function"},
    {"run_free_aligned_sized_test", run_free_aligned_sized_test, METH_NOARGS, "Test free_aligned_sized function"},
    {"run_both_tests", run_both_tests, METH_NOARGS, "Test both free functions"},
    {NULL, NULL, 0, NULL}
};

static PyModuleDef
free_sized_module = {
    PyModuleDef_HEAD_INIT,
    "free_sized_test",
    "Test module for free_sized and free_aligned_sized functions",
    -1,
    free_sized_methods,
    NULL,
    NULL,
    NULL,
    NULL
};

PyMODINIT_FUNC
PyInit_free_sized_test(void)
{
    return PyModule_Create(&free_sized_module);
}
