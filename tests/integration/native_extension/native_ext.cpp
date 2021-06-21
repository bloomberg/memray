#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <assert.h>
#include <pthread.h>
#include <malloc.h>

#pragma GCC push_options
#pragma GCC optimize ("O0")

// Regular call chain

__attribute__((noinline)) static void baz() {
    void* p = valloc(1234);
    free(p);
}

__attribute__((noinline)) static void bar() {
    baz();
}

__attribute__((noinline)) static void foo() {
    bar();
}

PyObject*
run_simple(PyObject*, PyObject*)
{
    foo();
    Py_RETURN_NONE;
}

// Inlined call chain

__attribute__((always_inline)) static inline void baz_inline() {
    void *p = valloc(1234);
    free(p);
}

__attribute__((always_inline)) static inline void bar_inline() {
    baz_inline();
}

__attribute__((always_inline)) static inline void foo_inline() {
    bar_inline();
}

PyObject*
run_inline(PyObject*, PyObject*)
{
    foo_inline();
    Py_RETURN_NONE;
}

void deep_call(long n) {
    if (n == 0) {
        return foo();
    }
    return deep_call(n-1);
}

PyObject*
run_deep(PyObject*, PyObject* n_stack)
{
    long n = PyLong_AsLong(n_stack);
    if (n == -1 && PyErr_Occurred()) {
        return NULL;
    }
    deep_call(n);
    Py_RETURN_NONE;
}



#pragma GCC pop_options

static PyMethodDef methods[] = {
        {"run_simple", run_simple, METH_NOARGS, "Execute a chain of native functions"},
        {"run_inline", run_inline, METH_NOARGS, "Execute a chain of native inlined_functions"},
        {"run_deep", run_deep, METH_O, "Execute a chain of native inlined functions in a deep stack"},
        {NULL, NULL, 0, NULL},
};

#if PY_MAJOR_VERSION >= 3
static struct PyModuleDef moduledef = {PyModuleDef_HEAD_INIT, "native_ext", "", -1, methods};

PyMODINIT_FUNC
PyInit_native_ext(void)
{
    return PyModule_Create(&moduledef);
}
#else
PyMODINIT_FUNC
initnative_ext(void)
{
    Py_InitModule("native_ext", methods);
}
#endif

