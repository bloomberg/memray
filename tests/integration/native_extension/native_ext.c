#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <assert.h>
#include <pthread.h>
#ifdef __linux__
#include <malloc.h>
#endif

#pragma GCC push_options
#pragma GCC optimize ("O0")

// Regular call chain
//
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
run_simple(PyObject* mod , PyObject* arg)
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
run_inline(PyObject* mod, PyObject* arg)
{
    foo_inline();
    Py_RETURN_NONE;
}

void* thread_worker(void* arg)
{
    foo();
    return NULL;
}

PyObject*
run_in_thread(PyObject* mod, PyObject* arg)
{
    pthread_t thread;
    pthread_create(&thread, NULL, &thread_worker, NULL);
    pthread_join(thread, NULL);
    Py_RETURN_NONE;
}

void deep_call(long n) {
    if (n == 0) {
        return foo();
    }
    return deep_call(n-1);
}

PyObject*
run_deep(PyObject* mod, PyObject* n_stack)
{
    long n = PyLong_AsLong(n_stack);
    if (n == -1 && PyErr_Occurred()) {
        return NULL;
    }
    deep_call(n);
    Py_RETURN_NONE;
}


PyObject*
run_recursive(PyObject* mod, PyObject* args)
{
    long n;
    PyObject* callback;
    if (!PyArg_ParseTuple(args, "lO", &n, &callback)) {
        return NULL;
    }
    if (n <= 0) {
        foo();
        Py_RETURN_NONE;
    }
    return PyObject_CallFunction(callback, "i", n-1);
}

#pragma GCC pop_options

static PyMethodDef methods[] = {
        {"run_simple", run_simple, METH_NOARGS, "Execute a chain of native functions"},
        {"run_inline", run_inline, METH_NOARGS, "Execute a chain of native inlined_functions"},
        {"run_in_thread", run_in_thread, METH_NOARGS, "Like run_simple, but in a bg thread"},
        {"run_deep", run_deep, METH_O, "Execute a chain of native inlined functions in a deep stack"},
        {"run_recursive", run_recursive, METH_VARARGS, "Execute a callback if the second argument is bigger than 0"},
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
